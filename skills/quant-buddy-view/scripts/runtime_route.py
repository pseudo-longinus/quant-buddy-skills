"""Build route evidence from owned, verified registrations. No network calls."""
import json
from pathlib import Path
import common as C
import execution_plan as EP
import runtime_credentials as RC


def bind(params):
    task = str(params.get('task_id') or '')
    turn = str(params.get('turn_id') or C.current_trace_context().get('turn_id') or '')
    if not turn:
        raise EP.PlanError('ROUTE_TURN_REQUIRED', 'bind_runtime_route需要当前turn_id')
    context = C.current_trace_context()
    if context.get('task_id') and context['task_id'] != task:
        raise EP.PlanError('ROUTE_TASK_MISMATCH', '任务与当前Trace身份不一致')
    if context.get('turn_id') and context['turn_id'] != turn:
        raise EP.PlanError('ROUTE_TURN_MISMATCH', '轮次与当前Trace身份不一致')
    plan = EP.require(task, page_id=params.get('page_id'), plan_hash=params.get('plan_hash'))
    scope = params.get('target_scope', plan['target_scope'])
    if scope != plan['target_scope'] or scope.get('kind') == 'unspecified':
        raise EP.PlanError('ROUTE_SCOPE_MISMATCH', '先在执行计划中声明目标范围')
    roles = params.get('runtime_roles', plan['runtime_roles'])
    if roles != plan['runtime_roles'] or not roles:
        raise EP.PlanError('ROUTE_ROLES_MISMATCH', '路由角色必须与当前计划完全一致')
    selected = []
    for role in roles:
        record = RC.verify_binding(task, role['kind'], role.get('package_id') or role.get('grant_id'), role.get('contract_fingerprint', ''))
        receipt_path = role.get('validation_receipt_file')
        proof = RC._proof(task, role['contract_fingerprint'], receipt_path, required=True)
        registered_proof = record.get('validation_receipt') or {}
        if registered_proof != proof:
            raise EP.PlanError('ROUTE_RECEIPT_MISMATCH', '必须使用注册时核验的原始收据')
        receipt = json.loads(Path(receipt_path).read_text(encoding='utf-8'))
        if receipt.get('turn_id') and receipt['turn_id'] != turn:
            raise EP.PlanError('ROUTE_TURN_MISMATCH', '验证收据属于其他轮次')
        contract = record['contract']
        if EP.digest(contract) != role['contract_fingerprint']:
            raise EP.PlanError('ROUTE_CONTRACT_MISMATCH', '注册合同内容不匹配')
        if role['kind'] == 'package':
            import package_contract as PC
            PC.normalize(contract)
            if not contract.get('reads'):
                raise EP.PlanError('ROUTE_OUTPUTS_REQUIRED', '发布公式包必须声明reads')
            kind = 'formula'
        else:
            kind = contract['kind']
        selected.append({'role': role['role_id'], 'source_role': str(receipt.get('role') or ''),
                         'kind': kind, 'receipt_file': proof['file'],
                         'receipt_sha256': proof['sha256'], 'contract_fingerprint': role['contract_fingerprint']})
    route = {'schema': 'live_data_route_receipt_v1', 'version': 'live_data_route_receipt_v1',
             'task_id': task, 'turn_id': turn, 'page_id': plan['target_page_id'], 'plan_hash': plan['plan_hash'],
             'target_scope': scope, 'status': 'live', 'required_roles_complete': True,
             'static_fallback_allowed': False, 'required_roles': [r['role_id'] for r in roles],
             'attempted_roles': [r['role_id'] for r in roles], 'selected_routes': selected,
             'attempts': [{'role': r['role_id'], 'route': 'registered_runtime', 'status': 'success'} for r in roles]}
    if scope.get('kind') == 'single_asset':
        route['asset'] = scope.get('asset') or scope.get('name')
        if not route['asset']:
            raise EP.PlanError('ROUTE_SCOPE_MISMATCH', '单资产范围缺少资产')
    # Use the publication validator at the producer boundary too. A successful
    # bind must not produce evidence rejected later by Compose/publication.
    import static_page as SP
    evidence_params = {'task_id': task, 'turn_id': turn, 'live_data_mode': 'live',
                       **({'asset': route['asset']} if route.get('asset') else {}),
                       'validation_receipt_files': [x['receipt_file'] for x in selected if x['kind'] == 'formula'],
                       'grant_validation_receipt_files': [x['receipt_file'] for x in selected if x['kind'] != 'formula']}
    error = SP._validate_live_receipts(evidence_params, route)
    if error:
        raise EP.PlanError(error['error'], error['message'])
    path = C.task_temp_path(task, 'live_data_route_receipts/bound-' + EP.digest(route) + '.json', create_parent=True)
    if not path.exists():
        EP.atomic_json(path, route)
    elif json.loads(path.read_text(encoding='utf-8')) != route:
        raise EP.PlanError('ROUTE_RECEIPT_CHANGED', '已保存路由发生变化')
    return {'code': 0, 'route_receipt_file': str(path), 'turn_id': turn, 'task_id': task,
            'live_data_mode': 'live', **({'asset': route['asset']} if route.get('asset') else {}),
            'selected_routes': selected, 'reused_registrations': len(roles),
            'next_action': {'command': 'compose_page' if plan['build_mode'] == 'compose_page' else 'build_dashboard' if plan['build_mode'] == 'unmatched' else 'fork_review_update',
                            'instruction': '沿用草稿并传入返回的route_receipt_file、turn_id、live_data_mode及asset（如有）'}}
