"""Read-only, bounded Host delivery projection. Never loads API credentials or calls APIs."""
import argparse
import json
import re
from urllib.parse import urlsplit
import delivery_state as DS
import execution_plan as EP


def _url(value):
    if not isinstance(value, str) or len(value) > 2048:
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query:
        return None
    return value


def export(task, turn):
    result = {'schema_version': 1, 'task_id': task, 'turn_id': turn, 'status': 'unknown'}
    try:
        if not all(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,159}', v) for v in (task, turn)):
            return result
        plan = EP.load(task)
        if not plan:
            return result
        state = DS.load(task, plan['target_page_id'])
        if state.get('turn_id') != turn:
            return result
        result['page_id'] = plan['target_page_id']
        execution = state.get('execution_status')
        public = state.get('delivery_state')
        write = state.get('last_write') or {}
        remote = write.get('remote') or {}
        if public == 'placeholder' and remote.get('page_id') == plan['target_page_id']:
            result['progress_url'] = _url(remote.get('url'))
        result['status'] = ('failed' if execution == 'failed' else 'waiting_input' if execution == 'waiting_input'
                            else 'placeholder' if public == 'placeholder' else 'unknown')
        good = state.get('last_good_version') or {}
        if (execution == 'succeeded' and public == 'published' and good.get('page_id') == plan['target_page_id']
                and state.get('reply_plan_hash') == plan['plan_hash']
                and all(re.fullmatch(r'[0-9a-f]{64}', str(state.get(k) or '')) for k in ('reply_contract_hash','validated_markdown_sha256'))
                and re.fullmatch(r'[0-9a-f]{64}', str(good.get('sha256') or '')) and good.get('version_no') is not None
                and _url(good.get('url'))):
            result.update(status='succeeded', result_url=_url(good['url']), version_no=good['version_no'])
        error = state.get('last_error') or {}
        for src, dst in [('stage','failure_stage'),('error_code','error_code')]:
            value = str(error.get(src) or '')
            if re.fullmatch(r'[A-Za-z0-9_-]{1,96}', value):
                result[dst] = value
    except (EP.PlanError, ValueError, TypeError, KeyError, OSError):
        return {'schema_version': 1, 'task_id': task, 'turn_id': turn, 'status': 'unknown'}
    return {k:v for k,v in result.items() if v is not None}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--turn-id', required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.task_id, args.turn_id), ensure_ascii=False))
