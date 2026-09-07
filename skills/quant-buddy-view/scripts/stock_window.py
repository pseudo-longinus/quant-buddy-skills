#!/usr/bin/env python3
r"""
Safely apply a rolling display window to a legacy stock_analysis_instance_v1 page.

Usage:
  python scripts/stock_window.py apply @params.json

Params:
  html_file / html, out_file,
  lookback_days (preferred) or start_date (YYYY-MM-DD),
  label (optional, defaults to 最近一年 for 365/366 days), task_id (audit passthrough only).
"""

import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

import common as C

MARKER = "QBV_STOCK_WINDOW_RUNTIME:v1"
_CONFIG_RE = re.compile(
    r"(<script\b[^>]*\bdata-qbv-stock-instance(?:\s*=\s*['\"][^'\"]*['\"])?[^>]*>)(.*?)(</script\s*>)",
    re.I | re.S,
)


def _resolve_local_path(value):
    path = os.path.expandvars(os.path.expanduser(str(value)))
    return os.path.abspath(path if os.path.isabs(path) else os.path.join(C.SKILL_ROOT, path))


def _read_html(params):
    html = params.get("html")
    source_file = None
    if not html and params.get("html_file"):
        source_file = _resolve_local_path(params["html_file"])
        if not os.path.isfile(source_file):
            raise ValueError(f"html_file 不存在: {source_file}")
        html = Path(source_file).read_text(encoding="utf-8-sig")
    if not isinstance(html, str) or not html.strip():
        raise ValueError("apply 需要 html 或 html_file")
    return html, source_file


def _replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise ValueError(f"STOCK_WINDOW_UNSUPPORTED: {label} 期望命中 1 次，实际 {count} 次")
    return text.replace(old, new, 1)


def _window_contract(params):
    start_date = str(params.get("start_date") or "").strip()
    lookback = params.get("lookback_days")
    if start_date:
        try:
            dt.date.fromisoformat(start_date)
        except ValueError as exc:
            raise ValueError("start_date 必须是 YYYY-MM-DD") from exc
        lookback_days = None
    else:
        try:
            lookback_days = int(lookback)
        except (TypeError, ValueError) as exc:
            raise ValueError("lookback_days 必须是正整数，或提供 start_date") from exc
        if lookback_days <= 0 or lookback_days > 3650:
            raise ValueError("lookback_days 必须在 1..3650")
    label = str(params.get("label") or "").strip()
    if not label:
        label = "最近一年" if lookback_days in (365, 366) else (f"最近 {lookback_days} 天" if lookback_days else f"自 {start_date}")
    return {"runtime": "stock-window-v1", "lookback_days": lookback_days, "start_date": start_date or None, "label": label}


def _patch_config(html, params):
    match = _CONFIG_RE.search(html)
    if not match:
        raise ValueError("STOCK_INSTANCE_NOT_FOUND: 缺少 data-qbv-stock-instance 配置块")
    try:
        config = json.loads(match.group(2).lstrip("\ufeff").strip() or "{}")
    except ValueError as exc:
        raise ValueError(f"STOCK_INSTANCE_INVALID: {exc}") from exc
    if config.get("version") != "stock_analysis_instance_v1":
        raise ValueError(f"STOCK_WINDOW_UNSUPPORTED: 实例版本 {config.get('version')!r}")
    config["display_window"] = _window_contract(params)
    body = "\n" + json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    return html[:match.start()] + match.group(1) + body + match.group(3) + html[match.end():], config


def _patch_runtime(html):
    if MARKER in html:
        return html, False

    state_line = "    const state = { config: null, data: null, loading: false, lastLoadedAt: null };"
    helpers = r"""    // QBV_STOCK_WINDOW_RUNTIME:v1
    const state = { config: null, data: null, loading: false, lastLoadedAt: null };
    function stockWindowLabel(config) {
      return (config && config.display_window && config.display_window.label) || '近 250 个交易日';
    }
    function stockWindowPoints(points) {
      const list = Array.isArray(points) ? points : [];
      const spec = state.config && state.config.display_window;
      if (!spec || !list.length) return list;
      let cutoff = spec.start_date ? new Date(spec.start_date + 'T00:00:00Z') : null;
      if (!cutoff && Number(spec.lookback_days) > 0) {
        const latestRaw = String(list[list.length - 1].date || '');
        const latestIso = /^\d{8}$/.test(latestRaw) ? latestRaw.slice(0,4)+'-'+latestRaw.slice(4,6)+'-'+latestRaw.slice(6,8) : latestRaw;
        const latest = new Date(latestIso + (/T/.test(latestIso) ? '' : 'T00:00:00Z'));
        if (!Number.isNaN(latest.getTime())) { cutoff = new Date(latest); cutoff.setUTCDate(cutoff.getUTCDate() - Number(spec.lookback_days)); }
      }
      if (!cutoff || Number.isNaN(cutoff.getTime())) return list;
      return list.filter(point => {
        const raw = String(point && point.date || '');
        const iso = /^\d{8}$/.test(raw) ? raw.slice(0,4)+'-'+raw.slice(4,6)+'-'+raw.slice(6,8) : raw;
        const when = new Date(iso + (/T/.test(iso) ? '' : 'T00:00:00Z'));
        return !Number.isNaN(when.getTime()) && when >= cutoff;
      });
    }"""
    html = _replace_once(html, state_line, helpers, "runtime marker")
    html = _replace_once(
        html,
        "      $('priceUnitText').textContent = '近 250 个交易日 · ' + meta.priceUnit;",
        "      $('priceUnitText').textContent = stockWindowLabel(config) + ' · ' + meta.priceUnit;",
        "price window label",
    )
    html = _replace_once(
        html,
        "      $('amountUnitText').textContent = '近 250 个交易日 · ' + meta.amountUnit;",
        "      $('amountUnitText').textContent = stockWindowLabel(config) + ' · ' + meta.amountUnit;",
        "amount window label",
    )
    html = _replace_once(
        html,
        "    function seriesTable(target, seriesList, valueFormatter) {",
        "    function seriesTable(target, seriesList, valueFormatter) {\n      seriesList = seriesList.map(s => Object.assign({}, s, {points: stockWindowPoints(s.points || [])}));",
        "table window",
    )
    html = _replace_once(
        html,
        "        .map((s,i) => ({ name:s.name, color:s.color || COLORS[i], points:(s.points||[]).filter(p => num(p.value) != null) }))",
        "        .map((s,i) => ({ name:s.name, color:s.color || COLORS[i], points:stockWindowPoints((s.points||[]).filter(p => num(p.value) != null)) }))",
        "line window",
    )
    html = _replace_once(
        html,
        "      const data = (points || []).filter(p => num(p.value) != null);",
        "      const data = stockWindowPoints((points || []).filter(p => num(p.value) != null));",
        "bar window",
    )
    html = _replace_once(
        html,
        "      const rows=close.map(p=>String(p.date)).filter(date=>maps.open.has(date)&&maps.high.has(date)&&maps.low.has(date)).map(date=>({date,open:maps.open.get(date),high:maps.high.get(date),low:maps.low.get(date),close:maps.close.get(date),volume:maps.volume.get(date)||0})).filter(r=>[r.open,r.high,r.low,r.close].every(Number.isFinite));",
        "      const rows=stockWindowPoints(close.map(p=>String(p.date)).filter(date=>maps.open.has(date)&&maps.high.has(date)&&maps.low.has(date)).map(date=>({date,open:maps.open.get(date),high:maps.high.get(date),low:maps.low.get(date),close:maps.close.get(date),volume:maps.volume.get(date)||0})).filter(r=>[r.open,r.high,r.low,r.close].every(Number.isFinite)));",
        "technical window",
    )
    html = _replace_once(
        html,
        "      const start=Math.max(0,100-(Math.min(120,rows.length)/rows.length*100));",
        "      const start=0;",
        "technical initial zoom",
    )
    return html, True


def transform(html, params):
    html, config = _patch_config(html, params)
    html, runtime_changed = _patch_runtime(html)
    if html.count(MARKER) != 1:
        raise ValueError("STOCK_WINDOW_UNSUPPORTED: runtime marker 数量异常")
    return html, config, runtime_changed


def cmd_apply(params):
    html, source_file = _read_html(params)
    updated, config, runtime_changed = transform(html, params)
    out_value = params.get("out_file")
    if out_value:
        out_file = _resolve_local_path(out_value)
    elif source_file:
        src = Path(source_file)
        out_file = str(src.with_name(src.stem + ".stock-window" + src.suffix))
    else:
        raise ValueError("使用 html 参数时必须提供 out_file")
    Path(out_file).parent.mkdir(parents=True, exist_ok=True)
    Path(out_file).write_text(updated, encoding="utf-8", newline="\n")
    spec = config["display_window"]
    return {
        "code": 0,
        "html_file": os.path.abspath(out_file),
        "size": len(updated.encode("utf-8")),
        "stock_instance_version": config.get("version"),
        "display_window": spec,
        "runtime_changed": runtime_changed,
        "message": "已把 legacy stock 页面转换为滚动展示窗口；请先浏览器预检，再 update 写回同一 page_id。",
    }


def main():
    command = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith(("{", "@")) else "apply"
    argv = sys.argv[2:] if command == "apply" and len(sys.argv) > 1 and sys.argv[1] == "apply" else sys.argv[1:]
    try:
        params = C.read_params(argv, env_var="SW_PARAMS")
        if command != "apply":
            raise ValueError(f"未知子命令: {command}")
        result = cmd_apply(params)
    except (OSError, ValueError) as exc:
        result = {"code": 1, "error": str(exc).split(":", 1)[0], "message": str(exc)}
    C.emit(result, out_name="stock_window_out.txt")
    raise SystemExit(0 if result.get("code") == 0 else 1)


if __name__ == "__main__":
    main()
