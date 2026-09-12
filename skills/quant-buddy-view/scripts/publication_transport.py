"""Skill-only publication through the existing updateStaticPage API.

The journal prevents this task from blindly replaying uncertain writes. It is not
server-side idempotency or atomic compare-and-swap, and makes no such guarantee.
"""
import copy
import hashlib
import re
import common as C
import execution_plan as EP
import delivery_state as DS

UPDATE_PATH = '/skill/updateStaticPage'
CONSISTENCY = 'local_lock_and_read_before_write_no_server_cas'
AUDIT_FIELDS = {'trace_evidence', 'user_query'}


def mutation_body(body):
    return {key: value for key, value in body.items() if key not in AUDIT_FIELDS}


def _fail(code, message, **details):
    return {'code': 1, 'error': code, 'message': message, **details}


def _check_ack(plan, intent, result):
    remote = DS._remote(result)
    version = remote['version_no']
    if (result.get('code') != 0 or remote['page_id'] != plan['target_page_id']
            or not isinstance(version, int) or isinstance(version, bool)
            or version <= intent['base']['version_no']
            or not re.fullmatch(r'[a-f0-9]{64}', str(remote['sha256'] or ''))
            or not remote['url']):
        raise EP.PlanError('PUBLISH_ACK_INVALID', '现有更新接口未返回目标页的有效版本/哈希/链接；不能确认发布成功')


def write(plan, body, endpoint, key, observe, content_kind='candidate'):
    try:
        with EP.locked(plan['task_id']):
            EP.require(plan['task_id'], page_id=body.get('page_id'), plan_hash=plan['plan_hash'])
            body = copy.deepcopy(body)
            observed = observe()
            if (not isinstance(observed, dict) or observed.get('code') not in (None, 0)
                    or observed.get('page_id') != plan['target_page_id']):
                return _fail('PUBLISH_VERSION_REQUIRED', '无法读取现有目标页面身份/版本；未写入')
            previous = DS.load(plan['task_id'], plan['target_page_id']).get('last_write') or {}
            if previous.get('status') in ('pending', 'unknown'):
                return _fail('PUBLISH_OUTCOME_UNKNOWN', '上次更新结果不确定；现有接口不能证明请求是否仍会执行，不自动重发或改用新任务绕过',
                             next_action={'command': 'delivery_status'}, write_consistency=CONSISTENCY)
            candidate_hash = hashlib.sha256(body['html'].encode('utf-8')).hexdigest()
            prepared = DS.prepare_write(plan, candidate_hash, observed, request_body=mutation_body(body), content_kind=content_kind)
            if prepared.get('reuse_result'):
                result = previous.get('confirmed_result')
                if not result:
                    return _fail('PUBLISH_RECEIPT_REQUIRED', '缺少上次已确认的发布收据；不自动重复更新')
                _check_ack(plan, previous, result)
                return {**result, 'reused_existing_version': True, 'write_consistency': CONSISTENCY}
            intent = prepared['intent']
            # Match the established API exactly: do not send invented conditional
            # fields or depend on new capabilities/status/reconciliation endpoints.
            try:
                result = C.http_json('POST', C.api_url(endpoint, UPDATE_PATH), C.headers(key), body, timeout=600)
            except (OSError, TimeoutError, ValueError):
                result = _fail('PUBLISH_OUTCOME_UNKNOWN', '更新请求未取得确定结果；保留现场且不自动重发')
            if not isinstance(result, dict):
                result = _fail('PUBLISH_RESPONSE_INVALID', '未取得结构化更新响应')
            if result.get('code') == 0:
                try:
                    _check_ack(plan, intent, result)
                except EP.PlanError as exc:
                    result = exc.as_dict()
            DS.record_write(plan, result, expected_idempotency_key=intent['idempotency_key'], content_kind=content_kind)
            return {**result, 'reused_existing_version': False, 'write_consistency': CONSISTENCY}
    except EP.PlanError as exc:
        return exc.as_dict()
    except (OSError, ValueError, KeyError, TypeError):
        return _fail('PUBLISH_JOURNAL_INVALID', '本地发布日志或版本证据不完整；保留状态并停止写入')


def verify_current(plan, published, observed, browser_evidence=None):
    if (observed.get('page_id') != plan['target_page_id']
            or DS._remote(observed)['version_no'] != DS._remote(published)['version_no']
            or observed.get('sha256') != published.get('sha256')):
        return _fail('PUBLISH_VERSION_CHANGED', '公开验收期间页面版本变化，不能确认当前交付')
    if browser_evidence is not None:
        viewports = (browser_evidence.get('browser') or {}).get('viewports') or []
        if not viewports or any(view.get('document_sha256') != published.get('sha256') for view in viewports):
            return _fail('PUBLIC_DOCUMENT_MISMATCH', '浏览器实际主文档字节不是已发布版本，不能用后台metadata代替公网验证')
    return {'code': 0, 'version_no': DS._remote(observed)['version_no'], 'sha256': observed.get('sha256'),
            'write_consistency': CONSISTENCY}
