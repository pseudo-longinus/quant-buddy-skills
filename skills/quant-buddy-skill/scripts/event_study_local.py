"""事件研究本地工具：博查搜索 + 公式生成。

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


# ── 博查 Web 搜索 ─────────────────────────────────────────

_BOCHA_BASE_URL = "https://api.bochaai.com/v1/web-search"
_BOCHA_TIMEOUT = 15
_BOCHA_COUNT = 8


def _freshness_param(months_back: int = 36) -> str:
    today = date.today()
    start = today - relativedelta(months=months_back)
    return f"{start.strftime('%Y-%m-%d')}..{today.strftime('%Y-%m-%d')}"


def bocha_web_search(query: str, freshness_months: int = 36, count: int | None = None) -> dict[str, Any]:
    """调用博查 web-search API，返回结构化搜索结果。"""
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


def build_single_formulas(prefix: str, asset: str, dates: list[int], windows: list[int]) -> list[str]:
    formulas = [
        f"{prefix}_事件日=选取日期({','.join(str(d) for d in dates)})",
        f"{prefix}_收盘=收盘价({asset})",
        f"{prefix}_日收益=涨跌幅(\"{prefix}_收盘\")",
    ]
    for window in windows:
        formulas.append(
            f"{prefix}_后{window}日路径=某天后累加(\"{prefix}_日收益\",\"{prefix}_事件日\",{window})"
        )
        formulas.append(f"{prefix}_后{window}日收益=分段最终值(\"{prefix}_后{window}日路径\")")
    return formulas


def build_compare_formulas(
    prefix: str,
    asset: str,
    group_a_name: str,
    group_a_dates: list[int],
    group_b_name: str,
    group_b_dates: list[int],
    windows: list[int],
) -> list[str]:
    formulas = [
        f"{prefix}_{group_a_name}=选取日期({','.join(str(d) for d in group_a_dates)})",
        f"{prefix}_{group_b_name}=选取日期({','.join(str(d) for d in group_b_dates)})",
        f"{prefix}_收盘=收盘价({asset})",
        f"{prefix}_日收益=涨跌幅(\"{prefix}_收盘\")",
    ]
    for name in (group_a_name, group_b_name):
        for window in windows:
            formulas.append(
                f"{prefix}_{name}后{window}日路径=某天后累加(\"{prefix}_日收益\",\"{prefix}_{name}\",{window})"
            )
            formulas.append(
                f"{prefix}_{name}后{window}日收益=分段最终值(\"{prefix}_{name}后{window}日路径\")"
            )
    return formulas


def sanitize_group_name(name: str, fallback: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", name or "")
    return cleaned or fallback


def build_event_study(params: dict[str, Any]) -> dict[str, Any]:
    mode = str(params.get("mode") or _EVENT_DEFAULTS["default_mode"])
    prefix = str(params.get("prefix") or "ES")
    windows = parse_windows(params.get("windows"))

    if mode == "single":
        dates = parse_dates(params.get("dates") or [])
        asset = str(params.get("asset") or "")
        if not dates:
            raise ValueError("single 模式需要 dates。")
        if not asset:
            raise ValueError("single 模式需要 asset。")

        return {
            "mode": "single",
            "asset": asset,
            "dates": dates,
            "windows": windows,
            "warnings": overlap_warning(dates, windows),
            "formulas": build_single_formulas(prefix=prefix, asset=asset, dates=dates, windows=windows),
        }

    if mode == "compare":
        asset = str(params.get("asset") or "")
        if not asset:
            raise ValueError("compare 模式需要 asset。")

        group_a_name = sanitize_group_name(str(params.get("group_a_name") or "A组"), "A组")
        group_b_name = sanitize_group_name(str(params.get("group_b_name") or "B组"), "B组")
        group_a_dates = parse_dates(params.get("group_a_dates") or [])
        group_b_dates = parse_dates(params.get("group_b_dates") or [])
        if not group_a_dates or not group_b_dates:
            raise ValueError("compare 模式需要 group_a_dates 和 group_b_dates。")

        warnings = []
        warnings.extend(overlap_warning(group_a_dates, windows))
        warnings.extend(overlap_warning(group_b_dates, windows))

        return {
            "mode": "compare",
            "asset": asset,
            "group_a_name": group_a_name,
            "group_a_dates": group_a_dates,
            "group_b_name": group_b_name,
            "group_b_dates": group_b_dates,
            "windows": windows,
            "warnings": warnings,
            "formulas": build_compare_formulas(
                prefix=prefix,
                asset=asset,
                group_a_name=group_a_name,
                group_a_dates=group_a_dates,
                group_b_name=group_b_name,
                group_b_dates=group_b_dates,
                windows=windows,
            ),
        }

    raise ValueError(f"不支持的 mode: {mode}")
