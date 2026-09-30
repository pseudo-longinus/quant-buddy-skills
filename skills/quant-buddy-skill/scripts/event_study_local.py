"""本地辅助工具：通用外部事实搜索（Bocha 兜底）+ 事件研究公式生成。

供 call.py 直接调用，不经过 executor.py（不是平台 HTTP API）。
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from pathlib import Path
from typing import Any

import requests


SKILL_ROOT = Path(__file__).resolve().parents[1]

# ── 配置 ──────────────────────────────────────────────────────

# 事件研究专用配置（窗口别名、默认值等），内嵌即可
_EVENT_DEFAULTS: dict[str, Any] = {
    "default_mode": "single",
    "default_windows": [5, 21],
    "window_aliases": {
        "1周": 5, "一周": 5, "5日": 5,
        "2周": 10, "两周": 10, "10日": 10,
        "1月": 21, "一个月": 21, "21日": 21,
        "3月": 63, "三个月": 63, "63日": 63,
        "半年": 126, "6月": 126, "126日": 126,
        "1年": 252, "一年": 252, "252日": 252,
    },
}


def _load_bocha_api_key() -> str:
    """读取博查 API key，优先级：环境变量 > config.local.json > config.json"""
    env_key = os.environ.get("BOCHA_API_KEY", "").strip()
    if env_key:
        return env_key

    for filename in ("config.local.json", "config.json"):
        path = SKILL_ROOT / filename
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    cfg = json.load(f)
                key = cfg.get("bocha_api_key", "").strip()
                if key:
                    return key
            except Exception:
                continue
    return ""


# ── 通用外部事实 Web 搜索（Bocha 兜底）──────────────────────

_BOCHA_BASE_URL = "https://api.bochaai.com/v1/web-search"
_BOCHA_TIMEOUT = 15
_BOCHA_COUNT = 8


def _freshness_param(months_back: int = 36) -> str:
    today = date.today()
    start = today - relativedelta(months=months_back)
    return f"{start.strftime('%Y-%m-%d')}..{today.strftime('%Y-%m-%d')}"


def bocha_web_search(query: str, freshness_months: int = 36, count: int | None = None) -> dict[str, Any]:
    """调用博查 web-search API，返回通用外部事实核验所需的结构化搜索结果。"""
    api_key = _load_bocha_api_key()
    if not api_key:
        return {"ok": False, "error": "BOCHA_API_KEY 未配置（环境变量 / config.local.json / config.json）", "results": []}

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "query": query,
        "freshness": _freshness_param(freshness_months),
        "summary": True,
        "count": count or _BOCHA_COUNT,
    }
    try:
        resp = requests.post(_BOCHA_BASE_URL, headers=headers, json=payload, timeout=_BOCHA_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return {"ok": False, "error": str(exc), "results": []}

    raw: list[dict[str, Any]] = []
    if "data" in data and "webPages" in data.get("data", {}) and "value" in data["data"]["webPages"]:
        raw = data["data"]["webPages"]["value"]
    elif "data" in data and isinstance(data["data"], list):
        raw = data["data"]

    items = []
    for item in raw:
        items.append({
            "title": item.get("name", ""),
            "url": item.get("url", item.get("link", "")),
            "snippet": item.get("summary", item.get("snippet", "")),
            "published": item.get("datePublished", "") or item.get("publishedTime", ""),
        })
    return {"ok": True, "query": query, "count": len(items), "results": items}


# ── 公式生成 ──────────────────────────────────────────────────

def parse_dates(values: list[Any]) -> list[int]:
    parsed: list[int] = []
    for value in values:
        if isinstance(value, int):
            parsed.append(value)
            continue
        text = str(value).strip().replace("-", "")
        if not text:
            continue
        parsed.append(int(text))
    return parsed


def parse_windows(values: list[Any] | None) -> list[int]:
    aliases = _EVENT_DEFAULTS["window_aliases"]
    raw_values = values or _EVENT_DEFAULTS["default_windows"]
    windows: list[int] = []
    for value in raw_values:
        if isinstance(value, int):
            windows.append(value)
            continue
        text = str(value).strip()
        if text.isdigit():
            windows.append(int(text))
            continue
        if text in aliases:
            windows.append(int(aliases[text]))
            continue
        raise ValueError(f"不支持的窗口写法: {value}")
    return windows


def int_to_date(value: int) -> datetime:
    return datetime.strptime(str(value), "%Y%m%d")


def overlap_warning(dates: list[int], windows: list[int]) -> list[str]:
    if len(dates) < 2 or not windows:
        return []
    sorted_dates = sorted(dates)
    min_gap = min((int_to_date(b) - int_to_date(a)).days for a, b in zip(sorted_dates, sorted_dates[1:]))
    max_window = max(windows)
    if min_gap < max_window:
        return [f"事件最小自然日间距为 {min_gap} 天，小于最大窗口 {max_window}，结果可能出现窗口重叠。"]
    return []


def build_event_study(params: dict[str, Any]) -> dict[str, Any]:
    """Compute independent endpoint returns from an unmodified daily price CSV.

    No return is inferred from a segmented formula's last non-null value.
    CSV provenance is carried, not authenticated: callers must retain the query
    response linking this asset/field/adjustment to the downloaded file.
    """
    import csv
    import hashlib
    import math
    import statistics

    mode = params.get("mode", "single")
    asset = str(params.get("asset") or "").strip()
    if not asset or mode not in ("single", "compare"):
        raise ValueError("需要 asset，mode 仅支持 single/compare")
    windows = parse_windows(params.get("windows"))
    if any(type(w) is not int or w <= 0 for w in windows) or len(set(windows)) != len(windows):
        raise ValueError("windows 必须是互不重复的正整数")
    groups = [("single", params.get("dates") or [])] if mode == "single" else [
        (str(params.get("group_a_name") or "A组"), params.get("group_a_dates") or []),
        (str(params.get("group_b_name") or "B组"), params.get("group_b_dates") or [])]
    if len({g for g, _ in groups}) != len(groups):
        raise ValueError("组名称必须唯一")
    groups = [(g, parse_dates(ds)) for g, ds in groups]
    for _, ds in groups:
        if not ds or len(set(ds)) != len(ds):
            raise ValueError("每组事件日期不能为空或重复")
        for d in ds:
            int_to_date(d)
    out = {"mode": mode, "asset": asset, "windows": windows, "formulas": [],
           "window_basis": "valid_daily_price_observations",
           "return_method": "end_close / anchor_close - 1",
           "warnings": ["窗口按有效日行情观察数计算，1月=21、1年=252仅为近似；不是自然月/自然年。缺失或停牌数据不能冒充交易所日历。事件可重叠，但独立计算，不代表独立统计样本。"]}
    price_file = params.get("price_file")
    if not price_file:
        out.update(status="price_series_required", next_action="获取本资产完整日收盘序列，以 readData(mode=csv) 返回的原始CSV保存到本地，再传 price_file 和 as_of 重调 buildEventStudy。保留取数响应、资产、复权口径；不手写价格，不使用某天后累加/分段最终值替代。",
                   start_date=min(d for _, ds in groups for d in ds), end_date=int(date.today().strftime("%Y%m%d")))
        return out
    as_of = int(str(params.get("as_of") or date.today().strftime("%Y%m%d")).replace("-", ""))
    int_to_date(as_of)
    path = Path(price_file)
    raw = path.read_bytes()
    records = list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
    if not records or set(records[0]) != {"date", "value"}:
        raise ValueError("需要单资产单字段原始CSV列 date,value；不可猜测多列数据或重写价格")
    points = []
    previous = None
    for r in records:
        d = int(str(r["date"]).replace("-", ""))
        int_to_date(d)
        value = float(r["value"])
        if not math.isfinite(value) or value <= 0:
            raise ValueError("价格必须为有限正数；缺失值需核实原始数据，不能补零或填充")
        if previous is not None and d <= previous:
            raise ValueError("价格日期必须严格递增且唯一")
        previous = d
        if d <= as_of:
            points.append((d, value))
    indexes = {d: i for i, (d, _) in enumerate(points)}
    rows = []
    for group, dates in groups:
        for event in dates:
            for window in windows:
                row = {"group": group, "event_date": event, "window": window,
                       "anchor_date": None, "end_date": None, "return": None,
                       "observations_after_anchor": 0, "status": "anchor_missing"}
                i = indexes.get(event)
                if i is not None:
                    available = len(points) - i - 1
                    row.update(anchor_date=event, anchor_close=points[i][1],
                               observations_after_anchor=min(window, available),
                               status="insufficient_observations")
                    if available >= window:
                        end, close = points[i + window]
                        row.update(status="complete", end_date=end, end_close=close,
                                   **{"return": close / points[i][1] - 1})
                rows.append(row)
    summary = []
    for group, _ in groups:
        for window in windows:
            values = [r["return"] for r in rows if r["group"] == group and r["window"] == window and r["status"] == "complete"]
            summary.append({"group": group, "window": window, "sample_count": len(values),
                            "mean_return": statistics.mean(values) if values else None,
                            "median_return": statistics.median(values) if values else None,
                            "up_count": sum(v > 0 for v in values), "down_count": sum(v < 0 for v in values)})
    out.update(status="evaluated", as_of=as_of, rows=rows, summary=summary,
               source={"file": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(),
                       "provenance": "caller_must_verify_asset_field_and_adjustment_from_query_receipt",
                       "first_date": points[0][0] if points else None,
                       "last_date": points[-1][0] if points else None, "points": len(points)})
    return out
