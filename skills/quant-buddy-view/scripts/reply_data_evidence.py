#!/usr/bin/env python3
"""Build compact, hash-bound reply evidence from already validated data."""

import copy
import hashlib
import json
import math
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import common as C
import reply_template_registry as RTR


EVIDENCE_VERSION = "reply_data_evidence_v1"
AVAILABILITY_VERSION = "reply_data_availability_v1"
POLICY_VERSION = "reply_data_policy_v1"
_SENSITIVE_KEYS = {
    "api_key", "apikey", "authorization", "bearer", "access_token",
    "refresh_token", "token", "signature", "signature_hash",
}


def _normalized_key(value):
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "_", str(value or "").strip().lower()).strip("_")


def redact(value):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            normalized = _normalized_key(key)
            if normalized in _SENSITIVE_KEYS or "signature" in normalized or normalized.endswith("_token"):
                continue
            out[key] = redact(item)
        return out
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str) and re.search(r"(?i)^bearer\s+\S+", value.strip()):
        return "[redacted]"
    return value


def get_policy(template_ref):
    policy = RTR.get_reply_data_policy(template_ref)
    return policy if isinstance(policy, dict) and policy.get("version") == POLICY_VERSION else None


def formula_output_needed(template_ref, output_name):
    policy = get_policy(template_ref)
    if not policy:
        return False
    target = _normalized_key(output_name)
    return any(
        target in {_normalized_key(alias) for alias in rule.get("output_aliases") or []}
        for rule in policy.get("formula_fields") or []
    )


def read_data_params(read_mode, mode_params=None, *, today=None):
    mode_params = dict(mode_params or {})
    params = {"mode": str(read_mode or "").strip()}
    if params["mode"] == "range_data":
        lookback_days = int(mode_params.pop("lookback_days", 366) or 366)
        end = today or date.today()
        start = end - timedelta(days=max(1, lookback_days))
        params.update({
            "start_date": int(start.strftime("%Y%m%d")),
            "end_date": int(end.strftime("%Y%m%d")),
        })
        for key in ("assets", "max_cells", "nan_handling"):
            if mode_params.get(key) is not None:
                params[key] = mode_params[key]
    else:
        for key, value in mode_params.items():
            if value is not None:
                params[key] = value
    return params


def extract_read_data_items(payload):
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("data", "results", "items"):
            if isinstance(data.get(key), list):
                return [item for item in data[key] if isinstance(item, dict)]
        if any(key in data for key in ("id", "data_id", "last_value", "last_day_stats", "range_data")):
            return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    for key in ("results", "items"):
        if isinstance(payload.get(key), list):
            return [item for item in payload[key] if isinstance(item, dict)]
    return []


def _valid_series(dates, values):
    pairs = []
    for index, value in enumerate(values or []):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            continue
        item_date = dates[index] if index < len(dates or []) else None
        pairs.append((item_date, float(value)))
    return pairs


def _range_series(item):
    block = item.get("range_data") if isinstance(item.get("range_data"), dict) else None
    if block is None and isinstance(item.get("data"), dict):
        block = item["data"].get("range_data")
    if not isinstance(block, dict):
        return []
    dates = block.get("dates") if isinstance(block.get("dates"), list) else []
    values = block.get("values") if isinstance(block.get("values"), list) else []
    if values and isinstance(values[0], list):
        values = values[0]
    return _valid_series(dates, values)


def compact_formula_read(output_name, data_id, read_mode, item):
    item = redact(item if isinstance(item, dict) else {})
    compact = {
        "output": str(output_name or ""),
        "data_id": str(data_id or ""),
        "read_mode": str(read_mode or ""),
    }
    last_value = item.get("last_value")
    if not isinstance(last_value, dict) and isinstance(item.get("data"), dict):
        last_value = item["data"].get("last_value")
    if isinstance(last_value, dict):
        compact["latest_value"] = last_value.get("value")
        compact["latest_date"] = last_value.get("date")
    stats = item.get("last_day_stats")
    if not isinstance(stats, dict) and isinstance(item.get("data"), dict):
        stats = item["data"].get("last_day_stats")
    if isinstance(stats, dict):
        compact.setdefault("latest_date", stats.get("date"))
        top_values = stats.get("top_values")
        if isinstance(top_values, list):
            compact["top_values"] = redact(top_values[:20])
    series = _range_series(item)
    if series:
        compact.update({
            "latest_date": series[-1][0],
            "latest_value": series[-1][1],
            "previous_date": series[-2][0] if len(series) > 1 else None,
            "previous_value": series[-2][1] if len(series) > 1 else None,
            "valid_sample_count": len(series),
        })
        returns = {}
        for window in (20, 60, 120, 250):
            if len(series) > window and series[-window - 1][1] != 0:
                returns[str(window)] = round((series[-1][1] / series[-window - 1][1] - 1) * 100, 6)
        if returns:
            compact["derived_returns"] = returns
    if compact.get("latest_value") is None:
        for key in ("value", "latest_value"):
            if item.get(key) is not None:
                compact["latest_value"] = item.get(key)
                compact["latest_date"] = item.get("date") or item.get("latest_date")
                break
    return compact


def compact_direct_formula_outputs(package_results):
    outputs = []
    for package in package_results or []:
        result = package.get("result") if isinstance(package, dict) else None
        for name, item in ((result or {}).get("outputs") or {}).items():
            if not isinstance(item, dict):
                continue
            summary = item.get("summary") if isinstance(item.get("summary"), dict) else {}
            outputs.append({
                "output": str(name),
                "data_id": str(item.get("data_id") or ""),
                "read_mode": str(item.get("read_mode") or "summary"),
                "latest_value": summary.get("latest_value"),
                "latest_date": summary.get("latest_date"),
                "previous_value": summary.get("first_value"),
                "previous_date": summary.get("first_date"),
            })
    return outputs


def _find_dimensions(value):
    if isinstance(value, dict):
        if isinstance(value.get("dimensions"), dict):
            return value.get("dimensions"), value
        for child in value.values():
            found, owner = _find_dimensions(child)
            if found is not None:
                return found, owner
    elif isinstance(value, list):
        for child in value:
            found, owner = _find_dimensions(child)
            if found is not None:
                return found, owner
    return None, None


def compact_grant_result(kind, result):
    safe = redact(result if isinstance(result, dict) else {})
    dimensions, owner = _find_dimensions(safe)
    compact = {"kind": str(kind or ""), "asset": None, "computed_at": None, "indicators": []}
    if isinstance(owner, dict):
        compact["asset"] = redact(owner.get("asset"))
        compact["computed_at"] = owner.get("computed_at")
    if isinstance(dimensions, dict):
        for dimension_name, dimension in dimensions.items():
            if not isinstance(dimension, dict):
                continue
            dimension_date = dimension.get("latest_date")
            dimension_unit = dimension.get("unit")
            indicators = dimension.get("indicators") if isinstance(dimension.get("indicators"), dict) else {}
            for base_id, indicator in indicators.items():
                if not isinstance(indicator, dict):
                    continue
                compact["indicators"].append({
                    "dimension": str(dimension_name),
                    "base_id": str(base_id),
                    "name": str(indicator.get("name") or base_id),
                    "latest_value": indicator.get("latest_value"),
                    "latest_date": indicator.get("latest_date") or dimension_date,
                    "unit": indicator.get("unit") or dimension_unit,
                    "previous_value": indicator.get("previous_value"),
                    "previous_date": indicator.get("previous_date"),
                    "variants": redact(indicator.get("variants") or {}),
                })
        return compact

    def visit(value, path=""):
        if isinstance(value, dict):
            name = value.get("name") or value.get("field_name") or value.get("indicator_name")
            latest = value.get("latest_value") if "latest_value" in value else value.get("value")
            if name and latest is not None:
                compact["indicators"].append({
                    "dimension": path.split(".")[0] if path else "其他",
                    "base_id": str(value.get("field") or value.get("id") or name),
                    "name": str(name),
                    "latest_value": latest,
                    "latest_date": value.get("latest_date") or value.get("date"),
                    "unit": value.get("unit"),
                    "previous_value": value.get("previous_value"),
                    "previous_date": value.get("previous_date"),
                    "variants": redact(value.get("variants") or {}),
                })
            for key, child in value.items():
                visit(child, f"{path}.{key}".strip("."))
        elif isinstance(value, list):
            for child in value:
                visit(child, path)

    visit(safe)
    return compact


def _get_path(value, path):
    current = value
    for part in str(path or "").split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _value_tokens(value):
    if value is None or isinstance(value, bool):
        return []
    tokens = []
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            return []
        tokens.extend([str(value), f"{number:.6f}".rstrip("0").rstrip(".")])
        if number.is_integer():
            tokens.append(str(int(number)))
    else:
        tokens.append(str(value).strip())
    return [item for item in dict.fromkeys(tokens) if item]


def _field(rule, value, *, date_value=None, unit=None, source=None, field_id=None, row_label=None, column_label=None):
    return {
        "field_id": field_id or rule.get("field_id"),
        "section": rule.get("section"),
        "row_label": row_label or rule.get("row_label"),
        "column_label": column_label if column_label is not None else rule.get("column_label"),
        "value": value,
        "date": date_value,
        "unit": unit if unit is not None else rule.get("unit"),
        "render_tokens": _value_tokens(value),
        "source": source or {},
    }


def _matches_indicator(rule, indicator):
    base = _normalized_key(indicator.get("base_id"))
    name = _normalized_key(indicator.get("name"))
    base_aliases = {_normalized_key(item) for item in rule.get("base_aliases") or []}
    name_aliases = [_normalized_key(item) for item in rule.get("name_aliases") or []]
    return base in base_aliases or any(alias and alias in name for alias in name_aliases)


def _variant_match(suffix, aliases):
    normalized = _normalized_key(suffix)
    for alias in aliases or []:
        target = _normalized_key(alias)
        if target and (normalized == target or normalized.endswith("_" + target)):
            return True
    return False


def _financial_variant_columns():
    return [
        ("single_quarter", ["quarter_level", "single_quarter", "quarter_value"], "单季最新"),
        ("quarter_yoy", ["quarter_yoy", "single_quarter_yoy"], "单季YoY"),
        ("quarter_qoq", ["quarter_qoq", "single_quarter_qoq"], "单季QoQ"),
        ("ttm", ["ttm_level", "ttm_value"], "TTM"),
        ("ttm_yoy", ["ttm_yoy"], "TTM YoY"),
        ("annual", ["annual_level", "annual_value"], "年度"),
        ("annual_yoy", ["annual_yoy"], "年度YoY"),
    ]


def _trading_variant_columns():
    return [
        ("ma5", ["ma:5", "ma_5", "ma5"], "5日均线"),
        ("trend60", ["trend:60", "trend_60", "trend60"], "60日趋势"),
        ("pctrank3y", ["pctrank:3y", "percentile:3y"], "3Y分位"),
        ("window5", ["ret:5", "window:5"], "5日"),
        ("window10", ["ret:10", "window:10"], "10日"),
        ("window20", ["ret:20", "window:20"], "20日"),
        ("window60", ["ret:60", "window:60"], "60日"),
        ("window120", ["ret:120", "window:120"], "120日"),
        ("window250", ["ret:250", "window:250"], "250日"),
    ]


def _percentile_variant_columns():
    return [
        ("pctrank1y", ["pctrank:1y", "percentile:1y"], "1Y分位"),
        ("pctrank3y", ["pctrank:3y", "percentile:3y"], "3Y分位"),
        ("pctrank5y", ["pctrank:5y", "percentile:5y"], "5Y分位"),
    ]


def project_fields(template_ref, formula_outputs, grant_results):
    policy = get_policy(template_ref)
    if not policy:
        return []
    projected = {}
    by_output = {}
    for item in formula_outputs or []:
        name = _normalized_key(item.get("output"))
        if name and name not in by_output:
            by_output[name] = item
    for rule in policy.get("formula_fields") or []:
        source = next((by_output.get(_normalized_key(alias)) for alias in rule.get("output_aliases") or [] if by_output.get(_normalized_key(alias))), None)
        if not source:
            continue
        value = _get_path(source, rule.get("source_key"))
        if value is None:
            continue
        field = _field(rule, value, date_value=source.get("latest_date"), source={"kind": "formula", "output": source.get("output")})
        projected.setdefault(field["field_id"], field)

    rules = policy.get("stock_profile_fields") or []
    calculation_dimensions = {_normalized_key(item) for item in policy.get("calculation_dimension_aliases") or []}
    for grant in grant_results or []:
        for indicator in grant.get("indicators") or []:
            matched = next((rule for rule in rules if _matches_indicator(rule, indicator)), None)
            if matched and indicator.get("latest_value") is not None:
                base_field = _field(
                    matched,
                    indicator.get("latest_value"),
                    date_value=indicator.get("latest_date"),
                    unit=indicator.get("unit"),
                    source={"kind": "grant", "grant_kind": grant.get("kind"), "indicator": indicator.get("base_id")},
                )
                projected.setdefault(base_field["field_id"], base_field)
                if matched.get("include_previous") and indicator.get("previous_value") is not None:
                    previous = _field(
                        matched,
                        indicator.get("previous_value"),
                        date_value=indicator.get("previous_date"),
                        unit=indicator.get("unit"),
                        field_id=matched["field_id"].rsplit(".", 1)[0] + ".previous",
                        column_label="上一期值",
                        source={"kind": "grant", "indicator": indicator.get("base_id")},
                    )
                    projected.setdefault(previous["field_id"], previous)
                variants = indicator.get("variants") if isinstance(indicator.get("variants"), dict) else {}
                custom = matched.get("variant_columns") if isinstance(matched.get("variant_columns"), dict) else {}
                for key, spec in custom.items():
                    suffix, variant = next(((suffix, value) for suffix, value in variants.items() if _variant_match(suffix, spec.get("aliases"))), (None, None))
                    if not isinstance(variant, dict) or variant.get("value") is None:
                        continue
                    field_id = spec.get("field_id") or matched["field_id"].rsplit(".", 1)[0] + "." + key
                    variant_field = _field(
                        matched,
                        variant.get("value"),
                        date_value=variant.get("date") or indicator.get("latest_date"),
                        unit=spec.get("unit") or indicator.get("unit"),
                        field_id=field_id,
                        row_label=spec.get("row_label") or matched.get("row_label"),
                        column_label=spec.get("column_label"),
                        source={"kind": "grant", "indicator": indicator.get("base_id"), "variant": suffix},
                    )
                    projected.setdefault(field_id, variant_field)
                variant_groups = []
                if matched.get("financial_variants"):
                    variant_groups = _financial_variant_columns()
                elif matched.get("trading_variants"):
                    variant_groups = _trading_variant_columns()
                elif matched.get("percentile_variants"):
                    variant_groups = _percentile_variant_columns()
                for key, aliases, column in variant_groups:
                    suffix, variant = next(((suffix, value) for suffix, value in variants.items() if _variant_match(suffix, aliases)), (None, None))
                    if not isinstance(variant, dict) or variant.get("value") is None:
                        continue
                    field_id = matched["field_id"].rsplit(".", 1)[0] + "." + key
                    variant_field = _field(
                        matched,
                        variant.get("value"),
                        date_value=variant.get("date") or indicator.get("latest_date"),
                        unit=indicator.get("unit"),
                        field_id=field_id,
                        column_label=column,
                        source={"kind": "grant", "indicator": indicator.get("base_id"), "variant": suffix},
                    )
                    projected.setdefault(field_id, variant_field)
                continue

            dimension = _normalized_key(indicator.get("dimension"))
            if dimension in calculation_dimensions and indicator.get("latest_value") is not None:
                label = str(indicator.get("name") or indicator.get("base_id") or "计算指标")
                field_id = "calculation.dynamic." + hashlib.sha256(
                    f"{indicator.get('dimension')}:{indicator.get('base_id')}".encode("utf-8")
                ).hexdigest()[:12]
                projected.setdefault(field_id, {
                    "field_id": field_id,
                    "section": "四、计算维度",
                    "row_label": label,
                    "column_label": "最新值",
                    "value": indicator.get("latest_value"),
                    "date": indicator.get("latest_date"),
                    "unit": indicator.get("unit"),
                    "render_tokens": _value_tokens(indicator.get("latest_value")),
                    "source": {"kind": "grant", "indicator": indicator.get("base_id")},
                })
    return list(projected.values())


def build_evidence(task_id, template_ref, formula_outputs=None, grant_results=None, warnings=None, stats=None):
    policy = get_policy(template_ref)
    if not policy:
        return None
    fields = project_fields(template_ref, formula_outputs or [], grant_results or [])
    sections = {}
    for heading in policy.get("sections") or []:
        section_fields = [field["field_id"] for field in fields if field.get("section") == heading]
        no_data_text = policy.get("message_no_data_text") if heading == "六、消息面（近30日）" else policy.get("standard_no_data_text")
        sections[heading] = {
            "has_data": bool(section_fields) or heading == "七、综合观察",
            "field_ids": section_fields,
            "no_data_text": no_data_text,
        }
    return {
        "version": EVIDENCE_VERSION,
        "task_id": str(task_id or ""),
        "template_ref": template_ref,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "fields": fields,
        "sections": sections,
        "formula_outputs": redact(formula_outputs or []),
        "grant_results": redact(grant_results or []),
        "warnings": redact(warnings or []),
        "stats": redact(stats or {}),
    }


def availability_from_evidence(evidence):
    return {
        "version": AVAILABILITY_VERSION,
        "template_ref": evidence.get("template_ref"),
        "available_template_fields": [
            {key: field.get(key) for key in ("field_id", "section", "row_label", "column_label", "date", "unit") if field.get(key) not in (None, "")}
            for field in evidence.get("fields") or []
        ],
        "sections": copy.deepcopy(evidence.get("sections") or {}),
        "warnings": copy.deepcopy(evidence.get("warnings") or []),
        "stats": copy.deepcopy(evidence.get("stats") or {}),
    }


def persist_evidence(task_id, evidence):
    if not isinstance(evidence, dict):
        return None
    path = Path(C.task_temp_path(task_id, "reply-data-evidence.json", create_parent=True))
    payload = json.dumps(evidence, ensure_ascii=False, indent=2).encode("utf-8")
    path.write_bytes(payload)
    return {
        "reply_data_evidence_file": str(path),
        "reply_data_evidence_sha256": hashlib.sha256(payload).hexdigest(),
        "reply_data_availability": availability_from_evidence(evidence),
    }


def build_from_validations(task_id, template_ref, package_validation, grant_validation, *, stats=None):
    formula_outputs = []
    warnings = []
    for package in (package_validation or {}).get("packages") or []:
        formula_outputs.extend(package.get("reply_evidence_outputs") or [])
        warnings.extend(package.get("reply_evidence_warnings") or [])
    grants = [item.get("reply_evidence") for item in (grant_validation or {}).get("grants") or [] if isinstance(item.get("reply_evidence"), dict)]
    warnings.extend((package_validation or {}).get("reply_evidence_warnings") or [])
    warnings.extend((grant_validation or {}).get("reply_evidence_warnings") or [])
    evidence = build_evidence(task_id, template_ref, formula_outputs, grants, warnings, stats)
    return persist_evidence(task_id, evidence)


def build_direct(task_id, template_ref, package_results, grant_results):
    formula_outputs = compact_direct_formula_outputs(package_results)
    grants = []
    for item in grant_results or []:
        if not isinstance(item, dict):
            continue
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        grants.append(compact_grant_result(str(result.get("kind") or "direct_grant"), result))
    evidence = build_evidence(
        task_id,
        template_ref,
        formula_outputs,
        grants,
        stats={"source": "direct_reuse", "extra_query_count": 0},
    )
    return persist_evidence(task_id, evidence)
