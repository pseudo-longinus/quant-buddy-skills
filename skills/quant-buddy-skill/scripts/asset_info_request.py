"""Optional page-only research request; never a selection predicate or verified insight."""
import re

DEFAULT_PROMPT = '梳理该公司的主营业务与近期重大事件，注明信息日期与可靠来源；无可靠依据时明确说明。'


def requires_request(user_query):
    """Recognize explicit selection supplements, never invent roles or prompts."""
    query = re.sub(r'\s+', '', str(user_query or ''))
    if re.search(r'不要(?:网页|活页)|不(?:生成|创建)(?:网页|活页)|只(?:要|回复)(?:文字|文本)|仅(?:文字|文本)', query):
        return False
    if not re.search(r'选股|筛选|选出|挑选', query):
        return False
    topic = r'主营(?:业务)?|近期(?:重大)?事件|公司(?:信息|资料)|企业(?:信息|资料)|上下游|上游供应商|下游客户'
    if re.search(r'(?:不要|无需|不必|不需要)(?:再)?(?:附上|附带|补充|介绍)?(?:' + topic + r')', query):
        return False
    return bool(re.search(r'(?:附上|附带|并附|补充|同时介绍|并介绍)[^。；;！？!?]{0,80}(?:' + topic + r')', query))


def normalize_request(value, outputs):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {'selection_role', 'prompt', 'word_count', 'output_format'}:
        raise ValueError('asset_info_request只能包含selection_role/prompt/word_count/output_format')
    role = value.get('selection_role')
    available = {item.get('role') for item in outputs if isinstance(item, dict)} if isinstance(outputs, list) else set()
    if not isinstance(role, str) or not role.strip() or role not in available:
        raise ValueError('selection_role必须引用本轮已验证的选股结果角色')
    prompt = value.get('prompt', DEFAULT_PROMPT)
    count = value.get('word_count', 300)
    output_format = value.get('output_format', 'text')
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4000:
        raise ValueError('prompt须为1～4000字符')
    if type(count) is not int or not 30 <= count <= 3000:
        raise ValueError('word_count须为30～3000整数')
    if output_format not in ('text', 'markdown'):
        raise ValueError('output_format仅支持text/markdown')
    return {'selection_role': role, 'prompt': prompt.strip(), 'word_count': count, 'output_format': output_format}
