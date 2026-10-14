"""Separate the exact trailing Codex citation envelope from business Markdown.

No arbitrary afterword is exempt. The caller retains the original text for
delivery/hashing and scans it for sensitive content as usual.
"""
import re


def split_host_metadata(text):
    match = re.search(
        r'\n<oai-mem-citation>\s*\n<citation_entries>\n(?P<entries>[^<>]+)\n</citation_entries>\s*'
        r'\n<rollout_ids>\n(?P<ids>[^<>]*)</rollout_ids>\s*\n</oai-mem-citation>\s*$', text)
    if not match or text.count('<oai-mem-citation>') != 1:
        return text, ''
    entries = match['entries'].splitlines()
    if not entries or not all(re.fullmatch(
            r'(?:MEMORY\.md|(?:rollout_summaries|skills)/[^<>|\s]+):[1-9]\d*-[1-9]\d*\|note=\[[^\[\]<>\r\n]+\]',
            entry) for entry in entries):
        return text, ''
    if not all(re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', item)
               for item in match['ids'].split()):
        return text, ''
    body = text[:match.start()].rstrip()
    return body, text[len(body):]
