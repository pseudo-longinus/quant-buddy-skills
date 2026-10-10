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


def export(task, turn, reply_text='', *, finalize_reply=False, plan_only=False):
    result = {'schema_version': 1, 'task_id': task, 'turn_id': turn, 'status': 'unknown',
              'page_delivery_required': False}
    try:
        if not all(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,159}', v) for v in (task, turn)):
            return result
        plan = EP.load(task)
        if plan_only:
            if plan and plan.get('delivery_kind')=='methodology' and plan.get('research_status')=='unavailable' and not plan.get('runtime_roles') and not plan.get('snapshot_roles'):
                result.update(page_delivery_required=True,page_id=plan['target_page_id'],delivery_kind='methodology',research_status='unavailable')
            return result
        if not plan:
            import fast_page_delivery as fast
            fast_result = fast.export(task, turn, reply_text, finalize_reply=finalize_reply)
            from qbs_job_lifecycle import find_job
            _,job,_ = find_job(task_id=task,turn_id=turn)
            if job and fast_result.get('status') != 'succeeded':
                fast_result.update(page_delivery_required=True,status='failed' if job.get('status') == 'failed' else 'unknown')
            import common as C
            path=C.task_temp_path(task,'receipts/local-delivery-artifact.json')
            if path.is_file():
                artifact=json.loads(path.read_text(encoding='utf-8'))
                if artifact.get('task_id') == task and artifact.get('turn_id') == turn:
                    fast_result.update({key:artifact[key] for key in ('artifact_file','artifact_sha256','artifact_verified') if key in artifact})
                    fast_result.update(page_delivery_required=True,status='failed',research_status='unavailable',delivery_kind='methodology',live_data_mode='static_content_only')
                    import bootstrap_publication as bootstrap
                    if bootstrap.load(task).get('status') in ('pending','unknown'): fast_result['error_code']='PUBLISH_OUTCOME_UNKNOWN'
            return fast_result
        state = DS.load(task, plan['target_page_id'])
        if state.get('turn_id') != turn:
            return result
        result['page_id'] = plan['target_page_id']
        result['page_delivery_required'] = True
        result['research_status'] = plan.get('research_status', 'unknown')
        result['delivery_kind'] = plan.get('delivery_kind', 'result')
        if state.get('live_data_mode'): result['live_data_mode'] = state['live_data_mode']
        for key in ('artifact_file','artifact_sha256','artifact_verified'):
            if key in state: result[key]=state[key]
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
    parser.add_argument('--reply-file')
    parser.add_argument('--finalize-reply', action='store_true')
    parser.add_argument('--plan-only-projection', action='store_true')
    args = parser.parse_args()
    reply = ''
    if args.reply_file:
        from pathlib import Path
        file = Path(args.reply_file)
        if file.stat().st_size <= 256 * 1024:
            reply = file.read_text(encoding='utf-8')
    print(json.dumps(export(args.task_id, args.turn_id, reply, finalize_reply=args.finalize_reply,plan_only=args.plan_only_projection), ensure_ascii=False))
