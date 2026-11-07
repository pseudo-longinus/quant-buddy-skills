"""Bounded same-page recovery. Reuse proven data; never retry unknown writes."""
import copy
import hashlib
import json
import re
from html import escape as _esc
from pathlib import Path
import common as C
import execution_plan as EP
import delivery_state as DS
import compose_inputs as CI
import handoff_snapshot_bridge as HSB
import compose_presentation as CP

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
    # Metadata is validated alongside HTML. Correcting it must reach validation;
    # dict key ordering alone must still count as an unchanged failed request.
    metadata = {key: params.get(key) for key in ('page_context', 'agent_reply_template')}
    return EP.digest([hashlib.sha256(Path(params['html_file']).read_bytes()).hexdigest(), params.get('title'), params.get('description'), params.get('plan_hash'),params.get('live_data_mode'),params.get('asset'),evidence,metadata])

def next_action(task, plan):
    return {'command': 'recover_delivery', 'params': {'task_id': task, 'plan_hash': plan['plan_hash']}}

REPAIR_BUDGET = 2
# Real compose_page builds per task/turn: the initial build plus REPAIR_BUDGET repairs.
BUILD_BUDGET = 1 + REPAIR_BUDGET
NETWORK_UNREACHABLE = 'network_unreachable'

CALLER_INPUT_ERRORS = {
    'RESEARCH_PLAN_CONFLICT', 'SNAPSHOT_PLAN_REQUIRED',
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
        if params.get('html_file') and Path(params['html_file']).is_file():
            state['last_candidate'] = candidate_key(params)
            state['last_candidate_file'] = str(Path(params['html_file']).resolve())
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


def _latest_task_handoff(task):
    """Find the newest non-failed handoff for the same task.

    Current-turn lineage remains authoritative, but a later page repair may run
    after trace context has moved on.  Reusing task-scoped verified evidence is
    safer than discarding it and falling back to a no-data methodology page.
    """
    from qbs_job_lifecycle import _job_root, _read_job
    root=_job_root()
    if not root.exists(): return None
    candidates=[]
    for handoff_path in root.glob('*.handoff.json'):
        value=_load_json_file(handoff_path)
        if not isinstance(value,dict) or value.get('task_id') != task: continue
        job_path=handoff_path.with_name(handoff_path.name.replace('.handoff.json','.job.json'))
        job=_read_job(job_path) if job_path.exists() else None
        status=str((job or {}).get('status') or '')
        if status == 'failed': continue
        updated=str((job or {}).get('updated_at') or '') + str((job or {}).get('started_at') or '')
        # completed is preferred, then queued/running handoffs with valid capsule evidence.
        candidates.append(((2 if status == 'completed' else 1, updated, handoff_path.stat().st_mtime_ns), handoff_path, value))
    if not candidates: return None
    return max(candidates, key=lambda item: item[0])[2]


def _find_handoff(task, params):
    value=params.get('handoff')
    if isinstance(value,dict): return value
    raw_file=params.get('handoff_file')
    if raw_file:
        value=_load_json_file(raw_file)
        if value is not None: return value
    turn=params.get('turn_id') or C.current_trace_context().get('turn_id')
    if turn:
        from qbs_job_lifecycle import find_job
        job_path,_,_=find_job(task_id=task,turn_id=turn)
        if job_path:
            candidate=job_path.with_name(job_path.name.replace('.job.json','.handoff.json'))
            value=_load_json_file(candidate) if candidate.exists() else None
            if value is not None: return value
    return _latest_task_handoff(task)


def _handoff_panel_id(seed):
    panel_id='handoff-'+re.sub(r'[^A-Za-z0-9_.-]+','-',str(seed or 'data')).strip('-')
    return panel_id if re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]*',panel_id) else 'handoff-data'


def _ensure_panel_ids(panels, prefix):
    """Fill unique mountable ids for panels; existing valid ids are preserved."""
    used={str(p.get('id') or '') for p in panels}
    for index,panel in enumerate(panels):
        current=str(panel.get('id') or '').strip()
        if current and re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]*',current):continue
        base=re.sub(r'[^A-Za-z0-9_.-]+','-',str(panel.get('title') or '')).strip('-')
        panel_id=f'{prefix}-{base}' if base else f'{prefix}-panel-{index+1}'
        candidate,counter=panel_id,2
        while candidate in used:candidate=f'{panel_id}-{counter}';counter+=1
        panel['id']=candidate;used.add(candidate)


def _machine_presentation(task,mounts,title,summary,metrics,filename,sources_note=None):
    """Machine-authored fallback presentation (draft presentation_origin='machine').

    It exists so a degraded page never ships as bare auto tables; the recovery
    instruction requires the agent to replace it with an authored presentation
    before delivery. mounts: list of (panel_id, mount title).
    """
    root=CI.editable_root(task); root.mkdir(parents=True,exist_ok=True)
    path=root/filename
    mount_html=''.join(
        f'<section class="qb-handoff-panel"><h3>{_esc(str(mount_title),quote=True)}</h3>'
        f'<div data-qb-panel="{_esc(str(panel_id),quote=True)}"></div></section>'
        for panel_id,mount_title in mounts
    )
    metric_html=''.join(f'<div data-qb-metric>{_esc(str(metric),quote=True)}</div>' for metric in metrics)
    sources_html=('')
    if sources_note:
        sources_html=(f'<section class="qb-researched-sources" data-qb-sources><h2>数据来源</h2>'
                      f'<p>{_esc(str(sources_note),quote=True)}</p></section>')
    style=('<style>.qb-handoff-hero{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}'
           '.qb-handoff-panel{margin-top:20px}.qb-researched-sources{margin-top:24px}</style>')
    body=(f'<main data-qb-page-design="compose-bespoke-v1"><h1>{_esc(str(title),quote=True)}</h1>'
          f'<p data-qb-summary>{_esc(str(summary),quote=True)}</p>'
          '<div class="qb-handoff-hero">'+metric_html+'</div>'+mount_html+sources_html+'</main>')
    path.write_text(style+body,encoding='utf-8')
    return {'version':1,'mode':'bespoke','html_file':str(path),'design':'compose-bespoke-v1'}


def _machine_presentation_for_panels(task, panels, title, summary, metrics, filename, sources_note=None):
    """Regenerate the machine fallback presentation to match the CURRENT panels.

    Machine presentations are ours: regenerating each recovery round keeps
    mounts 1:1 with panels even when panels were rebuilt. Authored files are
    never touched here (ensure_mount appends inert mounts instead).
    """
    mounts=[(str(p['id']), str(p.get('title') or p['id'])) for p in panels]
    return _machine_presentation(task,mounts,title,summary,metrics,filename,sources_note=sources_note)


def _handoff_snapshot_recovery(params,plan,changes,modules,panels):
    handoff=_find_handoff(plan['task_id'],params)
    if not isinstance(handoff,dict): return None
    bundle=HSB.build_bundle(handoff=handoff,materialized_file=params.get('materialized_file'),
                            required_roles=params.get('required_roles'))
    snapshot_roles=bundle.get('snapshot_roles') or []
    if not snapshot_roles:
        return {'bundle':bundle,'phase':'methodology'}
    # Authored presentations (explicit origin, or legacy drafts without one) are
    # preserved and only receive appended mounts; machine ones regenerate below.
    prior_authored=isinstance(changes.get('presentation'),dict) and changes.get('presentation_origin') in (None,'authored')
    text_panels=[copy.deepcopy(p) for p in panels if p.get('type') in ('text','image')]
    default_module=modules[0] if modules else '已验证研究结果'
    for role in snapshot_roles:
        title=str(role.get('role_id') or '已验证数据')
        panel_id=_handoff_panel_id(role.get('role_id') or title)
        if prior_authored:
            changes['presentation']=CP.ensure_mount(plan['task_id'],changes['presentation'],panel_id,title)
        text_panels.append({
            'type':'table','id':panel_id,'title':title,'compose_module':default_module,
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
    # Presentation Mode requires every panel to own a mount, text panels included.
    _ensure_panel_ids(text_panels,'handoff')
    if prior_authored:
        for panel in text_panels:
            changes['presentation']=CP.ensure_mount(plan['task_id'],changes['presentation'],panel['id'],str(panel.get('title') or panel['id']))
        changes['presentation_origin']='authored'
    else:
        changes['presentation']=_machine_presentation_for_panels(plan['task_id'],text_panels,'已验证研究结果',
            '本页展示本轮已通过QBS handoff校验的数据快照；结论只覆盖已验证角色，缺失角色不视为零命中。',
            ['已验证数据组 '+str(sum(1 for p in text_panels if p.get('type') not in ('text','image'))),'数据模式 verified snapshot'],
            'handoff-presentation.html')
        changes['presentation_origin']='machine'
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


def _researched_title(topic):
    """Readable draft title for the researched_static fallback; agent aligns h1."""
    text=re.sub(r'\s+',' ',str(topic or '')).strip()
    text=re.split(r'[。？！?！;；\n]',text)[0].strip()
    if len(text)>32:text=text[:32].rstrip()+'…'
    return (text+' · 公开来源研究') if text else '公开来源研究'


def recover(params):
    task = params['task_id']
    plan = EP.load(task)
    if plan and (DS.load(task,plan['target_page_id']).get('last_write') or {}).get('status') in ('pending','unknown'):
        raise EP.PlanError('PUBLISH_OUTCOME_UNKNOWN','先核对已有写入，不能自动重发')
    from delivery_requirements import recovery_boundary
    blocked=recovery_boundary(params,plan,DS.load(task,plan['target_page_id']) if plan else None)
    if blocked is not None: return blocked
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
    if not params.get('file_publish_dir') and C.existing_file_intent(params):
        return {'code': 1, 'error': 'EXISTING_FILE_ROUTE_REQUIRED', 'recoverable': True, 'terminal': False,
                'message': '用户请求以已有图片/文件为来源；先file_prepare原样托管并交付首链，不能降级为方法页或researched_static',
                'next_action': {'command': 'file_prepare',
                                'params': {'task_id': task, 'user_query': params.get('user_query'),
                                           **({'page_id': params['page_id']} if params.get('page_id') else {})}}}
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
    # Inspect publication before loading/rewriting any Compose workspace. Missing
    # internal candidate files say nothing about the published page's contents.
    from finish_research_delivery import preserve_publication
    preserved = preserve_publication(params, plan, public)
    if preserved is not None:
        return preserved
    mark_job_running(task_id=task, turn_id=C.current_trace_context().get('turn_id'), resume_failed=True)
    prior = CI._prior(plan, CI.editable_root(task))
    state = load(task)
    # Same turn resolution as record(); a different turn starts a fresh budget,
    # but the same turn keeps failures/last_candidate so the counter can move.
    turn = params.get('turn_id') or C.current_trace_context().get('turn_id')
    if state.get('turn_id') != turn: state = {'turn_id':turn,'failures':0,'targeted_repairs':0}
    if params.get('force_fallback'): state['targeted_repairs']=REPAIR_BUDGET
    preserved_candidate_file = state.get('last_candidate_file') if isinstance(state.get('last_candidate_file'), str) else None
    if preserved_candidate_file and not Path(preserved_candidate_file).is_file(): preserved_candidate_file = None
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
                       preserved_candidate_file=preserved_candidate_file,
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
        # Degraded snapshot deliveries never ship as bare auto tables: give every
        # panel a mountable id and default a machine presentation; authored
        # presentations keep their file and only get recovery mounts appended.
        _ensure_panel_ids(panels,'frozen')
        if isinstance(changes.get('presentation'),dict) and changes.get('presentation_origin') in (None,'authored'):
            for panel in panels:
                changes['presentation']=CP.ensure_mount(task,changes['presentation'],panel['id'],str(panel.get('title') or panel['id']))
            changes['presentation_origin']='authored'
        else:
            data_count=sum(1 for p in panels if p.get('type') not in ('text','image'))
            fallback_title=changes.get('title') or '已验证数据研究页'
            changes['presentation']=_machine_presentation_for_panels(task,panels,fallback_title,
                '本页为本轮可恢复的已验证数据快照；当前为机器保底版式，交付前应替换为手写presentation并保留数据缺口说明。',
                ['已验证数据组 '+str(data_count),'数据模式 verified snapshot'],
                'recovery-presentation.html')
            changes['presentation_origin']='machine'
    else:
        from delivery_requirements import current_query, live_required
        contract = plan.get('research_contract') or params.get('research_contract')
        context = C.current_trace_context()
        descriptions = [c['description'] for c in (contract or {}).get('conditions', [])]
        query = current_query(params)
        # Only the current request can add a live requirement. Historical
        # Handoff prose below may restore research scope, not authorize live.
        if live_required(params): changes['require_live_data']=True
        if not query and context.get('turn_id'):
            from qbs_job_lifecycle import find_job
            _,job,_=find_job(task_id=task,turn_id=context['turn_id'])
            query=(job or {}).get('handoff',{}).get('user_query')
        if not descriptions and not query:
            raise EP.PlanError('METHODOLOGY_INTENT_REQUIRED', '需原始用户研究范围或已确认合同，不能生成空方法页')
        methodology_text = ('已确认研究范围\n'+('\n'.join(descriptions) if descriptions else str(query))+
                '\n\n核验方法\n按上述条件逐项核对股票范围、阈值、基准、字段实际日期与排序。只有全部条件的证据齐备后，才生成符合条件的名单。'
                '\n\n数据覆盖\n本轮尚未取得足以验证标的的数据。未验证不代表符合条件的股票为零；当前不输出标的或虚构数值。'
                '\n\n后续核验\n补齐同口径的数据来源与观察日，再在本页更新研究结果。')
        for key in ('asset','route_receipt_file','validation_receipt_files','grant_validation_receipt_files','handoff_validation_receipt_files','sources_manifest_file'):
            changes.pop(key,None)
        changes['market_data_required'] = False
        if params.get('methodology_only'):
            # Host finisher (finish_research_delivery) runs without a live agent:
            # no web research is possible, keep the no-data methodology contract.
            changes['title']='策略研究与核验方法'
            panels = [{'type':'text','title':'研究范围与核验方法','compose_module':modules[0] if modules else '研究方法','text':methodology_text,'as_of_mode':'historical'}]
            modules = [str((panels[0] if panels else {}).get('compose_module') or (modules[0] if modules else '研究方法'))]
            changes.pop('presentation',None); changes.pop('presentation_origin',None)
            changes.update(research_contract=contract, research_status='unavailable',delivery_kind='methodology',
                           runtime_roles=[],snapshot_roles=[],panels=panels,live_data_mode='static_content_only',
                           description='已确认策略与核验方法研究页；本页为研究方法说明，数据待补。')
        else:
            # researched_static: no recoverable QBS evidence, so the degraded page
            # answers the original question from cited public sources instead of
            # shipping a data-less methodology skeleton. Publish is gated by the
            # researched_static_plan_hash origin lock in static_page.
            research_topic = str(descriptions[0]) if descriptions else str(query)
            changes['title'] = _researched_title(research_topic)
            answer_text = ('研究问题\n'+str(query or research_topic)+
                    '\n\n联网检索要求\n先联网检索回答上述问题；每个关键数字在 sources_manifest_file 登记公开来源（title/url/publisher/published_at/supports），关键数字尽量双源交叉；查无实据写明证据缺口，不得臆测或填占位数字。'
                    '\n\n边界\n本页数据来自公开来源，未能通过 QBS 实时验证；不与实时行情混排，不冒充实时研究，交付标签为可分享研究静态页（公开来源）。')
            panels = [
                {'type':'text','id':'web_research_answer','title':'公开来源研究','compose_module':'公开来源研究','text':answer_text,'as_of_mode':'historical'},
                {'type':'text','id':'methodology_note','title':'研究方法与边界','compose_module':'研究方法','text':methodology_text,'as_of_mode':'historical'},
            ]
            modules = ['公开来源研究','研究方法']
            _ensure_panel_ids(panels,'researched')
            if isinstance(changes.get('presentation'),dict) and changes.get('presentation_origin') in (None,'authored'):
                for panel in panels:
                    changes['presentation']=CP.ensure_mount(task,changes['presentation'],panel['id'],str(panel.get('title') or panel['id']))
                changes['presentation_origin']='authored'
            else:
                changes['presentation']=_machine_presentation_for_panels(task,panels,changes['title'],
                    '本页为公开来源研究静态页的机器保底骨架；联网检索后用手写presentation替换：首屏=结论+关键数字+来源日期，保留 data-qb-sources 来源汇总区。',
                    ['数据模式 公开来源','QBS验证 未执行'],
                    'researched-presentation.html',
                    sources_note='待联网检索后逐条列出来源、发布方与发布日期；替换骨架时保留本区块。')
                changes['presentation_origin']='machine'
            changes.update(research_contract=contract, research_status='partial',delivery_kind='partial_research',
                           runtime_roles=[],snapshot_roles=[],panels=panels,live_data_mode='researched_static',
                           description='公开来源研究静态页：以带来源的公开信息回答用户问题，未经QBS实时验证。')
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
    researched = (not frozen) and not params.get('methodology_only')
    out = SP.cmd_execution_plan(changes)
    out.update(recovery_phase=('partial_snapshot' if (missing or evidence_roles) else 'handoff_snapshot') if frozen else ('researched_static' if researched else 'methodology'),
               original_page_id=plan['target_page_id'], preserved_candidate_file=preserved_candidate_file,
               **({} if frozen else {
                   'downgraded_from': {'research_status':plan.get('research_status'),'delivery_kind':plan.get('delivery_kind'),'plan_hash':plan.get('plan_hash')},
                   'downgrade_reason': 'no_recoverable_qbs_snapshot_or_runtime_evidence_web_research_fallback' if researched else 'no_recoverable_qbs_snapshot_or_runtime_evidence',
               }))
    if researched:
        # Arm the recovery-origin lock for the exact plan researched_static may
        # publish under, then regenerate the handoff so the initial draft's
        # diagnostics no longer carry the origin-lock error.
        new_plan = out.get('execution_plan') or {}
        if new_plan.get('plan_hash'):
            with EP.locked(task):
                state = _turn_state(task, params)
                state['researched_static_plan_hash'] = new_plan['plan_hash']
                _save_state(task, state)
            try:
                out.update(CI.prepare(new_plan, {}))
            except EP.PlanError:
                pass
    if evidence_roles: out['evidence_roles_bound'] = len(evidence_roles)
    return out
