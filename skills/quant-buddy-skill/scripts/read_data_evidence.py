"""Expose nested read failures and assemble the documented PE/ROE screen.

Values come only from materialized readData columns. This module does not query,
invent a missing field, or infer values from natural-language answers.
"""
import math
import json
from pathlib import Path

PREFIX = '低PE高ROE_'
TITLES = [PREFIX + group + field for group in ('Top10', 'Next10') for field in ('Score', 'PE', 'ROE')]


def _items(raw):
    current = raw
    for _ in range(4):
        if not isinstance(current, dict):
            return current if isinstance(current, list) else []
        if isinstance(current.get('data'), list):
            return current['data']
        if isinstance(current.get('results'), list):
            return current['results']
        current = current.get('data')
    return []


def _ordered(result):
    # Put validated evidence before potentially large raw arrays so truncating
    # hosts still receive the error or materialized answer.
    return {**{key:result[key] for key in ('code','success','error','failed_ids','answer_evidence') if key in result}, **result}


def build_factor_table(columns, decimal_places=4):
    missing = [title for title in TITLES if title not in columns]
    if missing:
        return {'status':'incomplete', 'missing_columns':missing,
                'message':'缺列时不生成完整Top20；补读对应真实data_id，不能用Score填充PE。'}
    dates = {str(columns[title]['date']) for title in TITLES}
    if len(dates) != 1:
        return {'status':'invalid', 'error':'FACTOR_COLUMN_DATE_MISMATCH'}
    rows = []
    for group in ('Top10', 'Next10'):
        maps = {}
        for field in ('Score', 'PE', 'ROE'):
            values = columns[PREFIX + group + field]['values']
            maps[field] = {str(v['asset']):v for v in values if isinstance(v, dict) and v.get('asset')}
            if len(maps[field]) != len(values):
                return {'status':'invalid', 'error':'FACTOR_DUPLICATE_OR_MISSING_ASSET'}
        selected = [asset for asset, row in maps['Score'].items()
                    if isinstance(row.get('value'), (int,float)) and math.isfinite(row['value']) and row['value'] > 0]
        if len(selected) != 10:
            return {'status':'invalid', 'error':'FACTOR_GROUP_COUNT_MISMATCH', 'group':group, 'count':len(selected)}
        for asset in selected:
            source = {field:maps[field].get(asset) for field in maps}
            if any(not isinstance(v, dict) or not isinstance(v.get('value'), (int,float))
                   or not math.isfinite(v['value']) or v['value'] <= 0 for v in source.values()):
                return {'status':'invalid', 'error':'FACTOR_CELL_MISSING', 'asset':asset}
            pe, roe, score = (source[f]['value'] for f in ('PE','ROE','Score'))
            quantum = 0.5 * 10 ** (-decimal_places)
            if pe <= quantum:
                return {'status':'invalid', 'error':'FACTOR_PRECISION_INSUFFICIENT', 'asset':asset}
            # Compare intervals implied by the API's stated decimal precision,
            # not an arbitrary tolerance that rejects correctly rounded cells.
            if score + quantum + 1e-10 < (roe-quantum)/(pe+quantum) or score-quantum-1e-10 > (roe+quantum)/(pe-quantum):
                return {'status':'invalid', 'error':'FACTOR_RATIO_MISMATCH', 'asset':asset}
            rows.append({'asset':asset, 'name':str(source['Score'].get('name') or asset),
                         'pe_ttm':pe, 'roe_pct':roe, 'roe_pe':score, 'date':next(iter(dates))})
    if len({r['asset'] for r in rows}) != 20:
        return {'status':'invalid', 'error':'FACTOR_SEGMENTS_OVERLAP'}
    rows.sort(key=lambda row:(-row['roe_pe'], row['asset']))
    markdown = ['| 排名 | 代码 | 名称 | PE(TTM) | ROE(%) | ROE/PE | 实际数据日期 |',
                '|---:|---|---|---:|---:|---:|---|']
    for rank, row in enumerate(rows, 1):
        name = row['name'].replace('|', '\\|').replace('\n', ' ')
        markdown.append(f"| {rank} | {row['asset']} | {name} | {row['pe_ttm']:.4f} | {row['roe_pct']:.4f} | {row['roe_pe']:.4f} | {row['date']} |")
    return {'status':'verified', 'rows':rows,
            'column_sources':{title:columns[title]['data_id'] for title in TITLES},
            'markdown':'\n'.join(markdown),
            'methodology':'ROE为平台百分比数值，Score=ROE/PE；只按已返回截面排序，日期不冒充最新交易日。'}


def finalize_read_data(raw, params, skill_root):
    if not isinstance(raw, dict):
        return raw
    result = dict(raw)
    items = [item for item in _items(raw) if isinstance(item, dict)]
    failed = [item for item in items if item.get('status') in ('failed','error') or item.get('error') or item.get('error_code')]
    if failed:
        result.update(code=1, success=False,
                      error={'code':'READ_DATA_PARTIAL_FAILURE', 'message':'部分data_id读取失败；不得补造缺失列或将其他列当作该列。'},
                      failed_ids=[item.get('id') or item.get('data_id') for item in failed])
    if failed or params.get('mode') != 'last_column_full':
        return _ordered(result)
    # One read contains all six IDs: no stale columns from an earlier batch or
    # another process can be promoted into a verified answer.
    columns = {}
    for item in items:
        if item in failed:
            continue
        signature = item.get('signature') or {}
        title = signature.get('title') if isinstance(signature, dict) else None
        column = item.get('last_column_full')
        if title not in TITLES or not isinstance(column, dict):
            continue
        if title in columns:
            result['answer_evidence'] = {'status':'invalid', 'error':'FACTOR_DUPLICATE_TITLE'}
            return _ordered(result)
        if column.get('truncated') or column.get('is_truncated') or not column.get('date') or not isinstance(column.get('values'), list):
            result['answer_evidence'] = {'status':'invalid', 'error':'FACTOR_COLUMN_INCOMPLETE'}
            return _ordered(result)
        columns[title] = {'title':title, 'data_id':item.get('id') or item.get('data_id'),
                          'date':column['date'], 'values':column['values']}
    if columns:
        precision = params.get('decimal_places', 4)
        if not isinstance(precision, int) or not 0 <= precision <= 10:
            result['answer_evidence'] = {'status':'invalid', 'error':'FACTOR_PRECISION_INVALID'}
        else:
            result['answer_evidence'] = build_factor_table(columns, precision)
    return _ordered(result)


def attach_factor_answer(payload, receipt_file, read_data):
    """Materialize only the documented six-column screen from this receipt.

    No ID is transcribed by an LLM and no column from another batch is reused.
    Other formulas and deferred/failed runs retain their existing behavior.
    """
    if not receipt_file or not callable(read_data):
        return payload
    try:
        receipt = json.loads(Path(receipt_file).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return payload
    if receipt.get('success') is not True or receipt.get('status') != 'completed':
        return payload
    selected = [item for item in receipt.get('outputs', []) if item.get('index_title') in TITLES]
    if len(selected) != 6 or len({item['index_title'] for item in selected}) != 6:
        return payload
    sources = {item['index_title']:item.get('data_id') for item in selected}
    if any(not value for value in sources.values()) or len(set(sources.values())) != 6:
        return payload
    params = {'task_id':receipt['task_id'], 'ids':[sources[title] for title in TITLES],
              'mode':'last_column_full', 'decimal_places':8, 'max_items':10000}
    result = dict(payload)
    result['answer_read_params'] = params
    try:
        read = read_data(params)
        evidence = read.get('answer_evidence') or {'status':'invalid', 'error':'FACTOR_READ_FAILED',
                                                    'read_error':read.get('error')}
        if evidence.get('status') == 'verified' and evidence.get('column_sources') != sources:
            evidence = {'status':'invalid', 'error':'FACTOR_RECEIPT_BINDING_MISMATCH'}
        from validation_receipt import _write_json_atomic
        evidence_file = str(Path(receipt_file).with_suffix('.answer-read.json'))
        _write_json_atomic(evidence_file, {'params':params, 'response':read}, '.answer-')
        result['answer_read_evidence_file'] = evidence_file
    except Exception as exc:
        evidence = {'status':'invalid', 'error':'FACTOR_READ_UNAVAILABLE', 'exception_type':type(exc).__name__}
    result['answer_evidence'] = evidence
    result['answer_instruction'] = '仅在answer_evidence.status=verified时直接交付markdown；已自动按收据读取六列，不需手抄ID或重算。失败时明确缺失，不补造表格。'
    return _ordered(result)
