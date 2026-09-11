"""Revisioned task execution plan; local atomicity only, not a remote publishing CAS."""
import hashlib
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
import common as C

VERSION = 'qbv_execution_plan_v1'
FILE = 'receipts/execution-plan.json'

class PlanError(ValueError):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details
    def as_dict(self):
        return {'code': 1, 'error': self.code, 'message': str(self), 'retryable': False, **self.details}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, scratch = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(scratch, path)
    finally:
        if os.path.exists(scratch): os.unlink(scratch)


_LOCKS = {}
_LOCKS_GUARD = threading.Lock()
_LOCK_DEPTH = threading.local()


@contextmanager
def locked(task_id):
    """Reentrant in one thread, exclusive across threads/processes sharing the task path."""
    path = C.task_temp_path(task_id, 'receipts/execution-plan.lock', create_parent=True)
    name = str(Path(path).resolve())
    with _LOCKS_GUARD:
        mutex = _LOCKS.setdefault(name, threading.RLock())
    if not mutex.acquire(blocking=False):
        raise PlanError('PLAN_BUSY', '另一执行者正在处理该任务', retryable=True, next_action='retry_after_backoff')
    depths = getattr(_LOCK_DEPTH, 'depths', None)
    if depths is None:
        depths = _LOCK_DEPTH.depths = {}
    try:
        if depths.get(name, 0):
            depths[name] += 1
            try: yield
            finally: depths[name] -= 1
            return
        with open(path, 'a+b') as handle:
            handle.seek(0, 2)
            if handle.tell() == 0: handle.write(b'0'); handle.flush()
            handle.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise PlanError('PLAN_BUSY', '另一执行者正在处理该任务', retryable=True, next_action='retry_after_backoff') from exc
            depths[name] = 1
            try: yield
            finally:
                depths.pop(name, None)
                handle.seek(0)
                if os.name == 'nt': msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        mutex.release()


def load(task_id):
    if not task_id: return None
    path = C.task_temp_path(task_id, FILE)
    try: value = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError: return None
    except (OSError, ValueError) as exc: raise PlanError('PLAN_UNREADABLE', '任务计划无法读取，不能回退旧路径') from exc
    if not isinstance(value, dict): raise PlanError('PLAN_INVALID', '任务计划必须是对象')
    unsigned = {k: v for k, v in value.items() if k != 'plan_hash'}
    if value.get('schema_version') != VERSION or value.get('task_id') != task_id or value.get('plan_hash') != digest(unsigned):
        raise PlanError('PLAN_HASH_MISMATCH', '任务计划身份、版本或哈希不一致')
    return value


def _no_secrets(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in {'signature', 'api_key', 'authorization', 'access_token', 'secret'}:
                raise PlanError('PLAN_CREDENTIAL_FORBIDDEN', '执行计划只能引用受控凭据，不能携带秘密')
            _no_secrets(item)
    elif isinstance(value, list):
        for item in value: _no_secrets(item)


def bind(routing, *, target_scope=None, runtime_roles=None, borrow_modules=None,
         expected_revision=None, revision_reason='', compose_binding_sha256=None, snapshot_roles=None, require_live_data=None):
    task = str(routing.get('task_id') or '')
    page = str(routing.get('page_id') or '')
    decision = routing.get('routing_decision') or {}
    if not task or not page: raise PlanError('PLAN_IDENTITY_REQUIRED', '先创建/恢复同任务的目标page_id')
    with locked(task):
        previous = load(task)
        mode = decision.get('mode')
        borrow = decision.get('borrow_mode') if mode == 'fork' else None
        if mode not in ('fork', 'direct', 'unmatched'): raise PlanError('PLAN_ROUTE_INVALID', '需要有效路由')
        content = {
            'schema_version': VERSION, 'task_id': task, 'target_page_id': page,
            'source_route': mode, 'source_page_id': decision.get('source_template_id') or '',
            'borrow_mode': borrow,
            'target_scope': target_scope if target_scope is not None else (previous or {}).get('target_scope', {'kind': 'unspecified'}),
            'runtime_roles': runtime_roles if runtime_roles is not None else (previous or {}).get('runtime_roles', []),
            'snapshot_roles': snapshot_roles if snapshot_roles is not None else (previous or {}).get('snapshot_roles', []),
            'require_live_data': require_live_data if require_live_data is not None else (previous or {}).get('require_live_data', False),
            'borrow_modules': borrow_modules if borrow_modules is not None else (previous or {}).get('borrow_modules', []),
            'compose_binding_sha256': compose_binding_sha256 if compose_binding_sha256 is not None else (previous or {}).get('compose_binding_sha256'),
            'build_mode': 'compose_page' if borrow == 'compose' else ('inherit' if mode == 'fork' else mode),
            'plan_stage': 'prepared' if (target_scope is not None or runtime_roles is not None or borrow_modules is not None or (previous or {}).get('plan_stage') == 'prepared') else 'routing',
        }
        if not isinstance(content["require_live_data"],bool):raise PlanError("PLAN_LIVE_REQUIREMENT_INVALID","require_live_data必须为布尔值")
        if previous and previous.get("require_live_data") and not content["require_live_data"]:
            raise PlanError("PLAN_LIVE_REQUIREMENT_IMMUTABLE","不能用技术性修订取消用户实时要求；快照只能作为部分交付")
        _no_secrets(content)
        scope = content['target_scope']
        if not isinstance(scope, dict) or scope.get('kind') not in ('unspecified', 'single_asset', 'basket', 'sector', 'index', 'market'):
            raise PlanError('PLAN_SCOPE_INVALID', 'target_scope必须声明单资产或集合范围')
        roles = content['runtime_roles']
        if not isinstance(roles, list) or any(not isinstance(r, dict) or not r.get('role_id') or r.get('kind') not in ('grant', 'package') for r in roles):
            raise PlanError('PLAN_ROLES_INVALID', '运行角色需要唯一role_id和grant/package类型')
        if len({r['role_id'] for r in roles}) != len(roles): raise PlanError('PLAN_ROLES_INVALID', '运行角色重复')
        snapshots=content['snapshot_roles']
        if not isinstance(snapshots,list) or any(not isinstance(role,dict) or not role.get('role_id') or not role.get('snapshot_receipt_sha256') or not role.get('snapshot_receipt_file') for role in snapshots):
            raise PlanError('PLAN_SNAPSHOT_INVALID','快照角色必须包含role_id及不可变收据文件/hash')
        if len({role['role_id'] for role in snapshots})!=len(snapshots):raise PlanError('PLAN_SNAPSHOT_INVALID','快照角色重复')
        if snapshots:
            import verified_snapshot as VS
            for role in snapshots:VS.load(task,role['snapshot_receipt_file'],role['snapshot_receipt_sha256'])
        if previous:
            for key in ('target_page_id', 'source_page_id', 'source_route'):
                if previous.get(key) != content[key]: raise PlanError('PLAN_IDENTITY_CONFLICT', '不能变更来源或目标身份', field=key)
            stable = {k: v for k, v in previous.items() if k not in ('revision', 'plan_hash', 'revision_reason', 'previous_plan_hash')}
            stable.setdefault('snapshot_roles',[])
            stable.setdefault('require_live_data',False)
            if stable == content:
                if expected_revision is not None and expected_revision != previous['revision']:
                    raise PlanError('PLAN_REVISION_CONFLICT', '使用了过期计划', actual_revision=previous['revision'])
                return previous
            if previous.get('plan_stage') == 'routing' and expected_revision is None:
                expected_revision, revision_reason = previous['revision'], 'complete_initial_plan'
            if expected_revision != previous['revision'] or not str(revision_reason).strip():
                raise PlanError('PLAN_REVISION_REQUIRED', '计划变化需要expected_revision与revision_reason', actual_revision=previous['revision'])
            atomic_json(C.task_temp_path(task, 'receipts/plan-history/revision-%s.json' % previous['revision'], create_parent=True), previous)
        content.update(revision=(previous or {}).get('revision', 0) + 1,
                       revision_reason=str(revision_reason), previous_plan_hash=(previous or {}).get('plan_hash'))
        content['plan_hash'] = digest(content)
        atomic_json(C.task_temp_path(task, FILE, create_parent=True), content)
        return content


def require(task_id, *, page_id=None, source_page_id=None, plan_hash=None, runtime_roles=None, operation=None):
    value = load(task_id)
    if not value: raise PlanError('PLAN_REQUIRED', '请先创建/恢复执行计划', next_action='execution_plan')
    if page_id is not None and page_id != value['target_page_id']: raise PlanError('PLAN_PAGE_CONFLICT', '目标页不一致')
    if source_page_id is not None and source_page_id != value['source_page_id']: raise PlanError('PLAN_SOURCE_CONFLICT', '来源页不一致')
    if plan_hash is not None and plan_hash != value['plan_hash']: raise PlanError('PLAN_REVISION_CONFLICT', '构建/发布参数属于旧计划')
    if operation == 'fork_prepare' and value['build_mode'] == 'compose_page':
        raise PlanError('COMPOSE_PREPARE_FORBIDDEN', 'Compose计划不能全量继承来源运行时', next_action='compose_page')
    if runtime_roles is not None:
        actual = {(r['role_id'], r['kind']) for r in runtime_roles}
        expected = {(r['role_id'], r['kind']) for r in value['runtime_roles']}
        if actual != expected: raise PlanError('PLAN_ROLE_CONFLICT', '实际运行时角色与目标计划不同')
    return value
