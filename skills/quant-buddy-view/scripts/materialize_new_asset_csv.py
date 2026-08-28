#!/usr/bin/env python3
"""Safely materialize newAssetPage CSV URLs into task-scoped evidence.

The signed URLs are input-only capability credentials.  They are never copied to
the manifest, evidence, warnings, stdout, or exception messages emitted here.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import common as C


MANIFEST_VERSION = "new_asset_csv_manifest_v1"
EVIDENCE_VERSION = "new_asset_csv_evidence_v1"

DEFAULT_ALLOWED_HOSTS = {
    "quant-buddy-prod.oss-cn-hangzhou.aliyuncs.com",
}
DEFAULT_LIMITS = {
    "single_file_bytes": 10 * 1024 * 1024,
    "task_bytes": 40 * 1024 * 1024,
    "rows": 1000,
    "columns": 5000,
    "cells": 2_000_000,
    "timeout_seconds": 30,
    "redirects": 3,
}

_INTENTS = {
    "收盘价": ("close_price", "close_price.csv"),
    "成交额": ("turnover_amount", "turnover_amount.csv"),
    "PE_TTM": ("pe_ttm", "pe_ttm.csv"),
    "PB": ("pb", "pb.csv"),
}
_NULL_VALUES = {"", "--", "—", "null", "none", "nan", "n/a", "na"}


class MaterializeError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _utc_now():
    return datetime.now(timezone.utc)


def _iso(value):
    if not isinstance(value, datetime):
        return None
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_datetime(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            parsed = datetime.fromisoformat(text[:-1] + "+00:00")
        else:
            parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _signed_url_expiry(url):
    """Derive expiry without retaining or returning any query-string material."""
    try:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        stamp = (query.get("X-Amz-Date") or query.get("x-amz-date") or [""])[0]
        seconds = (query.get("X-Amz-Expires") or query.get("x-amz-expires") or [""])[0]
        if not stamp or not seconds:
            return None
        start = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return start + timedelta(seconds=int(seconds))
    except (TypeError, ValueError, OverflowError):
        return None


def _effective_expiry(field):
    candidates = [
        _parse_datetime(field.get("csv_expires_at")),
        _parse_datetime(field.get("csv_url_expires_at")),
        _signed_url_expiry(field.get("csv_url") or ""),
    ]
    candidates = [item for item in candidates if item is not None]
    return min(candidates) if candidates else None


def _allowed_hosts(explicit=None):
    hosts = set(DEFAULT_ALLOWED_HOSTS)
    extra = os.environ.get("QBV_NEW_ASSET_CSV_ALLOWED_HOSTS", "")
    hosts.update(item.strip().lower().rstrip(".") for item in extra.split(",") if item.strip())
    if explicit is not None:
        hosts = {str(item).strip().lower().rstrip(".") for item in explicit if str(item).strip()}
    return hosts


def _validate_url(url, allowed_hosts):
    try:
        parsed = urllib.parse.urlsplit(str(url or ""))
    except ValueError as exc:
        raise MaterializeError("CSV_URL_INVALID", "CSV 下载地址格式无效") from exc
    if parsed.scheme.lower() != "https":
        raise MaterializeError("CSV_URL_HTTPS_REQUIRED", "CSV 下载只允许 HTTPS")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or host not in allowed_hosts:
        raise MaterializeError("CSV_URL_HOST_NOT_ALLOWED", "CSV 下载地址不在允许的主机白名单")
    if parsed.username or parsed.password:
        raise MaterializeError("CSV_URL_USERINFO_FORBIDDEN", "CSV 下载地址禁止携带 userinfo")
    return parsed


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_hosts, max_redirects):
        self.allowed_hosts = allowed_hosts
        self.max_redirects = max_redirects
        super().__init__()

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_url(newurl, self.allowed_hosts)
        count = int(getattr(req, "_qbv_redirect_count", 0)) + 1
        if count > self.max_redirects:
            raise MaterializeError("CSV_REDIRECT_LIMIT", "CSV 下载重定向次数超限")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected._qbv_redirect_count = count
        return redirected


def _open_https(url, *, allowed_hosts, timeout_seconds, max_redirects):
    _validate_url(url, allowed_hosts)
    opener = urllib.request.build_opener(_SafeRedirectHandler(allowed_hosts, max_redirects))
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"quant-buddy-view/{C.SKILL_VERSION} new-asset-csv"},
        method="GET",
    )
    response = opener.open(request, timeout=timeout_seconds)
    final_url = response.geturl() if hasattr(response, "geturl") else url
    _validate_url(final_url, allowed_hosts)
    return response


def _atomic_write(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    with open(temporary, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def persist_data_sources(task_id, data_sources):
    if not isinstance(data_sources, dict):
        raise MaterializeError("DATA_SOURCES_INVALID", "newAssetPage data_sources 必须是对象")
    path = Path(C.task_temp_path(task_id, "new-asset-page-data-sources.json", create_parent=True))
    payload = json.dumps(data_sources, ensure_ascii=False, indent=2).encode("utf-8")
    _atomic_write(path, payload)
    return {
        "data_sources_file": str(path),
        "data_sources_sha256": hashlib.sha256(payload).hexdigest(),
    }


def _contained_data_sources_path(task_id, path):
    root = C.task_temp_dir(task_id, create=False).resolve()
    candidate = Path(path).resolve()
    if candidate != root and root not in candidate.parents:
        raise MaterializeError("DATA_SOURCES_PATH_OUTSIDE_TASK", "data_sources_file 必须位于当前 task 临时目录")
    return candidate


def _download_bytes(url, *, allowed_hosts, limits, remaining_bytes):
    maximum = min(int(limits["single_file_bytes"]), int(remaining_bytes))
    if maximum <= 0:
        raise MaterializeError("CSV_TASK_SIZE_LIMIT", "CSV 单任务下载总量超限")
    response = None
    try:
        response = _open_https(
            url,
            allowed_hosts=allowed_hosts,
            timeout_seconds=int(limits["timeout_seconds"]),
            max_redirects=int(limits["redirects"]),
        )
        length = None
        if getattr(response, "headers", None) is not None:
            try:
                length = int(response.headers.get("Content-Length") or 0) or None
            except (TypeError, ValueError):
                length = None
        if length is not None and length > maximum:
            code = "CSV_FILE_SIZE_LIMIT" if length > limits["single_file_bytes"] else "CSV_TASK_SIZE_LIMIT"
            raise MaterializeError(code, "CSV 下载大小超限")
        chunks = []
        total = 0
        while True:
            chunk = response.read(min(65536, maximum - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                code = "CSV_FILE_SIZE_LIMIT" if total > limits["single_file_bytes"] else "CSV_TASK_SIZE_LIMIT"
                raise MaterializeError(code, "CSV 下载大小超限")
            chunks.append(chunk)
        if total == 0:
            raise MaterializeError("CSV_EMPTY_FILE", "CSV 下载结果为空文件")
        return b"".join(chunks)
    except MaterializeError:
        raise
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise MaterializeError("CSV_URL_EXPIRED_OR_FORBIDDEN", "CSV 下载地址已过期或无权访问") from exc
        raise MaterializeError("CSV_DOWNLOAD_HTTP_ERROR", "CSV 下载返回 HTTP 错误") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise MaterializeError("CSV_DOWNLOAD_FAILED", "CSV 下载失败") from exc
    except Exception as exc:
        raise MaterializeError("CSV_DOWNLOAD_FAILED", "CSV 下载失败") from exc
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass


def _parse_date(value):
    text = str(value or "").strip()
    for pattern in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue
    raise MaterializeError("CSV_DATE_INVALID", "CSV 包含无法识别的日期列")


def _number(value):
    text = str(value or "").strip()
    if text.lower() in _NULL_VALUES:
        return None
    try:
        number = float(text.replace(",", ""))
    except ValueError as exc:
        raise MaterializeError("CSV_NUMBER_INVALID", "CSV 包含无法解析的数值") from exc
    if not math.isfinite(number):
        raise MaterializeError("CSV_NUMBER_INVALID", "CSV 包含非有限数值")
    return number


def _normalize_ticker(value):
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def _parse_wide_csv(payload, *, target_ticker, limits):
    try:
        text = payload.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise MaterializeError("CSV_ENCODING_INVALID", "CSV 必须使用 UTF-8 编码") from exc
    if "\x00" in text:
        raise MaterializeError("CSV_NUL_FORBIDDEN", "CSV 包含 NUL 字符")
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as exc:
        raise MaterializeError("CSV_MALFORMED", "CSV 结构无法解析") from exc
    rows = [row for row in rows if any(str(cell).strip() for cell in row)]
    if len(rows) < 2:
        raise MaterializeError("CSV_EMPTY_DATA", "CSV 不含数据行")
    header = [str(cell).strip() for cell in rows[0]]
    column_count = len(header)
    data_rows = rows[1:]
    if column_count < 3 or header[0].lower() != "ticker" or header[1].lower() != "name":
        raise MaterializeError("CSV_HEADER_INVALID", "CSV 表头必须以 ticker,name 开始")
    if column_count > int(limits["columns"]):
        raise MaterializeError("CSV_COLUMN_LIMIT", "CSV 列数超限")
    if len(data_rows) > int(limits["rows"]):
        raise MaterializeError("CSV_ROW_LIMIT", "CSV 行数超限")
    if len(data_rows) * column_count > int(limits["cells"]):
        raise MaterializeError("CSV_CELL_LIMIT", "CSV 单元格数量超限")
    if len(set(header)) != len(header):
        raise MaterializeError("CSV_DUPLICATE_HEADER", "CSV 存在重复表头")
    dates = [_parse_date(item) for item in header[2:]]
    if len(set(dates)) != len(dates):
        raise MaterializeError("CSV_DUPLICATE_DATE", "CSV 存在重复日期列")
    for row in data_rows:
        if len(row) != column_count:
            raise MaterializeError("CSV_ROW_WIDTH_INVALID", "CSV 数据行列数与表头不一致")

    normalized_target = _normalize_ticker(target_ticker)
    selected = None
    if normalized_target:
        selected = next((row for row in data_rows if _normalize_ticker(row[0]) == normalized_target), None)
    if selected is None and len(data_rows) == 1:
        selected = data_rows[0]
    if selected is None:
        raise MaterializeError("CSV_TARGET_TICKER_MISSING", "CSV 未找到目标 ticker 数据行")
    points = []
    for date_value, raw_value in zip(dates, selected[2:]):
        value = _number(raw_value)
        if value is not None:
            points.append({"date": date_value, "value": value})
    points.sort(key=lambda item: item["date"])
    if not points:
        raise MaterializeError("CSV_EMPTY_DATA", "CSV 目标 ticker 没有有效数值")
    return {
        "ticker": str(selected[0]).strip(),
        "name": str(selected[1]).strip(),
        "points": points,
        "row_count": len(data_rows),
        "column_count": column_count,
        "cell_count": len(data_rows) * column_count,
        "date_range": {"start": points[0]["date"], "end": points[-1]["date"]},
    }


def _round(number, digits=6):
    return round(float(number), digits)


def _return(points, window):
    if len(points) <= window or points[-window - 1]["value"] == 0:
        return None
    return _round((points[-1]["value"] / points[-window - 1]["value"] - 1) * 100)


def _mean(points, window):
    if len(points) < window:
        return None
    return _round(statistics.fmean(item["value"] for item in points[-window:]))


def _volatility(points, window):
    if len(points) <= window:
        return None
    values = [item["value"] for item in points[-window - 1:]]
    returns = [values[index] / values[index - 1] - 1 for index in range(1, len(values)) if values[index - 1] != 0]
    if len(returns) < 2:
        return None
    return _round(statistics.stdev(returns) * math.sqrt(252) * 100)


def _max_drawdown(points, window=250):
    sample = points[-min(len(points), window + 1):]
    if not sample:
        return None
    peak = sample[0]["value"]
    worst = 0.0
    for item in sample:
        peak = max(peak, item["value"])
        if peak != 0:
            worst = min(worst, item["value"] / peak - 1)
    return _round(worst * 100)


def _price_position(points, window=250):
    sample = points[-min(len(points), window):]
    if not sample:
        return None
    values = [item["value"] for item in sample]
    low = min(values)
    high = max(values)
    if high == low:
        return None
    return _round((sample[-1]["value"] - low) / (high - low) * 100)


def _uniform_sample(points, maximum=40):
    if len(points) <= maximum:
        return list(points)
    indices = [round(index * (len(points) - 1) / (maximum - 1)) for index in range(maximum)]
    return [points[index] for index in dict.fromkeys(indices)]


def _point_samples(points):
    recent = list(points[-20:])
    historical = points[:-20] if len(points) > 20 else []
    return recent, _uniform_sample(historical, 40)


def _percentile(points, years, latest_date, latest_value):
    end = datetime.strptime(latest_date, "%Y-%m-%d").date()
    start = end - timedelta(days=365 * years)
    selected = [item for item in points if datetime.strptime(item["date"], "%Y-%m-%d").date() >= start]
    if not selected:
        return None
    values = [item["value"] for item in selected]
    return {
        "value": _round(sum(1 for value in values if value <= latest_value) / len(values) * 100),
        "sample_count": len(values),
        "coverage_start": selected[0]["date"],
    }


def _metric_evidence(metric_id, intent, unit, parsed, sha256):
    points = parsed["points"]
    recent, sampled = _point_samples(points)
    values = [item["value"] for item in points]
    statistics_block = {
        "latest": {"date": points[-1]["date"], "value": points[-1]["value"]},
    }
    if metric_id == "close_price":
        statistics_block["returns"] = {str(window): _return(points, window) for window in (1, 20, 60, 120, 250)}
        statistics_block["means"] = {str(window): _mean(points, window) for window in (5, 20, 60, 120)}
        window = points[-min(250, len(points)):]
        high = max(window, key=lambda item: item["value"])
        low = min(window, key=lambda item: item["value"])
        statistics_block.update({
            "high_250": dict(high),
            "low_250": dict(low),
            "price_position_250": _price_position(points),
            "max_drawdown_250": _max_drawdown(points),
            "annualized_volatility_20": _volatility(points, 20),
            "annualized_volatility_60": _volatility(points, 60),
        })
    elif metric_id == "turnover_amount":
        means = {str(window): _mean(points, window) for window in (5, 20, 60)}
        latest = points[-1]["value"]
        window = points[-min(250, len(points)):]
        maximum = max(window, key=lambda item: item["value"])
        statistics_block.update({
            "means": means,
            "latest_to_mean_20": _round(latest / means["20"]) if means.get("20") not in (None, 0) else None,
            "latest_to_mean_60": _round(latest / means["60"]) if means.get("60") not in (None, 0) else None,
            "window_max": dict(maximum),
        })
    else:
        distribution_points = points
        negative_count = 0
        latest_is_negative = False
        if metric_id == "pe_ttm":
            negative_count = sum(1 for item in points if item["value"] < 0)
            latest_is_negative = points[-1]["value"] < 0
            distribution_points = [item for item in points if item["value"] > 0]
        distribution_values = [item["value"] for item in distribution_points]
        statistics_block.update({
            "latest_is_negative": latest_is_negative,
            "negative_sample_count": negative_count,
            "distribution_basis": "positive_values_only" if metric_id == "pe_ttm" else "all_finite_values",
            "median": _round(statistics.median(distribution_values)) if distribution_values else None,
            "maximum": _round(max(distribution_values)) if distribution_values else None,
            "minimum": _round(min(distribution_values)) if distribution_values else None,
        })
        if latest_is_negative:
            statistics_block["percentiles"] = None
            statistics_block["percentile_status"] = "not_applicable_negative_pe"
        else:
            statistics_block["percentiles"] = {
                str(year): _percentile(distribution_points, year, points[-1]["date"], points[-1]["value"])
                for year in (1, 3, 5)
            }
    return {
        "metric_id": metric_id,
        "intent": _safe_text(intent, 80),
        "ticker": _safe_text(parsed["ticker"], 40),
        "name": _safe_text(parsed["name"], 120),
        "unit": _safe_text(unit, 40),
        "source_file_sha256": sha256,
        "valid_sample_count": len(points),
        "date_range": parsed["date_range"],
        "statistics": statistics_block,
        "recent_points": recent,
        "sampled_points": sampled,
    }


def _tokens(value):
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        number = float(value)
        values = [str(value), f"{number:.6f}".rstrip("0").rstrip(".")]
        if number.is_integer():
            values.append(str(int(number)))
        return list(dict.fromkeys(values))
    return [str(value)]


def _safe_text(value, maximum=120):
    text = str(value or "").strip()
    text = re.sub(r"https?://\S+", "[redacted]", text, flags=re.IGNORECASE)
    text = re.sub(r"(?i)X-Amz-[A-Za-z-]+=[^\s,&]+", "[redacted]", text)
    return text[:maximum]


def _reply_field(metric, field_id, section, row_label, value, column_label=None, date=None, unit=None):
    if value is None:
        return None
    return {
        "field_id": field_id,
        "section": section,
        "row_label": row_label,
        "column_label": column_label,
        "value": value,
        "date": date,
        "unit": unit,
        "render_tokens": _tokens(value),
        "source": {
            "kind": "new_asset_csv",
            "intent": metric.get("intent"),
            "source_file_sha256": metric.get("source_file_sha256"),
        },
    }


def reply_fields_from_evidence(evidence):
    fields = []
    for metric in (evidence or {}).get("metrics") or []:
        metric_id = metric.get("metric_id")
        stats = metric.get("statistics") or {}
        latest = stats.get("latest") or {}
        unit = metric.get("unit")
        if metric_id == "close_price":
            returns = stats.get("returns") or {}
            means = stats.get("means") or {}
            specs = [
                ("market.close_price", "一、行情与估值", "最新价", latest.get("value"), None, latest.get("date"), unit),
                *[(f"market.ret_{window}", "一、行情与估值", f"近{window}日", returns.get(str(window)), None, latest.get("date"), "%") for window in (20, 60, 120, 250)],
                ("market.high_250", "一、行情与估值", "250日最高", (stats.get("high_250") or {}).get("value"), None, (stats.get("high_250") or {}).get("date"), unit),
                ("market.low_250", "一、行情与估值", "250日最低", (stats.get("low_250") or {}).get("value"), None, (stats.get("low_250") or {}).get("date"), unit),
                ("calculation.daily_change", "四、计算维度", "单日涨跌幅", returns.get("1"), "最新值", latest.get("date"), "%"),
                *[(f"calculation.ma{window}", "四、计算维度", f"{window}日均线", means.get(str(window)), "最新值", latest.get("date"), unit) for window in (5, 20, 60, 120)],
                ("calculation.price_position_250", "四、计算维度", "250日价格位置", stats.get("price_position_250"), "最新值", latest.get("date"), "%"),
                ("risk.max_drawdown_250", "五、波动率与风险", "250日最大回撤", stats.get("max_drawdown_250"), "最新值", latest.get("date"), "%"),
                ("risk.volatility_20", "五、波动率与风险", "20日年化波动率", stats.get("annualized_volatility_20"), "最新值", latest.get("date"), "%"),
                ("risk.volatility_60", "五、波动率与风险", "60日年化波动率", stats.get("annualized_volatility_60"), "最新值", latest.get("date"), "%"),
            ]
        elif metric_id == "turnover_amount":
            means = stats.get("means") or {}
            maximum = stats.get("window_max") or {}
            specs = [
                ("trading.turnover_amount.latest", "三、资金 / 交易特征", "最新成交额", latest.get("value"), "最新值", latest.get("date"), unit),
                *[(f"trading.turnover_amount.mean_{window}", "三、资金 / 交易特征", f"{window}日平均成交额", means.get(str(window)), "最新值", latest.get("date"), unit) for window in (5, 20, 60)],
                ("trading.turnover_amount.latest_to_mean_20", "三、资金 / 交易特征", "最新/20日均额", stats.get("latest_to_mean_20"), "倍数", latest.get("date"), "x"),
                ("trading.turnover_amount.latest_to_mean_60", "三、资金 / 交易特征", "最新/60日均额", stats.get("latest_to_mean_60"), "倍数", latest.get("date"), "x"),
                ("trading.turnover_amount.window_max", "三、资金 / 交易特征", "窗口最大成交额", maximum.get("value"), "最新值", maximum.get("date"), unit),
            ]
        else:
            prefix = "valuation.pe_ttm" if metric_id == "pe_ttm" else "valuation.pb"
            label = "PE(TTM)" if metric_id == "pe_ttm" else "PB"
            specs = [
                (f"{prefix}.latest", "一、行情与估值", label, latest.get("value"), "最新值", latest.get("date"), unit),
                (f"{prefix}.median", "一、行情与估值", label, stats.get("median"), "可得历史中位数", latest.get("date"), unit),
                (f"{prefix}.maximum", "一、行情与估值", label, stats.get("maximum"), "可得历史最高", latest.get("date"), unit),
                (f"{prefix}.minimum", "一、行情与估值", label, stats.get("minimum"), "可得历史最低", latest.get("date"), unit),
            ]
            if stats.get("latest_is_negative"):
                specs.append((f"{prefix}.negative_status", "一、行情与估值", f"{label}状态", "负值（历史分位不适用）", None, latest.get("date"), None))
            else:
                for year in (1, 3, 5):
                    pct = ((stats.get("percentiles") or {}).get(str(year)) or {}).get("value")
                    specs.append((f"{prefix}.pctrank{year}y", "一、行情与估值", label, pct, f"{year}Y可得分位", latest.get("date"), "%"))
        for spec in specs:
            field = _reply_field(metric, *spec)
            if field is not None:
                fields.append(field)
    return fields


def _warning(code, intent, message):
    return {"code": _safe_text(code, 80), "intent": _safe_text(intent, 80), "message": _safe_text(message, 300)}


def sanitize_warnings(items):
    """Keep warning semantics while removing URLs and capability query fragments."""
    safe = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        warning = {
            key: item.get(key)
            for key in ("code", "type", "intent", "status")
            if item.get(key) not in (None, "")
        }
        message = str(item.get("message") or "").strip()
        message = re.sub(r"https?://\S+", "[signed URL redacted]", message, flags=re.IGNORECASE)
        message = re.sub(r"(?i)X-Amz-[A-Za-z-]+=[^\s,&]+", "[signed query redacted]", message)
        if message:
            warning["message"] = message
        safe.append(warning)
    return safe


def persist_failure_artifacts(task_id, warnings, *, now=None):
    """Keep the output contract complete when CSV materialization fails globally."""
    now = now or _utc_now()
    safe_warnings = sanitize_warnings(warnings)
    csv_root = Path(C.task_temp_path(task_id, "new-asset-csv", create_parent=True))
    csv_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": MANIFEST_VERSION,
        "task_id": str(task_id),
        "created_at": _iso(now),
        "limits": dict(DEFAULT_LIMITS),
        "downloaded_bytes": 0,
        "files": [],
        "warnings": safe_warnings,
    }
    evidence = {
        "version": EVIDENCE_VERSION,
        "task_id": str(task_id),
        "created_at": _iso(now),
        "metrics": [],
        "warnings": safe_warnings,
    }
    manifest_path = csv_root / "manifest.json"
    evidence_path = Path(C.task_temp_path(task_id, "new-asset-csv-evidence.json", create_parent=True))
    _atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
    _atomic_write(evidence_path, json.dumps(evidence, ensure_ascii=False, indent=2).encode("utf-8"))
    return {
        "csv_manifest_file": str(manifest_path),
        "csv_evidence_file": str(evidence_path),
        "csv_success_count": 0,
        "csv_failure_count": 0,
        "warnings": safe_warnings,
        "evidence": evidence,
        "reply_fields": [],
    }


def materialize(task_id, data_sources_file, *, allowed_hosts=None, limits=None, now=None):
    task_id = str(task_id or "").strip()
    if not task_id or not data_sources_file:
        raise MaterializeError("MATERIALIZE_PARAMS_REQUIRED", "materialize 需要 task_id 和 data_sources_file")
    limits = {**DEFAULT_LIMITS, **(limits or {})}
    allowed_hosts = _allowed_hosts(allowed_hosts)
    now = now or _utc_now()
    source_path = _contained_data_sources_path(task_id, data_sources_file)
    try:
        data_sources = json.loads(source_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MaterializeError("DATA_SOURCES_UNREADABLE", "data_sources_file 无法读取") from exc
    market_series = data_sources.get("market_series") if isinstance(data_sources, dict) else None
    csv_fields = market_series.get("csv_fields") if isinstance(market_series, dict) else None
    if not isinstance(csv_fields, list):
        csv_fields = []
    profile = data_sources.get("profile") if isinstance(data_sources, dict) else {}
    asset = profile.get("asset") if isinstance(profile, dict) else {}
    target_ticker = asset.get("ticker") if isinstance(asset, dict) else ""

    csv_root = Path(C.task_temp_path(task_id, "new-asset-csv", create_parent=True))
    csv_root.mkdir(parents=True, exist_ok=True)
    warnings = []
    files = []
    metrics = []
    downloaded_bytes = 0
    seen = set()

    for field in csv_fields:
        if not isinstance(field, dict):
            warnings.append(_warning("CSV_FIELD_INVALID", "", "CSV 字段描述不是对象"))
            continue
        intent = str(field.get("intent") or "").strip()
        mapping = _INTENTS.get(intent)
        if not mapping:
            warnings.append(_warning("CSV_INTENT_UNSUPPORTED", intent, "CSV 指标不在允许列表"))
            continue
        metric_id, filename = mapping
        if metric_id in seen:
            warnings.append(_warning("CSV_INTENT_DUPLICATE", intent, "同一 CSV 指标重复出现，已忽略后续项"))
            continue
        seen.add(metric_id)
        manifest_item = {
            "intent": intent,
            "metric_id": metric_id,
            "status": "failed",
            "file_path": str(csv_root / filename),
            "downloaded_at": None,
            "url_expires_at": None,
        }
        expiry = _effective_expiry(field)
        manifest_item["url_expires_at"] = _iso(expiry)
        try:
            if expiry is not None and expiry <= now:
                raise MaterializeError("CSV_URL_EXPIRED", "CSV 下载地址已过期")
            declared_size = field.get("file_size")
            if isinstance(declared_size, (int, float)) and declared_size > limits["single_file_bytes"]:
                raise MaterializeError("CSV_FILE_SIZE_LIMIT", "CSV 声明大小超限")
            url = str(field.get("csv_url") or "")
            payload = _download_bytes(
                url,
                allowed_hosts=allowed_hosts,
                limits=limits,
                remaining_bytes=limits["task_bytes"] - downloaded_bytes,
            )
            parsed = _parse_wide_csv(payload, target_ticker=target_ticker, limits=limits)
            digest = hashlib.sha256(payload).hexdigest()
            path = csv_root / filename
            _atomic_write(path, payload)
            downloaded_bytes += len(payload)
            metric = _metric_evidence(metric_id, intent, field.get("unit"), parsed, digest)
            metrics.append(metric)
            manifest_item.update({
                "status": "success",
                "file_path": str(path),
                "sha256": digest,
                "size_bytes": len(payload),
                "row_count": parsed["row_count"],
                "column_count": parsed["column_count"],
                "cell_count": parsed["cell_count"],
                "date_range": parsed["date_range"],
                "ticker": _safe_text(parsed["ticker"], 40),
                "downloaded_at": _iso(now),
            })
        except MaterializeError as exc:
            warning = _warning(exc.code, intent, exc.message)
            warnings.append(warning)
            manifest_item["warning"] = warning
        except Exception:
            warning = _warning("CSV_PROCESSING_FAILED", intent, "CSV 下载或解析出现未预期错误")
            warnings.append(warning)
            manifest_item["warning"] = warning
        files.append(manifest_item)

    for intent, (metric_id, _filename) in _INTENTS.items():
        if metric_id not in seen:
            warnings.append(_warning("CSV_INTENT_MISSING", intent, "data_sources 未返回该 CSV 指标"))

    manifest = {
        "version": MANIFEST_VERSION,
        "task_id": str(task_id),
        "created_at": _iso(now),
        "limits": {key: int(value) for key, value in limits.items()},
        "downloaded_bytes": downloaded_bytes,
        "files": files,
        "warnings": warnings,
    }
    evidence = {
        "version": EVIDENCE_VERSION,
        "task_id": str(task_id),
        "created_at": _iso(now),
        "metrics": metrics,
        "warnings": warnings,
    }
    manifest_path = csv_root / "manifest.json"
    evidence_path = Path(C.task_temp_path(task_id, "new-asset-csv-evidence.json", create_parent=True))
    _atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
    _atomic_write(evidence_path, json.dumps(evidence, ensure_ascii=False, indent=2).encode("utf-8"))
    return {
        "csv_manifest_file": str(manifest_path),
        "csv_evidence_file": str(evidence_path),
        "csv_success_count": len(metrics),
        "csv_failure_count": len([item for item in files if item.get("status") != "success"]),
        "warnings": warnings,
        "evidence": evidence,
        "reply_fields": reply_fields_from_evidence(evidence),
    }


def main():
    params = C.read_params(sys.argv[1:], env_var="NEW_ASSET_CSV_PARAMS")
    try:
        result = materialize(
            str(params.get("task_id") or "").strip(),
            params.get("data_sources_file"),
        )
        safe = {key: value for key, value in result.items() if key not in {"evidence", "reply_fields"}}
        safe.update({"code": 0, "operation": "materialize_new_asset_csv"})
    except MaterializeError as exc:
        safe = {"code": 1, "error": exc.code, "message": exc.message}
    except Exception:
        safe = {"code": 1, "error": "CSV_MATERIALIZE_FAILED", "message": "CSV 材料化出现未预期错误"}
    C.emit(safe, out_name="materialize_new_asset_csv_out.txt")
    sys.exit(0 if safe.get("code") == 0 else 1)


if __name__ == "__main__":
    main()
