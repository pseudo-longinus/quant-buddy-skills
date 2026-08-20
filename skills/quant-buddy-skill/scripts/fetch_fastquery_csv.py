#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Download and normalize ``fast_query`` CSV exports.

When ``fast_query`` returns ``mode: csv``, this script consumes the returned
``csv_url`` values.  It can either print the legacy JSON result to stdout, or
write the full normalized series into a hash-bound artifact and print only a
compact receipt.  The artifact path is restricted to this skill's ``output``
directory so an Agent cannot use the helper as a general-purpose file writer.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import sys
import tempfile
import urllib.request
from itertools import combinations
from pathlib import Path
from typing import Any, Callable, Iterable, Optional


def _download(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "quant-buddy-skill/csv-fetch"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return raw.decode("utf-8-sig", errors="replace")


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "null", "none"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_csv_text(text: str):
    """Parse the wide export: ticker,name,<date1>,<date2>..."""
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header or len(header) < 3:
        raise ValueError("CSV 表头异常：期望 ticker,name,<日期...> 至少 3 列")
    dates = [cell.strip() for cell in header[2:]]
    rows = []
    for raw in reader:
        if not raw or len(raw) < 2:
            continue
        values = [_to_float(cell) for cell in raw[2:]]
        if len(values) < len(dates):
            values += [None] * (len(dates) - len(values))
        elif len(values) > len(dates):
            values = values[: len(dates)]
        rows.append({"ticker": raw[0].strip(), "name": raw[1].strip(), "values": values})
    return dates, rows


def _summarize_row(dates: Iterable[str], values: Iterable[Optional[float]]) -> dict[str, Any]:
    pairs = [(date, value) for date, value in zip(dates, values) if value is not None]
    if not pairs:
        return {"count": 0, "note": "该资产在区间内无有效数据"}
    first_date, first_value = pairs[0]
    last_date, last_value = pairs[-1]
    min_date, min_value = min(pairs, key=lambda pair: pair[1])
    max_date, max_value = max(pairs, key=lambda pair: pair[1])
    result: dict[str, Any] = {
        "count": len(pairs),
        "first": {"date": first_date, "value": first_value},
        "last": {"date": last_date, "value": last_value},
        "min": {"date": min_date, "value": min_value},
        "max": {"date": max_date, "value": max_value},
    }
    if first_value != 0:
        result["period_return_pct"] = round((last_value / first_value - 1) * 100, 4)
    return result


def _pearson(left: list[float], right: list[float]) -> Optional[float]:
    if len(left) < 2 or len(left) != len(right):
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    left_sq = sum((x - left_mean) ** 2 for x in left)
    right_sq = sum((y - right_mean) ** 2 for y in right)
    denominator = math.sqrt(left_sq * right_sq)
    if denominator == 0:
        return None
    return round(numerator / denominator, 8)


def _direction_agreement(left: list[float], right: list[float]) -> tuple[Optional[float], int]:
    comparable = 0
    agreed = 0
    for index in range(1, min(len(left), len(right))):
        left_delta = left[index] - left[index - 1]
        right_delta = right[index] - right[index - 1]
        # Flat/flat counts as agreement. Flat/non-flat is a disagreement.
        comparable += 1
        if (left_delta > 0) == (right_delta > 0) and (left_delta < 0) == (right_delta < 0):
            agreed += 1
    if comparable == 0:
        return None, 0
    return round(agreed / comparable * 100, 4), comparable


def _series_map(source: dict[str, Any]) -> dict[str, dict[str, float]]:
    mapped: dict[str, dict[str, float]] = {}
    for asset in source.get("assets") or []:
        key = str(asset.get("ticker") or asset.get("name") or "").strip()
        if not key:
            continue
        mapped[key] = {
            str(point["date"]): float(point["value"])
            for point in asset.get("series") or []
            if point.get("date") is not None and point.get("value") is not None
        }
    return mapped


def _pairwise_analysis(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    analyses: list[dict[str, Any]] = []
    for left, right in combinations(sources, 2):
        if "error" in left or "error" in right:
            continue
        left_assets = _series_map(left)
        right_assets = _series_map(right)
        for asset_key in sorted(set(left_assets) & set(right_assets)):
            left_by_date = left_assets[asset_key]
            right_by_date = right_assets[asset_key]
            aligned_dates = sorted(set(left_by_date) & set(right_by_date))
            left_values = [left_by_date[date] for date in aligned_dates]
            right_values = [right_by_date[date] for date in aligned_dates]
            agreement, direction_pairs = _direction_agreement(left_values, right_values)
            analyses.append({
                "asset": asset_key,
                "left_label": left.get("label"),
                "right_label": right.get("label"),
                "aligned_points": len(aligned_dates),
                "aligned_date_range": [aligned_dates[0], aligned_dates[-1]] if aligned_dates else [],
                "level_correlation": _pearson(left_values, right_values),
                "direction_agreement_pct": agreement,
                "direction_pairs": direction_pairs,
            })
    return analyses


def build_result(
    urls: Iterable[str],
    labels: Optional[Iterable[str]] = None,
    include_full: bool = False,
    max_points: int = 2000,
    timeout: int = 60,
    downloader: Callable[..., str] = _download,
) -> dict[str, Any]:
    """Build a normalized result from one or more ``fast_query`` CSV URLs."""
    url_list = [str(url).strip() for url in urls if str(url).strip()]
    if not url_list:
        raise ValueError("至少需要一个 csv_url")
    if max_points <= 0:
        raise ValueError("max_points 必须大于 0")
    label_list = [str(label).strip() for label in (labels or [])]
    result: dict[str, Any] = {"sources": []}
    total_data_points = 0

    # Pairwise analysis needs complete aligned series even when legacy stdout
    # only asks for summaries.  Internal series are removed before returning
    # when include_full=False.
    for index, url in enumerate(url_list):
        label = label_list[index] if index < len(label_list) and label_list[index] else f"field_{index + 1}"
        source: dict[str, Any] = {"label": label, "url": url}
        try:
            text = downloader(url, timeout=timeout)
            dates, rows = _parse_csv_text(text)
        except Exception as exc:  # noqa: BLE001 - surface per-source failure
            source["error"] = f"{type(exc).__name__}: {exc}"
            result["sources"].append(source)
            continue

        source["date_range"] = [dates[0], dates[-1]] if dates else []
        source["total_dates"] = len(dates)
        source["asset_count"] = len(rows)
        assets = []
        for row in rows:
            asset = {"ticker": row["ticker"], "name": row["name"]}
            asset.update(_summarize_row(dates, row["values"]))
            full_series = [
                {"date": date, "value": value}
                for date, value in zip(dates, row["values"])
                if value is not None
            ]
            total_data_points += len(full_series)
            if len(full_series) > max_points:
                asset["series_truncated"] = True
                asset["series_shown"] = max_points
                asset["series"] = full_series[:max_points]
            else:
                asset["series"] = full_series
            assets.append(asset)
        source["assets"] = assets
        result["sources"].append(source)

    result["pairwise_analysis"] = _pairwise_analysis(result["sources"])
    result["summary"] = {
        "source_count": len(result["sources"]),
        "successful_source_count": sum("error" not in source for source in result["sources"]),
        "error_count": sum("error" in source for source in result["sources"]),
        "total_data_points": total_data_points,
    }
    if not include_full:
        for source in result["sources"]:
            for asset in source.get("assets") or []:
                asset.pop("series", None)
                asset.pop("series_truncated", None)
                asset.pop("series_shown", None)
    return result


def _default_output_root() -> Path:
    return Path(__file__).resolve().parents[1] / "output"


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def write_artifact(result: dict[str, Any], output_path: Any, output_root: Any = None) -> dict[str, Any]:
    """Atomically write an artifact below ``output_root`` and return its hash."""
    root = Path(output_root or _default_output_root()).expanduser().resolve()
    target = Path(output_path).expanduser()
    if not target.is_absolute():
        target = (Path.cwd() / target).resolve()
    else:
        target = target.resolve()
    if target == root or not _is_under(target, root):
        raise ValueError(f"artifact 仅允许写入 skill/output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
    return {
        "artifact_file": str(target),
        "artifact_sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "artifact_bytes": len(payload),
    }


def _compact_receipt(result: dict[str, Any], artifact_receipt: dict[str, Any], code: int) -> dict[str, Any]:
    series_summaries = []
    for source in result.get("sources") or []:
        label = source.get("label")
        for asset in source.get("assets") or []:
            summary = {
                "label": label,
                "ticker": asset.get("ticker"),
                "name": asset.get("name"),
                "count": asset.get("count", 0),
            }
            for field in ("first", "last", "min", "max", "period_return_pct", "note"):
                if field in asset:
                    summary[field] = asset[field]
            series_summaries.append(summary)
    return {
        "code": code,
        **artifact_receipt,
        "summary": result.get("summary", {}),
        "source_summaries": [
            {
                "label": source.get("label"),
                "date_range": source.get("date_range", []),
                "asset_count": source.get("asset_count", 0),
                "error": source.get("error"),
            }
            for source in result.get("sources") or []
        ],
        "series_summaries": series_summaries,
        "pairwise_analysis": result.get("pairwise_analysis", []),
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="下载并解析 fast_query 的 csv_url")
    parser.add_argument("urls", nargs="+", help="一个或多个 fast_query csv_url")
    parser.add_argument("--labels", default="", help="逗号分隔的字段名，按顺序对应各 url")
    parser.add_argument("--full", action="store_true", help="保留完整 date/value 序列")
    parser.add_argument("--max-points", type=int, default=2000, help="每个资产最多保留的数据点")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--output", help="完整 artifact 输出路径，必须位于 skill/output")
    args = parser.parse_args(argv)

    labels = [item.strip() for item in args.labels.split(",")] if args.labels else []
    # An artifact is intended for QBV reuse, so it must contain the full series.
    include_full = bool(args.full or args.output)
    try:
        result = build_result(
            args.urls,
            labels=labels,
            include_full=include_full,
            max_points=args.max_points,
            timeout=args.timeout,
            downloader=_download,
        )
        code = 2 if any("error" in source for source in result["sources"]) else 0
        if args.output:
            artifact_receipt = write_artifact(result, args.output)
            print(json.dumps(_compact_receipt(result, artifact_receipt, code), ensure_ascii=False))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return code
    except (OSError, ValueError, urllib.error.URLError) as exc:
        print(json.dumps({"code": 1, "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
