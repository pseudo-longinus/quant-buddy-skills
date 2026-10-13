"""Materialize QBS handoff outputs as immutable QBV snapshot evidence.

The bridge never trusts a model-authored table.  Every output is read from the
data_id bound by QBS, row-count/hash checked, then captured by the existing
verified-snapshot contract before it can enter an execution plan.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import common as C
import execution_plan as EP
import qbs_handoff_adapter as QHA
import verified_snapshot as VS

VERSION = "qbs_handoff_snapshot_bundle_v1"


def _load_file(raw_path: Any, label: str) -> Dict[str, Any]:
    if not raw_path:
        raise EP.PlanError("HANDOFF_FILE_REQUIRED", f"缺少{label}")
    try:
        payload = json.loads(Path(str(raw_path)).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise EP.PlanError("HANDOFF_FILE_INVALID", f"{label}不可读取") from exc
    if not isinstance(payload, dict):
        raise EP.PlanError("HANDOFF_FILE_INVALID", f"{label}必须是对象")
    return payload


def _read_record_from_materialized(materialized: Dict[str, Any], data_id: str) -> Optional[Dict[str, Any]]:
    return QHA._find_data_record(materialized, data_id)


def _default_reader(task_id: str, data_id: str) -> Dict[str, Any]:
    """Read the complete common-date column; sparse latest-day summaries are rejected."""
    import formula_snapshot as FS
    import reply_data_evidence as RDE

    params = {
        "mode": "last_column_full",
        "task_id": task_id,
        "user_query": "物化QBS Handoff已验证研究快照",
        "ids": [data_id],
    }
    payload = FS.read_qbs(task_id, params)
    items = [item for item in RDE.extract_read_data_items(payload)
             if str(item.get("id") or item.get("data_id") or item.get("indexinfo_id") or "").strip() == data_id]
    if len(items) != 1:
        raise EP.PlanError("HANDOFF_DATA_ID_MISSING", "QBS读取结果与Handoff data_id不一致", data_id=data_id)
    record = items[0]
    if not isinstance(record.get("last_column_full"), dict):
        raise EP.PlanError("HANDOFF_COMMON_DATE_REQUIRED", "Handoff快照必须读取last_column_full共同完整截面")
    return record


def _normalized_reference_hash(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text[7:] if text.startswith("sha256:") else text


def build_bundle(
    *,
    handoff: Optional[Dict[str, Any]] = None,
    handoff_file: Any = None,
    materialized: Optional[Dict[str, Any]] = None,
    materialized_file: Any = None,
    required_roles: Any = None,
    reader: Optional[Callable[[str, str], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if handoff is None and handoff_file is not None:
        handoff = _load_file(handoff_file, "Handoff")
    if not isinstance(handoff, dict) or handoff.get("schema_version") != "qbs_qbv_handoff_v1":
        raise EP.PlanError("HANDOFF_SCHEMA_INVALID", "需要qbs_qbv_handoff_v1")
    if materialized is None and materialized_file is not None:
        materialized = _load_file(materialized_file, "物化数据")
    task_id = str(handoff.get("task_id") or "").strip()
    turn_id = str(handoff.get("turn_id") or "").strip()
    if not task_id or not turn_id:
        raise EP.PlanError("HANDOFF_IDENTITY_REQUIRED", "Handoff缺少task_id或turn_id")

    requested = [str(role).strip() for role in (required_roles or []) if str(role).strip()]
    coverage = QHA.evaluate_handoff(handoff, requested or None)
    covered = [str(role) for role in coverage.get("covered_roles") or []]
    missing = [str(role) for role in coverage.get("missing_roles") or []]
    if not covered:
        reason = coverage.get("reason") or "required_roles_not_covered"
        if reason in {"capsule_missing", "capsule_schema_unsupported", "capsule_lineage_mismatch"}:
            return {
                "version": VERSION, "task_id": task_id, "turn_id": turn_id,
                "required_roles": requested, "covered_roles": [], "missing_roles": missing,
                "snapshot_roles": [], "research_status": "unavailable",
                "delivery_kind": "methodology", "generated_at": datetime.now(timezone.utc).isoformat(),
                "coverage_reason": reason, "legacy_capsule": True,
            }
        if reason == "data_reference_hash_mismatch":
            raise EP.PlanError("HANDOFF_REFERENCE_HASH_MISMATCH", "Handoff数据引用hash不一致",
                               missing_roles=missing)
        if reason != "required_roles_not_covered":
            raise EP.PlanError("HANDOFF_EVIDENCE_INVALID", "Handoff证据校验失败，不能降级为方法页",
                               coverage_reason=reason, missing_roles=missing)
        return {
            "version": VERSION, "task_id": task_id, "turn_id": turn_id,
            "required_roles": requested, "covered_roles": [], "missing_roles": missing,
            "snapshot_roles": [], "research_status": "unavailable",
            "delivery_kind": "methodology", "generated_at": datetime.now(timezone.utc).isoformat(),
            "coverage_reason": reason,
        }

    outputs = {str(item.get("role") or ""): item for item in handoff.get("computation_capsule", {}).get("validated_outputs") or []}
    snapshot_roles = []
    read_record = reader or _default_reader
    for role_name in covered:
        entry = outputs.get(role_name)
        if not isinstance(entry, dict):
            raise EP.PlanError("HANDOFF_OUTPUT_MISSING", "coverage与validated_outputs不一致", role=role_name)
        reference = entry.get("data_reference")
        if not isinstance(reference, dict) or str(reference.get("read_tool") or "") != "readData":
            raise EP.PlanError("HANDOFF_DATA_REFERENCE_INVALID", "Handoff数据引用无效", role=role_name)
        data_id = str(reference.get("data_id") or "").strip()
        if not data_id:
            raise EP.PlanError("HANDOFF_DATA_REFERENCE_INVALID", "Handoff缺少data_id", role=role_name)
        record = materialized and _read_record_from_materialized(materialized, data_id)
        if record is None and materialized is not None:
            raise EP.PlanError("HANDOFF_DATA_ID_MISSING", "物化结果缺少Handoff data_id", role=role_name, data_id=data_id)
        if record is None:
            record = read_record(task_id, data_id)
        try:
            rows = QHA._normalized_rows(record, label="HANDOFF")
        except (ValueError, TypeError, KeyError) as exc:
            raise EP.PlanError("HANDOFF_ROWS_INVALID", str(exc), role=role_name, data_id=data_id) from exc
        expected_rows = int(entry.get("row_count") or 0)
        if expected_rows <= 0 or len(rows) != expected_rows:
            raise EP.PlanError("HANDOFF_ROW_COUNT_MISMATCH", "Handoff行数与验证结果不一致",
                               role=role_name, expected=expected_rows, actual=len(rows))
        expected_reference_hash = _normalized_reference_hash(entry.get("reference_hash"))
        actual_reference_hash = _normalized_reference_hash(QHA._fingerprint(reference))
        rows_hash = QHA._rows_digest(rows).split(":", 1)[1]
        if not expected_reference_hash or actual_reference_hash != expected_reference_hash:
            raise EP.PlanError("HANDOFF_REFERENCE_HASH_MISMATCH", "Handoff数据引用hash不一致", role=role_name)
        contract = {
            "schema_version": "qbs_handoff_snapshot_role_v1",
            "role": role_name,
            "data_id": data_id,
            "reference_hash": str(entry.get("reference_hash") or ""),
            "rows_sha256": "sha256:" + rows_hash,
            "row_count": len(rows),
            "field_mapping": entry.get("field_mapping") or {},
            "read_mode": "last_column_full",
            "reads": [{"output": role_name, "read_mode": "last_column_full"}],
        }
        saved = VS.capture(task_id, contract,
                           {"code": 0, "success": True, "outputs": {role_name: {"data": record}}},
                           resource="package")
        snapshot_roles.append({"role_id": role_name, "required_outputs": [role_name], **saved})

    handoff_status = str(handoff.get("research_status") or "").strip()
    handoff_kind = str(handoff.get("delivery_kind") or "").strip()
    if handoff_status in {"partial", "unavailable"} and handoff_kind in {"partial_research", "methodology"}:
        research_status, delivery_kind = handoff_status, handoff_kind
    else:
        # A covered role list is not research-completion evidence.  The original
        # contract/research_checks must separately prove a complete result.
        research_status, delivery_kind = ("partial", "partial_research")
    bundle = {
        "version": VERSION,
        "task_id": task_id,
        "turn_id": turn_id,
        "required_roles": requested or covered,
        "covered_roles": covered,
        "missing_roles": missing,
        "snapshot_roles": snapshot_roles,
        "research_status": research_status,
        "delivery_kind": delivery_kind,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    EP._no_secrets(bundle)
    bundle_path = C.task_temp_path(task_id, "receipts/handoff-snapshot-bundle.json", create_parent=True)
    EP.atomic_json(bundle_path, bundle)
    bundle["bundle_file"] = str(bundle_path)
    bundle["bundle_sha256"] = __import__("hashlib").sha256(bundle_path.read_bytes()).hexdigest()
    return {"code": 0, "success": True, **bundle}


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
        if not argv or argv[0] not in {"build"}:
            raise EP.PlanError("HANDOFF_BRIDGE_COMMAND_INVALID", "使用 build @params.json")
        command = argv.pop(0)
        params = _read_params(argv)
        if command != "build":
            raise EP.PlanError("HANDOFF_BRIDGE_COMMAND_INVALID", "未知命令")
        result = build_bundle(**params)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("code", 0) == 0 else 1
    except EP.PlanError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False, indent=2))
        return 1
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"code": 1, "error": "HANDOFF_SNAPSHOT_BRIDGE_FAILED", "message": str(exc)},
                         ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
