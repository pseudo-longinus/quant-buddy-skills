"""History-minute request contract; no I/O. Market-local today is checked by server."""
import calendar
import datetime as dt
import re

PARAMS = {'asset', 'start_date', 'end_date', 'start_offset', 'end_offset'}
MULTI_PARAMS = {'assets', 'asset', 'market', 'date_mode', 'start_date', 'end_date',
                'lookback_trade_days', 'end_trade_offset', 'start_minute', 'end_minute',
                'timezone', 'with_adjustment'}


def multi_date(value):
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(r'(?:[0-9]{8}|[0-9]{4}-[0-9]{2}-[0-9]{2})', value):
        raise ValueError('日期格式非法')
    parsed = dt.datetime.strptime(value, '%Y%m%d' if len(value) == 8 else '%Y-%m-%d').date()
    if not 1900 <= parsed.year <= 2149:
        raise ValueError('日期超出范围')
    return parsed


def validate_multi_request(payload):
    """Public multi contract only. Calendar/asset resolution remains server-owned."""
    if not isinstance(payload, dict):
        return [('INVALID_PAYLOAD', '参数必须为对象')]
    errors = []
    def add(code, message): errors.append((code, message))
    extra = sorted(set(payload) - MULTI_PARAMS)
    if extra: add('UNKNOWN_PARAMETER', '不支持字段：' + ', '.join(extra) + '；多资产请用assets，不传tickers/format/fields')
    if sum(k in payload for k in ('asset', 'assets', 'market')) != 1:
        add('PARAMETER_CONFLICT', 'assets、asset、market必须且只能提供一个')
    def asset_ok(value): return isinstance(value, str) and 1 <= len(value.strip()) <= 100
    if 'asset' in payload and not asset_ok(payload['asset']): add('INVALID_ASSET', 'asset须为非空名称或代码')
    if 'assets' in payload:
        assets = payload['assets']
        if not isinstance(assets, list) or not 1 <= len(assets) <= 5000 or not all(asset_ok(a) for a in assets):
            add('INVALID_ASSETS', 'assets须为1～5000个名称或代码')
    if 'market' in payload and payload['market'] not in ('cn_stock', 'cn_index', 'us_stock', 'hk_stock', 'cn_future'):
        add('INVALID_MARKET', 'market不在支持范围')
    mode = payload.get('date_mode', 'absolute')
    if mode not in ('absolute', 'rolling', 'current_trade_day'): add('INVALID_DATE_MODE', 'date_mode不支持')
    if mode == 'absolute':
        if any(k in payload for k in ('lookback_trade_days', 'end_trade_offset')): add('PARAMETER_CONFLICT', 'absolute禁止rolling参数')
        try:
            start = multi_date(payload.get('start_date'))
            end = multi_date(payload.get('end_date', payload.get('start_date')))
            if not 0 <= (end - start).days <= 372: add('INVALID_DATE_RANGE', '区间需正序且最多373自然日')
        except (ValueError, TypeError): add('INVALID_DATE', 'absolute需要start_date真实日期，end_date默认同日')
    elif mode in ('rolling', 'current_trade_day'):
        forbidden = ('start_date', 'end_date') + (('lookback_trade_days', 'end_trade_offset') if mode == 'current_trade_day' else ())
        if any(k in payload for k in forbidden): add('PARAMETER_CONFLICT', mode + '日期参数冲突')
    if mode == 'rolling':
        for key, lo, hi, default in (('lookback_trade_days', 1, 373, 1), ('end_trade_offset', -372, 0, 0)):
            value = payload.get(key, default)
            if type(value) is not int or not lo <= value <= hi: add('INVALID_PARAMETER', key + '超出整数范围')
    for key in ('start_minute', 'end_minute'):
        value = payload.get(key)
        if value is None: continue
        raw = str(value) if type(value) is int else value
        if isinstance(raw, str) and re.fullmatch(r'(?:[0-9]{1,4}|[0-9]{2}:[0-9]{2})', raw):
            digits = raw.replace(':', '').zfill(4)
            if int(digits[:2]) < 24 and int(digits[2:]) < 60: continue
        add('INVALID_MINUTE', key + '须为HH:MM/HHMM或null')
    if 'timezone' in payload and (not isinstance(payload['timezone'], str) or not payload['timezone'].strip()): add('INVALID_TIMEZONE', 'timezone须为IANA时区')
    if 'with_adjustment' in payload and type(payload['with_adjustment']) is not bool: add('INVALID_PARAMETER', 'with_adjustment须为布尔值')
    return errors

def validate_request(payload):
    if not isinstance(payload, dict):
        return [('INVALID_PAYLOAD', '参数必须为对象')]
    errors = []
    extra = sorted(set(payload) - PARAMS)
    if extra: errors.append(('UNSUPPORTED_PARAMETER', '不支持字段：' + ', '.join(extra)))
    if not isinstance(payload.get('asset'), str) or not payload['asset'].strip():
        errors.append(('ASSET_REQUIRED', 'asset必须是单个非空字符串'))
    absolute = any(k in payload for k in ('start_date', 'end_date'))
    offset = any(k in payload for k in ('start_offset', 'end_offset'))
    if absolute and offset: errors.append(('DATE_MODE_CONFLICT', '绝对日期与offset互斥'))
    if absolute:
        if not all(k in payload for k in ('start_date', 'end_date')):
            errors.append(('DATE_PAIR_REQUIRED', 'start_date和end_date必须成对'))
        else:
            try:
                values = [payload[k] for k in ('start_date', 'end_date')]
                if any(not isinstance(v, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', v) for v in values): raise ValueError()
                start, end = map(dt.date.fromisoformat, values)
                y, m = divmod(start.year * 12 + start.month - 1 + 3, 12)
                limit = dt.date(y, m + 1, min(start.day, calendar.monthrange(y, m + 1)[1]))
                if start > end: errors.append(('INVALID_DATE_RANGE', '起点不能晚于终点'))
                elif end >= limit: errors.append(('DATE_RANGE_TOO_LARGE', '终点必须早于起点加三个日历月'))
            except (ValueError, OverflowError): errors.append(('INVALID_DATE', '日期必须为YYYY-MM-DD真实日期'))
    if offset:
        for key in ('start_offset', 'end_offset'):
            if key in payload and (type(payload[key]) is not int or not -70 <= payload[key] <= -1):
                errors.append(('OFFSET_OUT_OF_RANGE', key + '必须为-70至-1整数自然日偏移'))
        start, end = payload.get('start_offset', payload.get('end_offset', -1)), payload.get('end_offset', -1)
        if type(start) is int and type(end) is int and start > end: errors.append(('INVALID_DATE_RANGE', 'offset起点不能晚于终点'))
    return errors
