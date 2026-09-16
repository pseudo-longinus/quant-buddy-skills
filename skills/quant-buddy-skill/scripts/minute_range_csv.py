"""Full-column minute-range CSV reader. UTC seconds and trade_date stay separate."""
import copy
import csv
import datetime as dt
import io
import math

_NULLS = {'', 'null', 'none', 'nan', 'inf', 'infinity', '-inf', '-infinity', '+inf', '+infinity'}
_OHLCVA = {'open', 'high', 'low', 'close', 'volume', 'amount'}

def parse_minute_range_csv(text, manifest):
    if not isinstance(manifest, dict) or manifest.get('query_type') != 'minute_range' or manifest.get('status') != 'ok':
        raise ValueError('历史分钟manifest类型或status不合法')
    shape = manifest.get('shape')
    if not isinstance(shape, list) or len(shape) != 2 or any(type(n) is not int or n < 0 for n in shape):
        raise ValueError('历史分钟shape不合法')
    if text is None:
        if shape != [0, 0] or manifest.get('csv_url') or manifest.get('empty') is not True:
            raise ValueError('仅显式无文件空结果可以省略CSV')
        return {**copy.deepcopy(manifest), 'columns': [], 'rows': [], 'source_mode': 'csv'}
    reader = csv.reader(io.StringIO(text.lstrip('\ufeff'), newline=''))
    header = next(reader, [])
    columns = [c.strip() for c in header]
    if len(columns) < 2 or columns[:2] != ['trade_date', 'timestamp'] or len(set(columns)) != len(columns) or any(not c for c in columns):
        raise ValueError('历史分钟CSV须以trade_date,timestamp开头，不能按日频宽表解析')
    if shape[1] != len(columns) or ('columns' in manifest and manifest['columns'] != columns):
        raise ValueError('历史分钟CSV表头与manifest/shape不一致')
    rows, previous = [], None
    for raw in reader:
        if len(raw) != len(columns): raise ValueError('历史分钟CSV行宽不一致')
        try:
            day = dt.datetime.strptime(raw[0], '%Y%m%d').date()
            if len(raw[0]) != 8: raise ValueError()
            stamp = float(raw[1])
            if not math.isfinite(stamp) or (previous is not None and stamp < previous): raise ValueError()
            if manifest.get('start_date') and day < dt.date.fromisoformat(manifest['start_date']): raise ValueError()
            if manifest.get('end_date') and day > dt.date.fromisoformat(manifest['end_date']): raise ValueError()
        except (ValueError, TypeError): raise ValueError('历史分钟交易日/UTC时间戳非法或未升序') from None
        row = [int(raw[0]), stamp]
        for name, cell in zip(columns[2:], raw[2:]):
            cell = cell.strip()
            if cell.lower() in _NULLS: row.append(None); continue
            try:
                value = float(cell)
                row.append(value if math.isfinite(value) else None)
            except ValueError:
                if name in _OHLCVA: raise ValueError('历史分钟行情列含非数值') from None
                row.append(cell)  # 保留上游额外字符串列，不猜列集合。
        rows.append(row); previous = stamp
    if len(rows) != shape[0]: raise ValueError('历史分钟CSV行数与shape不一致')
    return {**copy.deepcopy(manifest), 'columns': columns, 'rows': rows, 'source_mode': 'csv'}
