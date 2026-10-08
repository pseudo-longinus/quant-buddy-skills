"""One title for a research document and its publication metadata.

Only the document title and an unambiguously located page heading are editable.
Original-file publication deliberately uses its existing preservation contract.
"""
import html
import json
import re
from html.parser import HTMLParser


class TitleError(ValueError):
    def __init__(self, error, message, **evidence):
        super().__init__(message)
        self.error, self.evidence = error, evidence

    def as_dict(self):
        return {'code': 1, 'error': self.error, 'message': str(self), 'published': False,
                'verified': False, 'page_title_check': self.evidence}


def normalize(value):
    # HTMLParser decodes HTML entities exactly once. API titles are plain text.
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def valid(value):
    # JS/backend slice uses UTF-16 code units, including astral characters.
    value = normalize(value)
    if not value or len(value.encode('utf-16-le')) // 2 > 200:
        raise TitleError('PAGE_TITLE_INVALID', '页面主标题须为非空文本，且不超过200字符', title=value)
    return value


_VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}


class _Document(HTMLParser):
    def __init__(self, document):
        super().__init__(convert_charrefs=True)
        self.document, self.stack, self.nodes = document, [], []
        self.offsets = [0]
        self.offsets.extend(match.end() for match in re.finditer('\n', document))
        self.feed(document)
        self.close()

    def position(self):
        line, column = self.getpos()
        return self.offsets[line - 1] + column

    def handle_starttag(self, tag, pairs):
        attrs = dict(pairs)
        style = re.sub(r'\s+', '', attrs.get('style') or '').lower()
        excluded = (tag in ('template', 'script', 'style', 'noscript') or 'hidden' in attrs or 'inert' in attrs
                    or (attrs.get('aria-hidden') or '').lower() == 'true'
                    or re.search(r'(?:^|;)(?:display:none|visibility:hidden)(?:!important)?(?:;|$)', style)
                    or any(key.startswith('data-qb-card-') or key == 'data-qb-live-card-title' for key in attrs)
                    or any(node['excluded'] for node in self.stack))
        start = self.position()
        node = {'tag': tag, 'attrs': attrs, 'start': start,
                'content_start': start + len(self.get_starttag_text()), 'end': None,
                'excluded': bool(excluded), 'in_head': any(n['tag'] == 'head' for n in self.stack), 'text': []}
        self.nodes.append(node)
        if tag == 'br':
            self.handle_data(' ')
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]['tag'] == tag:
                node = self.stack[index]
                node['end'] = self.position()
                node['close_end'] = self.document.find('>', node['end']) + 1
                del self.stack[index:]
                break

    def handle_data(self, data):
        if self.stack and self.stack[-1]['excluded']:
            return
        for node in self.stack:
            node['text'].append(data)

    def heading(self):
        candidates = [n for n in self.nodes if not n['excluded'] and not n['in_head']]
        marked = [n for n in candidates if 'data-qb-page-title' in n['attrs']]
        candidates = marked or [n for n in candidates if n['tag'] == 'h1']
        if len(candidates) != 1 or candidates[0]['end'] is None:
            raise TitleError('PAGE_TITLE_AMBIGUOUS', '无法唯一定位页面主标题；请用data-qb-page-title标记主标题文本节点',
                             heading_count=len(candidates))
        return candidates[0]


def prepare(document, params, *, sync_heading=False):
    """Return normalized HTML and evidence; explicit conflicts fail before any write."""
    parsed = _Document(document)
    heading = parsed.heading()
    current = normalize(''.join(heading['text']))
    explicit = params.get('title')
    expected = valid(current if explicit is None else explicit)
    titles = [n for n in parsed.nodes if n['tag'] == 'title' and not n['excluded']]
    if len(titles) > 1 or (titles and titles[0]['end'] is None):
        raise TitleError('PAGE_TITLE_INVALID', 'HTML必须只有一个完整的<title>')
    old_document_title = normalize(''.join(titles[0]['text'])) if titles else ''
    edits = []
    if current != expected:
        if not sync_heading:
            raise TitleError('PAGE_TITLE_MISMATCH', '发布title与页面主标题冲突；请修正候选或发布参数',
                             title=expected, heading=current, document_title=old_document_title)
        inner = document[heading['content_start']:heading['end']]
        # Plain text or a single chain of formatting wrappers can be replaced
        # without destroying a layout. Multiple text nodes/line breaks cannot.
        pieces = re.split(r'(<[^>]*>)', inner)
        texts = [i for i in range(0, len(pieces), 2) if normalize(pieces[i])]
        if len(texts) != 1 or re.search(r'<(?:br|img|input|svg|script)\b', inner, re.I):
            raise TitleError('PAGE_TITLE_REWRITE_REQUIRED', '复杂主标题不能安全自动替换；请保留布局并标记可替换的标题文本节点',
                             title=expected, heading=current)
        pieces[texts[0]] = html.escape(expected)
        edits.append((heading['content_start'], heading['end'], ''.join(pieces)))
    else:
        valid(current)
    if old_document_title != expected or not titles:
        escaped = html.escape(expected)
        if titles:
            edits.append((titles[0]['content_start'], titles[0]['end'], escaped))
        else:
            head = next((n for n in parsed.nodes if n['tag'] == 'head'), None)
            root = next((n for n in parsed.nodes if n['tag'] == 'html'), None)
            doctype = re.match(r'\s*<!doctype[^>]*>', document, re.I)
            at = head['content_start'] if head else (root['content_start'] if root else (doctype.end() if doctype else 0))
            block = '<title>' + escaped + '</title>'
            edits.append((at, at, block if head else '<head>' + block + '</head>'))
    for start, end, replacement in sorted(edits, reverse=True):
        document = document[:start] + replacement + document[end:]
    return document, {'title': expected, 'heading': expected, 'document_title': expected,
                      'heading_locator': '[data-qb-page-title]' if 'data-qb-page-title' in heading['attrs'] else 'h1',
                      'synchronized': bool(edits)}


def acknowledgement(result, expected):
    if not isinstance(result, dict) or result.get('code') != 0:
        return result
    actual = normalize(result.get('title'))
    if actual == expected:
        result['page_title_check'] = {'title': expected, 'metadata_title': actual, 'ok': True}
        return result
    result = dict(result)
    for key in ('agent_reply_contract', 'agent_reply_template_file', 'validated_markdown'):
        result.pop(key, None)
    result.update(code=1, error='PAGE_TITLE_POSTCHECK_FAILED', published=True, verified=False,
                  message='页面已写入，但返回的元数据标题未通过检查；不自动重发',
                  page_title_check={'title': expected, 'metadata_title': actual, 'ok': False})
    return result


def prepare_fast_template(document, asset):
    """Adopt the template heading; recognise only the stock template's known writer.

    Its source h1 is a placeholder. The runtime uses config.asset.name for h1,
    but used to append the code and analysis label only to document.title.
    Unknown runtime writers require an explicit template repair, not a rewrite.
    """
    parsed = _Document(document)
    heading = parsed.heading()
    scripts = [node for node in parsed.nodes if node['tag'] == 'script' and node['end'] is not None]
    setter = re.compile(r"\$\(\s*['\"]assetName['\"]\s*\)\.textContent\s*=\s*config\.asset\.name\s*;")
    writers = [(node, document[node['content_start']:node['end']]) for node in scripts]
    runtime = [(node, source) for node, source in writers if setter.search(source)]
    assignments = sum(len(re.findall(r'\bdocument\.title\s*=(?!=)', source)) for _, source in writers)
    if not runtime:
        if assignments:
            raise TitleError('PAGE_TITLE_REWRITE_REQUIRED', '快页模板含未知标题脚本，不能安全同步；请修正模板标题赋值')
        return prepare(document, {})
    configs = [node for node in scripts if 'data-qbv-stock-instance' in node['attrs']]
    if len(runtime) != 1 or len(configs) != 1 or heading['attrs'].get('id') != 'assetName' or assignments != 1:
        raise TitleError('PAGE_TITLE_REWRITE_REQUIRED', '快页模板标题或实例结构无法安全识别')
    try:
        node = configs[0]
        configured = json.loads(document[node['content_start']:node['end']])['asset']
        if any(configured.get(key) != asset.get(key) for key in ('name', 'code')):
            raise ValueError('asset mismatch')
        expected = valid(configured['name'])
    except (ValueError, KeyError, TypeError) as exc:
        raise TitleError('PAGE_TITLE_REWRITE_REQUIRED', '快页实例资产与创建响应不一致，拒绝同步') from exc
    assignment = re.compile(
        r"\bdocument\.title\s*=\s*config\.asset\.name"
        r"(?:\s*\+\s*['\"]（['\"]\s*\+\s*config\.asset\.code\s*\+\s*['\"]）\s*·\s*个股综合分析['\"])?\s*;")
    node, source = runtime[0]
    match = assignment.search(source)
    if not match:
        raise TitleError('PAGE_TITLE_REWRITE_REQUIRED', '快页含未知document.title赋值，拒绝全文替换')
    start, end = node['content_start'] + match.start(), node['content_start'] + match.end()
    replacement = 'document.title = config.asset.name;'
    document = document[:start] + replacement + document[end:]
    prepared, check = prepare(document, {'title': expected}, sync_heading=True)
    check['runtime_title_synchronized'] = match.group(0) != replacement
    check['synchronized'] = check['synchronized'] or check['runtime_title_synchronized']
    return prepared, check
