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
import handoff_snapshot_bridge as HSB

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
    return EP.digest([hashlib.sha256(Path(params['html_file']).read_bytes()).hexdigest(), params.get('title'), params.get('description'), params.get('plan_hash'),params.get('live_data_mode'),params.get('asset'),evidence])

def next_action(task, plan):
    return {'command': 'recover_delivery', 'params': {'task_id': task, 'plan_hash': plan['plan_hash']}}

REPAIR_BUDGET = 2
# Real compose_page builds per task/turn: the initial build plus REPAIR_BUDGET repairs.
BUILD_BUDGET = 1 + REPAIR_BUDGET
NETWORK_UNREACHABLE = 'network_unreachable'

CALLER_INPUT_ERRORS = {
    'PAGE_ID_REQUIRED', 'HTML_REQUIRED', 'FINAL_DESCRIPTION_REQUIRED',
    'LIVE_DATA_MODE_REQUIRED', 'LIVE_DATA_ROUTE_RECEIPT_REQUIRED',
    'LIVE_DATA_ROUTE_ASSET_REQUIRED',
}

def repair_attempts_used(state):
    """Repairs already spent in this turn.

    The first failed publication is the initial attempt; every later failure
    (an edited candidate re-submitted, or a ``recover_delivery`` targeted
    repair) consumes one repair. Counting only ``recover_delivery`` calls left
    the value fixed at 2 when Agents edited and re-published directly.
    Every real ``compose_page`` build after the first also consumes one repair,
    so rebuilding without publishing cannot loop past the same budget.
    """
    return max(int(state.get('failures', 0) or 0) - 1, int(state.get('targeted_repairs', 0) or 0),
               int(state.get('compose_builds', 0) or 0) - 1, 0)

def repair_attempts_remaining(state):
    return max(0, REPAIR_BUDGET - repair_attempts_used(state))

def _turn(params):
    return params.get('turn_id') or C.current_trace_context().get('turn_id')

def _turn_state(task, params):
    """Recovery state of the current turn; a different turn starts a fresh budget."""
    state = load(task)
    turn = _turn(params)
    if state.get('turn_id') != turn:
        state = {'turn_id': turn, 'failures': 0, 'targeted_repairs': 0}
    return state

def _save_state(task, state):
    EP.atomic_json(C.task_temp_path(task, FILE, create_parent=True), state)

# verify_published is read-only but still needs a finite retry window per turn.
VERIFY_PUBLISHED_MAX_ATTEMPTS = 3

def verify_published_attempts(task, params):
    return int(_turn_state(task, params).get('verify_published_attempts', 0) or 0)

def record_verify_published_attempt(task, params):
    with EP.locked(task):
        state = _turn_state(task, params)
        state['verify_published_attempts'] = int(state.get('verify_published_attempts', 0) or 0) + 1
        _save_state(task, state)
    return state['verify_published_attempts']

def _publishable_candidate_action(task, plan, state):
    """publish_verified for the current plan's bound, not-yet-failed candidate; else None."""
    import static_page as SP
    action = SP._planned_publish_next_action(task)
    if not action or action.get('command') != 'publish_verified':
        return None
    try:
        candidate = json.loads(Path(action['params_file']).read_text(encoding='utf-8'))
        if not Path(candidate.get('html_file') or '').is_file():
            return None
        if state.get('last_failed') and state.get('last_candidate') == candidate_key(candidate):
            return None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return action

def compose_build_gate(params, plan):
    """Terminal error once this turn already ran BUILD_BUDGET real compose builds.

    Called only after all parameter/routing validation passed, so input errors
    never consume the budget. A degraded plan produced by recover_delivery may
    still be built once, otherwise the fallback could never be published.
    """
    task = plan['task_id']
    state = _turn_state(task, params)
    builds = int(state.get('compose_builds', 0) or 0)
    if builds < BUILD_BUDGET:
        return None
    if state.get('degraded_plan_hash') == plan['plan_hash'] and not state.get('degraded_built'):
        return None
    action = _publishable_candidate_action(task, plan, state)
    if action is None and state.get('degraded_plan_hash') == plan['plan_hash'] and state.get('degraded_built'):
        # The degraded page was already built once: stop instead of looping.
        action = {'command': 'delivery_status', 'params': {'task_id': task},
                  'instruction': '构建预算与降级构建均已用尽；查看 delivery_status 并向用户说明当前状态，不再构建'}
    elif action is None:
        action = {'command': 'recover_delivery', 'params': {'task_id': task, 'plan_hash': plan['plan_hash']},
                  'instruction': '构建预算已用尽；执行 recover_delivery 降级为可读研究页，不再重复构建'}
    return {'code': 1, 'error': 'DELIVERY_BUILD_BUDGET_EXHAUSTED', 'terminal': True, 'recoverable': False,
            'message': '本轮已执行%d次Compose构建（初次+%d次修复），预算已用尽；不再重新构建' % (builds, REPAIR_BUDGET),
            'compose_builds': builds, 'build_budget': BUILD_BUDGET,
            'repair_attempts_remaining': repair_attempts_remaining(state),
            'current_plan_hash': plan['plan_hash'], 'current_revision': plan['revision'], 'next_action': action}

def record_compose_build(params, plan):
    task = plan['task_id']
    with EP.locked(task):
        state = _turn_state(task, params)
        state['compose_builds'] = int(state.get('compose_builds', 0) or 0) + 1
        if state.get('degraded_plan_hash') == plan['plan_hash'] and state['compose_builds'] > BUILD_BUDGET:
            state['degraded_built'] = True  # the one post-budget degraded build is now used
        _save_state(task, state)
    return state

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
    document=BD._render_html({'delivery_kind':'methodology','research_status':'unavailable'},title=title,subtitle='本地备用成果 · 尚未公开发布',
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
        import static_page as SP
        out = {'code': 1, 'error': 'DELIVERY_REPAIR_REQUIRED', 'published': False, 'verified': False,
               'message': '同一失败候选不重复验收；先修复或恢复研究页', 'next_action': next_action(task, plan),
               'repair_attempts_remaining': repair_attempts_remaining(state)}
        # Repeat the previous failure reason so the Agent knows what to fix.
        previous = SP._publish_failure_summary({'code': 1, 'error': state.get('error_code'),
                                                'stages': (state.get('report') or {}).get('stages') or {}})
        if previous: out['failure_summary'] = previous
        return out

def record(params, result):
    task = params.get('task_id')
    plan = EP.load(task) if task else None
    if not plan: return result
    # A retired parameter/path and missing publish parameters — including the
    # structured live-data routing parameters — are caller input errors, not
    # candidate defects; they must not consume the repair budget, mark the
    # candidate as failed, nor trigger forced methodology-page recovery.
    if result.get('retired_path') or result.get('error') in CALLER_INPUT_ERRORS:
        return result
    # Stale plan parameters are an input error carrying the current plan.
    if result.get('error') == 'PLAN_REVISION_CONFLICT': return result
    with EP.locked(task):
        state = load(task)
        turn = params.get('turn_id') or C.current_trace_context().get('turn_id')
        if state.get('turn_id') != turn: state = {'failures': 0}
        if result.get('code') != 0 and result.get('published') is True and result.get('failure_kind') == NETWORK_UNREACHABLE:
            # The write is confirmed; only this host cannot reach the public URL
            # (DNS/TLS/proxy/CDN). That is not a candidate defect: keep the plan,
            # spend no repair and verify the existing publication read-only.
            state.update(turn_id=turn, last_failed=False, last_failure_kind=NETWORK_UNREACHABLE)
            state.setdefault('failures', 0)
            _save_state(task, state)
            result.update(recoverable=True, terminal=False, repair_attempts_remaining=repair_attempts_remaining(state))
            return result
        state.update(turn_id=turn, last_failed=result.get('code') != 0)
        state.pop('last_failure_kind', None)
        state.setdefault('failures', 0)
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
                              repair_attempts_remaining=repair_attempts_remaining(state))
            if state['failures'] >= 3 and not state['unsafe'] and not state.get('fallback_generated'):
                state['fallback_generated']=True
                EP.atomic_json(C.task_temp_path(task, FILE, create_parent=True), state)
                try:
                    recovery=recover({'task_id':task,'plan_hash':plan['plan_hash'],'force_fallback':True,'user_query':params.get('user_query')})
                except EP.PlanError as exc: recovery=exc.as_dict()
                # Keep the degraded-plan build allowance recover() just stored.
                state.update({k: v for k, v in load(task).items() if k in ('degraded_plan_hash', 'degraded_built')})
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

def _load_json_file(path):
    try:
        value=json.loads(Path(path).read_text(encoding='utf-8-sig'))
        return value if isinstance(value,dict) else None
    except (OSError,ValueError):
        return None


def _find_handoff(task, params):
    value=params.get('handoff')
    if isinstance(value,dict): return value
    raw_file=params.get('handoff_file')
    if raw_file:
        value=_load_json_file(raw_file)
        if value is not None: return value
    from qbs_job_lifecycle import find_job
    job_path,_,_=find_job(task_id=task,turn_id=params.get('turn_id') or C.current_trace_context().get('turn_id'))
    if not job_path: return None
    candidate=job_path.with_name(job_path.name.replace('.job.json','.handoff.json'))
    return _load_json_file(candidate) if candidate.exists() else None


def _handoff_snapshot_recovery(params,plan,changes,modules,panels):
    handoff=_find_handoff(plan['task_id'],params)
    if not isinstance(handoff,dict): return None
    bundle=HSB.build_bundle(handoff=handoff,materialized_file=params.get('materialized_file'),
                            required_roles=params.get('required_roles'))
    snapshot_roles=bundle.get('snapshot_roles') or []
    if not snapshot_roles:
        return {'bundle':bundle,'phase':'methodology'}
    text_panels=[copy.deepcopy(p) for p in panels if p.get('type') in ('text','image')]
    default_module=modules[0] if modules else '已验证研究结果'
    for role in snapshot_roles:
        title=str(role.get('role_id') or '已验证数据')
        text_panels.append({
            'type':'table','title':title,'compose_module':default_module,
            'snapshot_receipt_file':role['snapshot_receipt_file'],
            'snapshot_receipt_sha256':role['snapshot_receipt_sha256'],
            'snapshot_outputs':role.get('required_outputs') or [],
        })
    missing=bundle.get('missing_roles') or []
    if missing:
        text_panels.append({
            'type':'text','title':'研究覆盖与缺口','compose_module':default_module,
            'text':'本页为已验证快照的部分研究成果，不会自动更新。\n'+
                   '\n'.join('缺失角色：'+str(role) for role in missing)+
                   '\n缺失角色未被当作零命中或已核验条件。'
        })
    changes.update(
        runtime_roles=[],snapshot_roles=snapshot_roles,panels=text_panels,
        unassigned_panels=[],live_data_mode='verified_snapshot',
        research_status=bundle.get('research_status') or 'partial',
        delivery_kind=bundle.get('delivery_kind') or 'partial_research',
        research_checks={'contract_hash':(plan.get('research_contract') or {}).get('contract_hash'),
                         'research_status':bundle.get('research_status') or 'partial',
                         'missing_roles':missing},
        description='已验证Handoff快照的研究页，展示实际观察日、数据来源与研究边界。'
    )
    if changes.get('title') in ('策略研究与核验方法',''):
        changes['title']='策略研究与核验结果'
    return {'bundle':bundle,'phase':'partial_snapshot' if missing else 'handoff_snapshot'}


EVIDENCE_RECEIPT_KEYS = ('validation_receipt_files', 'grant_validation_receipt_files')
EVIDENCE_RECEIPT_DIRS = ('formula_validation_receipts', 'grant_validation_receipts')
MAX_EVIDENCE_RECEIPTS = 8


def _evidence_receipt_candidates(task, prior, skip=()):
    """Completed QBS validation receipts of this task that can be frozen.

    Prefer receipts the draft already referenced; scan the task-scoped receipt
    directories only when the draft named none. Receipts tied to plan runtime
    roles are skipped: they were just tried by the runtime-role loop.
    """
    listed = []
    for key in EVIDENCE_RECEIPT_KEYS:
        value = prior.get(key) or []
        listed.extend([value] if isinstance(value, str) else [p for p in value if isinstance(p, str)])
    if not listed:
        for name in EVIDENCE_RECEIPT_DIRS:
            root = C.task_temp_path(task, name)
            if root.is_dir(): listed.extend(str(p) for p in sorted(root.glob('*.json')))
    skipped = {str(Path(p).resolve()) for p in skip if p}
    seen, out = set(), []
    for raw in listed:
        path = Path(raw)
        key = str(path.resolve())
        if key in seen or key in skipped: continue
        seen.add(key)
        proof = _load_json_file(path)
        if (not proof or proof.get('task_id') != task or proof.get('success') is not True
                or proof.get('status') != 'completed' or proof.get('failures')):
            continue
        # Child formula receipts carry no read contract; only package-set or
        # snapshot-backed grant receipts can be frozen without new queries.
        if not proof.get('snapshot_receipt_file') and proof.get('tool_name') != 'validate_package_set':
            continue
        out.append((str(path), proof))
        if len(out) >= MAX_EVIDENCE_RECEIPTS: break
    return out


def _freeze_receipt_evidence(task, plan, prior, panels):
    """Freeze verified QBS data the methodology fallback would otherwise discard."""
    import verified_snapshot as VS
    roles, titles = [], {}
    known = {str(Path(r['snapshot_receipt_file']).resolve()) for r in plan.get('snapshot_roles', [])}
    skip = [r.get('validation_receipt_file') for r in plan.get('runtime_roles', [])]
    for path, proof in _evidence_receipt_candidates(task, prior, skip):
        result = VS.materialize_registered({'task_id': task, 'validation_receipt_file': path})
        if result.get('code') != 0: continue
        receipt = str(Path(result['snapshot_receipt_file']).resolve())
        if receipt in known: continue
        known.add(receipt)
        label = str(proof.get('role') or proof.get('package_name') or '已验证数据')
        role_id = 'evidence.' + hashlib.sha256(receipt.encode('utf-8')).hexdigest()[:12]
        roles.append({'role_id': role_id, 'snapshot_receipt_file': result['snapshot_receipt_file'],
                      'snapshot_receipt_sha256': result['snapshot_receipt_sha256']})
        titles[role_id] = label
    # Data panels the draft already bound to a verified snapshot outside the plan.
    for panel in panels:
        file = panel.get('snapshot_receipt_file')
        if not file or panel.get('type') in ('text', 'image'): continue
        receipt = str(Path(file).resolve())
        if receipt in known: continue
        try: VS.load(task, file)
        except EP.PlanError: continue
        known.add(receipt)
        role_id = 'evidence.' + hashlib.sha256(receipt.encode('utf-8')).hexdigest()[:12]
        roles.append({'role_id': role_id, 'snapshot_receipt_file': file,
                      'snapshot_receipt_sha256': hashlib.sha256(Path(file).read_bytes()).hexdigest()})
        titles[role_id] = str(panel.get('title') or '已验证数据')
    return roles, titles


def _evidence_panel(task, role, title, module):
    import verified_snapshot as VS
    data = VS.load(task, role['snapshot_receipt_file'], role['snapshot_receipt_sha256'])
    panel = {'type': 'table', 'title': title, 'compose_module': module,
             'snapshot_receipt_file': role['snapshot_receipt_file']}
    if data['resource'] == 'package':
        panel['snapshot_outputs'] = [r['output'] for r in data['contract'].get('reads', [])]
    return panel


def _network_only_failure(task, plan):
    """The latest failure was public reachability of an already written page."""
    try:
        public = DS.load(task, plan['target_page_id'])
    except EP.PlanError:
        return None
    write = public.get('last_write') or {}
    error = public.get('last_error') or {}
    if (write.get('status') == 'confirmed' and error.get('failure_kind') == NETWORK_UNREACHABLE
            and not DS.flags(public)['verified']):
        return public
    return None


def recover(params):
    task = params['task_id']
    plan = EP.load(task)
    if plan and not params.get('force_fallback') and _network_only_failure(task, plan):
        # Do not revise the plan or rebuild: the page is written; only the
        # public check from this host failed. Re-check it read-only.
        return {'code': 0, 'recovery_phase': 'verify_published', 'plan_revised': False,
                'failure_kind': NETWORK_UNREACHABLE, 'published': True, 'verified': False,
                'current_plan_hash': plan['plan_hash'], 'current_revision': plan['revision'],
                'repair_attempts_remaining': repair_attempts_remaining(_turn_state(task, params)),
                'message': '页面已写入，仅公网可达性校验失败；不修订计划、不重新发布，执行 verify_published 复验',
                'next_action': {'command': 'verify_published', 'params': {'task_id': task, 'page_id': plan['target_page_id']}}}
    out = _recover(params)
    after = EP.load(task) if plan else None
    if (isinstance(out, dict) and out.get('code') == 0 and after
            and out.get('recovery_phase') not in (None, 'targeted_repair')):
        # One build of each degraded plan is allowed even after the build
        # budget; never re-armed for the same plan, so this cannot loop.
        with EP.locked(task):
            state = _turn_state(task, params)
            if state.get('degraded_plan_hash') != after['plan_hash']:
                state.update(degraded_plan_hash=after['plan_hash'], degraded_built=False)
                _save_state(task, state)
    return out


def _recover(params):
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
    # Same turn resolution as record(); a different turn starts a fresh budget,
    # but the same turn keeps failures/last_candidate so the counter can move.
    turn = params.get('turn_id') or C.current_trace_context().get('turn_id')
    if state.get('turn_id') != turn: state = {'turn_id':turn,'failures':0,'targeted_repairs':0}
    if params.get('force_fallback'): state['targeted_repairs']=REPAIR_BUDGET
    changes = {key: copy.deepcopy(prior[key]) for key in CI.PASS_FIELDS if key in prior}
    changes.update(task_id=task, expected_revision=plan['revision'], revision_reason='bounded_delivery_recovery')
    changes.setdefault('description', '展示本轮已确认条件、验证数据、实际观察日与研究边界。')
    modules = [m['module'] for m in plan['borrow_modules']]
    panels = copy.deepcopy(prior.get('panels') or [])
    try:
        snapshot_recovery=_handoff_snapshot_recovery(params,plan,changes,modules,panels)
    except EP.PlanError as exc:
        return exc.as_dict()
    if snapshot_recovery:
        bundle=snapshot_recovery['bundle']
        if not bundle.get('snapshot_roles'):
            if bundle.get('coverage_reason') not in (None, 'required_roles_not_covered') and not bundle.get('legacy_capsule'):
                return {'code':1,'error':'HANDOFF_EVIDENCE_INVALID','terminal':False,
                        'coverage_reason':bundle.get('coverage_reason'),
                        'covered_roles':bundle.get('covered_roles') or [],
                        'missing_roles':bundle.get('missing_roles') or [],
                        'message':'Handoff capsule无效或证据不完整；不能自动降级为方法页',
                        'next_action':{'command':'delivery_status','params':{'task_id':task}}}
            missing=bundle.get('missing_roles') or []
            if missing:
                return {'code':1,'error':'HANDOFF_REQUIRED_ROLES_UNAVAILABLE','terminal':False,
                        'covered_roles':bundle.get('covered_roles') or [],
                        'missing_roles':missing,
                        'message':'Handoff缺少当前研究要求的角色；不得降级为无数据方法页',
                        'next_action':{'command':'delivery_status','params':{'task_id':task}}}
        else:
            out=SP.cmd_execution_plan(changes)
            out.update(recovery_phase=snapshot_recovery['phase'],original_page_id=plan['target_page_id'],
                       covered_roles=bundle.get('covered_roles') or [],
                       missing_roles=bundle.get('missing_roles') or [],
                       snapshot_roles_bound=len(bundle.get('snapshot_roles') or []))
            return out
    if repair_attempts_used(state) < REPAIR_BUDGET and panels and not params.get('force_fallback'):
        state['targeted_repairs'] = repair_attempts_used(state) + 1
        EP.atomic_json(C.task_temp_path(task, FILE, create_parent=True), state)
        data = [m for m in modules if any(p.get('compose_module') == m and p.get('type') not in ('text','image') for p in panels)]
        changes.update(module_order=data+[m for m in modules if m not in data], panels=panels)
        out = SP.cmd_execution_plan(changes)
        return {**out, 'recovery_phase':'targeted_repair', 'repair_attempts_remaining':repair_attempts_remaining(state)}
    frozen, missing = [], []
    for role in plan['runtime_roles']:
        result = VS.materialize_registered({'task_id':task,'validation_receipt_file':role.get('validation_receipt_file')})
        if result.get('code') == 0:
            frozen.append({'role_id':role['role_id'],'snapshot_receipt_file':result['snapshot_receipt_file'],
                           'snapshot_receipt_sha256':result['snapshot_receipt_sha256'],
                           **({'required_outputs':role['required_outputs']} if role.get('required_outputs') else {})})
        else: missing.append({'error':'ROLE_UNAVAILABLE','role_id':role['role_id'],'required_role':role,'cause_code':result.get('error')})
    frozen = list({r['role_id']:r for r in plan.get('snapshot_roles', []) + frozen}.values())
    # Before degrading to a no-data methodology page, keep any verified QBS
    # data this task already holds (validation receipts / snapshot panels).
    evidence_roles, evidence_titles = ([], {})
    if not frozen:
        evidence_roles, evidence_titles = _freeze_receipt_evidence(task, plan, prior, panels)
        frozen = list(evidence_roles)
    if public.get('last_good_version') and (missing or not frozen or evidence_roles or plan.get('require_live_data')):
        return {'code': 1, 'error': 'PRESERVED_LAST_GOOD_PAGE', 'terminal':False,
                'message':'本轮更新未完成；已保留原可读页面，不能用部分结果覆盖',
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
        if evidence_roles:
            if changes.get('title') in ('策略研究与核验方法', ''): changes['title'] = '策略研究与核验结果'
            # Receipt-derived snapshots have no plan role to map onto; give each
            # unconsumed one its own table so compose_page binds it exactly once.
            module = modules[0] if modules else '已验证研究结果'
            used_files = {str(Path(p['snapshot_receipt_file']).resolve()) for p in panels if p.get('snapshot_receipt_file')}
            for role in evidence_roles:
                if str(Path(role['snapshot_receipt_file']).resolve()) not in used_files:
                    panels.append(_evidence_panel(task, role, evidence_titles.get(role['role_id']) or '已验证数据', module))
        # Every valid frozen role must end up visible: unconsumed receipts become
        # real data tables instead of vanishing when the candidate had no panels
        # or every runtime panel was filtered out during role mapping.
        consumed_files = {str(Path(p['snapshot_receipt_file']).resolve()) for p in panels if p.get('snapshot_receipt_file')}
        default_module = str((panels[0] if panels else {}).get('compose_module') or (modules[0] if modules else '已验证研究结果'))
        for role in frozen:
            receipt = str(Path(role['snapshot_receipt_file']).resolve())
            if receipt in consumed_files: continue
            panels.append(_evidence_panel(task, role, str(role.get('role_id') or '已验证数据'), default_module))
            consumed_files.add(receipt)
        changes.update(runtime_roles=[],snapshot_roles=frozen,panels=panels, live_data_mode='verified_snapshot')
        if evidence_roles or missing or plan.get('require_live_data') or plan.get('research_status') == 'partial':
            gaps=copy.deepcopy((plan.get('research_checks') or {}).get('issues') or [])+missing
            if plan.get('require_live_data'): gaps.append({'error':'LIVE_REQUIREMENT_NOT_SATISFIED'})
            changes.update(research_status='partial',delivery_kind='partial_research',
                           research_checks={'contract_hash':(plan.get('research_contract') or {}).get('contract_hash'),
                                            'research_status':'partial','issues':gaps})
        changes['description'] = '已验证数据的静态研究页，展示实际观察日和研究口径，不会自动更新。'+('部分数据待补。' if changes.get('delivery_kind') == 'partial_research' else '')
        if changes.get('delivery_kind') == 'partial_research':
            gap_lines = ['核验缺口：'+str(item.get('condition_id') or item.get('role_id') or item.get('error')) for item in gaps]
            panels.append({'type':'text','title':'研究覆盖与缺口','compose_module':str((panels[0] if panels else {}).get('compose_module') or (modules[0] if modules else '已验证研究结果')),
                           'text':'本页展示已验证数据快照，快照不会自动更新。\n'+
                                  ('\n'.join(gap_lines) if gap_lines else '其余维度数据待补。')+
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
        modules = [str((panels[0] if panels else {}).get('compose_module') or (modules[0] if modules else '研究方法'))]
        for key in ('asset','route_receipt_file','validation_receipt_files','grant_validation_receipt_files','handoff_validation_receipt_files'):
            changes.pop(key,None)
        changes['market_data_required'] = False
        changes.update(research_contract=contract, research_status='unavailable',delivery_kind='methodology',
                       runtime_roles=[],snapshot_roles=[],panels=panels,live_data_mode='static_content_only',
                       description='已确认策略与核验方法研究页；本页为研究方法说明，数据待补。')
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
    out.update(recovery_phase=('partial_snapshot' if (missing or evidence_roles) else 'handoff_snapshot') if frozen else 'methodology',
               original_page_id=plan['target_page_id'])
    if evidence_roles: out['evidence_roles_bound'] = len(evidence_roles)
    return out
