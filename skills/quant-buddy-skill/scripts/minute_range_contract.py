"""History-minute request contract; no I/O. Market-local today is checked by server."""
import calendar
import datetime as dt
import re

PARAMS = {'asset', 'start_date', 'end_date', 'start_offset', 'end_offset'}

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
