#!/usr/bin/env python3
r"""
Safely retrofit a stock_analysis_instance_v1 page with one benchmark series.

The stock page keeps ownership of #priceChart. This transform extends its native
load/render/table lifecycle instead of injecting a second build_dashboard panel.
It is intentionally version-bound and fail-closed: every runtime seam must match
exactly once before an output file can be written.

Usage:
  python scripts/stock_comparison.py apply @params.json

Params:
  html_file / html, out_file,
  package_id, signature (optional when locally stored),
  benchmark_output, benchmark_name, benchmark_unit (default: 点),
  primary_name (default: 收盘价), task_id (optional audit passthrough only).
"""

import json
import os
import re
import sys
from pathlib import Path

import common as C
import formula_package as FP

MARKER = "QBV_STOCK_COMPARISON_RUNTIME:v1"


def _resolve_local_path(value):
    path = os.path.expandvars(os.path.expanduser(str(value)))
    return os.path.abspath(path if os.path.isabs(path) else os.path.join(C.SKILL_ROOT, path))
_STOCK_CONFIG_RE = re.compile(
    r"(<script\b[^>]*\bdata-qbv-stock-instance(?:\s*=\s*['\"][^'\"]*['\"])?[^>]*>)(.*?)(</script\s*>)",
    re.I | re.S,
)


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


def _credential(params):
    package_id = str(params.get("package_id") or "").strip()
    signature = str(params.get("signature") or "").strip()
    if package_id and not signature:
        record = FP.load_credential(package_id) or {}
        signature = str(record.get("signature") or "").strip()
    if not package_id or not signature:
        raise ValueError("需要 package_id + signature（signature 可由本地公式包凭证补全）")
    return package_id, signature


def _replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise ValueError(f"STOCK_RUNTIME_UNSUPPORTED: {label} 期望命中 1 次，实际 {count} 次")
    return text.replace(old, new, 1)


def _patch_config(html, params, package_id, signature):
    match = _STOCK_CONFIG_RE.search(html)
    if not match:
        raise ValueError("STOCK_INSTANCE_NOT_FOUND: 缺少 data-qbv-stock-instance 配置块")
    try:
        config = json.loads(match.group(2).lstrip("\ufeff").strip() or "{}")
    except ValueError as exc:
        raise ValueError(f"STOCK_INSTANCE_INVALID: {exc}") from exc
    if config.get("version") != "stock_analysis_instance_v1":
        raise ValueError(f"STOCK_RUNTIME_UNSUPPORTED: 实例版本 {config.get('version')!r}")

    output = str(params.get("benchmark_output") or "").strip()
    if not output:
        raise ValueError("benchmark_output 必填")
    name = str(params.get("benchmark_name") or output).strip()
    unit = str(params.get("benchmark_unit") or "点").strip()
    primary_name = str(params.get("primary_name") or "收盘价").strip()
    endpoint = str(params.get("endpoint") or C.endpoint_of(C.load_config())).strip()
    source = {
        "endpoint": endpoint,
        "package_id": package_id,
        "signature": signature,
        "output": output,
    }
    config.setdefault("data_sources", {})["benchmark_series"] = source
    config["comparison"] = {
        "mode": "benchmark",
        "name": name,
        "unit": unit,
        "primary_name": primary_name,
        "runtime": "stock-comparison-v1",
        "benchmark_series": source,
    }
    body = "\n" + json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    return html[:match.start()] + match.group(1) + body + match.group(3) + html[match.end():], config


def _patch_runtime(html):
    if MARKER in html:
        return html, False

    html = _replace_once(
        html,
        "    const state = { config: null, data: null, loading: false, lastLoadedAt: null };",
        "    // " + MARKER + "\n    const state = { config: null, data: null, loading: false, lastLoadedAt: null };",
        "runtime marker",
    )
    html = _replace_once(
        html,
        "      $('priceUnitText').textContent = '近 250 个交易日 · ' + meta.priceUnit;",
        "      $('priceUnitText').textContent = config.comparison && config.comparison.mode === 'benchmark'\n"
        "        ? '近 250 个交易日 · 左轴 ' + meta.priceUnit + ' · 右轴 ' + (config.comparison.unit || '点')\n"
        "        : '近 250 个交易日 · ' + meta.priceUnit;\n"
        "      const priceTitle = document.querySelector('#priceCard .chart-title');\n"
        "      if (priceTitle && config.comparison && config.comparison.mode === 'benchmark') priceTitle.textContent = '收盘价与' + config.comparison.name + '对比';",
        "price title",
    )
    html = _replace_once(
        html,
        "      const maps = seriesList.map(s => new Map(s.points.map(p => [String(p.date),p.value])));\n"
        "      target.innerHTML = '<table><thead><tr><th>日期</th>' + seriesList.map(s=>'<th>'+escapeHtml(s.name)+'</th>').join('') + '</tr></thead><tbody>' +\n"
        "        allDates.slice().reverse().map(date => '<tr><td>'+escapeHtml(dateText(date))+'</td>' + maps.map(m => '<td>' + (m.has(date) ? escapeHtml(valueFormatter(m.get(date))) : '--') + '</td>').join('') + '</tr>').join('') + '</tbody></table>';",
        "      const maps = seriesList.map(s => new Map(s.points.map(p => [String(p.date),p.value])));\n"
        "      target.innerHTML = '<table><thead><tr><th>日期</th>' + seriesList.map(s=>'<th>'+escapeHtml(s.name)+'</th>').join('') + '</tr></thead><tbody>' +\n"
        "        allDates.slice().reverse().map(date => '<tr><td>'+escapeHtml(dateText(date))+'</td>' + maps.map((m,index) => '<td>' + (m.has(date) ? escapeHtml(valueFormatter(m.get(date),seriesList[index])) : '--') + '</td>').join('') + '</tr>').join('') + '</tbody></table>';",
        "series table formatter",
    )
    html = _replace_once(
        html,
        "        .map((s,i) => ({ name:s.name, color:s.color || COLORS[i], points:(s.points||[]).filter(p => num(p.value) != null) }))",
        "        .map((s,i) => ({ name:s.name, color:s.color || COLORS[i], yAxisIndex:Number(s.yAxisIndex)||0, points:(s.points||[]).filter(p => num(p.value) != null) }))",
        "line prepared series",
    )
    html = _replace_once(
        html,
        "          yAxis: valueAxis(t, axisFormat, !options.includeZero),",
        "          yAxis: options.dualAxis ? [\n"
        "            Object.assign(valueAxis(t, axisFormat, !options.includeZero), { name: options.leftAxisName || '', position: 'left' }),\n"
        "            Object.assign(valueAxis(t, options.rightAxisFormat || axisFormat, true), { name: options.rightAxisName || '', position: 'right', splitLine: { show: false } }),\n"
        "          ] : valueAxis(t, axisFormat, !options.includeZero),",
        "dual y axes",
    )
    html = _replace_once(
        html,
        "              name: s.name, type: 'line', smooth: false, symbol: 'circle', symbolSize: 8, showSymbol: false,",
        "              name: s.name, type: 'line', yAxisIndex: s.yAxisIndex, smooth: false, symbol: 'circle', symbolSize: 8, showSymbol: false,",
        "series yAxisIndex",
    )
    html = _replace_once(
        html,
        "        const sources=config.data_sources, roles=['profile','market_series','financial_report'];\n"
        "        const results=await Promise.allSettled(roles.map(role=>QB.queryGrant(sources[role])));",
        "        const sources=config.data_sources, roles=['profile','market_series','financial_report'];\n"
        "        const benchmarkSource=sources.benchmark_series;\n"
        "        const requests=roles.map(role=>QB.queryGrant(sources[role]));\n"
        "        if(benchmarkSource) requests.push(QB.query(benchmarkSource,{outputs:[benchmarkSource.output]}));\n"
        "        const results=await Promise.allSettled(requests);",
        "benchmark request",
    )
    html = _replace_once(
        html,
        "        const price=cleanSeries(mf['收盘价'],true),amount=cleanSeries(mf['成交额'],true),pe=cleanSeries(mf['PE_TTM'],true),pb=cleanSeries(mf['PB'],true);",
        "        const price=cleanSeries(mf['收盘价'],true),amount=cleanSeries(mf['成交额'],true),pe=cleanSeries(mf['PE_TTM'],true),pb=cleanSeries(mf['PB'],true);\n"
        "        const benchmarkResult=benchmarkSource?results[roles.length]:null;\n"
        "        const benchmarkOut=benchmarkResult&&benchmarkResult.status==='fulfilled'?benchmarkResult.value:null;\n"
        "        const benchmark=benchmarkSource&&benchmarkOut?QB.series(benchmarkOut,benchmarkSource.output,{dropZero:true}).map(p=>({date:QB.fmtDate(p.d),value:p.v})):[];",
        "benchmark series",
    )
    html = _replace_once(
        html,
        "        if(price.length){renderLineChart($('priceChart'),[{name:'收盘价',points:price,color:COLORS[0]}],{ariaLabel:config.asset.name+'收盘价趋势',valueFormat:v=>format(v,2)+' '+meta.priceUnit,axisFormat:v=>format(v,0)});seriesTable($('priceTable'),[{name:'收盘价',points:price}],v=>format(v,2)+' '+meta.priceUnit);}",
        "        if(price.length){const comparison=config.comparison&&config.comparison.mode==='benchmark'?config.comparison:null;const priceSeries=[{name:(comparison&&comparison.primary_name)||'收盘价',points:price,color:COLORS[0],yAxisIndex:0,unit:meta.priceUnit}];if(comparison&&benchmark.length)priceSeries.push({name:comparison.name,points:benchmark,color:COLORS[1],yAxisIndex:1,unit:comparison.unit||'点'});renderLineChart($('priceChart'),priceSeries,{ariaLabel:comparison?config.asset.name+'收盘价与'+comparison.name+'对比':config.asset.name+'收盘价趋势',valueFormat:v=>format(v,2),axisFormat:v=>format(v,2),rightAxisFormat:v=>format(v,0),dualAxis:priceSeries.length>1,leftAxisName:meta.priceUnit,rightAxisName:comparison?(comparison.unit||'点'):''});seriesTable($('priceTable'),priceSeries,(v,s)=>format(v,2)+(s&&s.unit?' '+s.unit:''));}",
        "price comparison render",
    )
    return html, True


def transform(html, params):
    package_id, signature = _credential(params)
    html, config = _patch_config(html, params, package_id, signature)
    html, runtime_changed = _patch_runtime(html)
    if html.count("echarts@5/dist/echarts.min.js") != 1:
        raise ValueError("STOCK_RUNTIME_UNSUPPORTED: stock comparison 页面必须且只能加载一份 ECharts CDN")
    if html.count(MARKER) != 1:
        raise ValueError("STOCK_RUNTIME_UNSUPPORTED: comparison runtime marker 数量异常")
    return html, config, runtime_changed


def cmd_apply(params):
    html, source_file = _read_html(params)
    updated, config, runtime_changed = transform(html, params)
    out_value = params.get("out_file")
    if out_value:
        out_file = _resolve_local_path(out_value)
    elif source_file:
        src = Path(source_file)
        out_file = str(src.with_name(src.stem + ".stock-comparison" + src.suffix))
    else:
        raise ValueError("使用 html 参数时必须提供 out_file")
    Path(out_file).parent.mkdir(parents=True, exist_ok=True)
    Path(out_file).write_text(updated, encoding="utf-8", newline="\n")
    return {
        "code": 0,
        "html_file": os.path.abspath(out_file),
        "size": len(updated.encode("utf-8")),
        "stock_instance_version": config.get("version"),
        "benchmark_name": config["comparison"]["name"],
        "benchmark_output": config["comparison"]["benchmark_series"]["output"],
        "runtime_changed": runtime_changed,
        "echarts_cdn_count": updated.count("echarts@5/dist/echarts.min.js"),
        "message": "已把基准序列并入 stock 原生 load/render/table 生命周期；#priceChart 只有一个 owner。",
    }


def main():
    command = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith(("{", "@")) else "apply"
    argv = sys.argv[2:] if command == "apply" and len(sys.argv) > 1 and sys.argv[1] == "apply" else sys.argv[1:]
    try:
        params = C.read_params(argv, env_var="SC_PARAMS")
        if command != "apply":
            raise ValueError(f"未知子命令: {command}")
        result = cmd_apply(params)
    except (OSError, ValueError) as exc:
        result = {"code": 1, "error": str(exc).split(":", 1)[0], "message": str(exc)}
    C.emit(result, out_name="stock_comparison_out.txt")
    raise SystemExit(0 if result.get("code") == 0 else 1)


if __name__ == "__main__":
    main()
