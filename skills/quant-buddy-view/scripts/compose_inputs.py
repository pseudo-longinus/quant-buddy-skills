"""Compose handoff: editable workspace drafts, credential bindings and existing evidence.
Private plans/credentials stay in task storage; exported drafts never contain secrets.
"""
import copy
import hashlib
import json
import os
import re
from pathlib import Path
import common as C
import execution_plan as EP
import runtime_credentials as RC

POINTER='receipts/compose-draft.json'
PASS_FIELDS=('title','subtitle','description','page_context','agent_reply_template','live_card','agent_intent',
             'route_receipt_file','validation_receipt_files','grant_validation_receipt_files','handoff_validation_receipt_files','turn_id','asset')


def editable_root(task):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,159}',str(task)) or '..' in task:
        raise EP.PlanError('COMPOSE_WORKSPACE_INVALID','task_id不能包含路径片段')
    session=os.environ.get('SESSION_WORKSPACE')
    boundary=Path(session).resolve() if session else Path.cwd().resolve()
    configured=os.environ.get('QBV_OUTPUT_ROOT')
    base=Path(configured) if configured else boundary/'output'/'qbv'
    if not base.is_absolute():
        raise EP.PlanError('COMPOSE_WORKSPACE_INVALID','QBV_OUTPUT_ROOT必须是绝对路径')
    base=base.resolve();target=(base/task).resolve();skill=Path(C.SKILL_ROOT).resolve()
    if (not boundary.is_dir() or not base.is_relative_to(boundary) or not target.is_relative_to(base)
            or target.is_relative_to(skill) or (session and not Path(session).is_absolute())):
        raise EP.PlanError('COMPOSE_WORKSPACE_INVALID','Compose草稿必须位于会话可写目录，不能越界或写入Skill安装目录')
    return target


def _read(path):
    try:
        value=json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if not isinstance(value,dict):raise ValueError('object required')
        return value
    except (OSError,ValueError) as exc:
        raise EP.PlanError('COMPOSE_DRAFT_INVALID','草稿或证据文件不可读取') from exc


def _prior(plan,root):
    pointer=C.task_temp_path(plan['task_id'],POINTER)
    if pointer.exists():
        record=_read(pointer)
        if record.get('task_id')!=plan['task_id'] or record.get('page_id')!=plan['target_page_id']:
            raise EP.PlanError('COMPOSE_DRAFT_IDENTITY_CONFLICT','草稿指针不属于当前任务/页面')
        if not isinstance(record.get('params_file'),str) or not record['params_file']:
            raise EP.PlanError('COMPOSE_DRAFT_INVALID','草稿指针缺少有效路径')
        path=Path(record['params_file']).resolve()
        if not path.is_relative_to(root):raise EP.PlanError('COMPOSE_WORKSPACE_INVALID','已有草稿不在当前会话输出目录')
        value=_read(path)
    else:
        legacy=C.task_temp_path(plan['task_id'],'compose-build-params.json')
        value=_read(legacy) if legacy.exists() else {}
    if value and (value.get('task_id')!=plan['task_id'] or value.get('page_id')!=plan['target_page_id']):
        raise EP.PlanError('COMPOSE_DRAFT_IDENTITY_CONFLICT','旧草稿属于其他任务/页面')
    EP._no_secrets(value)
    return value


def registrations(plan):
    records={};issues=[]
    for role in plan['runtime_roles']:
        try:
            record=RC.verify_binding(plan['task_id'],role['kind'],role.get('grant_id') or role.get('package_id'),role.get('contract_fingerprint',''))
            proof=_read(role.get('validation_receipt_file',''))
            if (proof.get('task_id')!=plan['task_id'] or proof.get('status')!='completed' or proof.get('success') is not True
                    or proof.get('contract_fingerprint')!=role.get('contract_fingerprint')):
                raise EP.PlanError('COMPOSE_ROLE_EVIDENCE_INVALID','运行角色验证收据身份/合同不一致')
            records[role['role_id']]=record
        except EP.PlanError as exc:issues.append({'role_id':role['role_id'],'code':exc.code,'message':str(exc)})
    return records,issues


def normalize_panels(plan,params):
    """Resolve aliases, but reject text consumption and inconsistent dual identifiers."""
    result=copy.deepcopy(params);issues=[];roles={r['role_id']:r for r in plan['runtime_roles']};consumed=set()
    modules={m['module'] for m in plan['borrow_modules']}
    if result.get('package_id') and result['package_id'] not in {r.get('package_id') for r in roles.values() if r['kind']=='package'}:
        issues.append({'code':'COMPOSE_EXTRA_CREDENTIAL','package_id':result['package_id']})
    for i,p in enumerate(result.get('panels') or []):
        if not isinstance(p,dict):issues.append({'panel_index':i,'code':'COMPOSE_PANEL_INVALID'});continue
        ref=p.get('runtime_role_id');kind=p.get('type','table')
        if ref and ref not in roles:
            issues.append({'panel_index':i,'code':'COMPOSE_ROLE_UNKNOWN','role_id':ref});continue
        role=roles.get(ref)
        if role:
            field='grant_id' if role['kind']=='grant' else 'package_id';expected=role.get(field)
            given=p.get(field) if field=='grant_id' else p.get(field) or result.get(field)
            if given and given!=expected:
                issues.append({'panel_index':i,'code':'COMPOSE_ROLE_BINDING_CONFLICT','role_id':ref});continue
            if kind in ('text','image'):
                issues.append({'panel_index':i,'code':'COMPOSE_DATA_PANEL_REQUIRED','role_id':ref});continue
            if field=='grant_id':p[field]=expected
            else:result[field]=expected
        for candidate in roles.values():
            matched=(candidate['kind']=='grant' and p.get('grant_id')==candidate.get('grant_id')) or (
                candidate['kind']=='package' and not p.get('grant_id') and not p.get('snapshot_receipt_file')
                and result.get('package_id')==candidate.get('package_id') and (p.get('output') or p.get('outputs')))
            if matched and kind not in ('text','image'):consumed.add(candidate['role_id'])
        if p.get('grant_id') and p['grant_id'] not in {r.get('grant_id') for r in roles.values() if r['kind']=='grant'}:
            issues.append({'panel_index':i,'code':'COMPOSE_EXTRA_CREDENTIAL','grant_id':p['grant_id']})
        if (p.get('compose_module') or p.get('title')) not in modules:
            issues.append({'panel_index':i,'code':'COMPOSE_MODULE_MIGRATION_REQUIRED'})
    for missing in sorted(set(roles)-consumed):issues.append({'code':'COMPOSE_ROLE_UNCONSUMED','role_id':missing})
    if params.get('unassigned_panels'):issues.append({'code':'COMPOSE_MODULE_MIGRATION_REQUIRED','count':len(params['unassigned_panels'])})
    return result,issues


def _role_panel(role,record,module):
    contract=record['contract'];payload=contract.get('payload') or {}
    assets=payload.get('assets') or ([payload['asset']] if payload.get('asset') else [])
    name='、'.join(str(x) for x in assets) or role['role_id']
    p={'type':'table','title':name+' · 已验证数据','compose_module':module,'runtime_role_id':role['role_id']}
    if role['kind']=='grant':p['grant_id']=role['grant_id']
    else:p['outputs']=role.get('required_outputs') or [r['output'] for r in contract.get('reads',[])]
    return p


def route_leaf_files(route,path,seen=None):
    if not isinstance(route,dict) or not isinstance(path,(str,Path)) or not str(path):
        raise EP.PlanError('COMPOSE_ROUTE_INVALID','路由必须是对象并具有有效文件路径')
    seen=set() if seen is None else seen;key=str(Path(path).resolve())
    if key in seen:raise EP.PlanError('COMPOSE_ROUTE_INVALID','路由收据循环或重复引用')
    seen.add(key)
    if route.get('asset_results') is not None:
        entries=route['asset_results']
        if not isinstance(entries,list) or not entries:raise EP.PlanError('COMPOSE_ROUTE_INVALID','多资产路由为空')
        leaves=[]
        for item in entries:
            if not isinstance(item,dict) or not isinstance(item.get('route_receipt_file'),str) or not item['route_receipt_file']:
                raise EP.PlanError('COMPOSE_ROUTE_INVALID','多资产子项缺少路由文件')
            child_path=item['route_receipt_file'];child=_read(child_path)
            if child.get('asset')!=item.get('asset'):raise EP.PlanError('COMPOSE_ROUTE_INVALID','父子路由资产不一致')
            leaves+=route_leaf_files(child,child_path,seen)
        return leaves
    return [(route,path)]


def evidence(plan,params):
    """Select existing, complete receipts only; never manufacture financial evidence."""
    import static_page as SP
    out=copy.deepcopy(params);task=plan['task_id'];roles=plan['runtime_roles'];snapshots=plan.get('snapshot_roles',[])
    out['task_id']=task
    if snapshots and not roles:
        out['live_data_mode']='verified_snapshot'
        return out,SP._validate_publish_data_evidence(out)
    if not roles:
        return out,SP._validate_publish_data_evidence(out)
    out['live_data_mode']='mixed' if snapshots else 'live'
    explicit=out.get('route_receipt_file')
    paths=[Path(explicit)] if explicit else sorted(C.task_temp_path(task,'live_data_route_receipts').glob('*.json'))
    wanted={str(Path(r['validation_receipt_file']).resolve()):r['contract_fingerprint'] for r in roles};matches=[]
    for path in paths:
        try:
            route=_read(path);leaves=route_leaf_files(route,path)
            if route.get('task_id')!=task or any(r.get('task_id')!=task for r,_ in leaves):continue
            selected=[s for r,_ in leaves for s in r.get('selected_routes',[])]
            if {str(Path(s.get('receipt_file','')).resolve()) for s in selected}!=set(wanted):continue
            if any(_read(path).get('contract_fingerprint')!=fingerprint for path,fingerprint in wanted.items()):continue
            if any(s.get('contract_fingerprint') and s['contract_fingerprint']!=wanted[str(Path(s['receipt_file']).resolve())] for s in selected):continue
            candidate=copy.deepcopy(out);candidate['route_receipt_file']=str(path.resolve())
            candidate['validation_receipt_files']=[r['validation_receipt_file'] for r in roles if r['kind']=='package']
            candidate['grant_validation_receipt_files']=[r['validation_receipt_file'] for r in roles if r['kind']=='grant']
            if route.get('asset'):candidate['asset']=route['asset']
            elif route.get('asset_results'):candidate.pop('asset',None)
            if route.get('turn_id'):candidate.setdefault('turn_id',route['turn_id'])
            error=SP._validate_publish_data_evidence(candidate)
            if error is None:matches.append(candidate)
        except (EP.PlanError,OSError,ValueError,KeyError,TypeError):continue
    if len(matches)==1:return matches[0],None
    code='COMPOSE_ROUTE_AMBIGUOUS' if len(matches)>1 else 'COMPOSE_ROUTE_REQUIRED'
    return out,{'code':1,'error':code,'message':'请指定同任务且完整覆盖当前合同的route_receipt_file；不重复验证或注册','matching_candidates':[c['route_receipt_file'] for c in matches]}


def prepare(plan,params=None):
    task=plan['task_id'];root=editable_root(task)
    with EP.locked(task):
        prior=_prior(plan,root);incoming=params or {}
        source={**prior,**{k:v for k,v in incoming.items() if k in PASS_FIELDS or k in ('panels','unassigned_panels')}}
        if prior.get('plan_hash')!=plan['plan_hash'] and not incoming.get('route_receipt_file'):
            source.pop('route_receipt_file',None);source.pop('asset',None)
        EP._no_secrets(source)
        modules=[m['module'] for m in plan['borrow_modules']]
        if not modules:raise EP.PlanError('COMPOSE_MODULES_REQUIRED','先用fork_compose确认目标模块')
        draft={k:copy.deepcopy(v) for k,v in source.items() if k in PASS_FIELDS}
        draft.update(task_id=task,page_id=plan['target_page_id'],plan_hash=plan['plan_hash'])
        draft.setdefault('title','');draft.setdefault('live_card',False)
        panels=[];orphans=copy.deepcopy(source.get('unassigned_panels') or [])
        for p in copy.deepcopy(source.get('panels') or []):
            if not isinstance(p,dict):raise EP.PlanError('COMPOSE_PANEL_INVALID','panels必须是对象数组')
            if (p.get('compose_module') or p.get('title')) not in modules:orphans.append(p);continue
            p.setdefault('compose_module',p.get('title'))
            if p.get('type') in ('text','image'):
                for key in ('runtime_role_id','grant_id','package_id','signature'):p.pop(key,None)
            panels.append(p)
        for module in modules:
            if not any(p.get('compose_module')==module for p in panels):
                panels.append({'type':'text','title':module,'compose_module':module,'text':''})
        draft['panels']=panels
        if orphans:draft['unassigned_panels']=orphans
        records,issues=registrations(plan)
        normalized,binding_issues=normalize_panels(plan,draft);draft=normalized
        consumed={p.get('runtime_role_id') for p in draft['panels'] if p.get('type') not in ('text','image')}
        for role in plan['runtime_roles']:
            if role['kind']=='grant' and any(p.get('grant_id')==role.get('grant_id') and p.get('type') not in ('text','image') for p in draft['panels']):consumed.add(role['role_id'])
            if role['role_id'] in consumed or role['role_id'] not in records:continue
            module=role.get('compose_module') or modules[0]
            if module not in modules:issues.append({'code':'COMPOSE_MODULE_MIGRATION_REQUIRED','role_id':role['role_id']});continue
            if role['kind']=='package':
                if draft.get('package_id') and draft['package_id']!=role['package_id']:
                    issues.append({'code':'COMPOSE_MULTIPLE_PACKAGES_UNSUPPORTED','role_id':role['role_id']});continue
                draft['package_id']=role['package_id']
            draft['panels'].append(_role_panel(role,records[role['role_id']],module))
        draft,error=evidence(plan,draft)
        if error:issues.append(error)
        _,remaining=normalize_panels(plan,draft);issues+=remaining
        EP._no_secrets(draft)
        data=json.dumps(draft,ensure_ascii=False,indent=2).encode('utf-8')+b'\n'
        digest=hashlib.sha256(data).hexdigest();path=root/f'compose-r{plan["revision"]}-{digest[:16]}.json'
        root.mkdir(parents=True,exist_ok=True)
        if not path.resolve().is_relative_to(root.resolve()):raise EP.PlanError('COMPOSE_WORKSPACE_INVALID','草稿路径越界')
        # Existing edited files are never overwritten, even if their old name collides.
        index=0
        while path.exists() and path.read_bytes()!=data:
            index+=1;path=root/f'compose-r{plan["revision"]}-{digest[:16]}-{index}.json'
        if not path.exists():EP.atomic_json(path,draft)
        EP.atomic_json(C.task_temp_path(task,POINTER,create_parent=True),{'task_id':task,'page_id':plan['target_page_id'],'plan_hash':plan['plan_hash'],'params_file':str(path),'revision':plan['revision']})
        return {'next_action':{'command':'compose_page','params_file':str(path),'instruction':'先处理draft_diagnostics，再填写标题和研究文字。保留已绑定数据面板与真实口径，不编辑内部收据；不要原样重试未解决的诊断。'},
                'draft_diagnostics':issues,'draft_ready':not issues,'plan_hash':plan['plan_hash']}
