"""Bind a presentation edit to a verified, owned, already-published page.

This is a separate candidate receipt, never a rewritten Compose build receipt.
Publication continues through the normal browser, data and version gates.
"""
import hashlib
import json
import re
from pathlib import Path
import common as C
import execution_plan as EP
import delivery_state as DS

VERSION = 'qbv_presentation_maintenance_v1'


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def contract(document):
    document = document.replace('\r\n', '\n')
    matches = re.findall(r'^const BOOT = (.+);$', document, re.M)
    if len(matches) != 1:
        raise EP.PlanError('MAINTENANCE_RUNTIME_UNSUPPORTED', '此维护入口要求唯一标准看板BOOT合同')
    try:
        boot = json.loads(matches[0])
    except (ValueError, TypeError) as exc:
        raise EP.PlanError('MAINTENANCE_RUNTIME_INVALID', '看板合同不可解析') from exc
    # Only presentation panels/share labels/build time may change. Sources,
    # credentials, read configuration and any future unknown fields stay equal.
    source = {k: v for k, v in boot.items() if k not in ('panels', 'share', 'generatedAt')}
    kernels = re.findall(r'/\* QB_DATA_KERNEL_START:v2 \*/.*?/\* QB_DATA_KERNEL_END:v2 \*/', document, re.S)
    if len(kernels) != 1:
        raise EP.PlanError('MAINTENANCE_RUNTIME_UNSUPPORTED', '维护必须保留唯一标准实时取数内核')
    return EP.digest({'boot': source, 'kernel_sha256': sha(kernels[0])})


def _context(sp, params, plan):
    task, page = plan['task_id'], plan['target_page_id']
    routing, _, error = sp._read_routing_credential(task)
    if error:
        raise EP.PlanError('MAINTENANCE_ROUTE_REQUIRED', '维护路由不可读取')
    reference = (routing or {}).get('existing_page_reference') or {}
    if reference.get('page_id') != page or sp._existing_page_route_mode(reference) != 'in_place':
        raise EP.PlanError('MAINTENANCE_ROUTE_REQUIRED', '先interpret并确认同页原位维护权限')
    state = DS.load(task, page)
    if (state.get('last_write') or {}).get('status') in ('pending', 'unknown'):
        raise EP.PlanError('PUBLISH_OUTCOME_UNKNOWN', '先确认上次发布结果，不准备或重放维护写入')
    if state.get('delivery_state') != 'published' or not state.get('last_good_version'):
        raise EP.PlanError('MAINTENANCE_PUBLISHED_REQUIRED', '此入口只维护已完成公开验收的页面')
    result = sp.cmd_template({'page_id': page})
    if not isinstance(result, dict) or result.get('code') != 0:
        raise EP.PlanError('MAINTENANCE_PAGE_UNAVAILABLE', '无法核对线上页面，未写入')
    meta = sp._template_record(result)
    if meta.get('can_update_in_place') is not True or meta.get('access_role') not in ('owner', 'page_admin'):
        raise EP.PlanError('MAINTENANCE_OWNER_REQUIRED', '维护需要服务端确认owner/page_admin写权限')
    current = DS._remote(meta)
    if (current['page_id'] != page or type(current['version_no']) is not int
            or current['version_no'] < 1 or not re.fullmatch(r'[a-f0-9]{64}', str(current['sha256'] or ''))
            or not str(current['url'] or '').startswith('https://')):
        raise EP.PlanError('MAINTENANCE_BASE_INVALID', '维护基线身份、版本或哈希不完整')
    if current != state['last_good_version']:
        raise EP.PlanError('MAINTENANCE_BASE_CHANGED', '线上版本不是本任务最后已验收版本；先对齐并发修改')
    return current, meta


def _candidate(params):
    path = Path(str(params.get('html_file') or '')).resolve()
    try:
        raw = path.read_bytes()
        document = raw.decode('utf-8')
    except (OSError, UnicodeError) as exc:
        raise EP.PlanError('MAINTENANCE_CANDIDATE_REQUIRED', '提供可读取的UTF-8候选HTML文件') from exc
    return path, document, hashlib.sha256(raw).hexdigest()


def prepare(sp, params):
    try:
        plan = EP.require(str(params.get('task_id') or ''), page_id=params.get('page_id'), plan_hash=params.get('plan_hash'))
        base, meta = _context(sp, params, plan)
        path, document, candidate_hash = _candidate(params)
        source, error = sp._fetch_oss(base['url'])
        if error or sha(source) != base['sha256']:
            raise EP.PlanError('MAINTENANCE_BASE_DOCUMENT_MISMATCH', '线上正文与权威版本哈希不一致')
        runtime = contract(source)
        if contract(document) != runtime:
            raise EP.PlanError('MAINTENANCE_DATA_CONTRACT_CHANGED', '此入口仅支持展示层维护；数据源或实时取数合同变化需要重新验证构建')
        turn = C.current_trace_context().get('turn_id')
        if not turn:
            raise EP.PlanError('MAINTENANCE_TURN_REQUIRED', '维护需要可信的当前用户轮次')
        record = {'version': VERSION, 'task_id': plan['task_id'], 'page_id': plan['target_page_id'],
                  'plan_hash': plan['plan_hash'], 'turn_id': turn, 'base': base,
                  'html_file': str(path), 'html_sha256': candidate_hash, 'runtime_digest': runtime}
        digest = EP.digest(record)
        receipt = C.task_temp_path(plan['task_id'], 'receipts/maintenance/' + digest + '.json', create_parent=True)
        EP.atomic_json(receipt, record)
        publish = {k: v for k, v in params.items() if not k.startswith('_')}
        publish.update(maintenance_mode='presentation', maintenance_receipt_file=str(receipt),
                       maintenance_receipt_sha256=digest, html_file=str(path), plan_hash=plan['plan_hash'])
        publish_path = path.parent / ('maintenance-publish-' + digest[:12] + '.json')
        EP.atomic_json(publish_path, publish)
        return {'code': 0, 'terminal': False, 'page_id': plan['target_page_id'], 'base': base,
                'candidate_sha256': candidate_hash, 'runtime_unchanged': True,
                'maintenance_receipt_file': str(receipt),
                'next_action': {'command': 'publish_verified', 'params_file': str(publish_path)}}
    except EP.PlanError as exc:
        return exc.as_dict()


def validate(sp, params, plan):
    if params.get('maintenance_mode') != 'presentation':
        raise EP.PlanError('MAINTENANCE_MODE_INVALID', '仅支持presentation维护')
    digest = str(params.get('maintenance_receipt_sha256') or '')
    if not re.fullmatch(r'[a-f0-9]{64}', digest):
        raise EP.PlanError('MAINTENANCE_RECEIPT_REQUIRED', '先prepare_maintenance绑定候选')
    expected = C.task_temp_path(plan['task_id'], 'receipts/maintenance/' + digest + '.json').resolve()
    if Path(str(params.get('maintenance_receipt_file') or '')).resolve() != expected:
        raise EP.PlanError('MAINTENANCE_RECEIPT_INVALID', '维护收据必须属于当前任务')
    try:
        record = json.loads(expected.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise EP.PlanError('MAINTENANCE_RECEIPT_INVALID', '维护收据不可读取') from exc
    if EP.digest(record) != digest or record.get('version') != VERSION:
        raise EP.PlanError('MAINTENANCE_RECEIPT_INVALID', '维护收据哈希不一致')
    required = {'task_id': plan['task_id'], 'page_id': plan['target_page_id'],
                'plan_hash': plan['plan_hash'], 'turn_id': C.current_trace_context().get('turn_id')}
    if not required['turn_id'] or any(record.get(k) != v for k, v in required.items()):
        raise EP.PlanError('MAINTENANCE_RECEIPT_STALE', '候选不属于当前任务、轮次或计划')
    path, document, candidate_hash = _candidate(params)
    if str(path) != record['html_file'] or candidate_hash != record['html_sha256'] or contract(document) != record['runtime_digest']:
        raise EP.PlanError('MAINTENANCE_CANDIDATE_CHANGED', '维护候选已改变，重新prepare并验收')
    base, _ = _context(sp, params, plan)
    if base != record['base']:
        raise EP.PlanError('MAINTENANCE_BASE_CHANGED', '维护基线已改变，停止覆盖')
    return record
