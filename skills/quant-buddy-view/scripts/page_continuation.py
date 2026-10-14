"""Shared QBS routing for evidence handoff and the fixed-page write boundary.

The classifier runs read-only in its own interpreter so QBS/QBV modules with the
same names cannot shadow each other. Data readiness is never delivery evidence.
"""
import json
import os
import subprocess
import sys

import common as C


def _classify(payload):
    resolution = C.resolve_qbs_skill_root()
    root = resolution.get('root')
    script = root / 'scripts' / 'live_page_routing.py' if root else None
    if script is None or not script.is_file():
        return {'code': 1, 'error': 'PAGE_CLASSIFIER_UNAVAILABLE'}
    env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
    try:
        result = subprocess.run(
            [sys.executable, str(script), 'route', json.dumps(payload, ensure_ascii=False)],
            capture_output=True, text=True, encoding='utf-8', env=env, timeout=20,
        )
        route = json.loads(result.stdout)
        if result.returncode or not isinstance(route, dict) or route.get('code') != 0:
            return {'code': 1, 'error': 'PAGE_CLASSIFIER_FAILED'}
        return {key: route[key] for key in (
            'code', 'route', 'route_reason', 'page_reference', 'page_workflow',
            'asset', 'requires_persistence_confirmation',
        ) if key in route}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {'code': 1, 'error': 'PAGE_CLASSIFIER_FAILED'}


def route_request(params):
    """Recheck the original question; a caller-supplied fast hint is not authority."""
    import execution_plan as EP
    task = str(params.get('task_id') or '')
    reference = params.get('page_reference')
    requested = params.get('page_requested') is True or bool(params.get('page_workflow')) or bool(reference)
    payload = {'user_query': params.get('user_query', ''), 'page_requested': requested,
               'page_reference': reference,
               'persistence_confirmed': params.get('persistence_confirmed') is True}
    route = _classify(payload)
    # An explicit opt-out also wins over an unreadable old plan.
    if route.get('route') == 'none' and 'static_image_only' in route.get('route_reason', []):
        return {**route, 'page_delivery_required': False}
    try:
        plan = EP.load(task) if task else None
    except EP.PlanError as exc:
        # Keep query evidence usable, but do not invent a replacement page.
        return {'code': 1, 'error': exc.code, 'page_delivery_required': True}
    if not reference and (plan or {}).get('target_page_id'):
        requested = True
        route = _classify({**payload, 'page_requested': True, 'page_reference': plan['target_page_id']})
    if route.get('code') != 0:
        return {**route, 'page_delivery_required': requested or os.environ.get('QBS_DEFAULT_PAGE_REQUESTED') == '1'}
    route['page_delivery_required'] = route.get('route') in ('create', 'existing_page')
    if route.get('route') == 'existing_page':
        route['execution_plan_available'] = bool(plan)
    if route.get('page_workflow') == 'single_a_stock_fast':
        # The publisher must not accept a different asset than the question.
        asset = params.get('asset')
        identity = _classify({'user_query': asset}) if isinstance(asset, str) and asset else {}
        if (params.get('assets') or (asset and
                identity.get('asset', {}).get('ticker') != route.get('asset', {}).get('ticker'))):
            route.pop('page_workflow', None)
            route['route_reason'] = [*route.get('route_reason', []), 'asset_scope_mismatch']
    return route


def handoff(params, result, route):
    """Add continuation ahead of large evidence, preserving all legacy statuses."""
    required = route.get('page_delivery_required') is True
    fields = {'page_delivery_required': required, 'page_route': route,
              'data_status_note': 'status/success 仅表示数据查询与验证状态，不代表页面已生成、发布或验收。'}
    if not required:
        return fields
    task = params.get('task_id')
    evidence = result.get('publication_evidence', {})
    step = {
        'precondition': '先以非终止消息发送已验证业务答案及实际日期、单位和缺口，随后同轮继续；此对象不证明首答已送达。',
        'workflow': 'template_or_compose',
        'guide': 'guides/answer-first.md',
        'tool': 'static_page.py templates',
        'params': {'task_id': task, 'recommend': 'all'},
        'publication_evidence': evidence,
        'instruction': '页面仍待交付。复用本轮证据与答案结构完成选路、构建、公开验收和回复校验；不要重查已验证角色，也不要用最终文字答案结束。',
    }
    if route.get('code') != 0 or result.get('error') or result.get('status') == 'blocked':
        step.update(workflow='resolve_blocker', instruction='保留已验证结果，按原错误类别修复取数或路由阻断；权限拒绝与系统错误不能冒充无数据。实际恢复失败后说明具体阻断。')
        step.pop('tool')
        step.pop('params')
    elif route.get('route') == 'existing_page':
        reference = route['page_reference']
        resume = route.get('execution_plan_available') is True
        step.update(workflow='existing_page', guide='workflows/planned-delivery-recovery.md',
                    tool='static_page.py delivery_status' if resume else 'static_page.py interpret',
                    params=({'task_id': task} if resume else
                            {'task_id': task, 'url' if str(reference).startswith(('https://', 'http://')) else 'page_id': reference}),
                    instruction='复用原页身份及本轮证据，按现有原位更新/恢复流程继续；没有计划时先完成原页归属检查和计划绑定，不新建替代页。')
    elif (route.get('page_workflow') == 'single_a_stock_fast'
          and result.get('required_roles_complete') is True and result.get('answer_evidence')
          and any(item.get('role') == 'profile' for item in result['answer_evidence'])):
        step.update(workflow='single_a_stock_fast', tool='static_page.py new_asset_page',
                    params={'task_id': task, 'asset': params['asset'],
                            'user_query': params['user_query'], 'reply_mode': 'page_followup'},
                    fallback='宿主不能中途展示首答时继续建页并使用 reply_mode=full_answer，不声称已提前交付。')
    elif result.get('status') in ('incomplete', 'static_fallback_allowed'):
        step['instruction'] = '先披露实际日期与缺口，复用已有有效数据继续部分研究页；确无可用数据时沿既有方法页合同处理。不得把缺数据当零值或零命中。'
    fields['after_business_answer'] = step
    return fields
