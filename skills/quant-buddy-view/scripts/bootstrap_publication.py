"""Task-bound creation receipt: uncertain creates are never blindly repeated."""
import json
import common as C
import execution_plan as EP
import delivery_state as DS

FILE='receipts/page-bootstrap.json'

def load(task):
    path=C.task_temp_path(task,FILE)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}

_TRANSIENT_HINTS = ('timeout', 'timed out', 'connection', 'network', '502', '503', '504', 'unreachable', 'eof', 'reset')


def _is_definite_rejection(result):
    """Distinguish deterministic server rejections (safe to fix & retry) from
    uncertain transport/5xx outcomes (must lock as PUBLISH_OUTCOME_UNKNOWN)."""
    if not isinstance(result, dict):
        return False
    if result.get('_transport_error') is True:
        return False
    # Host proxy / prewrite guard explicitly attested that no remote write started.
    if result.get('registration_mutation_started') is False:
        return True
    http_status = result.get('_http_status')
    if type(http_status) is int:
        if 400 <= http_status < 500:
            return True
        if http_status >= 500:
            return False
    code = result.get('code')
    if type(code) is int and 400 <= code < 500:
        return True
    if type(code) is int and code >= 500:
        return False
    # Structured business rejection JSON from QuantBuddy API (typically code=-1 or code=1
    # with explicit message/error, and no transport/5xx indicators).
    msg = str(result.get('message') or result.get('detail') or (
        result.get('error', {}).get('message') if isinstance(result.get('error'), dict) else result.get('error')
    ) or '').strip()
    if msg and not any(hint in msg.lower() for hint in _TRANSIENT_HINTS):
        if result.get('success') is False or (type(code) is int and code != 0):
            return True
    return False


def write(task,body,endpoint,key,path,timeout):
    with EP.locked(task):
        previous=load(task)
        fingerprint=EP.digest(body)
        if previous.get('status') in ('pending','unknown'):
            return {'code':1,'error':'PUBLISH_OUTCOME_UNKNOWN','message':'页面创建结果未知；保留收据，禁止重复创建','published':False}
        if previous.get('status') == 'confirmed':
            if previous.get('request_hash') == fingerprint: return {**previous['result'],'reused_existing_page':True}
            return {'code':1,'error':'BOOTSTRAP_PAGE_ALREADY_CREATED','page_id':previous['result']['page_id'],'message':'已有唯一目标页；继续原页面，禁止另建'}
        receipt={'task_id':task,'turn_id':C.current_trace_context().get('turn_id'),'status':'pending','request_hash':fingerprint}
        receipt_path=C.task_temp_path(task,FILE,create_parent=True)
        EP.atomic_json(receipt_path,receipt)
        try: result=C.http_json('POST',C.api_url(endpoint,path),C.headers(key),body,timeout=timeout)
        except (OSError,ValueError): result={'code':1,'_transport_error':True}
        remote=DS._remote(result if isinstance(result,dict) else {})
        if isinstance(result,dict) and result.get('code') == 0 and remote.get('page_id') and remote.get('url'):
            data=result.get('data') if isinstance(result.get('data'),dict) else {}
            receipt.update(status='confirmed',result={'code':0,'page_id':remote['page_id'],'url':remote['url'],
                           'title':result.get('title') or data.get('title'),
                           'sha256':remote.get('sha256'),'version_no':remote.get('version_no')})
        else:
            receipt['status']='rejected' if _is_definite_rejection(result) else 'unknown'
        EP.atomic_json(receipt_path,receipt)
        if receipt['status']=='unknown': return {'code':1,'error':'PUBLISH_OUTCOME_UNKNOWN','message':'页面初始化请求未取得确定身份；禁止重发，保留同任务恢复信息','published':False}
        return result

def record_read_failure(task,result):
    if not task: return
    if isinstance(result,dict) and result.get('code') == 0:
        with EP.locked(task):
            state=load(task)
            if state.get('read_failures'):
                state['read_failures']=0;EP.atomic_json(C.task_temp_path(task,FILE,create_parent=True),state)
        return
    if not any(word in str(result).lower() for word in ('timeout','timed out','connection','network','503','502','504','unreachable')): return
    with EP.locked(task):
        state=load(task);state['read_failures']=state.get('read_failures',0)+1
        EP.atomic_json(C.task_temp_path(task,FILE,create_parent=True),state)
