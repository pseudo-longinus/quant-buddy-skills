#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_fastquery_csv.py — 下载并解析 fast_query 在 mode:"csv" 时返回的 csv_url。

背景：fast_query 单次查询数据点 > 500 时，服务端不内联返回数据，而是返回
`mode:"csv"` + `csv_url`（OSS 链接，每个字段一个 url）。本脚本把该 csv 下载下来，
解析这种「宽表」格式（首行 ticker,name,<日期1>,<日期2>...；其余每行一个资产），
对每个资产计算 首值/末值/最高/最低/数据点数/区间涨跌幅，输出干净的 JSON 供作答。

为什么用脚本而不是让模型现写 curl/解析：解析+统计确定性强、可审计，避免逐次手写易错。
这是「消费工具返回的 csv_url」，不是「包装平台原生工具」，属 skill 允许的本地脚本兜底。

用法：
    python scripts/fetch_fastquery_csv.py "<csv_url1>" ["<csv_url2>" ...] \
        [--labels 收盘价,成交额] [--full] [--max-points 2000]

参数：
    位置参数         一个或多个 csv_url（每个字段一个，来自 fast_query 响应的 csv_fields[].csv_url）
    --labels         可选，逗号分隔的字段名，按顺序对应各 url（仅用于输出标注）
    --full           额外输出每个资产的完整 (date,value) 序列（受 --max-points 截断）
    --max-points     --full 时单个资产最多输出多少个点，默认 2000；超出则截断并标注

输出：stdout 打印一个 JSON 对象（见文件末尾示例）。网络/解析失败时 stderr 报错并非零退出。
仅依赖 Python 标准库（urllib / csv / json），无需 pandas / requests。
"""
import sys
import csv
import json
import argparse
import io
import urllib.request


def _download(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "quant-buddy-skill/csv-fetch"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    # OSS 导出为 UTF-8（含中文资产名）；utf-8-sig 兼容可能的 BOM
    return raw.decode("utf-8-sig", errors="replace")


def _to_float(s):
    if s is None:
        return None
    s = s.strip()
    if s == "" or s.lower() in ("nan", "null", "none"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_csv_text(text):
    """解析宽表：返回 (dates[], rows[]) ，rows 每项 {ticker, name, values[]}（与 dates 等长）。"""
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header or len(header) < 3:
        raise ValueError("CSV 表头异常：期望 ticker,name,<日期...> 至少 3 列")
    # 约定前两列是 ticker,name，其余是日期列
    dates = [h.strip() for h in header[2:]]
    rows = []
    for r in reader:
        if not r or len(r) < 2:
            continue
        ticker = r[0].strip()
        name = r[1].strip()
        vals = [_to_float(x) for x in r[2:]]
        # 与 dates 对齐长度
        if len(vals) < len(dates):
            vals += [None] * (len(dates) - len(vals))
        elif len(vals) > len(dates):
            vals = vals[: len(dates)]
        rows.append({"ticker": ticker, "name": name, "values": vals})
    return dates, rows


def _summarize_row(dates, values):
    pairs = [(d, v) for d, v in zip(dates, values) if v is not None]
    if not pairs:
        return {"count": 0, "note": "该资产在区间内无有效数据"}
    first_d, first_v = pairs[0]
    last_d, last_v = pairs[-1]
    min_d, min_v = min(pairs, key=lambda p: p[1])
    max_d, max_v = max(pairs, key=lambda p: p[1])
    out = {
        "count": len(pairs),
        "first": {"date": first_d, "value": first_v},
        "last": {"date": last_d, "value": last_v},
        "min": {"date": min_d, "value": min_v},
        "max": {"date": max_d, "value": max_v},
    }
    # 区间涨跌幅（仅在首值非零时有意义；对价格类字段有意义，对“涨跌幅”等本身是%的字段无意义，由调用方判断）
    if first_v not in (0, None):
        out["period_return_pct"] = round((last_v / first_v - 1) * 100, 4)
    return out


def main():
    ap = argparse.ArgumentParser(description="下载并解析 fast_query 的 csv_url")
    ap.add_argument("urls", nargs="+", help="一个或多个 csv_url")
    ap.add_argument("--labels", default="", help="逗号分隔的字段名，按顺序对应各 url")
    ap.add_argument("--full", action="store_true", help="额外输出完整 (date,value) 序列")
    ap.add_argument("--max-points", type=int, default=2000, help="--full 时单资产最多输出点数")
    ap.add_argument("--timeout", type=int, default=60)
    args = ap.parse_args()

    labels = [s.strip() for s in args.labels.split(",")] if args.labels else []
    result = {"sources": []}

    for i, url in enumerate(args.urls):
        label = labels[i] if i < len(labels) and labels[i] else None
        src = {"label": label, "url_tail": url.split("/")[-1].split("?")[0]}
        try:
            text = _download(url, timeout=args.timeout)
            dates, rows = _parse_csv_text(text)
        except Exception as e:  # noqa: BLE001 — 兜底，错误透传给调用方
            src["error"] = f"{type(e).__name__}: {e}"
            result["sources"].append(src)
            continue

        src["date_range"] = [dates[0], dates[-1]] if dates else []
        src["total_dates"] = len(dates)
        src["asset_count"] = len(rows)
        assets = []
        for row in rows:
            a = {"ticker": row["ticker"], "name": row["name"]}
            a.update(_summarize_row(dates, row["values"]))
            if args.full:
                series = [
                    {"date": d, "value": v}
                    for d, v in zip(dates, row["values"]) if v is not None
                ]
                if len(series) > args.max_points:
                    a["series_truncated"] = True
                    a["series_shown"] = args.max_points
                    a["series"] = series[: args.max_points]
                else:
                    a["series"] = series
            assets.append(a)
        src["assets"] = assets
        result["sources"].append(src)

    # 任一 source 出错则非零退出，但仍打印已得到的结果
    had_error = any("error" in s for s in result["sources"])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(2 if had_error else 0)


if __name__ == "__main__":
    main()
