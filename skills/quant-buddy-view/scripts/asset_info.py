"""Page-only LLM research: contract proof and rendering, without generating content."""
import json
import re
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit

import common as C

RECEIPT_VERSION = 'asset_info_contract_receipt_v1'


def contract_errors(payload):
    if not isinstance(payload, dict):
        return [('ASSET_INFO_PAYLOAD_INVALID', '信息需求必须是对象')]
    errors = []
    if set(payload) - {'prompt', 'word_count', 'output_format'}:
        errors.append(('ASSET_INFO_SCOPE_INVALID', '注册只保存prompt/word_count/output_format，不接受股票或身份参数'))
    if not isinstance(payload.get('prompt'), str) or not payload['prompt'].strip() or len(payload['prompt']) > 4000:
        errors.append(('ASSET_INFO_PROMPT_REQUIRED', 'prompt须为1～4000字符'))
    count = payload.get('word_count')
    if type(count) is not int or not 30 <= count <= 3000:
        errors.append(('ASSET_INFO_WORD_COUNT_INVALID', 'word_count须为30～3000整数'))
    if payload.get('output_format') not in ('text', 'markdown'):
        errors.append(('ASSET_INFO_FORMAT_INVALID', 'output_format仅支持text/markdown'))
    return errors


def valid_receipt(value, task_id, fingerprint=None):
    import execution_plan as EP
    if not isinstance(value, dict):
        return False
    contract = value.get('contract')
    if not isinstance(contract, dict) or contract.get('kind') != 'asset_info' or contract_errors(contract.get('payload')):
        return False
    return (value.get('version') == RECEIPT_VERSION
            and value.get('kind') == 'asset_info' and value.get('task_id') == task_id
            and value.get('status') == 'contract_validated' and value.get('success') is True
            and value.get('validation_scope') == 'request_contract'
            and value.get('content_generated') is False
            and bool(value.get('contract_fingerprint'))
            and value['contract_fingerprint'] == EP.digest(contract)
            and (fingerprint is None or value['contract_fingerprint'] == fingerprint))


def bridge_url(endpoint):
    # The browser uses the official origin; registration HTTP stays on the host proxy.
    url = urlsplit(C.identity_endpoint(endpoint))
    if (url.scheme != 'https' or url.hostname not in ('www.quantbuddy.cn', 'test.quantbuddy.cn')
            or url.username or url.password or url.port not in (None, 443)):
        raise ValueError('asset_info须使用已支持环境的官方HTTPS页头和桥接脚本')
    return f'https://{url.hostname}/asset-info-bridge.js'


def resolve_config(value, task_id=None):
    """Bind a registered info grant to a real selection table, not to a frozen ticker list."""
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {
            'grant_id', 'signature', 'selection_output', 'asset_field', 'name_field', 'target_selector'}:
        raise ValueError('asset_info仅支持grant_id/signature/selection_output/asset_field/name_field/target_selector')
    config = dict(value)
    for field in ('grant_id', 'selection_output', 'asset_field'):
        if not isinstance(config.get(field), str) or not config[field].strip():
            raise ValueError('asset_info缺少' + field)
    if not re.fullmatch(r'(?:dg|grant)_[A-Za-z0-9._-]+', config['grant_id']):
        raise ValueError('asset_info grant_id无效')
    import data_grant as DG
    credential = DG.load_credential(config['grant_id'], task_id=task_id) if task_id else DG.load_credential(config['grant_id'])
    if not config.get('signature') and credential:
        config['signature'] = credential.get('signature')
    if not isinstance(config.get('signature'), str) or not config['signature']:
        raise ValueError('asset_info缺少已登记授权的signature')
    if credential and credential.get('kind') not in (None, 'asset_info'):
        raise ValueError('asset_info不能引用其他kind的授权')
    config['kind'] = 'asset_info'
    config.setdefault('name_field', 'name')
    config.setdefault('target_selector', '#qb-asset-info')
    if not re.fullmatch(r'#[A-Za-z][\w-]*', config['target_selector']):
        raise ValueError('asset_info target_selector须为单个ID选择器')
    return config


def config_from_html(source):
    marker = 'data-qb-asset-info-config'
    if not source or marker not in source.lower():
        return None

    class ConfigScripts(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.blocks = []
            self.current = None

        def handle_starttag(self, tag, attrs):
            if tag == 'script' and marker in dict(attrs):
                self.current = []
                self.blocks.append(self.current)

        def handle_endtag(self, tag):
            if tag == 'script':
                self.current = None

        def handle_data(self, data):
            if self.current is not None:
                self.current.append(data)

    parsed = ConfigScripts()
    parsed.feed(source)
    parsed.close()
    if not parsed.blocks:
        return None
    if len(parsed.blocks) != 1:
        raise ValueError('页面只能登记一份asset_info展示集合')
    value = json.loads(''.join(parsed.blocks[0]))
    if not isinstance(value, dict) or value.get('kind') != 'asset_info':
        raise ValueError('asset_info页面配置无效')
    return value


def markup(config, endpoint):
    if not config:
        return ''
    from html import escape
    script = json.dumps(config, ensure_ascii=False).replace('<', '\\u003c')
    style = (Path(C.SKILL_ROOT) / 'assets' / 'asset-info.css').read_text(encoding='utf-8')
    runtime = (Path(C.SKILL_ROOT) / 'assets' / 'asset-info.js').read_text(encoding='utf-8')
    return (f'<section id="{escape(config["target_selector"][1:], quote=True)}" data-qb-asset-info-panel>'
            '<h2>公司信息</h2><p hidden data-qb-asset-info-description>AI按本页信息需求整理，独立于量化筛选结果。</p>'
            '<p hidden data-qb-llm-notice>缓存命中免费；首次生成、过期更新与强制更新按实际Token及搜索费用扣作者积分。自动更新无需登录，费用由页面作者承担。</p>'
            '<button type="button" data-qb-llm-force hidden disabled>确认费用并更新全部</button>'
            '<p data-qb-asset-info-status role="status">等待选股结果</p>'
            '<div data-qb-asset-info-items></div><nav data-qb-asset-info-pagination aria-label="公司信息分页"></nav></section>'
            f'<style>{style}</style><script type="application/json" data-qb-asset-info-config>{script}</script>'
            f'<script src="{bridge_url(endpoint)}"></script><script>{runtime}</script>')


def required_module_error(source, params=None):
    """Do not silently downgrade a current handoff to manual company snapshots."""
    params = params or {}
    context = C.current_trace_context()
    task = params.get('task_id') or context.get('task_id')
    request = params.get('asset_info_request')
    if task:
        persisted = C.read_task_trace_context(task)
        handoff = persisted.get('handoff_context') or {}
        turn = params.get('turn_id') or context.get('turn_id') or persisted.get('current_turn_id')
        if handoff.get('source_turn_id') == turn and turn:
            reuse = handoff.get('computation_reuse') or {}
            request = request or reuse.get('asset_info_request')
    from asset_info_request import requires_request
    query = params.get('user_query') or context.get('user_query')
    if not query and task:
        # Only the current turn query may enable a module; old handoffs are not intent.
        if turn and turn == persisted.get('current_turn_id'):
            query = persisted.get('current_user_query')
    if request is None and not requires_request(query):
        return None
    try:
        config = config_from_html(source)
    except (ValueError, TypeError):
        config = None
    if config is None:
        return {'code': 1, 'error': 'ASSET_INFO_MODULE_REQUIRED',
                'message': '本轮交接要求公司信息模块；请按guides/asset-info.md验证需求合同、登记授权并绑定当前展示名单。手写公司资料快照不能替代官方异步模块。'}
    return None


def validate_panel_structure(source, config):
    """Require one bound official module and hidden controls in this release."""
    class Elements(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tags = []
        def handle_starttag(self, tag, attrs):
            self.tags.append((tag, dict(attrs)))
    parsed = Elements()
    parsed.feed(source)
    selector = config.get('target_selector')
    if not isinstance(selector, str) or not re.fullmatch(r'#[A-Za-z][\w-]*', selector):
        raise ValueError('asset_info target_selector须为单个ID选择器')
    targets = [attrs for _, attrs in parsed.tags if attrs.get('id') == selector[1:]]
    panels = [attrs for _, attrs in parsed.tags if 'data-qb-asset-info-panel' in attrs]
    if len(targets) != 1 or len(panels) != 1 or targets[0] is not panels[0]:
        raise ValueError('asset_info目标与模块必须唯一且一致；只保留一个<!-- QB_ASSET_INFO -->占位符，勿手写重复模块')
    for marker in ('data-qb-llm-notice', 'data-qb-llm-force', 'data-qb-asset-info-description'):
        controls = [attrs for _, attrs in parsed.tags if marker in attrs]
        if len(controls) != 1 or 'hidden' not in controls[0]:
            raise ValueError('asset_info本版须保留唯一且hidden的' + marker)
    return parsed.tags


def validate_html(source, endpoint):
    try:
        config = config_from_html(source)
        if config is None:
            return None
        expected = bridge_url(endpoint)
        tags = validate_panel_structure(source, config)
        frames = [attrs for tag, attrs in tags if tag == 'iframe' and attrs.get('id') == 'qbLivePageHeaderFrame']
        if not any(tag == 'script' and attrs.get('src') == expected for tag, attrs in tags) or len(frames) != 1:
            raise ValueError('asset_info必须保留同环境官方桥接脚本与完整官方页头')
        if frames[0].get('src'):
            header = urlsplit(frames[0]['src'])
            if f'{header.scheme}://{header.netloc}' != expected.rsplit('/', 1)[0] or header.path != '/embed/live-page-header':
                raise ValueError('asset_info页头与桥接脚本环境不一致')
        if not all(isinstance(config.get(f), str) and config[f].strip() for f in ('grant_id', 'signature', 'selection_output', 'asset_field')):
            raise ValueError('asset_info页面缺少授权或选股结果绑定')
    except (ValueError, TypeError, KeyError) as exc:
        return {'code': 1, 'error': 'ASSET_INFO_PAGE_INVALID', 'message': str(exc)}
    return None


def prepare(params):
    """Produce a contract-only registration command after a validated QBS handoff."""
    from asset_info_request import normalize_request
    from qbs_bridge import _validate_grant_set
    task = params.get('task_id')
    if not isinstance(task, str) or not task.strip():
        raise ValueError('prepare需要当前task_id')
    request = normalize_request(params.get('asset_info_request'), params.get('validated_outputs') or [])
    if request is None:
        raise ValueError('prepare需要asset_info_request')
    contract = {'kind': 'asset_info', 'payload': {k: request[k] for k in ('prompt', 'word_count', 'output_format')}}
    return _validate_grant_set(None, {'task_id': task, 'user_query': params.get('user_query', ''),
                                    'grants': [{'name': 'company_information', 'contract': contract}]}, {})


if __name__ == '__main__':
    import sys
    try:
        if len(sys.argv) < 2 or sys.argv[1] != 'prepare':
            raise ValueError('用法: asset_info.py prepare @params.json')
        result = prepare(C.read_params(sys.argv[2:], env_var='ASSET_INFO_PARAMS'))
    except ValueError as exc:
        result = {'code': 1, 'error': 'ASSET_INFO_REQUEST_INVALID', 'message': str(exc)}
    C.emit(result, out_name='asset_info_out.txt')
