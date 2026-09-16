"""Shared local Grant shape/capability checks. No credentials or network I/O."""
import math
import hashlib
import json
import re
from datetime import datetime

TOOL_BY_KIND = {
    'fast_query': 'fast_query',
    'fast_query_minute': 'fast_query_minute',
    'fast_query_minute_range': 'fast_query_minute_range',
    'stock_profile': 'stockProfile',
    'composition_select': 'selectByComposition',
}
MINUTE_FIELDS = {
    'open': 'open', '开盘价': 'open', 'high': 'high', '最高价': 'high',
    'low': 'low', '最低价': 'low', 'close': 'close', '收盘价': 'close',
    '最新价': 'close', '现价': 'close', '当前价': 'close',
    'volume': 'volume', '成交量': 'volume', 'amount': 'amount', '成交额': 'amount', 'money': 'amount',
}


def contract_errors(contract, role_id=''):
    errors = []
    def add(code, message):
        errors.append({'role_id': role_id, 'stage': 'grant_preflight', 'error_code': code,
                       'message': message, 'retryable': False, 'next_action': 'revise_contract'})
    if not isinstance(contract, dict):
        add('GRANT_PAYLOAD_INVALID', 'Grant contract必须是对象')
        return errors
    kind, payload = contract.get('kind'), contract.get('payload')
    if not isinstance(kind, str) or kind not in TOOL_BY_KIND:
        add('GRANT_KIND_UNSUPPORTED', '不支持的Grant kind；支持：' + ', '.join(TOOL_BY_KIND))
    if not isinstance(payload, dict) or not payload:
        add('GRANT_PAYLOAD_INVALID', 'Grant payload必须是非空对象')
        return errors
    if kind == 'fast_query_minute':
        extra = sorted(set(payload) - {'asset', 'fields'})
        if extra:
            add('MINUTE_SCOPE_UNSUPPORTED', '分钟Grant仅支持单资产当前/最近完整交易日，禁止历史或额外参数：' + ', '.join(extra))
        if not isinstance(payload.get('asset'), str) or not payload['asset'].strip():
            add('MINUTE_ASSET_REQUIRED', 'asset必须是一个真实资产名称或代码，不能是数组/研究ID')
        fields = payload.get('fields')
        if not isinstance(fields, list) or not fields or any(not isinstance(f, str) or f not in MINUTE_FIELDS for f in fields):
            add('MINUTE_FIELDS_INVALID', 'fields必须是非空OHLCVA字段数组')
    if kind == 'fast_query_minute_range':
        from minute_range_contract import validate_request
        for code, message in validate_request(payload): add(code, message)
    return errors


def grant_set_errors(grants):
    errors, names = [], set()
    for index, item in enumerate(grants):
        if not isinstance(item, dict):
            errors.append({'role_id': str(index), 'error_code': 'INVALID_GRANT', 'message': 'Grant必须是对象', 'retryable': False})
            continue
        name = str(item.get('role_id') or item.get('name') or '')
        if not name or name in names:
            errors.append({'role_id': name, 'error_code': 'INVALID_GRANT_NAME', 'message': 'role缺失或重复', 'retryable': False})
        names.add(name)
        contract = item.get('contract')
        errors.extend(contract_errors(contract, name))
        fingerprint = hashlib.sha256(json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if not contract_errors(contract, name) and item.get('contract_fingerprint') != fingerprint:
            errors.append({'role_id': name, 'error_code': 'GRANT_FINGERPRINT_MISMATCH', 'message': 'Grant合同fingerprint不一致', 'retryable': False})
    return errors


def _failure(code, error_class='system'):
    return {'success': False, 'error_class': error_class, 'error_code': code}


def _ticker(value):
    text = str(value or '').upper().replace(':', '')
    suffix = re.fullmatch(r'(\d{4,6})\.(SH|SZ|BJ|HK)', text)
    return suffix.group(2) + suffix.group(1) if suffix else text


def evaluate_minute(payload, result):
    """Validate the documented dates + fields parallel-array minute contract."""
    if not isinstance(result, dict) or result.get('code') not in (0, None) or result.get('success') is False:
        return _failure('MINUTE_QUERY_FAILED')
    data = result.get('data')
    if not isinstance(data, dict) or data.get('success') is False:
        return _failure('MINUTE_RESPONSE_INVALID')
    if data.get('query_type') != 'minute' or data.get('interval') != '1min':
        return _failure('MINUTE_RESPONSE_INVALID')
    if data.get('data_scope') not in ('current_session', 'latest_completed'):
        return _failure('MINUTE_SCOPE_INVALID')
    zone = data.get('timezone')
    if not isinstance(zone, str) or not zone.strip():
        return _failure('MINUTE_TIMEZONE_INVALID')
    requested = _ticker(payload.get('asset'))
    returned = _ticker(data.get('ticker'))
    if re.fullmatch(r'(?:SH|SZ|BJ|HK)\d{4,6}|[A-Z]{1,6}\.[NOA]', requested) and requested != returned:
        return _failure('MINUTE_ASSET_MISMATCH')
    if re.fullmatch(r'(?:SH|SZ|BJ)\d{6}', returned) and zone != 'Asia/Shanghai':
        return _failure('MINUTE_TIMEZONE_INVALID')
    if returned.startswith('HK') and zone not in ('Asia/Hong_Kong', 'Asia/Shanghai'):
        return _failure('MINUTE_TIMEZONE_INVALID')
    try:
        trade_date = datetime.strptime(str(data['trade_date']), '%Y%m%d').date()
        dates = data['dates']
        if not isinstance(dates, list):
            return _failure('MINUTE_TIMELINE_INVALID')
        times = [datetime.fromisoformat(str(d).replace('Z', '+00:00')) for d in dates]
        is_future = bool(re.fullmatch(r'[A-Z]+(?:_S|[0-9]+)?\.(?:DCE|CZC|CZCE|SHF|SHFE|CFE|CFFEX|INE|GFE|GFEX)', returned))
        wrong_day = any(t.date() > trade_date if is_future else t.date() != trade_date for t in times)
        if wrong_day or any(a >= b for a, b in zip(times, times[1:])):
            return _failure('MINUTE_TIMELINE_INVALID')
    except (ValueError, TypeError, KeyError):
        return _failure('MINUTE_TIMELINE_INVALID')
    fields = data.get('fields')
    required = list(dict.fromkeys(MINUTE_FIELDS[f] for f in payload['fields']))
    if not isinstance(fields, dict) or any(not isinstance(fields.get(f), list) or len(fields[f]) != len(dates) for f in required):
        return _failure('MINUTE_FIELDS_INVALID')
    if not dates:
        return _failure('MINUTE_DATA_EMPTY', 'data')
    def finite(value):
        return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)
    for field in required:
        values = fields[field]
        if any(v is not None and (not finite(v) or v < 0) for v in values):
            return _failure('MINUTE_VALUES_INVALID')
        if not any(finite(v) for v in values):
            return _failure('MINUTE_FIELD_UNAVAILABLE', 'data')
    if not any(all(finite(fields[f][i]) for f in required) for i in range(len(dates))):
        return _failure('MINUTE_ALIGNED_DATA_EMPTY', 'data')
    return {'success': True, 'trade_date': data['trade_date'], 'timezone': zone,
            'data_scope': data['data_scope'], 'row_count': len(dates), 'fields': required}


def evaluate_minute_range(payload, result):
    if not isinstance(result, dict) or result.get('code') not in (0, None) or result.get('success') is False:
        return _failure('MINUTE_RANGE_QUERY_FAILED')
    data = result.get('data')
    if not isinstance(data, dict) or data.get('status') != 'ok' or data.get('query_type') != 'minute_range':
        return _failure('MINUTE_RANGE_RESPONSE_INVALID')
    if data.get('interval') != '1min' or data.get('data_scope') != 'historical' or not data.get('timezone'):
        return _failure('MINUTE_RANGE_SCOPE_INVALID')
    requested = _ticker(payload.get('asset'))
    if re.fullmatch(r'(?:SH|SZ|BJ|HK)[0-9]{4,6}|[A-Z0-9_]+\.(?:DCE|CZC|SHF|CFE|INE|GFE|N|O|A)', requested) and requested != _ticker(data.get('ticker')):
        return _failure('MINUTE_RANGE_ASSET_MISMATCH')
    for key in ('start_date', 'end_date'):
        if key in payload and payload[key] != data.get(key): return _failure('MINUTE_RANGE_DATE_MISMATCH')
    try:
        from fast_query_csv import download_and_hydrate
        hydrated = download_and_hydrate(data, timeout=20)
        result['data'] = hydrated
    except (ValueError, OSError): return _failure('MINUTE_RANGE_CSV_INVALID')
    if not hydrated['rows']: return _failure('MINUTE_RANGE_DATA_EMPTY', 'data')
    return {'success': True, 'start_date': data.get('start_date'), 'end_date': data.get('end_date'),
            'row_count': len(hydrated['rows']), 'columns': hydrated['columns'], 'warnings': data.get('warnings', [])}
