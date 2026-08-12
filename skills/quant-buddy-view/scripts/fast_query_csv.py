#!/usr/bin/env python3
"""Strict FastQuery CSV hydration shared by build-time verification tools."""

from __future__ import annotations

import copy
import csv
import datetime as dt
import io
import math
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed


RETRYABLE_HTTP_STATUSES = {401, 403, 404}
MISSING_TOKENS = {"", "null", "none", "nan", "infinity", "+infinity", "-infinity", "inf", "+inf", "-inf"}


class CsvHydrationError(ValueError):
    def __init__(self, message, *, status=None, retryable=False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


def _normalise_date(value):
    raw = str(value or "").strip()
    try:
        if len(raw) == 8 and raw.isdigit():
            parsed = dt.datetime.strptime(raw, "%Y%m%d").date()
        elif len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
            parsed = dt.datetime.strptime(raw, "%Y-%m-%d").date()
        else:
            raise ValueError
    except ValueError as exc:
        raise CsvHydrationError(f"CSV 日期列无效: {raw or '<empty>'}") from exc
    return parsed.isoformat()


def _number(value, *, intent, row_number, date):
    raw = "" if value is None else str(value).strip()
    if raw.lower() in MISSING_TOKENS:
        return None
    try:
        parsed = float(raw)
    except ValueError as exc:
        raise CsvHydrationError(f"CSV 数值无效（字段={intent}, 行={row_number}, 日期={date}）") from exc
    if not math.isfinite(parsed):
        return None
    return parsed


def parse_wide_csv(text, *, intent="未知字段"):
    if not isinstance(text, str):
        raise CsvHydrationError(f"CSV 内容类型无效（字段={intent}）")
    reader = csv.reader(io.StringIO(text.lstrip("\ufeff"), newline=""))
    header = next(reader, None)
    if not header or len(header) < 3:
        raise CsvHydrationError(f"CSV 表头异常（字段={intent}）：期望 ticker,name,<日期...>")
    if header[0].strip().lower() != "ticker" or header[1].strip().lower() != "name":
        raise CsvHydrationError(f"CSV 表头异常（字段={intent}）：前两列必须是 ticker,name")
    dates = [_normalise_date(item) for item in header[2:]]
    if len(dates) != len(set(dates)):
        raise CsvHydrationError(f"CSV 日期列重复（字段={intent}）")

    rows = []
    seen = set()
    for row_number, row in enumerate(reader, start=2):
        if not row or not any(str(item).strip() for item in row):
            continue
        if len(row) != len(header):
            raise CsvHydrationError(f"CSV 列数不一致（字段={intent}, 行={row_number}）")
        ticker = row[0].strip()
        name = row[1].strip()
        if not ticker:
            raise CsvHydrationError(f"CSV ticker 为空（字段={intent}, 行={row_number}）")
        if ticker in seen:
            raise CsvHydrationError(f"CSV ticker 重复（字段={intent}, ticker={ticker}）")
        seen.add(ticker)
        values = [_number(value, intent=intent, row_number=row_number, date=dates[index])
                  for index, value in enumerate(row[2:])]
        if not any(value is not None for value in values):
            raise CsvHydrationError(f"CSV 字段无有效数据（字段={intent}, ticker={ticker}）")
        rows.append({"ticker": ticker, "name": name or ticker, "values": values})
    if not rows:
        raise CsvHydrationError(f"CSV 无资产数据（字段={intent}）")
    return {"dates": dates, "rows": rows}


def _field_unit(field, ticker):
    if field.get("unit_per_asset"):
        unit = (field.get("units") or {}).get(ticker)
        if unit is None:
            raise CsvHydrationError(f"CSV 缺少资产单位（字段={field.get('intent')}, ticker={ticker}）")
        return unit
    return field.get("unit")


def hydrate_fast_query_data(data, csv_texts):
    if not isinstance(data, dict) or str(data.get("mode") or "").lower() != "csv":
        return data
    fields = data.get("csv_fields") or []
    if not fields or len(fields) != len(csv_texts):
        raise CsvHydrationError("CSV 字段清单为空或文件数量不一致")

    assets = {}
    asset_order = []
    for field, text in zip(fields, csv_texts):
        intent = str(field.get("intent") or "").strip()
        if not intent:
            raise CsvHydrationError("CSV 字段缺少 intent")
        parsed = parse_wide_csv(text, intent=intent)
        rows_by_ticker = {row["ticker"]: row for row in parsed["rows"]}
        declared = [str(item) for item in (field.get("tickers") or []) if str(item)]
        missing = [ticker for ticker in declared if ticker not in rows_by_ticker]
        if missing:
            raise CsvHydrationError(f"CSV 缺少声明 ticker（字段={intent}, ticker={missing[0]}）")

        for row in parsed["rows"]:
            ticker = row["ticker"]
            if ticker not in assets:
                assets[ticker] = {
                    "asset_intent": row["name"],
                    "asset_name": row["name"],
                    "ticker": ticker,
                    "fields": [],
                }
                asset_order.append(ticker)
            elif assets[ticker]["asset_name"] != row["name"]:
                raise CsvHydrationError(f"CSV 资产名称不一致（ticker={ticker}）")
            series = [{"date": date, "value": value}
                      for date, value in zip(parsed["dates"], row["values"])]
            hydrated_field = {
                "intent": intent,
                "index_title": field.get("index_title"),
                "unit": _field_unit(field, ticker),
                "date_type": field.get("date_type"),
                "series": series,
            }
            if str(data.get("query_type") or "").lower() != "window":
                for point in reversed(series):
                    if point["value"] is not None:
                        hydrated_field.update({"date": point["date"], "value": point["value"]})
                        break
            assets[ticker]["fields"].append(hydrated_field)

    hydrated = copy.deepcopy(data)
    hydrated["source_mode"] = "csv"
    hydrated["results"] = [assets[ticker] for ticker in asset_order]
    return hydrated


def _download_field(field, timeout):
    intent = str(field.get("intent") or "未知字段")
    url = field.get("csv_url")
    if not url:
        raise CsvHydrationError(f"CSV 下载地址缺失（字段={intent}）")
    request = urllib.request.Request(url, headers={"Accept": "text/csv", "User-Agent": "quant-buddy-view/csv-runtime"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        raise CsvHydrationError(
            f"CSV 下载失败（字段={intent}, HTTP {status}）",
            status=status,
            retryable=status in RETRYABLE_HTTP_STATUSES,
        ) from exc
    except Exception as exc:
        raise CsvHydrationError(f"CSV 下载失败（字段={intent}, 网络或超时）") from exc
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvHydrationError(f"CSV UTF-8 解码失败（字段={intent}）") from exc


def download_and_hydrate(data, *, timeout=20, max_workers=4):
    fields = (data or {}).get("csv_fields") or []
    if not fields:
        raise CsvHydrationError("CSV 字段清单为空")
    texts = [None] * len(fields)
    with ThreadPoolExecutor(max_workers=min(max_workers, len(fields))) as pool:
        futures = {pool.submit(_download_field, field, timeout): index for index, field in enumerate(fields)}
        for future in as_completed(futures):
            texts[futures[future]] = future.result()
    return hydrate_fast_query_data(data, texts)


def hydrate_query_result(query_once, *, timeout=20, max_workers=4):
    """Run queryDataGrant and retry the whole query once for expired/missing CSV URLs."""
    result = query_once()
    for attempt in range(2):
        if not isinstance(result, dict) or result.get("code") != 0:
            return result
        data = result.get("data")
        if not isinstance(data, dict) or str(data.get("mode") or "").lower() != "csv":
            return result
        try:
            hydrated = download_and_hydrate(data, timeout=timeout, max_workers=max_workers)
        except CsvHydrationError as exc:
            if attempt == 0 and exc.retryable:
                result = query_once()
                continue
            raise
        output = dict(result)
        output["data"] = hydrated
        return output
    return result
