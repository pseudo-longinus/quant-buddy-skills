"""Bounded same-page recovery. Reuse proven data; never retry unknown writes."""
import copy
import hashlib
import json
import re
from pathlib import Path
import common as C
import execution_plan as EP
import delivery_state as DS
import compose_inputs as CI

FILE = 'receipts/delivery-recovery.json'
UNSAFE = {'PUBLISH_OUTCOME_UNKNOWN', 'PUBLISH_VERSION_CONFLICT', 'PUBLISH_RESPONSE_STALE'}

def load(task):
    try: return json.loads(C.task_temp_path(task, FILE).read_text(encoding='utf-8'))
    except FileNotFoundError: return {'failures': 0, 'last_candidate': None}

def candidate_key(params):
    evidence = {}
    for key in ('route_receipt_file','validation_receipt_files','grant_validation_receipt_files','handoff_validation_receipt_files'):
        paths = params.get(key) or []
        if isinstance(paths,str): paths=[paths]
        evidence[key]=[(str(p), hashlib.sha256(Path(p).read_bytes()).hexdigest() if Path(p).is_file() else None) for p in paths]
    return EP.digest([hashlib.sha256(Path(params['html_file']).read_bytes()).hexdigest(), params.get('title'), params.get('description'), params.get('plan_hash'),params.get('live_data_mode'),evidence])

def next_action(task, plan):
    return {'command': 'recover_delivery', 'params': {'task_id': task, 'plan_hash': plan['plan_hash']}}

def backup_html(params, plan=None):
    """Locally accepted fallback; never changes a pending remote write or plan."""
    import static_page as SP
    import build_dashboard as BD
    task=params['task_id']
    contract=(plan or {}).get('research_contract') or params.get('research_contract') or {}
    context=C.current_trace_context()
    query=params.get('user_query') or (context.get('user_query') if context.get('task_id') in (None,task) else None)
    conditions=[c['description'] for c in contract.get('conditions',[])]
    if not conditions and not query: return {'code':1,'error':'METHODOLOGY_INTENT_REQUIRED'}
    content=('已确认研究范围\n'+'\n'.join(conditions)) if conditions else ('原始研究请求\n'+str(query))
    if not conditions and params.get('description'): content+='\n当前研究计划：'+str(params['description'])
    content+='\n\n研究状态\n本轮尚未取得足以确认完整名单的证据。未验证不代表符合条件为零。公开服务暂未完成发布，本文件是可打开的备用成果。\n\n核验步骤\n逐项核对原始条件、价格基准、单位、实际数据日期与排序；取得同口径证据后继续原任务、原页面更新。'
    refs=contract.get('evidence',[])
    for ref in refs:
        if isinstance(ref,dict) and str(ref.get('url','')).startswith('https://'):
            content+='\n公开来源：['+str(ref.get('title') or '来源')+']('+ref['url']+')；实际数据日期：'+str(ref.get('date') or '待核验')
    title='策略研究与核验方法'
    document=BD._render_html({'delivery_kind':'methodology','research_status':'unavailable'},title=title,subtitle='研究尚未完成 · 尚未公开发布',
        panels=[{'type':'text','title':'研究范围、缺口与核验方法','text':content}],endpoint='',package_id='',signature='',generated_at='')
    # Preserve a locally accepted snapshot rather than discarding usable results
    # when only the remote publication service is unavailable.
    candidate=Path(params['html_file']) if params.get('html_file') else None
    if (plan and params.get('plan_hash') == plan['plan_hash'] and candidate and candidate.is_file()
            and params.get('live_data_mode') == 'verified_snapshot'
            and SP._validate_publish_data_evidence(params) is None):
        check=SP._run_page_verifier(str(candidate),'self-built',expected_title=params.get('title'))
        if check.get('code') == 0:
            document=candidate.read_text(encoding='utf-8');title=params.get('title')
    path=CI.editable_root(task)/'research-fallback.html';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(document,encoding='utf-8')
    check=SP._run_page_verifier(str(path),'self-built',expected_title=title)
    if check.get('code') != 0: return {'code':1,'error':'BACKUP_HTML_VALIDATION_FAILED','local_verification':check}
    result={'task_id':task,'turn_id':params.get('turn_id') or context.get('turn_id'),
            'artifact_file':str(path),'artifact_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'artifact_verified':True}
    if plan:
        state=DS.load(task,plan['target_page_id']);state.update(result);DS._save(state)
    else:
        EP.atomic_json(C.task_temp_path(task,'receipts/local-delivery-artifact.json',create_parent=True),result)
    return {'code':1,'published':False,'verified':False,**result,'message':'可打开的完整HTML备用成果已本地验收，尚未公开发布'}

def before(params):
    task = params.get('task_id')
    plan = EP.load(task) if task else None
    if not plan or not params.get('html_file'): return None
    state = load(task)
    if state.get('turn_id') != (params.get('turn_id') or C.current_trace_context().get('turn_id')): return None
    if state.get('last_candidate') == candidate_key(params) and state.get('last_failed'):
        stages=(state.get('report') or {}).get('stages') or {}
        if (params.get('verify_existing_publication') is True and not state.get('unsafe')
                and (stages.get('local_browser') or {}).get('code') == 0
                and (stages.get('public_smoke') or {}).get('code') == 0
                and (DS.load(task,plan['target_page_id']).get('last_write') or {}).get('status') == 'confirmed'):
            return None
        return {'code': 1, 'error': 'DELIVERY_REPAIR_REQUIRED', 'published': False, 'verified': False,
                'message': '同一失败候选不重复验收；先修复或恢复研究页', 'next_action': next_action(task, plan)}

def record(params, result):
    task = params.get('task_id')
    plan = EP.load(task) if task else None
    if not plan: return result
    with EP.locked(task):
        state = load(task)
        turn = params.get('turn_id') or C.current_trace_context().get('turn_id')
        if state.get('turn_id') != turn: state = {'failures': 0}
        state.update(turn_id=turn, last_failed=result.get('code') != 0)
        if params.get('html_file') and Path(params['html_file']).is_file(): state['last_candidate'] = candidate_key(params)
        if state['last_failed']:
            state['failures'] += 1
            state['error_code'] = result.get('error') or 'PUBLICATION_VALIDATION_FAILED'
            public = DS.load(task, plan['target_page_id'])
            write = public.get('last_write') or {}
            state['unsafe'] = state['error_code'] in UNSAFE or write.get('status') in ('pending','unknown')
            import static_page as SP
            state['report'] = SP._redact_persisted_secrets({'error': state['error_code'], 'stages': result.get('stages', {})})
            public.update(execution_status='failed', last_error={'stage':'publication_validation', 'error_code':state['error_code'],
                          'next_action': {'command':'delivery_status'} if state['unsafe'] else next_action(task, plan)})
            DS._save(public)
            if not state['unsafe']:
                result.update(recoverable=True, terminal=False, next_action=next_action(task, plan),
                              repair_attempts_remaining=max(0, 2-state.get('targeted_repairs',0)))
            if state['failures'] >= 3 and not state['unsafe'] and not state.get('fallback_generated'):
                state['fallback_generated']=True
                EP.atomic_json(C.task_temp_path(task, FILE, create_parent=True), state)
                try:
                    recovery=recover({'task_id':task,'plan_hash':plan['plan_hash'],'force_fallback':True,'user_query':params.get('user_query')})
                except EP.PlanError as exc: recovery=exc.as_dict()
                result.update(recovery_result=recovery, next_action=recovery.get('next_action',result.get('next_action')),
                              recovery_phase=recovery.get('recovery_phase'))
            # Local files are a publication-service fallback, not a way to skip
            # correctable content, layout or evidence gates.
            stages=result.get('stages') or {}
            service_failed=any((stages.get(stage) or {}).get('code') not in (None,0)
                               for stage in ('publish_final','public_smoke'))
            if state['failures'] >= 4 and state.get('fallback_generated') and service_failed:
                backup=backup_html(params,plan)
                result.update({k:v for k,v in backup.items() if k.startswith('artifact_')})
        if not state['last_failed']:
            public = DS.load(task, plan['target_page_id'])
            public.update(live_data_mode=params.get('live_data_mode','unknown'), research_status=plan.get('research_status','unknown'), delivery_kind=plan.get('delivery_kind','result'))
            DS._save(public)
            result.update(live_data_mode=public['live_data_mode'], research_status=public['research_status'], delivery_kind=public['delivery_kind'])
        EP.atomic_json(C.task_temp_path(task, FILE, create_parent=True), state)
    return result

def recover(params):
    import static_page as SP
    import verified_snapshot as VS
    task = params['task_id']
    if not EP.load(task):
        import bootstrap_publication as bootstrap
        boot=bootstrap.load(task)
        if boot.get('status') in ('pending','unknown') or boot.get('read_failures',0)>=2:
            return backup_html(params)
        return {'code':1,'error':'DELIVERY_BOOTSTRAP_REQUIRED','recoverable':True,'terminal':False,
                'message':'尚未建立页面计划；先完成模板路由与唯一页面初始化，不能据此判定发布服务不可用',
                'next_action':{'command':'templates','params':{'task_id':task,'recommend':'all'}}}
    plan = EP.require(task, plan_hash=params.get('plan_hash'))
    from qbs_job_lifecycle import mark_job_running
    public = DS.load(task, plan['target_page_id'])
    if (public.get('last_write') or {}).get('status') in ('pending','unknown'):
        raise EP.PlanError('PUBLISH_OUTCOME_UNKNOWN', '先核对已有写入，不能自动重发')
    mark_job_running(task_id=task, turn_id=C.current_trace_context().get('turn_id'), resume_failed=True)
    prior = CI._prior(plan, CI.editable_root(task))
    state = load(task)
    turn = C.current_trace_context().get('turn_id')
    if state.get('turn_id') != turn: state = {'turn_id':turn,'targeted_repairs':0}
    if params.get('force_fallback'): state['targeted_repairs']=2
    changes = {key: copy.deepcopy(prior[key]) for key in CI.PASS_FIELDS if key in prior}
    changes.update(task_id=task, expected_revision=plan['revision'], revision_reason='bounded_delivery_recovery')
    changes.setdefault('description', '展示本轮已确认条件、验证数据、实际观察日与研究边界。')
    modules = [m['module'] for m in plan['borrow_modules']]
    panels = copy.deepcopy(prior.get('panels') or [])
    if state.get('targeted_repairs', 0) < 2 and panels and not params.get('force_fallback'):
        state['targeted_repairs'] = state.get('targeted_repairs', 0) + 1
        EP.atomic_json(C.task_temp_path(task, FILE, create_parent=True), state)
        data = [m for m in modules if any(p.get('compose_module') == m and p.get('type') not in ('text','image') for p in panels)]
        changes.update(module_order=data+[m for m in modules if m not in data], panels=panels)
        out = SP.cmd_execution_plan(changes)
        return {**out, 'recovery_phase':'targeted_repair', 'repair_attempts_remaining':max(0,2-state['targeted_repairs'])}
    frozen, missing = [], []
    for role in plan['runtime_roles']:
        result = VS.materialize_registered({'task_id':task,'validation_receipt_file':role.get('validation_receipt_file')})
        if result.get('code') == 0:
            frozen.append({'role_id':role['role_id'],'snapshot_receipt_file':result['snapshot_receipt_file'],
                           'snapshot_receipt_sha256':result['snapshot_receipt_sha256'],
                           **({'required_outputs':role['required_outputs']} if role.get('required_outputs') else {})})
        else: missing.append({'error':'ROLE_UNAVAILABLE','role_id':role['role_id'],'required_role':role,'cause_code':result.get('error')})
    frozen = list({r['role_id']:r for r in plan.get('snapshot_roles', []) + frozen}.values())
    if public.get('last_good_version') and (missing or not frozen or plan.get('require_live_data')):
        return {'code': 1, 'error': 'PRESERVED_LAST_GOOD_PAGE', 'terminal':False,
                'message':'本轮研究尚未完成；已保留原可读页面，不能用部分结果覆盖',
                'preserved_version':public['last_good_version'], 'next_action':{'command':'delivery_status','params':{'task_id':task}}}
    if frozen:
        # Preserve original formula/read contracts and all requested outputs.
        mapping = {role['role_id']:role for role in frozen}
        for panel in panels:
            role_id = panel.get('runtime_role_id')
            if not role_id:
                matches = [r['role_id'] for r in plan['runtime_roles'] if
                           (r.get('grant_id') and r['grant_id'] == panel.get('grant_id')) or
                           (r.get('package_id') and r['package_id'] == prior.get('package_id') and not panel.get('grant_id'))]
                role_id = matches[0] if len(matches) == 1 else None
            if role_id in mapping and panel.get('type') not in ('text','image'):
                for key in ('runtime_role_id','grant_id','package_id','signature'): panel.pop(key,None)
                panel['snapshot_receipt_file'] = mapping[role_id]['snapshot_receipt_file']
                if 'output' in panel: panel['snapshot_output'] = panel.pop('output')
                if 'outputs' in panel: panel['snapshot_outputs'] = panel.pop('outputs')
        panels = [p for p in panels if p.get('type') in ('text','image') or p.get('snapshot_receipt_file')]
        changes.update(runtime_roles=[],snapshot_roles=frozen,panels=panels, live_data_mode='verified_snapshot')
        if missing or plan.get('require_live_data') or plan.get('research_status') == 'partial':
            gaps=copy.deepcopy((plan.get('research_checks') or {}).get('issues') or [])+missing
            if plan.get('require_live_data'): gaps.append({'error':'LIVE_REQUIREMENT_NOT_SATISFIED'})
            changes.update(research_status='partial',delivery_kind='partial_research',
                           research_checks={'contract_hash':(plan.get('research_contract') or {}).get('contract_hash'),
                                            'research_status':'partial','issues':gaps})
        changes['description'] = '已验证数据的静态研究页，展示实际观察日和研究口径，不会自动更新。'+('部分条件尚未完成。' if changes.get('delivery_kind') == 'partial_research' else '')
        if changes.get('delivery_kind') == 'partial_research':
            panels.append({'type':'text','title':'研究覆盖与缺口','compose_module':panels[0]['compose_module'],
                           'text':'本页为部分研究成果，快照不会自动更新。\n'+
                                  '\n'.join('核验缺口：'+str(item.get('condition_id') or item.get('role_id') or item.get('error')) for item in gaps)+
                                  '\n已确认的策略条件保持不变，缺失条件未被视为通过。'})
    else:
        contract = plan.get('research_contract') or params.get('research_contract')
        context = C.current_trace_context()
        descriptions = [c['description'] for c in (contract or {}).get('conditions', [])]
        query = params.get('user_query') or (context.get('user_query') if context.get('task_id') in (None,task) else None)
        if not query and context.get('turn_id'):
            from qbs_job_lifecycle import find_job
            _,job,_=find_job(task_id=task,turn_id=context['turn_id'])
            query=(job or {}).get('handoff',{}).get('user_query')
        if params.get('require_live_data') is True or re.search(r'实时|持续刷新',str(query or '')): changes['require_live_data']=True
        changes['title']='策略研究与核验方法'
        if not descriptions and not query:
            raise EP.PlanError('METHODOLOGY_INTENT_REQUIRED', '需原始用户研究范围或已确认合同，不能生成空方法页')
        text = ('已确认研究范围\n'+('\n'.join(descriptions) if descriptions else str(query))+
                '\n\n核验方法\n按上述条件逐项核对股票范围、阈值、基准、字段实际日期与排序。只有全部条件的证据齐备后，才生成符合条件的名单。'
                '\n\n数据覆盖\n本轮尚未取得足以验证标的的数据。未验证不代表符合条件的股票为零；当前不输出标的或虚构数值。'
                '\n\n后续核验\n补齐同口径的数据来源与观察日，再在本页更新研究结果。')
        panels = [{'type':'text','title':'研究范围与核验方法','compose_module':modules[0] if modules else '研究方法','text':text,'as_of_mode':'historical'}]
        modules = [panels[0]['compose_module']]
        for key in ('asset','route_receipt_file','validation_receipt_files','grant_validation_receipt_files','handoff_validation_receipt_files'):
            changes.pop(key,None)
        changes['market_data_required'] = False
        changes.update(research_contract=contract, research_status='unavailable',delivery_kind='methodology',
                       runtime_roles=[],snapshot_roles=[],panels=panels,live_data_mode='static_content_only',
                       description='已确认策略与核验方法研究页；标的数据暂未取得，研究尚未完成。')
    # Recovery retains page/source identity, but uses an original readable shell.
    if changes.get('research_status',plan.get('research_status')) in ('partial','unavailable','unknown'):
        from prose_contract import research_claim_errors
        for panel in panels:
            if panel.get('type')!='text': continue
            if research_claim_errors(panel.get('title',''),'partial'): panel['title']='研究观察与核验边界'
            parts=re.split(r'(?<=[。\n；])',panel.get('text',''))
            panel['text']=''.join('当前仅展示已核验部分，完整股票池与全部条件仍待核验。\n' if research_claim_errors(part,'partial') else part for part in parts)
    used = list(dict.fromkeys(p['compose_module'] for p in panels))
    changes['borrow_modules'] = [{'module':m,'borrow_level':'original','analysis_role':m,'rationale':'有限修复后的可读研究页恢复'} for m in used]
    data_modules=[m for m in used if any(p['compose_module']==m and p.get('type') not in ('text','image') for p in panels)]
    changes['module_order'] = data_modules+[m for m in used if m not in data_modules]
    if not changes.get('title'): changes['title'] = '策略研究与核验结果'
    out = SP.cmd_execution_plan(changes)
    out.update(recovery_phase='verified_snapshot' if frozen else 'methodology', original_page_id=plan['target_page_id'])
    return out
