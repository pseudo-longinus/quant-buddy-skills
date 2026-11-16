"""Structured daily K-line contracts and normalization; no network or credentials."""
import math
import re
from datetime import datetime

FIELDS = ('open', 'high', 'low', 'close', 'volume')


def normalized_indicators(values):
    if not isinstance(values, list) or len(values) > 128:
        raise ValueError('indicators必须为字符串数组，最多128项')
    names = set()
    for value in values:
        if not isinstance(value, str):
            raise ValueError('指标必须为字符串')
        name = value.strip().lower()
        match = re.fullmatch(r'(?:vol)?ma([1-9]\d{0,2})', name)
        if name not in ('volume', 'boll', 'macd', 'rsi') and not (match and int(match[1]) <= 250):
            raise ValueError('不支持的指标：' + value)
        names.add(name)
    if len(names) > 32:
        raise ValueError('最多32个不同指标')
    return sorted(names)


def indicator_fields(names):
    result = []
    for name in names:
        result.extend({'volume': [], 'boll': ['boll_mid', 'boll_up', 'boll_dn'],
                       'macd': ['macd_dif', 'macd_dea', 'macd_bar']}.get(name, [name]))
    return result


def valid_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{8}', value):
        return False
    try:
        return datetime.strptime(value, '%Y%m%d').strftime('%Y%m%d') == value and int(value[:4]) >= 1900
    except ValueError:
        return False


def validate_request(payload, *, grant=False):
    errors = []
    if not isinstance(payload, dict):
        return [('INVALID_KLINE_REQUEST', 'payload必须为对象')]
    extras = set(payload) - ({'begin_date', 'limit_candles', 'indicators'} if grant else {'asset', 'ticker', 'begin_date', 'limit_candles', 'indicators'})
    if extras:
        errors.append(('UNSUPPORTED_PARAMETER', 'K线授权不支持参数：' + ', '.join(sorted(extras))))
    if not grant:
        if 'asset' in payload and 'ticker' in payload:
            errors.append(('INVALID_KLINE_REQUEST', 'asset与ticker不能同时传入'))
        if 'asset' in payload:
            asset = payload['asset']
            if not isinstance(asset, str) or not asset.strip() or len(asset) > 100:
                errors.append(('INVALID_ASSET', 'asset必须为单个资产名称、简称或代码，长度不超过100字符'))
        elif not isinstance(payload.get('ticker'), str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.^:_-]{0,63}', payload['ticker'].strip()):
            errors.append(('INVALID_KLINE_REQUEST', 'asset必填；兼容ticker必须为单个标准资产代码'))
    if type(payload.get('limit_candles', 120)) is not int or not 1 <= payload.get('limit_candles', 120) <= 2000:
        errors.append(('INVALID_KLINE_REQUEST', 'limit_candles必须为1..2000整数'))
    if 'begin_date' in payload and (type(payload['begin_date']) is not int or not valid_date(str(payload['begin_date']))):
        errors.append(('INVALID_KLINE_REQUEST', 'begin_date必须为整数YYYYMMDD合法日期'))
    try:
        normalized_indicators(payload.get('indicators', []))
    except ValueError as error:
        errors.append(('INVALID_INDICATOR', str(error)))
    return errors


def validate_result(payload, result):
    def fail(code):
        return {'success': False, 'error_class': 'system', 'error_code': code}
    if validate_request(payload):
        return fail('INVALID_KLINE_REQUEST')
    if not isinstance(result, dict) or result.get('code') != 0 or result.get('success') is False:
        return fail('KLINE_QUERY_FAILED')
    data = result.get('data')
    if not isinstance(data, dict) or type(data.get('schema_version')) is not int or data['schema_version'] != 1 or data.get('period') != '1d':
        return fail('KLINE_RESPONSE_INVALID')
    ticker = data.get('ticker')
    if not isinstance(ticker, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.^:_-]{0,63}', ticker):
        return fail('KLINE_ASSET_MISMATCH')
    if 'asset' in payload:
        resolution = data.get('asset_resolution')
        if not isinstance(resolution, dict) or resolution.get('asset') != payload['asset'].strip() or resolution.get('ticker') != ticker:
            return fail('KLINE_ASSET_MISMATCH')
    elif ticker != payload['ticker'].strip():
        return fail('KLINE_ASSET_MISMATCH')
    dates = data.get('labels')
    if not isinstance(dates, list) or not dates or len(dates) > payload.get('limit_candles', 120):
        return fail('KLINE_WINDOW_INVALID')
    if any(not valid_date(day) or i and day <= dates[i - 1] for i, day in enumerate(dates)):
        return fail('KLINE_DATES_INVALID')
    if payload.get('begin_date') and int(dates[0]) < payload['begin_date']:
        return fail('KLINE_WINDOW_INVALID')
    if type(data.get('data_points')) is not int or data['data_points'] != len(dates) or data.get('first_date') != dates[0] or data.get('last_date') != dates[-1]:
        return fail('KLINE_WINDOW_INVALID')
    expected = normalized_indicators(payload.get('indicators', []))
    try:
        if normalized_indicators(data.get('indicators')) != expected:
            return fail('KLINE_INDICATORS_MISMATCH')
    except ValueError:
        return fail('KLINE_INDICATORS_MISMATCH')
    calculated = data.get('indicator_data')
    if not isinstance(calculated, dict) or set(calculated) != set(indicator_fields(expected)):
        return fail('KLINE_INDICATORS_MISMATCH')
    finite = lambda value: type(value) in (int, float) and math.isfinite(value)
    for name, values in [(key, data.get(key)) for key in FIELDS] + list(calculated.items()):
        if not isinstance(values, list) or len(values) != len(dates):
            return fail('KLINE_DATA_MISMATCH')
        nullable = name not in ('open', 'high', 'low', 'close')
        if any(not (nullable and value is None) and not finite(value) for value in values):
            return fail('KLINE_VALUES_INVALID')
    for i in range(len(dates)):
        o, h, low, c, vol = (data[key][i] for key in FIELDS)
        if min(o, h, low, c) <= 0 or low > min(o, c) or h < max(o, c) or vol is not None and vol < 0:
            return fail('KLINE_VALUES_INVALID')
    if not isinstance(data.get('warnings'), list):
        return fail('KLINE_RESPONSE_INVALID')
    return {'success': True}


def rows_from_data(data):
    payload = {'ticker': data.get('ticker'), 'limit_candles': 2000, 'indicators': data.get('indicators')}
    checked = validate_result(payload, {'code': 0, 'data': data})
    if not checked['success']:
        raise ValueError(checked['error_code'])
    columns = {key: data[key] for key in FIELDS}
    columns.update(data['indicator_data'])
    return [{'日期': day, **{key: values[i] for key, values in columns.items()}}
            for i, day in enumerate(data['labels'])]
