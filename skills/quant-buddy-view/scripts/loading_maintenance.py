"""Constrained loading-hook edits for already verified bespoke pages.

The strict presentation contract remains the default. This opt-in path freezes
all original statements except load/redraw, and seals the reviewed hook delta.
It is not a verifier of arbitrary JavaScript's financial semantics.
"""
import re
from html.parser import HTMLParser
import execution_plan as EP
import chart_dependency as CD


def fail(message):
    raise EP.PlanError('MAINTENANCE_LOADING_CONTRACT_CHANGED', message)


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.items, self.active = [], None
        self.bespoke = False

    def handle_starttag(self, tag, attrs):
        if dict(attrs).get('data-qb-page-design') == 'bespoke-v1':
            self.bespoke = True
        if tag == 'script':
            self.active = [sorted(attrs), '']

    def handle_data(self, data):
        if self.active is not None:
            self.active[1] += data

    def handle_endtag(self, tag):
        if tag == 'script' and self.active is not None:
            self.items.append(self.active)
            self.active = None


def statements(js):
    try:
        from tree_sitter import Language, Parser
        import tree_sitter_javascript
    except ImportError as exc:
        raise EP.PlanError('MAINTENANCE_JS_PARSER_REQUIRED',
                           '加载维护需安装 tree-sitter 和 tree-sitter-javascript；未写入页面') from exc
    tree = Parser(Language(tree_sitter_javascript.language())).parse(js.encode('utf-8'))
    if tree.root_node.has_error:
        fail('加载维护脚本存在语法错误')
    return [n for n in tree.root_node.named_children if n.type != 'comment']


def names(node):
    if node.type == 'function_declaration':
        return [node.child_by_field_name('name').text.decode()]
    if node.type in ('lexical_declaration', 'variable_declaration'):
        result = []
        for child in node.named_children:
            name = child.child_by_field_name('name')
            if child.type != 'variable_declarator' or name is None or name.type != 'identifier':
                fail('新增加载状态必须使用明确的变量名')
            result.append(name.text.decode())
        return result
    return []


def walk(node):
    yield node
    for child in node.named_children:
        yield from walk(child)


def business_delta(before, after):
    old, new = statements(before), statements(after)
    hooks = {'load', 'redraw'}
    original_names = {name for node in old for name in names(node)}
    old_hooks = [n for n in old if n.type == 'function_declaration' and names(n)[0] in hooks]
    new_hooks = [n for n in new if n.type == 'function_declaration' and names(n)[0] in hooks]
    if {names(n)[0] for n in old_hooks} != hooks or len(new_hooks) != 2 or {names(n)[0] for n in new_hooks} != hooks:
        fail('必须保留唯一 load/redraw 加载入口')
    protected = [n.text for n in old if n not in old_hooks]
    index, additions = 0, []
    for node in new:
        if node in new_hooks:
            continue
        if index < len(protected) and node.text == protected[index]:
            index += 1
            continue
        added_names = names(node)
        if added_names and not original_names.intersection(added_names):
            original_names.update(added_names)
            additions.append(node)
        elif node.text in (b"QBCharts.prepare('.chart');", b'QBCharts.prepare(".chart");'):
            additions.append(node)
        else:
            fail('金融计算、绘图、日期、事件或原状态声明发生变化')
    if index != len(protected):
        fail('原金融脚本语句缺失或顺序变化')
    changed = new_hooks + additions
    forbidden = re.compile(r'\b(?:fetch|XMLHttpRequest|WebSocket|EventSource|sendBeacon|'
                           r'importScripts|eval|Function|package_id|grant_id|signature)\b|https?://|\bimport\s*\(')
    if any(forbidden.search(n.text.decode()) for n in changed):
        fail('加载钩子不得引入直接网络请求、动态执行或凭证')
    # Preserve the exact query invocation: scheduling may move, query arguments may not.
    def queries(nodes):
        return sorted(n.text for root in nodes for n in walk(root)
                      if n.type == 'call_expression' and n.child_by_field_name('function') is not None
                      and n.child_by_field_name('function').text == b'QB.query')
    if queries(old) != queries(new):
        fail('加载维护不得改变 QB.query 参数或调用数量')
    return {'protected_statements': len(protected),
            'protected_digest': EP.digest([s.decode() for s in protected]),
            'loading_delta_digest': EP.digest([n.text.decode() for n in changed]),
            'added_names': [name for node in additions for name in names(node)]}


def review(source, candidate):
    source, candidate = source.replace('\r\n', '\n'), candidate.replace('\r\n', '\n')
    # Freeze every layout, description, formula label and declarative binding.
    def dom(text):
        text = re.sub(r'<script\b.*?</script>', '', text, flags=re.S)
        text = text.replace(' data-qb-chart role="region" aria-live="polite" aria-busy="true"', '')
        return text.replace('>正在加载数据…</div>', '></div>')
    if dom(source) != dom(candidate):
        fail('加载维护不得改变页面布局、文字、公式或图表绑定')
    parsers = [Scripts(), Scripts()]
    for parser, text in zip(parsers, (source, candidate)):
        parser.feed(text)
        if parser.active is not None or not parser.bespoke:
            fail('加载维护要求完整bespoke-v1页面')
    a, b = [p.items for p in parsers]
    if len(a) != len(b):
        fail('加载维护不得增删整段脚本')
    deltas, loaders = [], 0
    for (attrs, old), (new_attrs, new) in zip(a, b):
        if attrs != new_attrs:
            fail('脚本属性不得变化')
        if old == new:
            continue
        if '/* QB_ECHARTS_RUNTIME_V1 */' in old:
            if new.strip() != CD.runtime_source().strip():
                fail('图表运行时只能升级为当前共享双源Loader')
            sources = re.search(r'const sources = (.*?);', old)
            if sources is None or sources[1] != re.search(r'const sources = (.*?);', new)[1]:
                fail('图表运行时来源和超时配置不得改变')
            loaders += 1
        else:
            deltas.append(business_delta(old, new))
    if len(deltas) != 1 or loaders > 1:
        fail('只允许一段加载业务脚本和至多一次共享Loader升级')
    return {'kind': 'bespoke-loading-v1', 'business': deltas[0], 'loader_upgraded': bool(loaders)}
