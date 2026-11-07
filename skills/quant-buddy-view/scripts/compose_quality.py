"""Non-blocking Compose quality diagnostics.

Warnings are advisory in v1.  They surface draft/layout regressions without
changing publication success semantics.
"""
from __future__ import annotations

import re
from typing import Any

CHART_TYPES = {"line", "bar", "candlestick", "radar"}
DATA_TYPES = CHART_TYPES | {"table", "number", "raw"}
INTERACTIVE_PATTERN = re.compile(r"echarts|缩放|平移|悬停|时间窗|区间切换", re.I)


def _data_rows(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if not isinstance(value, dict):
        return 0
    for key in ("values", "rows", "top_values", "last_valid_per_asset"):
        item = value.get(key)
        if isinstance(item, list):
            return len(item)
    nested = value.get("data")
    if nested is not value and nested is not None:
        return _data_rows(nested)
    outputs = value.get("outputs")
    if isinstance(outputs, dict):
        return max((_data_rows(item) for item in outputs.values()), default=0)
    return 0


def _panel_rows(task: str, panel: dict[str, Any], plan: dict[str, Any]) -> int:
    expected = panel.get("expected_rows")
    if isinstance(expected, int) and expected > 0:
        return expected
    receipt_file = panel.get("snapshot_receipt_file")
    if not receipt_file:
        return 0
    import verified_snapshot as VS
    try:
        snapshot = VS.load(task, receipt_file, panel.get("snapshot_receipt_sha256"))
    except Exception:
        return 0
    if snapshot.get("resource") == "grant":
        return _data_rows(snapshot.get("result", {}).get("data"))
    outputs = snapshot.get("result", {}).get("outputs") or {}
    names = panel.get("snapshot_outputs") or [panel.get("snapshot_output")]
    return max((_data_rows(outputs.get(str(name))) for name in names), default=0)


def evaluate(task: str, plan: dict[str, Any], panels: list[dict[str, Any]],
             presentation: dict[str, Any] | None, params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    try:
        import common as C
        context = C.current_trace_context()
        if context.get('task_id') in (None, task):
            params = {**params, 'user_query': params.get('user_query') or context.get('user_query')}
    except Exception:
        pass
    mount_by_id = {str(item.get("id")): item for item in (presentation or {}).get("mounts", [])}
    ids = [str(panel.get("id") or "") for panel in panels]
    if presentation and all(ids):
        ordered_indices = sorted(range(len(panels)), key=lambda i: mount_by_id.get(ids[i], {}).get("index", i))
    else:
        ordered_indices = list(range(len(panels)))

    data_indices = [i for i in ordered_indices if str(panels[i].get("type") or "table") in DATA_TYPES]
    first_data = data_indices[0] if data_indices else None
    rows_by_index = {i: _panel_rows(task, panels[i], plan) for i in range(len(panels))}
    summary_present = bool(presentation and presentation.get("summary_present", presentation.get("mode") == "bespoke")) or (
        bool(panels) and panels[0].get("type") == "text" and panels[0].get("hero") is True
    )
    metric_present = bool(presentation and presentation.get("metric_present", presentation.get("mode") == "bespoke")) or any(
        panels[i].get("type") == "number" for i in (data_indices or [])
    )
    chart_present = any(panels[i].get("type") in CHART_TYPES for i in range(len(panels)))
    long_first = bool(first_data is not None and panels[first_data].get("type") == "table" and rows_by_index[first_data] > 12)
    long_any = any(
        panels[i].get("type") == "table" and rows_by_index[i] > 50
        and not panels[i].get("collapsed")
        and not mount_by_id.get(ids[i], {}).get("collapsed")
        for i in range(len(panels)) if ids[i]
    )
    interactive_required = bool(INTERACTIVE_PATTERN.search(" ".join(
        str(params.get(key) or "") for key in ("user_query", "agent_intent", "description")
    )))
    result_kind = (plan.get("delivery_kind") or params.get("delivery_kind") or "result") != "methodology"

    warnings = []
    if result_kind and not summary_present:
        warnings.append("FIRST_SCREEN_SUMMARY_MISSING")
    if long_first:
        warnings.append("LONG_TABLE_FIRST_SCREEN")
    if long_any:
        warnings.append("LONG_TABLE_NOT_COLLAPSED")
    if interactive_required and not chart_present:
        warnings.append("INTERACTIVITY_REQUIREMENT_LOST")
    if result_kind and data_indices and first_data is not None and panels[first_data].get("type") == "table" and not (metric_present or chart_present):
        warnings.append("FIRST_SCREEN_EVIDENCE_NOT_READABLE")
    if result_kind and data_indices and not presentation:
        warnings.append("COMPOSE_PRESENTATION_RECOMMENDED")
    # Degraded deliveries (recovery ladder) carry a machine fallback presentation
    # so they never ship as bare tables; an authored replacement is still due.
    degraded_delivery = str(plan.get("delivery_kind") or params.get("delivery_kind") or "") in ("partial_research", "methodology") \
        or str(params.get("live_data_mode") or "") == "researched_static"
    if degraded_delivery and str(params.get("presentation_origin") or "") == "machine":
        warnings.append("PRESENTATION_AUTHORED_MISSING")

    return {
        "version": 1,
        "warnings": warnings,
        "firstScreenSummary": summary_present,
        "longTableInFirstScreen": long_first,
        "interactiveChartPresent": chart_present,
        "interactivityRequired": interactive_required,
    }
