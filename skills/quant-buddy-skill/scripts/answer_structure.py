"""Optional presentation intent; never replaces validated computation evidence.

Vendored identically in QBS and QBV so either Skill can be installed alone.
"""
import copy

SCHEMA = 'qbs_answer_structure_v1'
DEFAULT_RANK_LIMIT = 20
PANEL_TYPES = {'summary': 'text', 'metric': 'number', 'ranking': 'bar',
               'comparison': 'table', 'timeseries': 'line', 'table': 'table', 'note': 'text'}


def normalize_answer_structure(value, outputs, insights):
    """Return (normalized_or_none, status, reason); invalid optional intent is soft."""
    if value is None:
        return None, 'absent', None
    try:
        if not isinstance(value, dict) or value.get('schema_version') != SCHEMA:
            raise ValueError('unsupported_schema')
        blocks = value.get('blocks')
        if not isinstance(blocks, list) or not blocks or len(blocks) > 40:
            raise ValueError('invalid_blocks')
        roles = {o.get('role') for o in outputs if isinstance(o, dict)}
        insight_ids = {o.get('id') for o in insights if isinstance(o, dict) and isinstance(o.get('id'), str)}
        seen = set()
        result = []
        for raw in blocks:
            if not isinstance(raw, dict):
                raise ValueError('invalid_block')
            block = {}
            for key in ('id', 'type', 'title', 'as_of', 'unit', 'methodology', 'update_mode'):
                item = raw.get(key)
                if not isinstance(item, str) or not item.strip():
                    raise ValueError('missing_' + key)
                block[key] = item.strip()
            if block['id'] in seen or block['type'] not in PANEL_TYPES:
                raise ValueError('duplicate_id_or_unknown_type')
            seen.add(block['id'])
            if block['update_mode'] not in {'dynamic', 'fixed', 'historical'}:
                raise ValueError('invalid_update_mode')
            for key, allowed in (('role_refs', roles), ('insight_refs', insight_ids)):
                refs = raw.get(key, [])
                if not isinstance(refs, list) or any(not isinstance(ref, str) or ref not in allowed for ref in refs):
                    raise ValueError('unknown_' + key)
                block[key] = list(dict.fromkeys(refs))
            if block['type'] not in {'summary', 'note'} and not block['role_refs']:
                raise ValueError('data_block_without_role')
            if block['update_mode'] == 'dynamic' and not block['role_refs']:
                raise ValueError('dynamic_block_without_role')
            if block['type'] in {'summary', 'note'} and not block['insight_refs']:
                raise ValueError('text_without_verified_insight')
            if block['type'] == 'ranking':
                if raw.get('rank_order') not in {'asc', 'desc'}:
                    raise ValueError('invalid_rank_order')
                # Keep ranking output bounded by default. This controls the
                # page's visible rows, not the size of the computed universe.
                limit = DEFAULT_RANK_LIMIT if 'rank_limit' not in raw else raw.get('rank_limit')
                if type(limit) is not int or limit < 1:
                    raise ValueError('invalid_rank_limit')
                block.update(rank_order=raw['rank_order'], rank_limit=limit)
            result.append(block)
        return {'schema_version': SCHEMA, 'blocks': result}, 'valid', None
    except (ValueError, TypeError) as exc:
        return None, 'invalid', str(exc)


def attach_answer_structure(target, value):
    normalized, status, reason = normalize_answer_structure(
        value, target.get('validated_outputs', []), target.get('validated_insights', []))
    target.pop('answer_structure', None)
    if status != 'absent':
        target['answer_structure_status'] = status
        if normalized is not None:
            target['answer_structure'] = normalized
            if isinstance(value, dict) and value.get('source') == 'validated_role_order':
                target['answer_structure_source'] = 'validated_role_order'
            target.pop('answer_structure_warning', None)
        else:
            target['answer_structure_warning'] = reason
    return target


def structure_from_roles(roles):
    """Conservative ordered evidence layout, never reverse-engineer prose.

    Callers order roles as in their answer. Explicit structures are preferred
    for summaries, TopN splits or charts; absent semantics remain unverified.
    """
    blocks = []
    for index, role in enumerate(roles):
        blocks.append({
            'id': 'evidence_' + str(index + 1), 'type': 'table',
            'title': str(role.get('title') or role.get('index_title') or role['role']),
            'role_refs': [role['role']], 'insight_refs': [],
            'as_of': str(role.get('date') or role.get('as_of') or '未核验'),
            'unit': str(role.get('unit') or '未核验'),
            'methodology': str(role.get('description') or role.get('methodology') or '未核验'),
            'update_mode': 'historical',
        })
    return {'schema_version': SCHEMA, 'source': 'validated_role_order', 'blocks': blocks}


def layout_for(structure):
    """Semantic panel plan, not a publishable spec or substitute for runtime binding."""
    if structure is None:
        return []
    return [{**copy.deepcopy(block), 'panel_type': PANEL_TYPES[block['type']],
             'requires_dynamic_text_binding': block['update_mode'] == 'dynamic' and
                 block['type'] in {'summary', 'note'}} for block in structure['blocks']]
