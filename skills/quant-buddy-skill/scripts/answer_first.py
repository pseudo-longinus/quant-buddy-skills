"""Audit observed, ordered host messages/tool calls; this does not send messages."""
import json
import re
import sys
from pathlib import Path

PAGE_TOOL = re.compile(
    r'(?:static_page\.py|build_dashboard\.py|formula_package\.py|publish_workflow\.py|'
    r'compose_page|register_formula_package|registerFormulaPackage|upload_static_page|'
    r'update_static_page|list_pages|spawn_agent|sessions_spawn)')


def is_page_execution(event):
    if event.get('type') != 'tool_call' or event.get('name') in {'Read', 'read_skill_file', 'Grep', 'Glob', 'write_skill_file'}:
        return False
    text = str(event.get('name', '')) + ' ' + json.dumps(event.get('arguments', {}), ensure_ascii=False)
    # Inspecting an existing page and establishing lineage are read-only preflight.
    if re.search(r'static_page\.py[\s"\x27,]+(?:interpret(?:_csv)?|inspect|get_page_detail)\b', text):
        return False
    return bool(PAGE_TOOL.search(text))


def verify_events(events, *, answer_text):
    if not isinstance(events, list) or not isinstance(answer_text, str) or not answer_text.strip():
        raise ValueError('events and exact expected business answer are required')
    answers = [i for i, event in enumerate(events) if event.get('type') == 'assistant_message'
               and event.get('text', '').strip() == answer_text.strip()]
    pages = [i for i, event in enumerate(events) if is_page_execution(event)]
    if not answers:
        return {'status': 'unverified', 'reason': 'NO_OBSERVED_BUSINESS_MESSAGE'}
    first = answers[0]
    if events[first].get('channel') not in {'commentary', 'intermediate'}:
        return {'status': 'failed', 'reason': 'ANSWER_TERMINATES_EXECUTION'}
    if not pages:
        return {'status': 'unverified', 'reason': 'NO_OBSERVED_PAGE_CONTINUATION'}
    return {'status': 'passed' if first < pages[0] else 'failed',
            'reason': 'ANSWER_BEFORE_PAGE' if first < pages[0] else 'PAGE_BEFORE_ANSWER',
            'answer_index': first, 'first_page_tool_index': pages[0]}


if __name__ == '__main__':
    params = json.loads(Path(sys.argv[1].removeprefix('@')).read_text(encoding='utf-8-sig'))
    result = verify_events(params['events'], answer_text=params['answer_text'])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result['status'] == 'passed' else 1)
