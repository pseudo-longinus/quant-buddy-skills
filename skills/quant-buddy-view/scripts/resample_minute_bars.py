#!/usr/bin/env python3
"""Derive 30-minute bars from a materialized 1-minute range artifact.

The upstream contract remains 1-minute CSV. This helper is an explicit,
lossy display/analysis transform and keeps the source interval in metadata.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import math
import os
import tempfile
from pathlib import Path
try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python 3.8: domestic futures use a fixed +08:00 offset.
    ZoneInfo = None


_OHLC = ("open", "high", "low", "close")
_SUM = ("volume", "amount")
_LAST = ("open_interest",)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _last_value(values):
    for value in reversed(values):
        if value is not None:
            return value
    return None


def _first_value(values):
    for value in values:
        if value is not None:
            return value
    return None


def _bucket_timestamp(timestamp, timezone, interval_minutes):
    local = dt.datetime.fromtimestamp(float(timestamp), dt.timezone.utc).astimezone(timezone)
    minute = (local.minute // interval_minutes) * interval_minutes
    bucket = local.replace(minute=minute, second=0, microsecond=0)
    return int(bucket.timestamp())


def _resolve_timezone(name):
    if ZoneInfo is not None:
        return ZoneInfo(name)
    if name in ("Asia/Shanghai", "Asia/Hong_Kong"):
        return dt.timezone(dt.timedelta(hours=8))
    raise ValueError("当前Python版本无法解析该timezone；国内期货请使用Asia/Shanghai")


def _aggregate_column(name, values):
    if name == "open":
        return _first_value(values)
    if name == "high":
        numeric = [value for value in values if _number(value)]
        return max(numeric) if numeric else None
    if name == "low":
        numeric = [value for value in values if _number(value)]
        return min(numeric) if numeric else None
    if name == "close":
        return _last_value(values)
    if name in _SUM:
        numeric = [value for value in values if _number(value)]
        return sum(numeric) if numeric else None
    if name in _LAST:
        return _last_value(values)
    return _last_value(values)


def resample_minute_data(data, *, interval_minutes=30):
    """Return a 30-minute derived artifact from parsed minute-range data."""
    if interval_minutes != 30:
        raise ValueError("目前只支持30分钟聚合")
    if not isinstance(data, dict) or data.get("query_type") != "minute_range":
        raise ValueError("输入必须是历史分钟minute_range数据")
    if data.get("interval") not in (None, "1min"):
        raise ValueError("输入必须是1分钟原始数据")
    columns = data.get("columns")
    rows = data.get("rows")
    if not isinstance(columns, list) or columns[:2] != ["trade_date", "timestamp"]:
        raise ValueError("输入缺少trade_date,timestamp列")
    if not isinstance(rows, list):
        raise ValueError("输入rows必须是数组")
    if not rows:
        result = copy.deepcopy(data)
        result.update({"interval": "30min", "source_interval": "1min", "derived": True,
                       "aggregation": "ohlcva_time_bucket", "source_mode": "derived",
                       "rows": [], "shape": [0, len(columns)], "empty": True})
        result.pop("csv_url", None)
        return result

    timezone_name = str(data.get("timezone") or "Asia/Shanghai")
    try:
        timezone = _resolve_timezone(timezone_name)
    except Exception as exc:
        raise ValueError("分钟数据timezone无效") from exc
    indexes = {name: index for index, name in enumerate(columns)}
    if not any(name in indexes for name in _OHLC + _SUM + _LAST):
        raise ValueError("输入缺少可聚合的OHLCVA列")

    groups = {}
    for row in rows:
        if not isinstance(row, list) or len(row) != len(columns):
            raise ValueError("分钟行与columns列数不一致")
        trade_date = row[0]
        timestamp = row[1]
        if not isinstance(trade_date, int) or not _number(timestamp):
            raise ValueError("分钟行trade_date/timestamp无效")
        bucket = _bucket_timestamp(timestamp, timezone, interval_minutes)
        groups.setdefault((trade_date, bucket), []).append(row)

    output_rows = []
    for (trade_date, bucket), grouped_rows in sorted(groups.items(), key=lambda item: item[0][1]):
        output = []
        for index, name in enumerate(columns):
            if name == "trade_date":
                output.append(trade_date)
            elif name == "timestamp":
                output.append(bucket)
            else:
                output.append(_aggregate_column(name, [row[index] for row in grouped_rows]))
        output_rows.append(output)

    result = copy.deepcopy(data)
    result.update({"interval": "30min", "source_interval": "1min", "derived": True,
                   "aggregation": "ohlcva_time_bucket", "source_mode": "derived",
                   "rows": output_rows, "shape": [len(output_rows), len(columns)],
                   "empty": not output_rows})
    result.pop("csv_url", None)
    return result


def _load_data(path):
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if raw.get("schema") == "qb_minute_range_artifact_v1":
        return raw.get("data")
    return raw.get("data") if isinstance(raw.get("data"), dict) else raw


def main(argv=None):
    parser = argparse.ArgumentParser(description="将物化的1分钟历史数据聚合为30分钟")
    parser.add_argument("artifact", help="fetch_minute_range_csv.py生成的JSON，可用@file")
    parser.add_argument("--output", required=True, help="输出文件，必须位于本skill/output内")
    args = parser.parse_args(argv)
    try:
        root = (Path(__file__).resolve().parents[1] / "output").resolve()
        source = Path(args.artifact.lstrip("@")).resolve()
        target = Path(args.output).resolve()
        source.relative_to(root)
        target.relative_to(root)
        data = resample_minute_data(_load_data(source))
        content = json.dumps({"schema": "qb_minute_range_artifact_v1", "data": data},
                             ensure_ascii=False, allow_nan=False).encode("utf-8")
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
            temporary = handle.name
            handle.write(content)
        try:
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        print(json.dumps({"code": 0, "artifact_file": str(target), "interval": "30min",
                          "shape": data["shape"], "source_interval": "1min"}, ensure_ascii=False))
        return 0
    except Exception:
        print(json.dumps({"code": 1, "error": "MINUTE_RESAMPLE_FAILED",
                          "message": "1分钟历史数据聚合30分钟失败；检查物化文件、时区和输出路径。"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
