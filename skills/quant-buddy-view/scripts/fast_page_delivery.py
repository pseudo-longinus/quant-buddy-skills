"""Fast-page public receipt and read-only validation of the actual final reply."""
import json
import re
import common as C
import execution_plan as EP
import delivery_state as DS
import publication_transport as PT
from single_stock_reply import AGENT_SUMMARY_MARKER

FILE = 'receipts/new-asset-delivery.json'


def persist_verified(task, turn, page_id, url, draft, *, observe, verify):
    record = dict(schema_version='fast_page_delivery_v1', task_id=task, turn_id=turn,
                  page_id=page_id, url=url, status='failed', error_code='FAST_PAGE_PUBLIC_VERIFICATION_FAILED')
    def save():
        record.pop('receipt_hash', None)
        record['receipt_hash'] = EP.digest(record)
        EP.atomic_json(C.task_temp_path(task, FILE, create_parent=True), record)
    # Invalidate any earlier receipt before starting a new inspection.
    save()
    try:
        before = observe()
        remote = DS._remote(before)
        if (before.get('code') not in (None, 0) or remote['page_id'] != page_id or remote['url'] != url
                or type(remote['version_no']) is not int or remote['version_no'] < 1
                or not re.fullmatch('[a-f0-9]{64}', str(remote['sha256'] or ''))):
            return {'code': 1, 'error': record['error_code']}
        browser = verify(url)
        checked = PT.verify_current({'target_page_id': page_id}, before, observe(), browser_evidence=browser)
        if browser.get('code') != 0 or checked.get('code') != 0:
            return {'code': 1, 'error': checked.get('error') or record['error_code']}
        record.update(remote, status='verified', draft=draft)
        record.pop('error_code', None)
        save()
        return {'code': 0, 'version_no': remote['version_no'], 'sha256': remote['sha256']}
    except (OSError, ValueError, TypeError, KeyError):
        return {'code': 1, 'error': record['error_code']}


def export(task, turn, reply_text='', *, finalize_reply=False):
    unknown = {'schema_version': 1, 'task_id': task, 'turn_id': turn, 'status': 'unknown'}
    try:
        path = C.task_temp_path(task, FILE)
        if path.stat().st_size > 256 * 1024:
            return unknown
        record = json.loads(path.read_text(encoding='utf-8'))
        if (record.get('schema_version') != 'fast_page_delivery_v1' or record.get('task_id') != task
                or record.get('turn_id') != turn
                or record.get('receipt_hash') != EP.digest({k:v for k,v in record.items() if k != 'receipt_hash'})):
            return unknown
        if record.get('status') != 'verified':
            return {**unknown, 'status':'failed', 'failure_stage':'public_verify', 'error_code':'FAST_PAGE_PUBLIC_VERIFICATION_FAILED'}
        if type(record.get('version_no')) is not int or record['version_no'] < 1 or not re.fullmatch('[a-f0-9]{64}', record.get('sha256','')):
            return unknown
        draft = record.get('draft', '').strip()
        reply = str(reply_text or '').strip()
        if draft.count(AGENT_SUMMARY_MARKER) != 1:
            return unknown
        prefix, suffix = draft.split(AGENT_SUMMARY_MARKER)
        # The Host may remove an unsolicited preamble, but only when the entire
        # immutable body is present exactly once and the original ending matches.
        # It must deliver this returned Markdown, not mark the raw reply successful.
        if finalize_reply and prefix and reply.count(prefix) == 1:
            reply = reply[reply.index(prefix):]
        summary = reply[len(prefix):len(reply)-len(suffix)] if suffix else reply[len(prefix):]
        if (not reply.startswith(prefix) or not reply.endswith(suffix) or not summary.strip()
                or (prefix and reply.count(prefix) != 1) or (suffix and reply.count(suffix) != 1)
                or AGENT_SUMMARY_MARKER in reply):
            return {**unknown, 'status':'failed' if reply else 'unknown', 'failure_stage':'reply_validation',
                    'error_code':'FAST_PAGE_REPLY_MISMATCH', 'page_id':record['page_id'], 'progress_url':record['url']}
        result = {**unknown, 'status':'succeeded', 'page_id':record['page_id'], 'result_url':record['url'], 'version_no':record['version_no']}
        if finalize_reply:
            result['validated_markdown'] = reply
        return result
    except (OSError, ValueError, TypeError, KeyError):
        return unknown
