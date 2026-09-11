"""Recoverable existing-file publication. Journal never contains credentials or raw errors.

Only HTML artifacts (needed for faithful restoration) may contain page runtime grants;
keep the caller's task workspace private. Do not collect config/API keys in artifacts.
"""
import contextlib
import hashlib
import json
import os
import re
from pathlib import Path
import tempfile
import time


# Verified against skill_server/src/service/staticTracker.js and Test's stored HTML.
# Unknown scripts are NEVER stripped merely because they borrow this id.
KNOWN_TRACKER_RUNTIME_SHA256 = {'8fa77a59cb13426720cd1be6a51ddab7931d1441fc870a3e042870e7592e9de0'}
TRACKER_RE = re.compile(r'<script\s+id=["\']qb-static-tracker["\']\s*>(.*?)</script>\s*', re.I | re.S)


def tracker_free_html(html, page_id=None, *, server_attested=False):
    def remove(match):
        inner=match.group(1)
        prefix='window.__QB_TRACK_CONFIG__='
        if not inner.startswith(prefix): raise ValueError('unrecognized tracker config')
        config,end=json.JSONDecoder().raw_decode(inner[len(prefix):])
        offset=len(prefix)+end
        if inner[offset:offset+1]!=';': raise ValueError('invalid tracker config boundary')
        if config.get('app')!='quant-buddy-view' or config.get('endpoint')!='https://www.quantbuddy.cn/webapi/skill/track':
            raise ValueError('unexpected tracker endpoint/app')
        if not config.get('page_id') or (page_id and config['page_id']!=page_id):
            raise ValueError('tracker page mismatch')
        runtime=inner[offset+1:]
        if not server_attested and digest(runtime) not in KNOWN_TRACKER_RUNTIME_SHA256:
            raise ValueError('unrecognized tracker runtime')
        return ''
    return TRACKER_RE.sub(remove,html)


class PublishError(Exception):
    pass


def digest(value):
    return hashlib.sha256(value.encode('utf-8') if isinstance(value, str) else value).hexdigest()


def atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.publish-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextlib.contextmanager
def locked(root):
    """OS advisory lock: released on process death; never delete a peer's lock file."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'publish.lock').open('a+b') as handle:
        handle.seek(0, 2)
        if not handle.tell():
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise PublishError('FILE_PUBLISH_BUSY')
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def binding_root():
    # Persistent per-user default; workers must configure this directory on shared storage.
    value = os.environ.get('QBV_FILE_BINDING_DIR')
    root = Path(value) if value else Path.home() / '.quantbuddy' / 'file-publication-bindings'
    if not root.is_absolute():
        raise PublishError('FILE_PUBLISH_BINDING_DIR_ABSOLUTE_REQUIRED')
    return root.resolve()


def binding_path(endpoint, identity, kind):
    return binding_root() / kind / (digest(endpoint + '\0' + identity) + '.json')


def register_binding(state, root):
    """Pointers only; journal remains authoritative. Register BEFORE a network write."""
    task, endpoint = state['task_id'], state['endpoint']
    path = binding_path(endpoint, task, 'tasks')
    with locked(path.parent):
        try:
            entries = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
        except (OSError, ValueError):
            raise PublishError('FILE_PUBLISH_BINDING_UNREADABLE')
        value = str(root.resolve())
        if value not in entries:
            entries.append(value)
            atomic(path, json.dumps(entries).encode('utf-8'))
    if state.get('page_id'):
        path = binding_path(endpoint, state['page_id'], 'pages')
        with locked(path.parent):
            if path.exists():
                try:
                    old = json.loads(path.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    raise PublishError('FILE_PUBLISH_BINDING_UNREADABLE')
                if old != value:
                    raise PublishError('FILE_PUBLISH_PAGE_ALREADY_BOUND')
            else:
                atomic(path, json.dumps(value).encode('utf-8'))


def mutation_guard(sp, params, endpoint, *, action):
    """Do not let ordinary update/upload silently escape a previously managed page."""
    task = str(params.get('task_id') or sp.C.current_trace_context().get('task_id') or '')
    page = str(params.get('page_id') or '')
    roots = set()
    try:
        if task:
            path = binding_path(endpoint, task, 'tasks')
            if path.exists(): roots.update(json.loads(path.read_text(encoding='utf-8')))
        if page:
            path = binding_path(endpoint, page, 'pages')
            if path.exists(): roots.add(json.loads(path.read_text(encoding='utf-8')))
        for root in roots:
            path = Path(root) / 'publication.json'
            record = json.loads(path.read_text(encoding='utf-8'))
            if record.get('endpoint') != endpoint:
                raise PublishError('FILE_PUBLISH_BINDING_MISMATCH')
            matches = (page and record.get('page_id') == page) or (action == 'upload' and not page and record.get('task_id') == task)
            if not matches: continue
            supplied = params.get('file_publish_dir')
            if not supplied or Path(supplied).resolve() != Path(root).resolve() or not sp._is_preserve_html_qbs_live(params):
                return {'code': 1, 'error': 'FILE_PUBLISH_MANAGED_UPDATE_REQUIRED', 'recoverable': True,
                        'page_id': record.get('page_id'), 'bound_task_id': record.get('task_id'),
                        'file_publish_dir': str(Path(root)),
                        'message': '该任务/页面已绑定可恢复发布记录。保留原file_publish_dir及transformation_mode，使用同页update；内容重做用file_enhancement_mode=content，不得省略记录绕过验收。'}
        if params.get('file_publish_dir') and not sp._is_preserve_html_qbs_live(params):
            return {'code': 1, 'error': 'FILE_PUBLISH_TRANSFORMATION_MODE_REQUIRED',
                    'message': '有file_publish_dir时必须保留transformation_mode=preserve_html_qbs_live。'}
    except (OSError, ValueError, TypeError, PublishError):
        return {'code': 1, 'error': 'FILE_PUBLISH_BINDING_UNREADABLE',
                'message': '发布绑定不可读；恢复原工作目录后继续，不能退回普通写入。'}
    return None


class Publication:
    def __init__(self, sp, params, endpoint, api_key):
        self.sp, self.params, self.endpoint, self.api_key = sp, dict(params), endpoint, api_key
        if 'snapshot_only' in params and not isinstance(params['snapshot_only'], bool):
            raise PublishError('PRESERVE_HTML_SNAPSHOT_ONLY_INVALID')
        root = Path(str(params.get('file_publish_dir') or ''))
        if not root.is_absolute():
            raise PublishError('FILE_PUBLISH_DIR_ABSOLUTE_REQUIRED')
        root = root.resolve()
        skill = Path(sp.C.SKILL_ROOT).resolve()
        if root == skill or skill in root.parents:
            raise PublishError('FILE_PUBLISH_DIR_MUST_BE_TASK_WORKSPACE')
        task = str(params.get('task_id') or sp.C.current_trace_context().get('task_id') or '')
        if not task:
            raise PublishError('FILE_PUBLISH_TASK_REQUIRED')
        self.root, self.task = root, task
        self.path = root / 'publication.json'
        self.state = {}

    def load(self):
        if self.path.exists():
            try:
                self.state = json.loads(self.path.read_text(encoding='utf-8'))
            except (ValueError, OSError):
                raise PublishError('FILE_PUBLISH_STATE_UNREADABLE')
            if self.state.get('schema') != 'qbv_file_publication_v1' or self.state.get('task_id') != self.task or self.state.get('endpoint') != self.endpoint:
                raise PublishError('FILE_PUBLISH_STATE_BINDING_MISMATCH')
            source = self.params.get('source_html_sha256')
            if source and source != self.state.get('source_sha256'):
                raise PublishError('FILE_PUBLISH_SOURCE_CHANGED')
            page = self.params.get('page_id')
            if page and page != self.state.get('page_id'):
                # A lost CREATE receipt can only be resolved by explicit page + hash check.
                if not (self.state.get('operation', {}).get('kind') == 'create' and not self.state.get('page_id')):
                    raise PublishError('FILE_PUBLISH_PAGE_BINDING_MISMATCH')
        return self.state

    def save(self):
        self.state['updated_at'] = time.time()
        atomic(self.path, json.dumps(self.state, ensure_ascii=False, indent=2).encode('utf-8'))
        register_binding(self.state, self.root)

    def artifact(self, html):
        sha = digest(html)
        path = self.root / 'versions' / (sha + '.html')
        atomic(path, html.encode('utf-8'))
        return {'file': str(path), 'sha256': sha}

    def backup_metadata(self, record):
        # Omitted fields must be restored to null, not left at the rejected candidate's values.
        value = {k: record.get(k) for k in ('title', 'description', 'page_context', 'agent_reply_template', 'reply_contract_binding')}
        text = json.dumps(value, ensure_ascii=False)
        ref = {'file': str(self.root / 'versions' / (digest(text) + '.json')), 'sha256': digest(text)}
        atomic(ref['file'], text.encode('utf-8'))
        self.state['previous_metadata'] = ref

    def read_artifact(self, artifact):
        path = Path(artifact['file']).resolve()
        if self.root not in path.parents:
            raise PublishError('FILE_PUBLISH_ARTIFACT_OUTSIDE_WORKSPACE')
        value = path.read_bytes().decode('utf-8')
        if digest(value) != artifact['sha256']:
            raise PublishError('FILE_PUBLISH_ARTIFACT_CHANGED')
        return value

    def remote(self, page_id=None):
        result = self.sp.cmd_download({'page_id': page_id or self.state.get('page_id')})
        if not isinstance(result, dict) or result.get('code') != 0 or not isinstance(result.get('html'), str):
            raise PublishError('FILE_PUBLISH_REMOTE_UNAVAILABLE')
        if result.get('page_id') != (page_id or self.state.get('page_id')):
            raise PublishError('FILE_PUBLISH_REMOTE_ID_MISMATCH')
        # is_live describes QBS runtime bindings, not publication availability.
        # An accessible all-Snapshot page is intentionally is_live=False.
        if result.get('sha256_match') is False or result.get('status') in {'revoked','expired','deleted','inactive'}:
            raise PublishError('FILE_PUBLISH_REMOTE_INVALID')
        return result

    def verify(self, target, profile):
        try:
            result = self.sp._run_page_verifier(target, profile)
            allowed = {'EMPTY_SOURCE_SNAPSHOT','BROKEN_IMAGES','LOCAL_RESOURCE_REFERENCE',
                       'HORIZONTAL_OVERFLOW','SCRIPT_ERROR','RESOURCE_LOAD_FAILED','DOCUMENT_HTTP_ERROR'}
            diagnostic = {'code': result.get('code', 1), 'profile': profile,
                          'target_kind': 'public' if str(target).startswith(('https://','http://')) else 'local',
                          'problems': [p for p in result.get('problems', []) if p in allowed]}
            if result.get('error') in {'FILE_SNAPSHOT_BROWSER_CHECK_FAILED','BROWSER_VERIFICATION_TIMEOUT'}:
                diagnostic['error'] = result['error']
            diagnostic['viewports'] = [{k: v[k] for k in ('width','hasContent','brokenImages','horizontalOverflow',
                                     'scriptErrors','resourceErrors','ignoredIdlePosters') if k in v}
                                     for v in result.get('browser', {}).get('viewports', []) if isinstance(v, dict)]
            self.state['last_verification'] = diagnostic
            return result.get('code') == 0
        except Exception:
            self.state['last_verification'] = {'code':1,'profile':profile,'error':'FILE_VERIFICATION_PROCESS_FAILED'}
            return False

    def response(self, problem=None):
        state = self.state
        delivered = bool(state.get('last_good'))
        result = {
            'code': 0 if delivered else 1,
            'page_id': state.get('page_id'), 'public_url': state.get('public_url'),
            'delivery_stage': state.get('stage', 'not_published'),
            'page_delivered': delivered,
            'last_verified_at': state.get('last_verified_at'),
            'current_page_verified': bool(delivered and state.get('operation', {}).get('status') == 'verified' and not state.get('problem')),
            'snapshot_published_first': bool(state.get('snapshot_published_first')),
            'source_snapshot_published': bool(state.get('snapshot_published_first')),
            'transformation_status': state.get('transformation_status', 'pending'),
            'publish_sequence': state.get('publish_sequence', []),
            'file_publish_dir': str(self.root),
            'next_action': ('continue_authorized_enhancement_same_page' if state.get('static_delivery') else 'deliver_static_link_then_continue_authorized_enhancement'
                            if state.get('stage') == 'static_snapshot' else
                            'continue_same_page' if delivered else 'resolve_publication_state'),
        }
        if problem or state.get('problem'):
            result['stage_error'] = problem or state['problem']
            result['next_action'] = 'resolve_stage_error_on_same_page'
            if state.get('last_verification'):
                result['verification'] = state['last_verification']
            if state.get('candidate'):
                candidate = Path(state['candidate']['file']).as_posix()
                result['candidate_html_file'] = candidate
                result['candidate_verification_command'] = 'node scripts/verify_file_snapshot.mjs ' + json.dumps(candidate, ensure_ascii=False)
                result['recovery_hint'] = '先执行candidate_verification_command查看实际问题。不要用未编译的原HTML猜测缺少分享壳；编译后的候选已在该路径。验证通过后保留file_publish_dir重试同页update，不得改用普通写入。'
        if delivered:
            result['static_delivery_confirmed'] = bool(state.get('static_delivery'))
            if state.get('stage') == 'static_snapshot' and not state.get('static_delivery'):
                result['required_user_message'] = '原始静态版本已托管并验收：[查看活页](' + str(state.get('public_url')) + ')。当前为Snapshot。'
                result['next_action'] = 'emit_required_user_message_before_next_tool_then_file_confirm_delivery'
            self.sp._attach_agent_reply_contract(result, operation='update')
            contract = result.get('agent_reply_contract', {})
            if isinstance(contract, dict):
                contract['terminal'] = state.get('stage') == 'enhanced'
                contract['file_publication_schema'] = 'qbv_file_publication_v1'
                contract['delivery_link_label'] = '可分享活页'
                contract['file_delivery_label'] = ('原始静态版本' if state.get('stage') == 'static_snapshot'
                                                   else '同页增强版本')
            result['file_delivery_hint'] = '本文件流程所有版本链接统一称可分享活页，按实际数据另说明Snapshot/Live，不套用可分享实时活页固定措辞。若有required_user_message，下一次工具调用前先把这句话发给用户，再运行file_confirm_delivery。不得把工具返回的URL当成用户已收到；确认后继续已授权增强。'
            if isinstance(contract, dict) and result.get('required_user_message'):
                contract['reply_instruction'] = result['file_delivery_hint']
                contract['required_user_message'] = result['required_user_message']
        return result

    def fail(self, problem):
        self.state['problem'] = problem
        self.save()
        return self.response(problem)

    def write(self, html, kind, *, metadata=None):
        """Persist intent BEFORE network; a crash is always a recoverable unknown write."""
        candidate = self.artifact(html)
        self.state['operation'] = {'kind': kind, 'status': 'pending', 'candidate': candidate}
        self.state['problem'] = None
        self.save()
        params = self.params if metadata is None else metadata
        page_id = self.state.get('page_id')
        body = self.sp._publish_body(params, html, page_id=page_id, snapshot_stage=kind in ('create', 'snapshot'))
        try:
            out = self.sp.C.http_json('POST', self.sp.C.api_url(self.endpoint, self.sp._PATH['update' if page_id else 'upload']),
                                      self.sp.C.headers(self.api_key), body, timeout=self.sp._UPLOAD_TIMEOUT)
        except Exception:
            return self.fail('FILE_PUBLISH_WRITE_UNCONFIRMED')
        # Nonzero transport responses may be timeouts or committed writes. Never assume absence.
        if not isinstance(out, dict) or out.get('code') != 0:
            if isinstance(out, dict) and out.get('code') in (400, 401, 403, 404, 413, 422):
                self.state['operation']['status'] = 'rejected'
                return self.fail('FILE_PUBLISH_WRITE_REJECTED')
            return self.fail('FILE_PUBLISH_WRITE_UNCONFIRMED')
        returned_id = out.get('page_id') or page_id
        if not returned_id or (page_id and returned_id != page_id):
            return self.fail('FILE_PUBLISH_ID_UNCONFIRMED')
        self.state['page_id'] = returned_id
        url = self.sp._record_url(out)
        if url:
            self.state['public_url'] = self.sp._delivery_public_url(url)
            self.state['verification_url'] = url
        self.state['operation']['status'] = 'written'
        if isinstance(out.get('sha256'),str) and re.fullmatch(r'[0-9a-fA-F]{64}',out['sha256']):
            self.state['operation']['server_sha256']=out['sha256'].lower()
            self.state['operation']['tracker_injected']=out.get('tracker_injected') is True
        self.save()  # Identity survives failed browser checks and process restart.
        return self.finish_written()

    def matches_write(self, html, *, page_id=None):
        op=self.state['operation']
        client=self.read_artifact(op['candidate'])
        remote_sha=digest(html)
        expected=op.get('server_sha256')
        if expected and remote_sha!=expected:
            return False
        if remote_sha==op['candidate']['sha256']:
            return True
        try:
            # A successful write response authenticates its exact stored bytes. Without it,
            # recovery accepts only the pinned standard runtime, not arbitrary id-labelled JS.
            attested=bool(expected and op.get('tracker_injected'))
            source=tracker_free_html(client, server_attested=(op.get('kind')=='restore'))
            actual=tracker_free_html(html, page_id or self.state.get('page_id'), server_attested=attested)
            return source==actual
        except (ValueError,TypeError):
            return False

    def finish_written(self):
        op = self.state['operation']
        try:
            remote = self.remote()
        except PublishError as exc:
            return self.fail(str(exc))
        sha = digest(remote['html'])
        if not self.matches_write(remote['html']):
            # Eventual consistency and third-party writes are both unsafe to overwrite.
            return self.fail('FILE_PUBLISH_REMOTE_VERSION_CONFLICT')
        op['published']=self.artifact(remote['html'])
        op['server_sha256']=sha
        self.save()
        url = remote.get('url') or self.state.get('verification_url')
        if url:
            self.state['verification_url'] = url
            self.state['public_url'] = self.sp._delivery_public_url(url)
        if not url:
            return self.fail('FILE_PUBLISH_URL_REQUIRED')
        if not self.verify(url, 'file-snapshot'):
            if op['kind'] == 'restore':
                op['status'] = 'restore_pending'
                return self.fail('FILE_PUBLISH_RESTORE_VERIFICATION_FAILED')
            if self.state.get('previous'):
                return self.restore()
            op['status'] = 'verification_pending'
            return self.fail('FILE_PUBLISH_STATIC_VERIFICATION_FAILED')
        restored = op['kind'] == 'restore'
        self.state['last_good'] = op['published']
        self.state['last_verified_at'] = time.time()
        if restored:
            self.state['stage'] = self.state.get('previous_stage', 'existing_page')
            self.state['problem'] = 'FILE_PUBLISH_CANDIDATE_REJECTED_RESTORED'
        else:
            initial = op['kind'] in ('create', 'snapshot')
            self.state['snapshot_published_first'] = True
            self.state['stage'] = 'static_snapshot' if initial else 'enhanced'
            self.state['transformation_status'] = 'pending' if initial else self.state.get('candidate_status', 'complete')
            self.state['problem'] = None
        self.state.setdefault('publish_sequence', []).append(op['kind'])
        op['status'] = 'verified'
        self.save()
        return self.response()

    def restore(self):
        op = self.state['operation']
        try:
            current = self.remote()
            if digest(current['html']) != op.get('published',op['candidate'])['sha256']:
                return self.fail('FILE_PUBLISH_RESTORE_VERSION_CONFLICT')
            previous = self.state['previous']
            html = self.read_artifact(previous)
        except (PublishError, OSError) as exc:
            return self.fail(str(exc) if isinstance(exc, PublishError) else 'FILE_PUBLISH_RESTORE_ARTIFACT_UNAVAILABLE')
        # No server CAS exists: guard with immediate read, report the remaining race in docs.
        metadata = json.loads(self.read_artifact(self.state['previous_metadata'])) if self.state.get('previous_metadata') else {}
        self.state['restore_from_sha256'] = op.get('published',op['candidate'])['sha256']
        return self.write(html, 'restore', metadata=metadata)

    def confirm_delivery(self):
        if not self.state.get('last_good') or not self.state.get('snapshot_published_first'):
            return self.response('FILE_STATIC_VERSION_NOT_VERIFIED')
        message = str(self.params.get('delivery_message') or '')
        url = self.state.get('public_url')
        if self.params.get('page_id') != self.state.get('page_id') or self.params.get('public_url') != url or not url or url not in message:
            return self.response('FILE_STATIC_DELIVERY_REFERENCE_MISMATCH')
        # CLI cannot inspect chat UI. This is explicitly an agent attestation, not UI evidence.
        # Hosts/acceptance tests must independently check the preceding user-visible message.
        if not self.state.get('static_delivery'):
            self.state['static_delivery'] = {'confirmed_at': time.time(), 'page_id': self.state['page_id'],
                'message_sha256': digest(message), 'url_sha256': digest(url), 'evidence_kind': 'agent_attestation'}
            self.save()
        result = self.response()
        result['enhancement_instruction'] = '确认已记录。若用户要求纠错/重做，生成自包含主体HTML，沿用第一版参数、file_publish_dir和page_id，设置snapshot_only:false、file_enhancement_mode:content、html_file，直接调用update。update内部先编译分享壳并验收再写入，不需要手工retrofit，也不要把未编译主体的ui-refinement/额外字号门槛作为前置。仅接QBS时保留preserve口径门禁；无可接入指标时如实保留Snapshot。'
        return result

    def repair_snapshot(self):
        """Repair display on a known written first page without being trapped by its failed QA."""
        op = self.state.get('operation', {})
        if self.state.get('last_good') or op.get('kind') not in ('create', 'snapshot') or op.get('status') not in ('written', 'verification_pending'):
            return self.fail('FILE_PUBLISH_SNAPSHOT_REPAIR_NOT_APPLICABLE')
        try:
            remote = self.remote()
            if digest(remote['html']) != op.get('published',op['candidate'])['sha256']:
                return self.fail('FILE_PUBLISH_REMOTE_VERSION_CONFLICT')
            candidate, error = self.sp._read_html(self.params)
            if error or self.sp._publish_html_error(candidate):
                return self.fail('FILE_PUBLISH_REPAIR_HTML_INVALID')
            artifact = self.artifact(candidate)
            if not self.verify(artifact['file'], 'file-snapshot'):
                return self.fail('FILE_PUBLISH_REPAIR_BROWSER_FAILED')
            if digest(self.remote()['html']) != op['candidate']['sha256']:
                return self.fail('FILE_PUBLISH_REMOTE_VERSION_CONFLICT')
            return self.write(candidate, 'snapshot')
        except PublishError as exc:
            return self.fail(str(exc))

    def reconcile(self):
        op = self.state['operation']
        page = self.state.get('page_id') or self.params.get('page_id')
        if not page:
            return self.fail('FILE_PUBLISH_CREATE_UNCONFIRMED_SUPPLY_PAGE_ID')
        try:
            remote = self.remote(page)
        except PublishError as exc:
            return self.fail(str(exc))
        if not self.matches_write(remote['html'], page_id=page):
            # If an update is confirmed not applied, retain it as unresolved rather than guessing
            # a delayed request cannot still commit. Operator/server evidence is required to retry.
            return self.fail('FILE_PUBLISH_WRITE_UNCONFIRMED_OR_CONFLICT')
        self.state['page_id'] = page
        self.state['operation']['status'] = 'written'
        self.save()
        return self.finish_written()

    def run(self, *, status_only=False, confirm_delivery=False):
        with locked(self.root.parent / '.task-locks' / digest(self.task)), locked(self.root):
            self.load()
            if self.state:
                register_binding(self.state, self.root)
            if confirm_delivery:
                return self.confirm_delivery()
            if status_only:
                if not self.state:
                    return self.response('FILE_PUBLISH_STATE_NOT_FOUND')
                if self.params.get('reconcile', True) and self.state.get('operation', {}).get('status') not in (None, 'verified', 'rejected'):
                    return self.reconcile()
                return self.response()
            if self.params.get('file_repair') is True:
                return self.repair_snapshot()
            if self.state.get('operation', {}).get('status') == 'rejected':
                if self.state['operation']['kind'] == 'restore':
                    # Restoration cannot be retried without checking the version it replaces.
                    try:
                        if digest(self.remote()['html']) != self.state.get('restore_from_sha256'):
                            return self.fail('FILE_PUBLISH_RESTORE_VERSION_CONFLICT')
                        metadata = json.loads(self.read_artifact(self.state['previous_metadata'])) if self.state.get('previous_metadata') else {}
                        return self.write(self.read_artifact(self.state['previous']), 'restore', metadata=metadata)
                    except PublishError as exc:
                        return self.fail(str(exc))
                self.state.pop('operation')
                self.save()  # Explicitly rejected create/update may be retried, never ambiguous writes.
            if self.state.get('operation', {}).get('status') not in (None, 'verified'):
                return self.reconcile()
            if not self.state:
                snapshot, resolution, error = self.sp._prepare_preserve_snapshot_stage({**self.params, "snapshot_only": True})
                if error:
                    return error
                self.state = {'schema': 'qbv_file_publication_v1', 'task_id': self.task, 'endpoint': self.endpoint,
                              'source_sha256': self.params.get('source_html_sha256'),
                              'original_sha256': self.params.get('source_original_sha256'),
                              'page_id': self.params.get('page_id'), 'stage': 'prepared',
                              'source': self.artifact(snapshot['html']), 'publish_sequence': []}
                self.save()
                if self.state.get('page_id'):
                    try:
                        current = self.remote()
                        if not self.verify(current.get('url'), 'file-snapshot'):
                            return self.fail('FILE_PUBLISH_EXISTING_BACKUP_NOT_VERIFIED')
                        self.state['verification_url'] = current.get('url')
                        self.state['public_url'] = self.sp._delivery_public_url(current.get('url'))
                        self.backup_metadata(current)
                        self.state['previous'] = self.artifact(current['html'])
                        self.state['previous_stage'] = 'existing_page'
                        self.state['last_good'] = self.state['previous']
                    except PublishError as exc:
                        # Do not latch a half-initialized record as an enhanced page.
                        self.state['stage'] = 'prepared'
                        return self.fail(str(exc))
                return self.write(snapshot['html'], 'snapshot' if self.state.get('page_id') else 'create', metadata=snapshot['params'])
            if self.state.get('stage') == 'prepared' and not self.state.get('operation'):
                # Backup failure may be retried without recreating page identity.
                if self.state.get('page_id'):
                    try:
                        current = self.remote()
                        if not self.verify(current.get('url'), 'file-snapshot'):
                            return self.fail('FILE_PUBLISH_EXISTING_BACKUP_NOT_VERIFIED')
                        self.state['verification_url'] = current.get('url')
                        self.state['public_url'] = self.sp._delivery_public_url(current.get('url'))
                        self.backup_metadata(current)
                        self.state['previous'] = self.artifact(current['html'])
                        self.state['last_good'] = self.state['previous']
                        self.state['previous_stage'] = 'existing_page'
                    except PublishError as exc:
                        return self.fail(str(exc))
                snapshot, _, error = self.sp._prepare_preserve_snapshot_stage({**self.params, "snapshot_only": True})
                if error:
                    return error
                return self.write(snapshot['html'], 'snapshot' if self.state.get('page_id') else 'create', metadata=snapshot['params'])
            if self.params.get('snapshot_only') is True:
                return self.response()  # repeated first-stage calls never reset enhanced content
            # No candidate read/query/write before the initial link delivery checkpoint.
            if not self.state.get('static_delivery'):
                return self.response('FILE_STATIC_LINK_DELIVERY_REQUIRED')
            # All later enhancement is read/validate/build first; no snapshot rewrite.
            try:
                remote = self.remote()
                expected = self.state.get('last_good', {}).get('sha256')
                if digest(remote['html']) != expected:
                    return self.fail('FILE_PUBLISH_REMOTE_VERSION_CONFLICT')
                html, error = self.sp._read_html(self.params)
                if error:
                    return self.fail('FILE_PUBLISH_CANDIDATE_UNAVAILABLE')
                mode = self.params.get('file_enhancement_mode', 'preserve')
                if mode == 'preserve':
                    stage, validation, error = self.sp._prepare_preserve_live_stage(self.params, html, endpoint=self.endpoint)
                elif mode == 'content':
                    # Explicit user-authorized rewrite; ordinary gates still apply. No fake fidelity flags.
                    p = dict(self.params)
                    p.pop('transformation_mode', None)
                    validation, error = self.sp._validate_transformation_contract(p, html, endpoint=self.endpoint)
                    stage = None
                    if not error:
                        html, shell = self.sp._ensure_share_shell(html, p)
                        error = self.sp._publish_html_error(html) or self.sp._validate_reply_metadata_pair(p)
                        check = self.sp._maybe_verify_card_runtime(html, p) if not error else None
                        if check and not check.get('ok'):
                            error = {'code': 1}
                        stage = {'html': html, 'validation': validation, 'shell_check': shell}
                else:
                    return self.fail('FILE_PUBLISH_ENHANCEMENT_MODE_INVALID')
                if error:
                    return self.fail('FILE_PUBLISH_CANDIDATE_VALIDATION_FAILED')
                artifact = self.artifact(stage['html'])
                self.state['candidate'] = artifact
                if not self.verify(artifact['file'], 'file-snapshot'):
                    return self.fail('FILE_PUBLISH_CANDIDATE_BROWSER_FAILED')
                # Recheck immediately before write; never overwrite a known competing update.
                if digest(self.remote()['html']) != expected:
                    return self.fail('FILE_PUBLISH_REMOTE_VERSION_CONFLICT')
                self.backup_metadata(remote)
                self.state['previous'] = self.state['last_good']
                self.state['previous_stage'] = self.state['stage']
                self.state['candidate_status'] = (validation or {}).get('transformation_status', 'complete')
                return self.write(stage['html'], 'enhance')
            except PublishError as exc:
                return self.fail(str(exc))
            except (ValueError, OSError):
                return self.fail('FILE_PUBLISH_CANDIDATE_PREPARATION_FAILED')


def run(sp, params, endpoint, api_key, *, status_only=False, confirm_delivery=False):
    try:
        return Publication(sp, params, endpoint, api_key).run(status_only=status_only, confirm_delivery=confirm_delivery)
    except PublishError as exc:
        return {'code': 1, 'error': str(exc)}
    except (OSError, ValueError):
        # State errors must not erase an in-flight journal or leak raw response credentials.
        return {'code': 1, 'error': 'FILE_PUBLISH_STATE_IO_ERROR',
                'next_action': 'inspect_saved_publication_before_any_retry'}
