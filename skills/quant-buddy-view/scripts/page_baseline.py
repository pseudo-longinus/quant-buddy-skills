"""Persist the version read for editing; never replace it during publication."""
import json
import hashlib
import common as C
import execution_plan as EP


def _path(task,page):
    return C.task_temp_path(task,'receipts/edit-base-'+hashlib.sha256(page.encode()).hexdigest()[:20]+'.json',create_parent=True)


def remember(task,page,version_id):
    if task and page and version_id:
        EP.atomic_json(_path(task,page),{'task_id':task,'page_id':page,'expected_current_version_id':version_id})


def expected(params):
    if params.get('expected_current_version_id'):
        return params['expected_current_version_id']
    task=params.get('task_id') or C.current_trace_context().get('task_id')
    page=params.get('page_id')
    if not task or not page: return None
    path=_path(task,page)
    if not path.is_file(): return None
    value=json.loads(path.read_text(encoding='utf-8'))
    if value.get('task_id')!=task or value.get('page_id')!=page:
        raise ValueError('PAGE_BASELINE_IDENTITY_CONFLICT')
    return value['expected_current_version_id']
