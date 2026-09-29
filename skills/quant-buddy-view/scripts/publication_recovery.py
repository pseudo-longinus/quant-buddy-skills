"""Resume a page with verified snapshots without retrying uncertain remote writes."""
import copy
import json
from pathlib import Path
import execution_plan as EP
import compose_inputs as CI
import verified_snapshot as VS


def failure_details(task, result, validations=()):
    result = result if isinstance(result, dict) else {}
    out = {k: result[k] for k in ('cause_code', 'retryable') if k in result}
    out.update(cause_error=result.get('error') or 'REGISTRATION_RESPONSE_INVALID', stage='registration')
    plan = EP.load(task)
    roles = []
    for kind, validation in validations:
        key = 'packages' if kind == 'package' else 'grants'
        for item in (validation or {}).get(key, []):
            candidates = [r for r in (plan or {}).get('runtime_roles', []) if r['kind'] == kind
                          and (r['role_id'] == item.get('name') or r['role_id'] == kind + '.' + str(item.get('name'))
                               or item.get('contract_fingerprint') and r.get('contract_fingerprint') == item['contract_fingerprint'])]
            if len(candidates) == 1:
                roles.append({'role_id': candidates[0]['role_id'], 'validation_receipt_file': item['validation_receipt_file']})
            elif plan and not plan.get('runtime_roles'):
                roles.append({'role_id': kind + '.' + str(item.get('name')), 'validation_receipt_file': item['validation_receipt_file']})
    if plan and roles and not plan.get('require_live_data'):
        out.update(recoverable=True, terminal=False, next_action={'command': 'recover_snapshot', 'params': {
            'task_id': task, 'plan_hash': plan['plan_hash'], 'roles': roles},
            'instruction': '继续同页快照恢复；不重复注册，不把中间失败当最终答复。'})
    else:
        out.update(recoverable=False, terminal=False,
                   next_action=result.get('next_action') or 'materialize_snapshot',
                   recovery_reason='实时要求或验证角色未齐；保留任务并补齐原合同，不改为纯静态内容')
    return out


def registration_error(resource, params, result):
    if result.get('error') not in ('REGISTRATION_REJECTED', 'REGISTRATION_OUTCOME_UNKNOWN', 'REGISTRATION_PERSIST_FAILED'):
        return result
    path = params.get('validation_receipt_file')
    if not path: return result
    try:
        proof = json.loads(Path(path).read_text(encoding='utf-8'))
        task = str(params.get('task_id') or proof.get('task_id') or '')
        if proof.get('task_id') != task or proof.get('status') != 'completed' or proof.get('success') is not True:
            return result
        item = {'name': proof.get('package_name') or proof.get('role') or 'data',
                'contract_fingerprint': proof.get('contract_fingerprint'), 'validation_receipt_file': path}
        details = failure_details(task, result, [(resource, {'packages' if resource == 'package' else 'grants': [item]})])
        if not isinstance(details.get('next_action'), dict):
            details['next_action'] = {'command': 'materialize_snapshot', 'params': {'task_id': task, 'validation_receipt_file': path},
                'instruction': '保留已验证结果；已有页面时继续recover_snapshot，用户实时要求保持不变。'}
        return {**result, **details}
    except (OSError, ValueError, TypeError, EP.PlanError):
        return result


def recover(params):
    import static_page as SP
    task = str(params.get('task_id') or '')
    if not params.get('plan_hash'):
        raise EP.PlanError('PLAN_HASH_REQUIRED', '恢复需要当前计划hash')
    plan = EP.require(task, page_id=params.get('page_id'), plan_hash=params['plan_hash'])
    if plan.get('require_live_data'):
        raise EP.PlanError('PLAN_LIVE_DATA_REQUIRED', '用户要求实时；不能把静态研究页当完整交付，需修复受支持的实时合同')
    roles = params.get('roles') or [r for r in plan['runtime_roles'] if r.get('validation_receipt_file')]
    if not isinstance(roles, list) or not roles or any(not isinstance(r, dict) or not r.get('role_id') or not r.get('validation_receipt_file') for r in roles):
        raise EP.PlanError('RECOVERY_VALIDATION_REQUIRED', '提供各目标角色的已完成验证收据')
    if len({r['role_id'] for r in roles}) != len(roles):
        raise EP.PlanError('PLAN_ROLES_INVALID', '恢复角色重复')
    known = {r['role_id']: r for r in plan['runtime_roles']}
    existing = {r['role_id']: r for r in plan.get('snapshot_roles', [])}
    if known and any(r['role_id'] not in known and r['role_id'] not in existing for r in roles):
        raise EP.PlanError('PLAN_ROLE_CONFLICT', '恢复角色不在当前计划中')
    frozen = {}
    for role in roles:
        result = VS.materialize_registered({'task_id': task, 'validation_receipt_file': role['validation_receipt_file']})
        if result.get('code') != 0:
            return {**result, 'failed_role': role['role_id'], 'terminal': False,
                    'next_action': result.get('next_action') or {'command': 'materialize_snapshot', 'params': {
                        'task_id': task, 'validation_receipt_file': role['validation_receipt_file']}}}
        data = VS.load(task, result['snapshot_receipt_file'], result['snapshot_receipt_sha256'])
        before = known.get(role['role_id'], {})
        if not before and role['role_id'] in existing:
            saved = existing[role['role_id']]
            original = VS.load(task, saved['snapshot_receipt_file'], saved['snapshot_receipt_sha256'])
            before = dict(saved, kind=original['resource'], contract_fingerprint=original['contract_fingerprint'])
        if before and (before['kind'] != data['resource'] or (before.get('contract_fingerprint') and before['contract_fingerprint'] != data['contract_fingerprint'])):
            raise EP.PlanError('SNAPSHOT_CONTRACT_MISMATCH', '恢复快照与当前目标角色合同不一致')
        frozen[role['role_id']] = {'role_id': role['role_id'],
            'snapshot_receipt_file': result['snapshot_receipt_file'], 'snapshot_receipt_sha256': result['snapshot_receipt_sha256'],
            **({'required_outputs': before['required_outputs']} if before.get('required_outputs') else {})}
    runtime = [r for r in plan['runtime_roles'] if r['role_id'] not in frozen]
    snapshots = list({**existing, **frozen}.values())
    incoming = {k: copy.deepcopy(params[k]) for k in CI.PASS_FIELDS if k in params}
    # Preserve the editable research draft; convert only bindings for selected roles.
    prior = CI._prior(plan, CI.editable_root(task))
    panels = copy.deepcopy(params.get('panels', prior.get('panels', [])))
    for panel in panels:
        role_id = panel.get('runtime_role_id')
        if role_id not in frozen:
            matches = [r['role_id'] for r in known.values() if r['role_id'] in frozen and (
                r.get('grant_id') and r['grant_id'] == panel.get('grant_id') or
                r.get('package_id') and r['package_id'] == prior.get('package_id') and not panel.get('grant_id') and panel.get('type') not in ('text', 'image'))]
            role_id = matches[0] if len(matches) == 1 else None
        if role_id in frozen:
            for key in ('runtime_role_id', 'grant_id', 'package_id', 'signature'): panel.pop(key, None)
            panel['snapshot_receipt_file'] = frozen[role_id]['snapshot_receipt_file']
            if 'outputs' in panel: panel['snapshot_outputs'] = panel.pop('outputs')
            if 'output' in panel: panel['snapshot_output'] = panel.pop('output')
    changes = dict(incoming, task_id=task, expected_revision=plan['revision'],
                   revision_reason='registration_recovery_verified_snapshot', runtime_roles=runtime, snapshot_roles=snapshots)
    if plan.get('build_mode') == 'compose_page':
        modules = [m['module'] for m in plan['borrow_modules']]
    elif plan['source_route'] == 'unmatched':
        terms = [p.get('compose_module') or p.get('title') for p in panels if p.get('compose_module') or p.get('title')]
        modules = list(dict.fromkeys(terms)) or ['研究结果']
        changes['borrow_modules'] = [{'module': name, 'borrow_level': 'original',
            'analysis_role': name, 'rationale': '沿用unmatched原创研究范围，用已验证快照恢复生成'} for name in modules]
    elif plan['source_route'] == 'fork':
        research = SP.cmd_research_templates({'task_id': task, 'template_ids': [plan['source_page_id']], 'include': ['layout', 'style']})
        if research.get('code') != 0: return {**research, 'terminal': False}
        digest = json.loads(SP._task_receipt_path(task, SP._RESEARCH_DIGEST_FILE).read_text(encoding='utf-8'))
        entry = next(e for e in digest['templates'] if e['page_id'] == plan['source_page_id'])
        blocks = entry.get('section_blocks', [])
        if not blocks: raise EP.PlanError('COMPOSE_LAYOUT_REQUIRED', '来源无可借鉴的有效section，不能伪造布局')
        terms = list(dict.fromkeys([d['user_term'] for d in (SP._read_intent_profile(task) or {}).get('dimensions', [])]
                                  + [p.get('compose_module') or p.get('title') for p in panels if p.get('compose_module') or p.get('title')])) or ['研究结果']
        borrow = [{'module': term, 'dimension': term, 'borrow_level': 'layout+style',
                   'borrowed_from': {'page_id': plan['source_page_id'], 'ref': 'section:' + str(blocks[0]['sec_id'])},
                   'adaptation': '只复用布局，展示当前任务已验证数据'} for term in terms]
        changes.update(source_template_id=plan['source_page_id'], borrow_plan={'modules': borrow},
                       research_digest_sha256=digest['digest_sha256'], downgraded_from=plan.get('borrow_mode'),
                       downgrade_reason='来源或注册失败后复用布局与已验证快照')
        modules = terms
    else:
        raise EP.PlanError('RECOVERY_COMPOSE_REQUIRED', '先按当前路由准备Compose候选；已物化的快照可复用', snapshot_roles=snapshots)
    for role in frozen.values():
        if not any(p.get('snapshot_receipt_file') == role['snapshot_receipt_file'] for p in panels):
            data = VS.load(task, role['snapshot_receipt_file'])
            panel = {'type': 'table', 'title': role['role_id'], 'compose_module': modules[0],
                     'snapshot_receipt_file': role['snapshot_receipt_file']}
            if data['resource'] == 'package': panel['snapshot_outputs'] = [r['output'] for r in data['contract']['reads']]
            panels.append(panel)
    changes['panels'] = panels
    if plan.get('build_mode') == 'compose_page':
        out = SP.cmd_execution_plan(changes)
    elif plan['source_route'] == 'unmatched':
        route, _, error = SP._read_routing_credential(task)
        if error: return error
        new_plan = EP.bind(route, runtime_roles=runtime, snapshot_roles=snapshots,
                           target_scope=params.get('target_scope'), borrow_modules=changes['borrow_modules'],
                           expected_revision=plan['revision'], revision_reason=changes['revision_reason'])
        out = {'code': 0, 'execution_plan': new_plan, **CI.prepare(new_plan, changes)}
    else:
        out = SP.cmd_fork_compose(changes)
    if out.get('code') == 0:
        out.update(operation='recover_snapshot', page_id=plan['target_page_id'], terminal=False,
                   recovered_roles=list(frozen), message='已保留原页身份并生成快照候选参数；继续compose_page和publish_verified，验收后补链接。')
    return out
