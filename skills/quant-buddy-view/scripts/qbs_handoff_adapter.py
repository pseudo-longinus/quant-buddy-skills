#!/usr/bin/env python3
"""Thin QBV adapter for reusable computation capsules produced by QBS.

This module does not route, render, publish, or decide page ownership.  It only
checks whether the QBS handoff safely covers the data roles QBV needs so the
existing QBV SOP can skip duplicate QBS computation or request only the delta.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from qbs_job_lifecycle import fail_job, mark_job_running


CAPSULE_SCHEMA_VERSION = "qbs_computation_capsule_v1"
FORMULA_RUNTIME_SCHEMA_VERSION = "qbs_formula_runtime_contract_v1"
_HASH_RE = re.compile(r"^(?:sha256:)?([0-9a-fA-F]{64})$")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _normalize_hash(value: Any) -> Optional[str]:
    match = _HASH_RE.fullmatch(str(value or "").strip())
    return "sha256:" + match.group(1).lower() if match else None


def _normalize_formula_runtime_contract(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("formula_runtime_contract_not_object")
    if value.get("schema_version") != FORMULA_RUNTIME_SCHEMA_VERSION:
        raise ValueError("formula_runtime_schema_unsupported")
    raw_formulas = value.get("formulas")
    if not isinstance(raw_formulas, list) or not raw_formulas:
        raise ValueError("formula_runtime_formulas_required")
    formulas = []
    left_names = set()
    for raw in raw_formulas:
        if not isinstance(raw, str) or not raw.strip() or "=" not in raw:
            raise ValueError("formula_runtime_formula_invalid")
        left_name = raw.split("=", 1)[0].strip()
        if not left_name:
            raise ValueError("formula_runtime_formula_invalid")
        formulas.append(raw)
        left_names.add(left_name)

    raw_reusable = value.get("force_reusable_array", [])
    if not isinstance(raw_reusable, list):
        raise ValueError("formula_runtime_force_reusable_invalid")
    reusable = []
    for raw in raw_reusable:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("formula_runtime_force_reusable_invalid")
        output = raw.strip()
        if output not in left_names:
            raise ValueError("formula_runtime_output_unknown")
        if output not in reusable:
            reusable.append(output)

    raw_reads = value.get("reads", [])
    if not isinstance(raw_reads, list):
        raise ValueError("formula_runtime_reads_invalid")
    reads = []
    for raw in raw_reads:
        if not isinstance(raw, dict):
            raise ValueError("formula_runtime_reads_invalid")
        output = str(raw.get("output") or "").strip()
        read_mode = str(raw.get("read_mode") or "").strip()
        if not output or output not in left_names or not read_mode:
            raise ValueError("formula_runtime_reads_invalid")
        read = {"output": output, "read_mode": read_mode}
        if "mode_params" in raw:
            if not isinstance(raw.get("mode_params"), dict):
                raise ValueError("formula_runtime_reads_invalid")
            read["mode_params"] = dict(raw["mode_params"])
        reads.append(read)

    normalized = {
        "schema_version": FORMULA_RUNTIME_SCHEMA_VERSION,
        "formulas": formulas,
        "include_description": value.get("include_description", False),
        "use_minute_data": value.get("use_minute_data", False),
        "force_reusable_array": reusable,
        "reads": reads,
    }
    if not isinstance(normalized["include_description"], bool) or not isinstance(normalized["use_minute_data"], bool):
        raise ValueError("formula_runtime_flags_invalid")
    if "begin_date" in value and value.get("begin_date") is not None:
        if isinstance(value.get("begin_date"), (dict, list, bool)):
            raise ValueError("formula_runtime_begin_date_invalid")
        normalized["begin_date"] = value.get("begin_date")
    expected = _normalize_hash(value.get("contract_fingerprint"))
    actual = _fingerprint(normalized)
    if expected is None or expected != actual:
        raise ValueError("formula_runtime_fingerprint_mismatch")
    normalized["contract_fingerprint"] = actual
    return normalized


def _unusable(reason: str, detail: Optional[str] = None) -> Dict[str, Any]:
    result = {
        "schema_version": "qbs_handoff_coverage_v1",
        "coverage": "unusable",
        "covered_roles": [],
        "missing_roles": [],
        "qbs_action": "normal",
        "reason": reason,
        "reusable_contracts": [],
        "reusable_outputs": [],
        "validated_insights": [],
        "validation_receipts": [],
    }
    if detail:
        result["detail"] = detail
    return result


def evaluate_handoff(handoff: Any, required_roles: Any = None) -> Dict[str, Any]:
    if not isinstance(handoff, dict):
        return _unusable("handoff_invalid")
    capsule = handoff.get("computation_capsule")
    if not isinstance(capsule, dict):
        return _unusable("capsule_missing")
    if capsule.get("schema_version") != CAPSULE_SCHEMA_VERSION:
        return _unusable("capsule_schema_unsupported")
    for field in ("task_id", "turn_id"):
        if str(capsule.get(field) or "").strip() != str(handoff.get(field) or "").strip():
            return _unusable("capsule_lineage_mismatch", field)

    formula_runtime_contract = None
    if capsule.get("formula_runtime_contract") is not None:
        try:
            formula_runtime_contract = _normalize_formula_runtime_contract(capsule.get("formula_runtime_contract"))
        except ValueError as exc:
            return _unusable("formula_runtime_contract_invalid", str(exc))

    intent = capsule.get("page_intent") if isinstance(capsule.get("page_intent"), dict) else {}
    raw_required = required_roles if required_roles is not None else intent.get("required_roles")
    if raw_required is None:
        raw_required = []
    if not isinstance(raw_required, list):
        return _unusable("required_roles_invalid")
    required = []
    for value in raw_required:
        role = str(value or "").strip()
        if not role:
            return _unusable("required_roles_invalid")
        if role not in required:
            required.append(role)

    contracts_by_role = {}
    contracts = capsule.get("validated_contracts")
    if not isinstance(contracts, list):
        return _unusable("validated_contracts_invalid")
    for item in contracts:
        if not isinstance(item, dict):
            return _unusable("validated_contracts_invalid")
        role = str(item.get("role") or "").strip()
        contract = item.get("contract")
        expected = _normalize_hash(item.get("contract_fingerprint"))
        if not role or role in contracts_by_role or not isinstance(contract, dict) or expected is None:
            return _unusable("validated_contracts_invalid")
        if _fingerprint(contract) != expected:
            return _unusable("contract_fingerprint_mismatch", role)
        contracts_by_role[role] = item

    outputs_by_role = {}
    outputs = capsule.get("validated_outputs")
    if not isinstance(outputs, list):
        return _unusable("validated_outputs_invalid")
    for item in outputs:
        if not isinstance(item, dict):
            return _unusable("validated_outputs_invalid")
        role = str(item.get("role") or "").strip()
        if not role or role in outputs_by_role:
            return _unusable("validated_outputs_invalid")
        artifact_file = str(item.get("artifact_file") or "").strip()
        if artifact_file or "data" in item:
            expected = _normalize_hash(item.get("data_hash"))
            if expected is None:
                return _unusable("validated_outputs_invalid")
            if artifact_file:
                path = Path(artifact_file).expanduser().resolve()
                if not path.is_file():
                    return _unusable("artifact_file_missing", role)
                if _file_hash(path) != expected:
                    return _unusable("artifact_hash_mismatch", role)
            elif _fingerprint(item.get("data")) != expected:
                return _unusable("artifact_hash_mismatch", role)
        elif isinstance(item.get("data_reference"), dict):
            reference = item["data_reference"]
            expected = _normalize_hash(item.get("reference_hash"))
            if expected is None or _fingerprint(reference) != expected:
                return _unusable("data_reference_hash_mismatch", role)
            if (
                reference.get("schema_version") != "quant_buddy_data_reference_v1"
                or reference.get("provider") != "quant_buddy"
                or reference.get("read_tool") != "readData"
                or not str(reference.get("data_id") or "").strip()
                or item.get("data_hash")
            ):
                return _unusable("data_reference_invalid", role)
        else:
            return _unusable("output_evidence_missing", role)
        outputs_by_role[role] = item

    available = [role for role in contracts_by_role if role in outputs_by_role]
    if not required:
        required = list(available)
    covered = [role for role in required if role in available]
    missing = [role for role in required if role not in available]
    if not covered:
        return {
            **_unusable("required_roles_not_covered"),
            "missing_roles": missing,
        }
    coverage = "covered" if not missing else "partial"
    materialized_reads = []
    for role in covered:
        reference = outputs_by_role[role].get("data_reference")
        if isinstance(reference, dict):
            materialized_reads.append({
                "role": role,
                "tool": "readData",
                "data_id": str(reference.get("data_id") or "").strip(),
            })
    result = {
        "schema_version": "qbs_handoff_coverage_v1",
        "coverage": coverage,
        "covered_roles": covered,
        "missing_roles": missing,
        "qbs_action": "skip" if coverage == "covered" else "delta_only",
        "materialization_action": "read_existing_data" if materialized_reads else "consume_snapshot",
        "materialized_reads": materialized_reads,
        "reason": None,
        "page_intent": intent,
        "asset_resolution": capsule.get("asset_resolution") if isinstance(capsule.get("asset_resolution"), dict) else {},
        "reusable_contracts": [contracts_by_role[role] for role in covered],
        "reusable_outputs": [outputs_by_role[role] for role in covered],
        "validated_insights": list(capsule.get("validated_insights") or []) if isinstance(capsule.get("validated_insights"), list) else [],
        "validation_receipts": list(capsule.get("validation_receipts") or []) if isinstance(capsule.get("validation_receipts"), list) else [],
    }
    if formula_runtime_contract is not None:
        result["formula_runtime_action"] = "register_exact"
        result["formula_runtime_contract"] = formula_runtime_contract
    return result


PUBLISH_RECEIPT_VERSION = "qbs_handoff_validation_receipt_v1"
LIVE_ROUTE_RECEIPT_VERSION = "live_data_route_receipt_v1"


def _load_json_file(raw_path: Any, label: str) -> tuple[Path, Dict[str, Any]]:
    path = Path(str(raw_path or "")).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"{label.upper()}_MISSING:{path}")
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label.upper()}_INVALID")
    return path, payload


def _find_data_record(value: Any, data_id: str) -> Optional[Dict[str, Any]]:
    if isinstance(value, dict):
        if str(value.get("id") or "").strip() == data_id and (
            isinstance(value.get("last_column_full"), dict)
            or isinstance(value.get("last_valid_per_asset"), dict)
        ):
            return value
        for child in value.values():
            found = _find_data_record(child, data_id)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_data_record(child, data_id)
            if found is not None:
                return found
    return None


def _normalized_rows(record: Dict[str, Any], *, label: str) -> list[Dict[str, Any]]:
    section = record.get("last_column_full")
    default_date = None
    if not isinstance(section, dict):
        section = record.get("last_valid_per_asset")
    else:
        default_date = section.get("date")
    if not isinstance(section, dict) or not isinstance(section.get("values"), list):
        raise ValueError(f"{label}_ROWS_MISSING")
    if section.get("is_truncated") is True:
        raise ValueError(f"{label}_TRUNCATED")
    rows = []
    seen = set()
    for index, item in enumerate(section["values"]):
        if not isinstance(item, dict):
            raise ValueError(f"{label}_ROW_INVALID:{index}")
        asset = str(item.get("asset") or "").strip()
        raw_value = item.get("value")
        raw_date = item.get("date", default_date)
        if not asset or asset in seen or isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            raise ValueError(f"{label}_ROW_INVALID:{index}")
        try:
            date = int(raw_date)
        except (TypeError, ValueError):
            raise ValueError(f"{label}_ROW_INVALID:{index}") from None
        value = float(raw_value)
        if not math.isfinite(value):
            raise ValueError(f"{label}_ROW_INVALID:{index}")
        seen.add(asset)
        rows.append({"asset": asset, "date": date, "value": value})
    if not rows:
        raise ValueError(f"{label}_ROWS_MISSING")
    declared = section.get("returned_rows", section.get("returned_assets"))
    valid = section.get("valid_rows", section.get("valid_assets"))
    if declared is not None and int(declared) != len(rows):
        raise ValueError(f"{label}_ROW_COUNT_MISMATCH")
    if valid is not None and int(valid) != len(rows):
        raise ValueError(f"{label}_ROW_COUNT_MISMATCH")
    return sorted(rows, key=lambda item: item["asset"])


def _rows_digest(rows: list[Dict[str, Any]]) -> str:
    normalized = [
        {"asset": row["asset"], "date": row["date"], "value": format(row["value"], ".17g")}
        for row in rows
    ]
    return _fingerprint(normalized)


def _assert_rows_match(expected: list[Dict[str, Any]], actual: list[Dict[str, Any]]) -> None:
    if len(expected) != len(actual):
        raise ValueError("PACKAGE_OUTPUT_MISMATCH:row_count")
    for left, right in zip(expected, actual):
        if left["asset"] != right["asset"] or left["date"] != right["date"]:
            raise ValueError("PACKAGE_OUTPUT_MISMATCH:identity")
        if not math.isclose(left["value"], right["value"], rel_tol=1e-10, abs_tol=1e-12):
            raise ValueError("PACKAGE_OUTPUT_MISMATCH:value")


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_publish_evidence(
    *,
    handoff_file: Any,
    materialized_file: Any,
    package_contract_file: Any,
    package_query_file: Any,
    package_manifest_file: Any,
    role: Any,
    output_dir: Any = None,
) -> Dict[str, Any]:
    """Bind one covered QBS role to an already-registered live package without recomputing it."""

    handoff_path, handoff = _load_json_file(handoff_file, "handoff")
    materialized_path, materialized = _load_json_file(materialized_file, "materialized")
    contract_path, package_contract = _load_json_file(package_contract_file, "package_contract")
    query_path, package_query = _load_json_file(package_query_file, "package_query")
    manifest_path, package_manifest = _load_json_file(package_manifest_file, "package_manifest")
    role_name = str(role or "").strip()
    if not role_name:
        raise ValueError("ROLE_REQUIRED")

    coverage = evaluate_handoff(handoff, [role_name])
    if coverage.get("coverage") != "covered" or role_name not in coverage.get("covered_roles", []):
        raise ValueError(str(coverage.get("reason") or "HANDOFF_ROLE_NOT_COVERED"))
    contract_entry = next(item for item in coverage["reusable_contracts"] if item.get("role") == role_name)
    output_entry = next(item for item in coverage["reusable_outputs"] if item.get("role") == role_name)
    if contract_entry.get("kind") != "quant_buddy_materialized_data":
        raise ValueError("HANDOFF_CONTRACT_KIND_UNSUPPORTED")
    reference = output_entry.get("data_reference")
    if not isinstance(reference, dict):
        raise ValueError("HANDOFF_DATA_REFERENCE_MISSING")
    data_id = str(reference.get("data_id") or "").strip()
    output_name = str(reference.get("index_title") or "").strip()
    formula = str(reference.get("formula") or "").strip()
    if not data_id or not output_name or not formula:
        raise ValueError("HANDOFF_DATA_REFERENCE_INCOMPLETE")

    task_id = str(handoff.get("task_id") or "").strip()
    turn_id = str(handoff.get("turn_id") or "").strip()
    materialized_task_id = str(materialized.get("task_id") or "").strip()
    if materialized_task_id and materialized_task_id != task_id:
        raise ValueError("MATERIALIZED_TASK_MISMATCH")
    materialized_record = _find_data_record(materialized, data_id)
    if materialized_record is None:
        raise ValueError("MATERIALIZED_DATA_ID_MISSING")
    materialized_rows = _normalized_rows(materialized_record, label="MATERIALIZED")
    expected_row_count = int(output_entry.get("row_count") or 0)
    if expected_row_count <= 0 or len(materialized_rows) != expected_row_count:
        raise ValueError("MATERIALIZED_ROW_COUNT_MISMATCH")

    if str(package_contract.get("task_id") or "").strip() != task_id:
        raise ValueError("PACKAGE_TASK_MISMATCH")
    formulas = package_contract.get("formulas")
    reads = package_contract.get("reads")
    if not isinstance(formulas, list) or formula not in formulas:
        raise ValueError("PACKAGE_FORMULA_MISMATCH")
    if not isinstance(reads, list) or not any(
        isinstance(item, dict) and str(item.get("output") or "").strip() == output_name
        for item in reads
    ):
        raise ValueError("PACKAGE_READ_MISMATCH")

    package_id = str(package_manifest.get("package_id") or "").strip()
    signature = str(package_manifest.get("signature") or "").strip()
    manifest_outputs = package_manifest.get("outputs")
    if not package_id or not signature or not isinstance(manifest_outputs, list) or not any(
        isinstance(item, dict) and str(item.get("output") or "").strip() == output_name
        for item in manifest_outputs
    ):
        raise ValueError("PACKAGE_MANIFEST_INVALID")
    if package_query.get("code") not in (0, None) or package_query.get("success") is not True:
        raise ValueError("PACKAGE_QUERY_FAILED")
    if str(package_query.get("package_id") or "").strip() != package_id:
        raise ValueError("PACKAGE_QUERY_ID_MISMATCH")
    output_payload = (package_query.get("outputs") or {}).get(output_name)
    if not isinstance(output_payload, dict) or output_payload.get("error") not in (None, ""):
        raise ValueError("PACKAGE_OUTPUT_MISSING")
    live_record = output_payload.get("data")
    if not isinstance(live_record, dict):
        raise ValueError("PACKAGE_OUTPUT_MISSING")
    live_rows = _normalized_rows(live_record, label="PACKAGE")
    _assert_rows_match(materialized_rows, live_rows)
    done = package_query.get("done") if isinstance(package_query.get("done"), dict) else {}
    summary = done.get("summary") if isinstance(done.get("summary"), dict) else {}
    if done.get("code") not in (0, None) or int(summary.get("failed") or 0) != 0:
        raise ValueError("PACKAGE_QUERY_FAILED")

    evidence_paths = {
        "handoff": handoff_path,
        "materialized": materialized_path,
        "package_contract": contract_path,
        "package_query": query_path,
        "package_manifest": manifest_path,
    }
    evidence_files = {
        name: {"file": str(path), "sha256": _file_hash(path).split(":", 1)[1]}
        for name, path in evidence_paths.items()
    }
    contract_fingerprint = str(contract_entry.get("contract_fingerprint") or "")
    reference_hash = str(output_entry.get("reference_hash") or "")
    package_contract_fingerprint = _fingerprint({
        "begin_date": package_contract.get("begin_date"),
        "formulas": formulas,
        "reads": reads,
    })
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    receipt = {
        "schema": PUBLISH_RECEIPT_VERSION,
        "version": PUBLISH_RECEIPT_VERSION,
        "task_id": task_id,
        "turn_id": turn_id,
        "source_skill_id": handoff.get("source_skill_id"),
        "source_skill_id_status": handoff.get("source_skill_id_status"),
        "source_skill_name": handoff.get("source_skill_name"),
        "source_skill_version": handoff.get("source_skill_version"),
        "role": role_name,
        "kind": "handoff_materialized",
        "status": "completed",
        "success": True,
        "coverage": "covered",
        "contract_fingerprint": contract_fingerprint,
        "reference_hash": reference_hash,
        "row_count": len(materialized_rows),
        "rows_sha256": _rows_digest(materialized_rows),
        "package_contract_fingerprint": package_contract_fingerprint,
        "package_id": package_id,
        "package_output": output_name,
        "package_data_id": str(output_payload.get("data_id") or live_record.get("id") or "").strip(),
        "package_signature_sha256": hashlib.sha256(signature.encode("utf-8")).hexdigest(),
        "evidence_files": evidence_files,
        "created_at": created_at,
    }
    output_root = Path(output_dir).expanduser().resolve() if output_dir else Path(__file__).resolve().parents[1] / "output" / "qbs_handoff_validation_receipts"
    digest = hashlib.sha256(f"{task_id}:{turn_id}:{role_name}:{contract_fingerprint}:{package_id}".encode("utf-8")).hexdigest()
    receipt_path = output_root / f"{digest}.handoff-receipt.json"
    route_path = output_root / f"{digest}.route-receipt.json"
    _write_json(receipt_path, receipt)
    route = {
        "schema": LIVE_ROUTE_RECEIPT_VERSION,
        "version": LIVE_ROUTE_RECEIPT_VERSION,
        "task_id": task_id,
        "turn_id": turn_id,
        "asset": "",
        "status": "live",
        "required_roles": [role_name],
        "attempted_roles": [role_name],
        "attempts": [{
            "role": role_name,
            "route": "qbs_handoff_materialized",
            "status": "success",
            "covered_fields": [output_name],
        }],
        "selected_routes": [{
            "role": role_name,
            "kind": "handoff_materialized",
            "receipt_file": str(receipt_path),
            "contract_fingerprint": contract_fingerprint,
            "package_id": package_id,
            "output": output_name,
        }],
        "required_roles_complete": True,
        "static_fallback_allowed": False,
        "created_at": created_at,
    }
    _write_json(route_path, route)
    return {
        "code": 0,
        "success": True,
        "task_id": task_id,
        "turn_id": turn_id,
        "role": role_name,
        "package_id": package_id,
        "row_count": len(materialized_rows),
        "handoff_validation_receipt_file": str(receipt_path),
        "route_receipt_file": str(route_path),
    }


def _read_params(args: list[str]) -> Dict[str, Any]:
    if not args:
        return {}
    token = args[0]
    if token.startswith("@"):
        return json.loads(Path(token[1:]).read_text(encoding="utf-8-sig"))
    return json.loads(token)


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        command = "evaluate"
        if argv and argv[0] in {"evaluate", "validate-publish", "fail-job"}:
            command = argv.pop(0)
        params = _read_params(argv)
        if command == "validate-publish":
            result = build_publish_evidence(**params)
        elif command == "fail-job":
            result = {
                "code": 0,
                "job_lifecycle": fail_job(
                    qbv_job_id=params.get("qbv_job_id"),
                    task_id=params.get("task_id"),
                    turn_id=params.get("turn_id"),
                    job_file=params.get("qbv_job_file") or params.get("job_file"),
                    job_dir=params.get("qbv_job_dir") or params.get("job_dir"),
                    failure_code=params.get("failure_code"),
                    retryable=bool(params.get("retryable", False)),
                ),
            }
            if not result["job_lifecycle"].get("updated") and result["job_lifecycle"].get("reason") not in {"already_failed", "already_completed"}:
                result["code"] = 1
        else:
            handoff = params.get("handoff")
            if handoff is None and params.get("handoff_file"):
                handoff = json.loads(Path(params["handoff_file"]).read_text(encoding="utf-8-sig"))
            if handoff is None:
                handoff = params
            result = {"code": 0, **evaluate_handoff(handoff, params.get("required_roles"))}
            result["job_lifecycle"] = mark_job_running(
                qbv_job_id=params.get("qbv_job_id"),
                task_id=handoff.get("task_id") if isinstance(handoff, dict) else None,
                turn_id=handoff.get("turn_id") if isinstance(handoff, dict) else None,
                job_file=params.get("qbv_job_file") or params.get("job_file"),
                job_dir=params.get("qbv_job_dir") or params.get("job_dir"),
                target_skill_id=params.get("target_skill_id"),
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("code") in (0, None) else 1
    except (OSError, json.JSONDecodeError, TypeError, ValueError, TimeoutError) as exc:
        print(json.dumps({"code": 1, "error": "HANDOFF_ADAPTER_FAILED", "message": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
