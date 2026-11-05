"""Fast-page public receipt and read-only validation of the actual final reply."""
import json
import re
import common as C
from reply_host_metadata import split_host_metadata
import execution_plan as EP
import delivery_state as DS
import publication_transport as PT
import page_title_contract as PTC
from single_stock_reply import AGENT_SUMMARY_MARKER

FILE = 'receipts/new-asset-delivery.json'


def _verify_observation(page_id, url, expected_title, observed):
    if expected_title is not None and PTC.normalize(observed.get('title')) != expected_title:
        return 'PAGE_TITLE_POSTCHECK_FAILED', None
    remote = DS._remote(observed)
    if (observed.get('code') not in (None, 0) or remote['page_id'] != page_id or remote['url'] != url
            or type(remote['version_no']) is not int or remote['version_no'] < 1
            or not re.fullmatch('[a-f0-9]{64}', str(remote['sha256'] or ''))):
        return 'FAST_PAGE_PUBLIC_VERIFICATION_FAILED', None
    return None, remote


def persist_template_verified(task, turn, page_id, url, draft, *, observe, expected_title=None,
                              source_template=None, page_ready_markdown='',
                              page_ready_data_markdown='', page_ready_tail_markdown='',
                              summary_heading=''):
    """Persist a release-certified template page without per-request Playwright.

    Public page identity, version and hash are still checked before and after
    the receipt is written. Standard fast-page delivery retains Playwright.
    """
    record = dict(schema_version='fast_page_delivery_v1', task_id=task, turn_id=turn,
                  page_id=page_id, url=url, status='failed',
                  error_code='FAST_PAGE_PUBLIC_VERIFICATION_FAILED',
                  verification_mode='release_template_trusted')
    if isinstance(source_template, dict):
        record['source_template'] = source_template
    if page_ready_markdown:
        record['reply_mode'] = 'page_first_answer_v1'
        record['page_ready_markdown'] = str(page_ready_markdown).strip()
        if page_ready_data_markdown:
            record['page_ready_data_markdown'] = str(page_ready_data_markdown).strip()
        if page_ready_tail_markdown:
            record['page_ready_tail_markdown'] = str(page_ready_tail_markdown).strip()
        if summary_heading:
            record['summary_heading'] = str(summary_heading).strip()

    def save():
        record.pop('receipt_hash', None)
        record['receipt_hash'] = EP.digest(record)
        EP.atomic_json(C.task_temp_path(task, FILE, create_parent=True), record)

    save()
    try:
        before = observe()
        error_code, remote = _verify_observation(page_id, url, expected_title, before)
        if error_code:
            record['error_code'] = error_code
            save()
            return {'code': 1, 'error': error_code, 'published': True, 'verified': False}
        after = observe()
        error_code, after_remote = _verify_observation(page_id, url, expected_title, after)
        if error_code:
            record['error_code'] = error_code
            save()
            return {'code': 1, 'error': error_code, 'published': True, 'verified': False}
        checked = PT.verify_current({'target_page_id': page_id}, before, after)
        if checked.get('code') != 0:
            record['error_code'] = checked.get('error') or record['error_code']
            save()
            return {'code': 1, 'error': record['error_code']}
        record.update(after_remote, status='verified', draft=draft, page_title=expected_title)
        record.pop('error_code', None)
        save()
        return {
            'code': 0,
            'version_no': after_remote['version_no'],
            'sha256': after_remote['sha256'],
            'verification_mode': record['verification_mode'],
        }
    except (OSError, ValueError, TypeError, KeyError):
        return {'code': 1, 'error': record['error_code'], 'published': True, 'verified': False}


def persist_verified(task, turn, page_id, url, draft, *, observe, verify, expected_title=None):
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
        if expected_title is not None and PTC.normalize(before.get('title')) != expected_title:
            record['error_code'] = 'PAGE_TITLE_POSTCHECK_FAILED'
            save()
            return {'code': 1, 'error': record['error_code'], 'published': True, 'verified': False}
        remote = DS._remote(before)
        if (before.get('code') not in (None, 0) or remote['page_id'] != page_id or remote['url'] != url
                or type(remote['version_no']) is not int or remote['version_no'] < 1
                or not re.fullmatch('[a-f0-9]{64}', str(remote['sha256'] or ''))):
            return {'code': 1, 'error': record['error_code']}
        browser = verify(url)
        after = observe()
        if expected_title is not None and PTC.normalize(after.get('title')) != expected_title:
            record['error_code'] = 'PAGE_TITLE_POSTCHECK_FAILED'
            save()
            return {'code': 1, 'error': record['error_code'], 'published': True, 'verified': False}
        checked = PT.verify_current({'target_page_id': page_id}, before, after, browser_evidence=browser)
        if browser.get('code') != 0 or checked.get('code') != 0:
            title_failed = expected_title is not None and any(
                'PAGE_TITLE_' in str(problem) for problem in browser.get('problems') or [])
            record['error_code'] = ('PAGE_TITLE_POSTCHECK_FAILED' if title_failed
                                    else checked.get('error') or record['error_code'])
            record['public_verification'] = browser
            save()
            return {'code': 1, 'error': record['error_code'], 'published': True, 'verified': False,
                    'public_verification': browser}
        record.update(remote, status='verified', draft=draft, page_title=expected_title)
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
            return {**unknown, 'status':'failed', 'failure_stage':'public_verify',
                    'error_code':record.get('error_code') or 'FAST_PAGE_PUBLIC_VERIFICATION_FAILED'}
        if type(record.get('version_no')) is not int or record['version_no'] < 1 or not re.fullmatch('[a-f0-9]{64}', record.get('sha256','')):
            return unknown
        draft = record.get('draft', '').strip()
        reply = str(reply_text or '').strip()
        reply, host_metadata = split_host_metadata(reply)
        if host_metadata:
            from validate_agent_reply import _SENSITIVE_PATTERNS
            if any(pattern.search(host_metadata) for _, pattern in _SENSITIVE_PATTERNS):
                return {**unknown, 'status': 'failed', 'failure_stage': 'reply_validation',
                        'error_code': 'SENSITIVE_CONTENT'}
        if record.get('reply_mode') == 'page_first_answer_v1':
            page_ready = str(record.get('page_ready_markdown') or '').strip()
            if not page_ready or not reply.startswith(page_ready):
                return {**unknown, 'status': 'failed', 'failure_stage': 'reply_validation',
                        'error_code': 'FAST_PAGE_REPLY_MISMATCH', 'page_id': record['page_id'],
                        'progress_url': record['url']}
            data_markdown = str(record.get('page_ready_data_markdown') or '').strip()
            lead = f'{page_ready}\n\n---\n\n{data_markdown}' if data_markdown else page_ready
            if not reply.startswith(lead):
                return {**unknown, 'status': 'failed', 'failure_stage': 'reply_validation',
                        'error_code': 'FAST_PAGE_REPLY_MISMATCH', 'page_id': record['page_id'],
                        'progress_url': record['url']}
            analysis = reply[len(lead):].lstrip(' -\n')
            if not analysis or AGENT_SUMMARY_MARKER in reply:
                return {**unknown, 'status': 'failed', 'failure_stage': 'reply_validation',
                        'error_code': 'FAST_PAGE_REPLY_MISMATCH', 'page_id': record['page_id'],
                        'progress_url': record['url']}
            summary_heading = str(record.get('summary_heading') or '').strip()
            if summary_heading and (not analysis.startswith(summary_heading)
                    or reply.count(summary_heading) != 1):
                return {**unknown, 'status': 'failed', 'failure_stage': 'reply_validation',
                        'error_code': 'FAST_PAGE_REPLY_MISMATCH', 'page_id': record['page_id'],
                        'progress_url': record['url']}
            tail = str(record.get('page_ready_tail_markdown') or '').strip()
            if tail and not reply.rstrip().endswith(tail):
                return {**unknown, 'status': 'failed', 'failure_stage': 'reply_validation',
                        'error_code': 'FAST_PAGE_REPLY_MISMATCH', 'page_id': record['page_id'],
                        'progress_url': record['url']}
            result = {**unknown, 'status': 'succeeded', 'page_id': record['page_id'],
                      'result_url': record['url'], 'version_no': record['version_no']}
            if finalize_reply:
                result['validated_markdown'] = reply + host_metadata
            return result
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
            result['validated_markdown'] = reply + host_metadata
        return result
    except (OSError, ValueError, TypeError, KeyError):
        return unknown
