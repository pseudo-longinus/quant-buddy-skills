"""Full-column minute-range CSV reader. UTC seconds and trade_date stay separate."""
import copy
import csv
import datetime as dt
import io
import math

_NULLS = {'', 'null', 'none', 'nan', 'inf', 'infinity', '-inf', '-infinity', '+inf', '+infinity'}
_OHLCVA = {'open', 'high', 'low', 'close', 'volume', 'amount'}
_OPTION_CHAIN_NUMS = _OHLCVA | {'strike', 'timestamp', 'open_interest', 'forward', 'self_iv', 'self_delta'}
_OPTION_CHAIN_PREFIX = ['trade_date', 'contract_id', 'expiration', 'strike', 'option_type', 'timestamp']


def _parse_ymd_int(value):
    raw = str(value or '').strip().replace('-', '')
    if len(raw) != 8 or not raw.isdigit():
        raise ValueError(f'非法日期: {value}')
    dt.datetime.strptime(raw, '%Y%m%d')
    return int(raw)


def is_option_chain_minute_result(data):
    if not isinstance(data, dict) or data.get('mode') not in ('json', 'csv'):
        return False
    if is_multi_result(data) or data.get('query_type') == 'minute_range' or data.get('csv_fields'):
        return False
    if not isinstance(data.get('ticker'), str) or not data['ticker'].strip():
        return False
    if data.get('start_date') is None or data.get('end_date') is None:
        return False
    if data['mode'] == 'json':
        cols = data.get('columns')
        return isinstance(cols, list) and cols[:5] == _OPTION_CHAIN_PREFIX[:5]
    shape = data.get('shape')
    return isinstance(data.get('url'), str) and bool(data['url'].strip()) and isinstance(shape, list) and len(shape) == 2


def parse_option_chain_minute_result(manifest, text=None):
    """Validate JSON/CSV 16-column option_chain_minute long tables."""
    if not is_option_chain_minute_result(manifest):
        raise ValueError('期权链分钟结果类型非法')
    result = copy.deepcopy(manifest)
    if manifest['mode'] == 'csv' and text is not None:
        reader = csv.reader(io.StringIO(text.lstrip('\ufeff'), newline=''))
        columns = [c.strip() for c in next(reader, [])]
        rows = list(reader)
        result['source_mode'] = 'csv'
    elif isinstance(manifest.get('rows'), list):
        columns, rows = manifest.get('columns') or [], manifest['rows']
    elif manifest['mode'] == 'json':
        columns, rows = manifest.get('columns') or [], manifest.get('data')
    else:
        raise ValueError('期权链分钟CSV尚未下载')
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise ValueError('期权链分钟表格非法')
    if columns and (columns[:6] != _OPTION_CHAIN_PREFIX or len(set(columns)) != len(columns) or any(not c for c in columns)):
        raise ValueError('期权链分钟表头非法')
    if rows and not columns:
        raise ValueError('期权链分钟缺少列名')
    start_ymd = _parse_ymd_int(manifest.get('start_date'))
    end_ymd = _parse_ymd_int(manifest.get('end_date'))
    if start_ymd > end_ymd:
        raise ValueError('期权链分钟日期区间非法')
    parsed = []
    for raw in rows:
        if not isinstance(raw, list) or len(raw) != len(columns):
            raise ValueError('期权链分钟行宽不一致')
        row = []
        for name, value in zip(columns, raw):
            if name in ('trade_date', 'expiration'):
                ymd = _parse_ymd_int(value)
                if name == 'trade_date' and not (start_ymd <= ymd <= end_ymd):
                    raise ValueError('期权链分钟交易日越界')
                row.append(ymd)
            elif name in ('contract_id', 'option_type'):
                text_val = '' if value is None else str(value).strip()
                if not text_val:
                    raise ValueError(f'期权链分钟{name}缺失')
                row.append(text_val)
            elif name in _OPTION_CHAIN_NUMS:
                if value is None or (isinstance(value, str) and value.strip().lower() in _NULLS):
                    if name in ('strike', 'timestamp'):
                        raise ValueError(f'期权链分钟{name}缺失')
                    row.append(None)
                else:
                    if isinstance(value, bool):
                        raise ValueError('期权链分钟数值非法')
                    number = float(value)
                    if not math.isfinite(number):
                        raise ValueError('期权链分钟数值非法')
                    row.append(int(number) if name == 'timestamp' and number.is_integer() else number)
            else:
                row.append(None if isinstance(value, str) and value.strip().lower() in _NULLS else value)
        parsed.append(row)
    shape = manifest.get('shape')
    if shape is not None and (
        not isinstance(shape, list) or len(shape) != 2
        or any(type(n) is not int or n < 0 for n in shape)
        or shape != [len(parsed), len(columns)]
    ):
        raise ValueError('期权链分钟shape与内容不一致')
    result.update(columns=columns, rows=parsed)
    return result


def is_multi_result(data):
    return isinstance(data, dict) and data.get('status') == 'ok' and 'asset_count' in data and 'lifecycle' in data


def parse_multi_result(manifest, text=None):
    """Validate JSON/CSV multi long tables without changing their public schema."""
    from minute_range_contract import multi_date
    if not is_multi_result(manifest) or manifest.get('mode') not in ('json', 'csv'):
        raise ValueError('多资产分钟结果类型非法')
    result = copy.deepcopy(manifest)
    if manifest['mode'] == 'csv' and text is not None:
        reader = csv.reader(io.StringIO(text.lstrip('\ufeff'), newline=''))
        columns = [c.strip() for c in next(reader, [])]
        if 'columns' in manifest and manifest['columns'] != columns: raise ValueError('多资产分钟CSV表头不一致')
        rows = list(reader)
        result['source_mode'] = 'csv'
    elif isinstance(manifest.get('rows'), list):
        columns, rows = manifest.get('columns'), manifest['rows']
    elif manifest['mode'] == 'json':
        columns, rows = manifest.get('columns', []), manifest.get('data')
    else:
        raise ValueError('多资产分钟CSV尚未下载')
    if not isinstance(columns, list) or not isinstance(rows, list): raise ValueError('多资产分钟表格非法')
    if any(not isinstance(c, str) or not c for c in columns) or len(set(columns)) != len(columns): raise ValueError('多资产分钟列名非法')
    if columns and (columns[:2] != ['trade_date', 'ticker'] or 'timestamp' not in columns): raise ValueError('多资产分钟须包含trade_date,ticker及timestamp')
    if rows and not columns: raise ValueError('多资产分钟缺少列名')
    start, end = multi_date(manifest.get('start_date')), multi_date(manifest.get('end_date'))
    if start > end: raise ValueError('多资产分钟日期区间非法')
    parsed, previous = [], None
    for raw in rows:
        if not isinstance(raw, list) or len(raw) != len(columns): raise ValueError('多资产分钟行宽不一致')
        row = []
        for name, value in zip(columns, raw):
            if name == 'ticker':
                if not isinstance(value, str) or not value.strip(): raise ValueError('多资产分钟ticker缺失')
                row.append(value)
            elif name == 'trade_date':
                day = multi_date(value)
                if not start <= day <= end: raise ValueError('多资产分钟交易日越界')
                row.append(int(day.strftime('%Y%m%d')))
            elif name == 'timestamp' or name in _OHLCVA or name in ('open_interest', 'self_iv', 'self_delta'):
                if value is None or (isinstance(value, str) and value.strip().lower() in _NULLS):
                    if name == 'timestamp': raise ValueError('多资产分钟时间戳缺失')
                    row.append(None)
                else:
                    if isinstance(value, bool): raise ValueError('多资产分钟数值非法')
                    number = float(value)
                    if not math.isfinite(number): raise ValueError('多资产分钟数值非法')
                    row.append(number)
            else:
                row.append(None if isinstance(value, str) and value.strip().lower() in _NULLS else value)
        key = (row[1], row[columns.index('timestamp')])
        if previous is not None and key < previous: raise ValueError('多资产分钟行须按ticker及timestamp升序')
        previous = key
        parsed.append(row)
    shape = manifest.get('shape')
    if shape is not None and (not isinstance(shape, list) or len(shape) != 2 or any(type(n) is not int or n < 0 for n in shape) or shape != [len(rows), len(columns)]):
        raise ValueError('多资产分钟shape与内容不一致')
    if type(manifest.get('asset_count')) is not int or manifest['asset_count'] != len({r[1] for r in parsed}): raise ValueError('多资产分钟asset_count不一致')
    if type(manifest.get('empty')) is not bool or manifest['empty'] != (not parsed): raise ValueError('多资产分钟empty与内容不一致')
    result.update(columns=columns, rows=parsed)
    return result

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
