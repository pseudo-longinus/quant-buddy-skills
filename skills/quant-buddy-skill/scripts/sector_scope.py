"""Keep named industry requests within the catalogue's industry taxonomy."""
import re
from pathlib import Path


def requested_industry(query):
    query = str(query or '')
    catalog = (Path(__file__).resolve().parents[1] / 'presets/sectors.yaml').read_text(encoding='utf-8-sig')
    choices = []
    for name, kind in re.findall(r'- name: "([^"]+)"\s+type: (\w+)', catalog):
        if kind not in {'primary_industry', 'secondary_industry'} or '申万' not in name:
            continue
        base = re.sub(r'[ⅠⅡⅢIVX]+$', '', name.split('（')[0]).strip()
        if len(base) < 2 or base + '概念' in query:
            continue
        if base + '股' in query or base + '行业' in query or name in query:
            choices.append((base, name))
    if not choices:
        return None
    if len({base for base, _ in choices}) > 1:
        return None  # Multi-industry comparison is not a single-universe request.
    longest = max(len(base) for base, _ in choices)
    matches = {name for base, name in choices if len(base) == longest}
    return next(iter(matches)) if len(matches) == 1 else None


def validate_formula_scope(query, params):
    expected = requested_industry(query)
    if not expected:
        return None
    formulas = params.get('formulas') or []
    if not isinstance(formulas, list):
        return None
    sectors = [value.strip().strip('"\'') for formula in formulas if isinstance(formula, str)
               for value in re.findall(r'板块\(([^)]+)\)', formula)]
    # An A-share mask can accompany the precise industry mask. Never infer or
    # replace membership; unknown/alternative sector labels require correction.
    mismatched = [value for value in sectors if value not in {expected, '万得全A'}]
    if not mismatched:
        return None
    return {'code': 1, 'success': False,
            'error': {'code': 'UNIVERSE_SCOPE_MISMATCH',
                      'message': '行业请求不能替换为概念或其他板块；核验精确行业，无法取得时请求澄清。'},
            'expected_sector': expected, 'actual_sectors': mismatched,
            'query_submitted': False}
