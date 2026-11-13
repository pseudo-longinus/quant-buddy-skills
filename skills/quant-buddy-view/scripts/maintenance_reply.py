"""Task-only confirmation for a narrowly identified same-page presentation edit.

Never changes page metadata, its research template, data evidence or Grants.
Unknown/mixed requests retain the page's original research reply contract.
"""
import hashlib
import re
from html.parser import HTMLParser
from pathlib import Path
import common as C
import delivery_state as DS
import execution_plan as EP
import reply_template_registry as RTR

TEMPLATE = 'same_page_maintenance_v1'


class _Projection(HTMLParser):
    """Compare document structure and executable bytes, allowing CSS only on request."""
    def __init__(self, document, style=False):
        super().__init__(convert_charrefs=True)
        self.tokens, self.raw, self.style = [], None, style
        self.feed(document)
        self.close()

    def handle_starttag(self, tag, attrs):
        if tag == 'style' and self.style:
            self.raw = 'style'
            return
        if self.style:
            attrs = [(k, v) for k, v in attrs if k not in ('class', 'style')]
        self.tokens.append(('start', tag, sorted(attrs)))
        if tag in ('script', 'style'):
            self.raw = tag

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if not (tag == 'style' and self.style):
            self.tokens.append(('end', tag))
        if tag == self.raw:
            self.raw = None

    def handle_data(self, value):
        if self.raw == 'style' and self.style:
            return
        text = value if self.raw else re.sub(r'\s+', '', value)
        if text:
            self.tokens.append(('text', text))


def preservation(source, candidate, query):
    """No migration exception: remove only a literal note, then compare structure."""
    import page_title_contract as PTC
    source, candidate = source.replace('\r\n', '\n'), candidate.replace('\r\n', '\n')
    scope = intent(query)
    if not scope:
        raise EP.PlanError('MAINTENANCE_SCOPE_REQUIRED', '仅明确的备注或样式维护适用')
    if '备注' in scope['change_kinds']:
        notes = re.findall(r'“([^”]*)”|‘([^’]*)’|"([^"\n]*)"|\'([^\'\n]*)\'', query)
        notes = [''.join(parts) for parts in notes]
        if len(notes) != 1 or not notes[0].strip():
            raise EP.PlanError('MAINTENANCE_NOTE_REQUIRED', '请在原请求中明确唯一的引号内备注文本')
        marker = re.sub(r'\s+', '', notes[0])
        parsed = PTC._Document(candidate)
        nodes = [n for n in parsed.nodes if n['tag'] in ('p', 'div', 'span', 'aside')
                 and n.get('close_end') and not n['excluded'] and not n['in_head']
                 and re.sub(r'\s+', '', ''.join(n['text'])) == marker]
        # The outermost matching container can include formatting, never code or bindings.
        if not nodes:
            raise EP.PlanError('MAINTENANCE_NOTE_REQUIRED', '备注须为独立的p/div/span/aside文本节点')
        node = min(nodes, key=lambda n: n['start'])
        snippet = candidate[node['start']:node['close_end']]
        fragment = _Projection(snippet)
        for token in fragment.tokens:
            if token[0] == 'start' and (token[1] not in ('p', 'div', 'span', 'aside', 'b', 'strong', 'em', 'br')
                                       or any(k not in ('class', 'style') for k, v in token[2])):
                raise EP.PlanError('MAINTENANCE_SCOPE_CHANGED', '备注不得携带脚本、事件或数据绑定')
        candidate = candidate[:node['start']] + candidate[node['close_end']:]
    if _Projection(source, '样式' in scope['change_kinds']).tokens != _Projection(candidate, '样式' in scope['change_kinds']).tokens:
        raise EP.PlanError('MAINTENANCE_SCOPE_CHANGED',
                           '纯维护必须保留原正文、标题、脚本及数据绑定；不要为加备注迁移图表或数据运行库')
    return scope


def prepare_update(sp, params, candidate):
    context = C.current_trace_context()
    task = sp._routing_task_id(params)
    query = context.get('user_query') or ''
    if not task or context.get('task_id') != task or not context.get('turn_id') or not intent(query):
        return None
    result = sp.cmd_template({'page_id': params['page_id']})
    meta = sp._template_record(result)
    version = meta.get('current_version_id') or meta.get('version_id')
    if result.get('code') != 0 or meta.get('page_id') != params['page_id'] or not version:
        raise EP.PlanError('MAINTENANCE_BASE_REQUIRED', '无法核验原页身份和版本，未写入')
    source, error = sp._fetch_oss(meta.get('url'))
    if error or hashlib.sha256((source or '').encode('utf-8')).hexdigest() != meta.get('sha256'):
        raise EP.PlanError('MAINTENANCE_BASE_DOCUMENT_MISMATCH', '原页正文与版本哈希不一致，未写入')
    scope = preservation(source, candidate, query)
    out = dict(params)
    for key in ('title', 'description', 'page_context', 'agent_reply_template', 'reply_contract_binding',
                'scene_tags', 'paradigm_tags', 'user_query'):
        if key in params and params[key] != meta.get(key):
            raise EP.PlanError('MAINTENANCE_METADATA_CHANGED', '纯维护不得改写原页面元信息', field=key)
        if key in meta:
            out[key] = meta[key]
    if params.get('expected_current_version_id') not in (None, version):
        raise EP.PlanError('MAINTENANCE_BASE_CHANGED', '原页版本已变化，未写入')
    out['expected_current_version_id'] = version
    return out, {'checked': True, 'reason': 'verified_same_page_maintenance',
                 'base_version_id': version, 'source_sha256': meta['sha256'], **scope}


def intent(query):
    """Whole-clause allowlist. Quoted note text is content, never instructions."""
    text = str(query or '').strip()
    if not text or len(text) > 3000:
        return None
    text = re.sub(r'“[^”]*”|‘[^’]*’|"[^"\n]*"|\'[^\'\n]*\'', '备注文本', text)
    text = re.sub(r'https?://[^\s，。；]+', '', text)
    text = re.sub(r'\s+', '', text)
    clauses = [x for x in re.split(r'[，,。；;！!\n]', text) if x]
    prefix = r'(?:请|麻烦|帮我)*(?:在|给|把|将)?(?:这个|当前|原来的|原)?(?:原活页|活页|页面|原页)(?:的)?'
    note = prefix + r'(?:底部|末尾|尾部)?(?:只)?(?:追加|添加|加|补充)(?:一条|一句|一个)?(?:备注|说明|尾注|验收说明)?(?:[：:]?备注文本|验收说明)'
    style = prefix + r'(?:只)?(?:样式|排版|字体|字号|背景|背景色|颜色|间距)(?:调整为|改成|改为|调整成|调成)(?:暖白|白色|浅灰|深灰|黑色|深蓝|大一点|小一点|紧凑|宽松|\d+(?:px|像素))'
    preserve = r'(?:保持|保留)(?:原有|原)?(?:数据|内容|链接|模板|数据合同|研究结论)(?:(?:、|和|与|及)(?:原有|原)?(?:数据|内容|链接|模板|数据合同|研究结论))*(?:不变)?'
    actions = []
    for clause in clauses:
        if re.fullmatch(note, clause):
            actions.append('备注')
        elif re.fullmatch(style, clause):
            actions.append('样式')
        elif re.fullmatch(preserve, clause) or clause in ('不做新研究', '无需重新研究', '不重新计算'):
            continue
        else:
            return None
    return {'query_sha256': hashlib.sha256(str(query).encode('utf-8')).hexdigest(),
            'change_kinds': sorted(set(actions))} if actions else None


def contract(task, page, public_url):
    state = DS.load(task, page)
    scope = state.get('maintenance_reply_intent')
    if not scope:
        return None
    write = state.get('last_write') or {}
    good = state.get('last_good_version') or {}
    if (state.get('delivery_state') != 'published'
            or not all(DS.flags(state).get(k) for k in ('written', 'verified', 'public_reachable'))
            or write.get('status') != 'confirmed' or write.get('turn_id') != state.get('turn_id')
            or good != write.get('remote') or good.get('url') != public_url):
        raise EP.PlanError('MAINTENANCE_RECEIPT_REQUIRED', '维护确认需要同轮已确认写入与公开验收')
    entry = RTR.get_template_entry(TEMPLATE)
    return {'required': True, 'terminal': True, 'operation': 'same_page_maintenance',
            'template_ref': TEMPLATE, 'template_file': str(Path(C.SKILL_ROOT) / 'reply-templates' / entry['file']),
            'template_exists': True, 'reply_render_policy': entry['reply_render_policy'],
            'page_id': page, 'public_url': public_url, 'delivery_link_label': '原活页',
            'maintenance_binding': {'task_id': task, 'turn_id': state['turn_id'],
                                    'publication': dict(good), **scope}}


def check_binding(contract, task, *, observe=True, turn_id=None):
    """A task-only contract must match the current sealed journal and version."""
    binding = contract.get('maintenance_binding') or {}
    page = contract.get('page_id')
    context = ({'task_id': task, 'turn_id': turn_id}
               if turn_id is not None else C.current_trace_context())
    state = DS.load(task, page)
    write = state.get('last_write') or {}
    good = state.get('last_good_version') or {}
    scope = state.get('maintenance_reply_intent') or {}
    if (contract.get('template_ref') != TEMPLATE or binding.get('task_id') != task
            or context.get('task_id') != task or context.get('turn_id') != binding.get('turn_id')
            or state.get('turn_id') != binding.get('turn_id')
            or binding.get('query_sha256') != scope.get('query_sha256') or not scope
            or binding.get('change_kinds') != scope.get('change_kinds')
            or binding.get('publication') != good or write.get('remote') != good
            or write.get('status') != 'confirmed' or write.get('turn_id') != binding.get('turn_id')
            or contract.get('public_url') != good.get('url')
            or not all(DS.flags(state).get(k) for k in ('written', 'verified', 'public_reachable'))):
        raise EP.PlanError('MAINTENANCE_CONTRACT_STALE', '维护确认与当前轮或页面版本不一致')
    if observe:
        import static_page as SP
        result = SP._observe_published_template(page)
        if result.get('code') != 0 or DS._remote(SP._template_record(result)) != good:
            raise EP.PlanError('MAINTENANCE_PAGE_CHANGED', '页面版本已变化或无法核验；保留待校验状态')


def reply(contract):
    changes = '、'.join((contract.get('maintenance_binding') or {}).get('change_kinds') or [])
    notice = str(contract.get('presentation_notice') or '')
    if (contract.get('presentation') or {}).get('status') == 'degraded' and not notice:
        titles = sorted({p.get('title', '图表') for v in contract['presentation'].get('viewports', [])
                         for p in v.get('panels', []) if p.get('state') == 'table_fallback'})
        notice = '图表降级为数据表：' + '、'.join(titles)
    return ('## 本次改动\n\n已完成本轮' + changes + '更新，并通过公开页面验收。\n\n'
            '## 范围与限制\n\n沿用原活页及其研究和数据合同，本轮未开展新研究或重新核算数据。' + notice + '\n\n'
            '原活页：[' + contract['public_url'] + '](' + contract['public_url'] + ')\n若效果不满意，页面可进一步升级')
