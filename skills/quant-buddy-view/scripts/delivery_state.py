"""Task execution vs published-content state; preserves last good content on failure.

Locks serialize local callers only. No remote atomic/CAS guarantees are claimed.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import common as C
import execution_plan as EP

FILE = 'receipts/delivery-state.json'


def _now(): return datetime.now(timezone.utc).isoformat()


def load(task, page):
    path = C.task_temp_path(task, FILE)
    try: state = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {'version': 'qbv_delivery_state_v1', 'task_id': task, 'page_id': page,
                'execution_status': 'running', 'delivery_state': 'unknown', 'revision': 0,
                'last_good_version': None, 'last_write': None}
    except (OSError, ValueError) as exc: raise EP.PlanError('DELIVERY_STATE_INVALID', '交付状态不可读') from exc
    if state.get('task_id') != task or state.get('page_id') != page:
        raise EP.PlanError('DELIVERY_STATE_IDENTITY_CONFLICT', '交付状态身份不一致')
    if state.get('state_hash') != EP.digest({k: v for k, v in state.items() if k != 'state_hash'}):
        raise EP.PlanError('DELIVERY_STATE_INVALID', '交付状态hash不一致')
    return state


def _save(state):
    state['revision'] += 1
    state['updated_at'] = _now()
    state.pop('state_hash', None)
    state['state_hash'] = EP.digest(state)
    EP.atomic_json(C.task_temp_path(state['task_id'], FILE, create_parent=True), state)
    return state


def initialize(task, page):
    """Only call after successful new_page, not after loading an arbitrary old URL."""
    with EP.locked(task):
        state = load(task, page)
        if state['revision'] == 0:
            state['delivery_state'] = 'placeholder'
            return _save(state)
        return state


def record_progress(plan, params):
    with EP.locked(plan['task_id']):
        state = load(plan['task_id'], plan['target_page_id'])
        requested = params.get('page_status', 'running')
        if requested == 'done': raise EP.PlanError('PROGRESS_TERMINAL_REQUIRED', '交付成功由发布验收生成，不能用进度命令设置')
        state.update(execution_status=requested, current_step=params['current_step'],
                     plan_hash=plan['plan_hash'], required_input=params.get('required_input') if requested == 'waiting_input' else None)
        if requested == 'failed':
            state['last_error'] = {'error_code': params.get('error_code') or 'PROGRESS_FAILED',
                                   'stage': params['current_step'], 'message': params.get('message', ''),
                                   'next_action': params.get('next_action') or {'command': 'delivery_status'}}
        return _save(state)


def _remote(meta):
    return {'page_id': meta.get('page_id'), 'version_no': meta.get('version_no') if meta.get('version_no') is not None else meta.get('current_version_no'),
            'sha256': meta.get('sha256'), 'url': meta.get('public_url') or meta.get('url') or meta.get('download_url')}


def prepare_write(plan, candidate_hash, observed, request_body=None):
    """Record intent before write. Uncertain prior writes never retry blindly."""
    task, page = plan['task_id'], plan['target_page_id']
    current = _remote(observed)
    if current['page_id'] != page or not current['sha256'] or current['version_no'] is None:
        raise EP.PlanError('PUBLISH_VERSION_REQUIRED', '发布前需要同页权威版本与hash，不能盲写')
    with EP.locked(task):
        state = load(task, page)
        previous = state.get('last_write') or {}
        if previous.get('status') in ('pending', 'unknown'):
            raise EP.PlanError('PUBLISH_OUTCOME_UNKNOWN', '前一次写入结果尚不确定；现有接口无法证明请求不会迟到，不自动重发或仅凭哈希猜测成功', next_action='delivery_status')
        if previous.get('status') == 'rejected' and previous.get('request_body_sha256') == (EP.digest(request_body) if request_body is not None else None):
            raise EP.PlanError('PUBLISH_VERSION_CONFLICT','先重新对齐目标内容，不原样重复冲突请求')
        if previous.get('status') == 'confirmed' and previous.get('candidate_hash') == candidate_hash:
            remote = previous.get('remote') or {}
            if current['sha256'] == remote.get('sha256') and current['version_no'] == remote.get('version_no') and (request_body is None or previous.get('request_body_sha256')==EP.digest(request_body)):
                return {'reuse_result': observed, 'state': state}
        last_good = state.get('last_good_version')
        reference = previous.get('remote') if previous.get('status') == 'confirmed' else last_good
        if reference and (current['sha256'], current['version_no']) != (reference.get('sha256'), reference.get('version_no')):
            raise EP.PlanError('PUBLISH_VERSION_CONFLICT', '页面被其他执行者修改；停止覆盖并重新对齐')
        intent = {'status': 'pending', 'candidate_hash': candidate_hash, 'plan_hash': plan['plan_hash'],
                  'base': current, 'idempotency_key': EP.digest([task, page, plan['plan_hash'], candidate_hash, EP.digest(request_body) if request_body is not None else None, current['version_no'], current['sha256']]),
                  'request_body_sha256': EP.digest(request_body) if request_body is not None else None,
                  'started_at': _now(), 'consistency': 'local_lock_and_read_before_write_no_server_cas'}
        state.update(last_write=intent, execution_status='running', current_step='final_publish')
        return {'intent': intent, 'state': _save(state)}


def record_write(plan, result, expected_idempotency_key=None, content_kind='candidate'):
    with EP.locked(plan['task_id']):
        state = load(plan['task_id'], plan['target_page_id'])
        write = state.get('last_write') or {}
        if expected_idempotency_key and write.get('idempotency_key')!=expected_idempotency_key:
            raise EP.PlanError('PUBLISH_RESPONSE_STALE','旧请求响应不能覆盖新发布状态')
        if write.get('status')=='confirmed' and result.get('code')!=0:
            return state # a late failed retry must not erase a confirmed success
        remote = _remote(result)
        if result.get('code') == 0 and remote['page_id'] == plan['target_page_id'] and remote['sha256'] and remote['version_no'] is not None:
            write.update(status='confirmed', remote=remote, confirmed_result={k:v for k,v in result.items() if k not in ('signature','api_key')})
            # Do not promote last_good until the public verification succeeds.
            if content_kind!='progress':state['delivery_state'] = 'partial'
        else:
            error=result.get('error');error=error.get('code') if isinstance(error,dict) else error
            write['status'] = 'rejected' if error in ('PAGE_VERSION_CONFLICT','IDEMPOTENCY_KEY_REUSED','WRITE_APPLIED_NOT_CURRENT') else 'unknown'
            write['error_code']=error
            state.update(execution_status='failed', last_error={'error_code': 'PUBLISH_OUTCOME_UNKNOWN',
                         'next_action': {'command': 'delivery_status'}, 'stage': 'final_publish'})
        state['last_write'] = write
        return _save(state)


def mark_verified(plan, result, *, complete):
    with EP.locked(plan['task_id']):
        state = load(plan['task_id'], plan['target_page_id'])
        write = state.get('last_write') or {}
        if not complete:
            state.update(execution_status='failed', last_error={'error_code': 'PUBLIC_VERIFICATION_FAILED',
                         'next_action': {'command': 'publish_verified'}, 'stage': 'public_verify'})
            return _save(state)
        if write.get('status') != 'confirmed':
            raise EP.PlanError('PUBLISH_RECEIPT_REQUIRED', '公开验收不能替代发布版本收据')
        state.update(execution_status='running', current_step='reply_validation', delivery_state='published',
                     last_good_version=write['remote'], required_input=None, last_error=None)
        return _save(state)


def bind_reply_contract(plan, contract_hash):
    with EP.locked(plan['task_id']):
        state = load(plan['task_id'], plan['target_page_id'])
        if state['delivery_state'] != 'published':
            raise EP.PlanError('PUBLIC_VERIFICATION_REQUIRED', '公开验收后才能绑定终态回复')
        state['reply_contract_hash'] = contract_hash
        state['reply_plan_hash'] = plan['plan_hash']
        return _save(state)


def finish_reply(plan, contract_hash, markdown_hash):
    with EP.locked(plan['task_id']):
        state = load(plan['task_id'], plan['target_page_id'])
        if state.get('reply_contract_hash') != contract_hash or state.get('reply_plan_hash') != plan['plan_hash']:
            raise EP.PlanError('REPLY_CONTRACT_STALE', '回复合同不是当前已验收版本')
        if state['delivery_state'] != 'published' or not state.get('last_good_version'):
            raise EP.PlanError('PUBLIC_VERIFICATION_REQUIRED', '不能在页面验收之前完成任务')
        state.update(execution_status='succeeded', current_step='reply_validated',
                     validated_markdown_sha256=markdown_hash)
        return _save(state)
