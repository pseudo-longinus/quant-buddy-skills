"""Reconcile an uncertain local publish journal with a read-only server outcome."""
import urllib.parse

import common as C
import delivery_state as DS
import execution_plan as EP

OUTCOME_PATH = '/skill/publicationOutcome'


def _fail(code, message, **details):
    return {'code': 1, 'error': code, 'message': message, **details}


def _success(plan, result):
    state = result['state']
    return {
        'code': 0,
        'page_id': plan['target_page_id'],
        'reconciled': not result['reused_reconciliation'],
        'reused_reconciliation': result['reused_reconciliation'],
        'delivery_state': state,
        'next_action': (state.get('last_error') or {}).get('next_action'),
    }


def reconcile(params):
    try:
        task = str(params.get('task_id') or '')
        plan = EP.require(task, page_id=params.get('page_id'), plan_hash=params.get('plan_hash'))
        state = DS.load(task, plan['target_page_id'])
        write = state.get('last_write') or {}
        stored_trace = write.get('publish_trace_id')
        requested_trace = str(params.get('trace_id') or '').strip() or None
        if stored_trace and requested_trace and stored_trace != requested_trace:
            return _fail('PUBLISH_RECONCILE_TRACE_CONFLICT', '指定trace与本地写入绑定trace不一致')
        trace_id = stored_trace or requested_trace
        if write.get('status') == 'rejected' and trace_id and DS.find_reconciliation(write, trace_id):
            return _success(plan, {'state': state, 'reused_reconciliation': True})
        if write.get('status') != 'unknown':
            return _fail('PUBLISH_RECONCILE_NOT_ALLOWED', '只有结果不确定的旧写入可以核销')
        local_error = write.get('error_code')
        if not isinstance(local_error, str) or not local_error:
            return _fail('PUBLISH_RECONCILE_NOT_ALLOWED', '旧写入缺少可匹配的服务端错误码，不能核销')
        if not trace_id:
            return _fail('PUBLISH_TRACE_REQUIRED', '旧记录未保存发布trace，必须显式提供准确trace_id')

        cfg = C.load_config_require_key()
        endpoint = C.endpoint_of(cfg)
        query = urllib.parse.urlencode({
            'trace_id': trace_id, 'task_id': task, 'page_id': plan['target_page_id'],
        })
        response = C.http_json('GET', C.api_url(endpoint, OUTCOME_PATH) + '?' + query,
                               C.headers(cfg.get('api_key')), timeout=30)
        if not isinstance(response, dict) or response.get('code') != 0:
            return _fail('PUBLISH_OUTCOME_UNCONFIRMED', '服务端未确认该写入结果，保持unknown',
                         server_error=response.get('error') if isinstance(response, dict) else None)
        result = DS.reconcile_write(plan, trace_id, response.get('data'))
        return _success(plan, result)
    except EP.PlanError as exc:
        return exc.as_dict()
    except (OSError, ValueError, TypeError) as exc:
        return _fail('PUBLISH_OUTCOME_UNCONFIRMED', '无法核对发布结果，保持unknown', detail=str(exc))
