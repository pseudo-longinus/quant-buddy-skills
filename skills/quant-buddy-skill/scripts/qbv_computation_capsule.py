#!/usr/bin/env python3
"""Build and validate reusable QBS computation capsules for QBV handoff.

The capsule carries both a verified result snapshot and the reproducible query or
formula contract that produced it.  It is deliberately page-implementation
agnostic: QBV still owns routing, ownership, rendering, publishing, and public
acceptance.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


SCHEMA_VERSION = "qbs_computation_capsule_v1"
FORMULA_RUNTIME_SCHEMA_VERSION = "qbs_formula_runtime_contract_v1"
_HASH_RE = re.compile(r"^(?:sha256:)?([0-9a-fA-F]{64})$")


class ComputationCapsuleError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _text(name: str, value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        raise ComputationCapsuleError(f"{name.upper()}_REQUIRED", f"{name} 不能为空")
    return text


def _object(name: str, value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ComputationCapsuleError(f"INVALID_{name.upper()}", f"{name} 必须是 JSON object")
    return dict(value)


def _list(name: str, value: Any) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ComputationCapsuleError(f"INVALID_{name.upper()}", f"{name} 必须是 JSON array")
    return list(value)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint_contract(contract: Dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(contract).encode("utf-8")).hexdigest()


def _formula_left_names(formulas: list[str]) -> set[str]:
    names = set()
    for formula in formulas:
        if "=" not in formula:
            raise ComputationCapsuleError("INVALID_FORMULA_RUNTIME_CONTRACT", "formula 必须包含输出变量左值")
        name = formula.split("=", 1)[0].strip()
        if not name:
            raise ComputationCapsuleError("INVALID_FORMULA_RUNTIME_CONTRACT", "formula 输出变量不能为空")
        names.add(name)
    return names


def _normalize_formula_runtime_contract(value: Any) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    item = _object("formula_runtime_contract", value)
    if item.get("schema_version") != FORMULA_RUNTIME_SCHEMA_VERSION:
        raise ComputationCapsuleError(
            "FORMULA_RUNTIME_SCHEMA_UNSUPPORTED",
            f"仅支持 {FORMULA_RUNTIME_SCHEMA_VERSION}",
        )
    raw_formulas = _list("formula_runtime_contract.formulas", item.get("formulas"))
    if not raw_formulas:
        raise ComputationCapsuleError("FORMULA_RUNTIME_FORMULAS_REQUIRED", "formula runtime contract 至少需要一条公式")
    formulas = []
    for raw in raw_formulas:
        if not isinstance(raw, str) or not raw.strip():
            raise ComputationCapsuleError("INVALID_FORMULA_RUNTIME_FORMULA", "formulas 必须是非空字符串数组")
        formulas.append(raw)
    left_names = _formula_left_names(formulas)

    reusable = []
    for raw in _list("formula_runtime_contract.force_reusable_array", item.get("force_reusable_array")):
        if not isinstance(raw, str) or not raw.strip():
            raise ComputationCapsuleError("INVALID_FORCE_REUSABLE_ARRAY", "force_reusable_array 必须是非空字符串数组")
        output = raw.strip()
        if output not in left_names:
            raise ComputationCapsuleError("FORMULA_RUNTIME_OUTPUT_UNKNOWN", f"force_reusable_array 输出不存在于公式左值: {output}")
        if output not in reusable:
            reusable.append(output)

    reads = []
    for index, raw in enumerate(_list("formula_runtime_contract.reads", item.get("reads"))):
        read = _object(f"formula_runtime_contract.reads[{index}]", raw)
        output = _text("formula_runtime_contract.reads.output", read.get("output"))
        if output not in left_names:
            raise ComputationCapsuleError("FORMULA_RUNTIME_OUTPUT_UNKNOWN", f"reads 输出不存在于公式左值: {output}")
        normalized_read = {
            "output": output,
            "read_mode": _text("formula_runtime_contract.reads.read_mode", read.get("read_mode")),
        }
        if "mode_params" in read:
            normalized_read["mode_params"] = _object("formula_runtime_contract.reads.mode_params", read.get("mode_params"))
        reads.append(normalized_read)

    normalized = {
        "schema_version": FORMULA_RUNTIME_SCHEMA_VERSION,
        "formulas": formulas,
        "include_description": item.get("include_description", False),
        "use_minute_data": item.get("use_minute_data", False),
        "force_reusable_array": reusable,
        "reads": reads,
    }
    for field in ("include_description", "use_minute_data"):
        if not isinstance(normalized[field], bool):
            raise ComputationCapsuleError("INVALID_FORMULA_RUNTIME_FLAG", f"{field} 必须是 boolean")
    if "begin_date" in item and item.get("begin_date") is not None:
        if isinstance(item.get("begin_date"), (dict, list, bool)):
            raise ComputationCapsuleError("INVALID_FORMULA_RUNTIME_BEGIN_DATE", "begin_date 必须是日期字符串或整数")
        normalized["begin_date"] = item.get("begin_date")
    actual = fingerprint_contract(normalized)
    supplied = _normalized_hash("formula_runtime_contract.contract_fingerprint", item.get("contract_fingerprint"))
    if supplied and supplied != actual:
        raise ComputationCapsuleError("FORMULA_RUNTIME_FINGERPRINT_MISMATCH", "formula runtime contract fingerprint 不一致")
    normalized["contract_fingerprint"] = actual
    return normalized


def _runtime_contract_from_receipts(receipts: list[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    contracts = []
    seen = set()
    for receipt in receipts:
        if not isinstance(receipt, dict) or receipt.get("runtime_contract") is None:
            continue
        contract = _normalize_formula_runtime_contract(receipt.get("runtime_contract"))
        fingerprint = contract["contract_fingerprint"]
        if fingerprint not in seen:
            contracts.append(contract)
            seen.add(fingerprint)
    if len(contracts) > 1:
        raise ComputationCapsuleError(
            "MULTIPLE_FORMULA_RUNTIME_CONTRACTS",
            "存在多个不同的公式运行合同，请显式提供本活页需要的 formula_runtime_contract",
        )
    return contracts[0] if contracts else None


def _formula_map(runtime_contract: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not isinstance(runtime_contract, dict):
        return {}
    result = {}
    for formula in runtime_contract.get("formulas", []):
        if not isinstance(formula, str) or "=" not in formula:
            continue
        output = formula.split("=", 1)[0].strip()
        if output:
            result[output] = formula
    return result


def _receipt_data_bindings(
    receipts: list[Dict[str, Any]],
    runtime_contract: Optional[Dict[str, Any]],
) -> Dict[str, Dict[str, str]]:
    formulas_by_output = _formula_map(runtime_contract)
    bindings: Dict[str, Dict[str, str]] = {}
    for receipt in receipts:
        if not isinstance(receipt, dict):
            continue
        outputs = receipt.get("outputs")
        if not isinstance(outputs, list):
            continue
        for item in outputs:
            if not isinstance(item, dict):
                continue
            data_id = _compact_optional(item.get("data_id") or item.get("indexinfo_id"))
            if not data_id:
                continue
            index_title = _compact_optional(item.get("index_title") or item.get("leftName"))
            expression_id = _compact_optional(item.get("expression_id"))
            if index_title is None and expression_id in formulas_by_output:
                index_title = expression_id
            if index_title is None or index_title not in formulas_by_output:
                continue
            formula = formulas_by_output[index_title]
            supplied_formula = _compact_optional(item.get("formula"))
            if supplied_formula is not None and supplied_formula != formula:
                raise ComputationCapsuleError(
                    "RECEIPT_FORMULA_BINDING_MISMATCH",
                    f"validation receipt data_id={data_id} 的公式与 runtime contract 不一致",
                )
            binding = {"index_title": index_title, "formula": formula}
            existing = bindings.get(data_id)
            if existing is not None and existing != binding:
                raise ComputationCapsuleError(
                    "AMBIGUOUS_DATA_REFERENCE_BINDING",
                    f"data_id={data_id} 命中多个不同公式输出，禁止猜测",
                )
            bindings[data_id] = binding
    return bindings


def _bind_materialized_outputs(
    outputs: list[Dict[str, Any]],
    receipts: list[Dict[str, Any]],
    runtime_contract: Optional[Dict[str, Any]],
) -> None:
    if not isinstance(runtime_contract, dict):
        return
    formulas_by_output = _formula_map(runtime_contract)
    readable_outputs = {
        str(item.get("output") or "").strip()
        for item in runtime_contract.get("reads", [])
        if isinstance(item, dict) and str(item.get("output") or "").strip()
    }
    receipt_bindings = _receipt_data_bindings(receipts, runtime_contract)
    for output in outputs:
        reference = output.get("data_reference")
        if not isinstance(reference, dict):
            continue
        data_id = _compact_optional(reference.get("data_id"))
        if not data_id:
            continue
        binding = receipt_bindings.get(data_id, {})
        index_title = _compact_optional(reference.get("index_title")) or binding.get("index_title")
        formula = _compact_optional(reference.get("formula")) or binding.get("formula")
        if not index_title or not formula:
            raise ComputationCapsuleError(
                "DATA_REFERENCE_BINDING_REQUIRED",
                f"data_id={data_id} 缺少由 validation receipt/runtime contract 证明的 index_title 与 formula 绑定",
            )
        expected_formula = formulas_by_output.get(index_title)
        if expected_formula != formula:
            raise ComputationCapsuleError(
                "DATA_REFERENCE_FORMULA_MISMATCH",
                f"data_id={data_id} 的 formula 与 runtime contract 不一致",
            )
        if index_title not in readable_outputs:
            raise ComputationCapsuleError(
                "DATA_REFERENCE_READ_MISSING",
                f"data_id={data_id} 对应输出 {index_title} 不在 runtime reads 中",
            )
        reference["index_title"] = index_title
        reference["formula"] = formula
        output["reference_hash"] = hash_inline_data(reference)


def hash_file(path: Any) -> str:
    target = Path(path).expanduser().resolve()
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def hash_inline_data(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _normalized_hash(name: str, value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    match = _HASH_RE.fullmatch(text)
    if not match:
        raise ComputationCapsuleError(f"INVALID_{name.upper()}", f"{name} 必须是 SHA256")
    return "sha256:" + match.group(1).lower()


def _normalize_roles(values: Any, name: str = "required_roles") -> list[str]:
    roles = _list(name, values)
    normalized = []
    for raw in roles:
        role = _text("role", raw)
        if role not in normalized:
            normalized.append(role)
    return normalized


def _normalize_contracts(values: Any) -> list[Dict[str, Any]]:
    contracts = []
    seen = set()
    for index, raw in enumerate(_list("validated_contracts", values)):
        item = _object(f"validated_contracts[{index}]", raw)
        role = _text("role", item.get("role"))
        if role in seen:
            raise ComputationCapsuleError("DUPLICATE_CONTRACT_ROLE", f"validated_contracts role 重复: {role}")
        kind = _text("kind", item.get("kind"))
        contract = _object("contract", item.get("contract"))
        actual = fingerprint_contract(contract)
        supplied = _normalized_hash("contract_fingerprint", item.get("contract_fingerprint"))
        if supplied and supplied != actual:
            raise ComputationCapsuleError("CONTRACT_FINGERPRINT_MISMATCH", f"{role} contract fingerprint 不一致")
        normalized = dict(item)
        normalized.update({"role": role, "kind": kind, "contract": contract, "contract_fingerprint": actual})
        contracts.append(normalized)
        seen.add(role)
    return contracts


def _normalize_outputs(values: Any, verify_artifacts: bool) -> list[Dict[str, Any]]:
    outputs = []
    seen = set()
    for index, raw in enumerate(_list("validated_outputs", values)):
        item = _object(f"validated_outputs[{index}]", raw)
        role = _text("role", item.get("role"))
        if role in seen:
            raise ComputationCapsuleError("DUPLICATE_OUTPUT_ROLE", f"validated_outputs role 重复: {role}")
        artifact_text = str(item.get("artifact_file") or "").strip()
        has_inline = "data" in item
        has_reference = isinstance(item.get("data_reference"), dict)
        evidence_count = int(bool(artifact_text)) + int(has_inline) + int(has_reference)
        if evidence_count != 1:
            raise ComputationCapsuleError(
                "OUTPUT_EVIDENCE_REQUIRED",
                f"validated_outputs[{index}] 必须且只能包含 artifact_file、data 或 data_reference 之一",
            )
        normalized = dict(item)
        if has_reference:
            reference = _object("data_reference", item.get("data_reference"))
            reference["schema_version"] = _text("data_reference.schema_version", reference.get("schema_version"))
            reference["provider"] = _text("data_reference.provider", reference.get("provider"))
            reference["data_id"] = _text("data_reference.data_id", reference.get("data_id"))
            reference["read_tool"] = _text("data_reference.read_tool", reference.get("read_tool"))
            if reference["schema_version"] != "quant_buddy_data_reference_v1" or reference["provider"] != "quant_buddy" or reference["read_tool"] != "readData":
                raise ComputationCapsuleError("INVALID_DATA_REFERENCE", f"{role} data_reference 不是受支持的 Quant Buddy 已物化数据引用")
            if item.get("data_hash"):
                raise ComputationCapsuleError("DATA_REFERENCE_MUST_NOT_USE_DATA_HASH", f"{role} 数据引用不得冒充完整数据快照 hash")
            actual_reference_hash = hash_inline_data(reference)
            supplied_reference_hash = _normalized_hash("reference_hash", item.get("reference_hash"))
            if supplied_reference_hash and supplied_reference_hash != actual_reference_hash:
                raise ComputationCapsuleError("DATA_REFERENCE_HASH_MISMATCH", f"{role} data reference hash 不一致")
            normalized["evidence_kind"] = "quant_buddy_data_id"
            normalized["data_reference"] = reference
            normalized["reference_hash"] = actual_reference_hash
            normalized.pop("data_hash", None)
        else:
            if artifact_text:
                artifact = Path(artifact_text).expanduser().resolve()
                if verify_artifacts and not artifact.is_file():
                    raise ComputationCapsuleError("ARTIFACT_FILE_MISSING", f"artifact_file 不存在: {artifact}")
                actual_hash = hash_file(artifact) if verify_artifacts else None
                normalized["artifact_file"] = str(artifact)
            else:
                actual_hash = hash_inline_data(item.get("data"))
            supplied_hash = _normalized_hash("data_hash", item.get("data_hash"))
            if actual_hash and supplied_hash and supplied_hash != actual_hash:
                raise ComputationCapsuleError("ARTIFACT_HASH_MISMATCH", f"{role} artifact hash 不一致")
            if actual_hash:
                normalized["data_hash"] = actual_hash
            elif supplied_hash:
                normalized["data_hash"] = supplied_hash
            else:
                raise ComputationCapsuleError("DATA_HASH_REQUIRED", f"{role} 缺少可验证 data_hash")
        if "row_count" in normalized:
            try:
                row_count = int(normalized["row_count"])
            except (TypeError, ValueError) as exc:
                raise ComputationCapsuleError("INVALID_ROW_COUNT", f"{role} row_count 必须是非负整数") from exc
            if row_count < 0:
                raise ComputationCapsuleError("INVALID_ROW_COUNT", f"{role} row_count 必须是非负整数")
            normalized["row_count"] = row_count
        mapping = normalized.get("field_mapping", {})
        if not isinstance(mapping, dict):
            raise ComputationCapsuleError("INVALID_FIELD_MAPPING", f"{role} field_mapping 必须是 JSON object")
        normalized["field_mapping"] = dict(mapping)
        outputs.append(normalized)
        seen.add(role)
    return outputs



def _compact_optional(value: Any) -> Optional[str]:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text or None


def _validate_receipt_lineage(
    receipt: Dict[str, Any],
    *,
    expected_task_id: str,
    expected_turn_id: str,
    expected_user_query: str,
) -> None:
    lineage = receipt.get("lineage") if isinstance(receipt.get("lineage"), dict) else {}
    expected = {
        "task_id": expected_task_id,
        "turn_id": expected_turn_id,
        "user_query": expected_user_query,
    }
    for field, expected_value in expected.items():
        actual_values = []
        if field in receipt:
            actual_values.append(receipt.get(field))
        if field in lineage:
            actual_values.append(lineage.get(field))
        for raw in actual_values:
            actual = _compact_optional(raw)
            if actual is not None and actual != expected_value:
                raise ComputationCapsuleError(
                    "RECEIPT_LINEAGE_MISMATCH",
                    f"validation receipt {field} 与当前 QBS Turn 不一致",
                )


def _normalize_validation_receipts(
    values: Any,
    *,
    expected_task_id: str,
    expected_turn_id: str,
    expected_user_query: str,
    receipt_file: Optional[Path] = None,
) -> list[Dict[str, Any]]:
    receipts = []
    for index, raw in enumerate(_list("validation_receipts", values)):
        # Agent-authored prepare-page JSON naturally represents an existing
        # receipt as its file path. Accept that compact top-level form in
        # addition to an inline receipt object, while refusing nested file
        # references inside a receipt file to keep loading finite and explicit.
        if isinstance(raw, (str, Path)):
            if receipt_file is not None:
                raise ComputationCapsuleError(
                    f"INVALID_VALIDATION_RECEIPTS[{index}]",
                    "validation receipt 文件内部不得再引用其它 receipt 文件",
                )
            receipts.extend(_load_validation_receipt_file(
                raw,
                expected_task_id=expected_task_id,
                expected_turn_id=expected_turn_id,
                expected_user_query=expected_user_query,
            ))
            continue
        item = _object(f"validation_receipts[{index}]", raw)
        _validate_receipt_lineage(
            item,
            expected_task_id=expected_task_id,
            expected_turn_id=expected_turn_id,
            expected_user_query=expected_user_query,
        )
        if receipt_file is not None:
            item.setdefault("receipt_file", str(receipt_file))
            item.setdefault("receipt_sha256", hash_file(receipt_file))
        receipts.append(item)
    return receipts


def _load_validation_receipt_file(
    path: Any,
    *,
    expected_task_id: str,
    expected_turn_id: str,
    expected_user_query: str,
) -> list[Dict[str, Any]]:
    target = Path(str(path or "")).expanduser().resolve()
    if not target.is_file():
        raise ComputationCapsuleError("RECEIPT_FILE_MISSING", f"validation_receipt_file 不存在: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ComputationCapsuleError("INVALID_RECEIPT_FILE", f"validation_receipt_file 不是有效 JSON: {target}") from exc
    if isinstance(payload, dict) and isinstance(payload.get("validation_receipts"), list):
        raw_receipts = payload["validation_receipts"]
    elif isinstance(payload, list):
        raw_receipts = payload
    elif isinstance(payload, dict):
        raw_receipts = [payload]
    else:
        raise ComputationCapsuleError("INVALID_RECEIPT_FILE", "validation_receipt_file 必须包含 JSON object 或 array")
    return _normalize_validation_receipts(
        raw_receipts,
        expected_task_id=expected_task_id,
        expected_turn_id=expected_turn_id,
        expected_user_query=expected_user_query,
        receipt_file=target,
    )


def build_computation_capsule_from_validated_roles(
    *,
    task_id: Any,
    turn_id: Any,
    user_query: Any,
    page_intent: Any,
    validated_roles: Any,
    asset_resolution: Any = None,
    validated_insights: Any = None,
    validation_receipts: Any = None,
    formula_runtime_contract: Any = None,
) -> Dict[str, Any]:
    """Build a full capsule from the compact role-oriented QBS handoff input.

    Agents provide one business-level entry per validated role.  This helper
    expands those entries into the existing contract/output schema, binds every
    artifact and receipt by SHA256, and validates any lineage fields present in
    receipts before QBV is allowed to reuse them.
    """
    task_value = _text("task_id", task_id)
    turn_value = _text("turn_id", turn_id)
    query_value = _text("user_query", user_query)
    roles = _list("validated_roles", validated_roles)
    if not roles:
        raise ComputationCapsuleError("VALIDATED_ROLES_REQUIRED", "validated_roles 至少需要一个已验证 role")
    role_names = [_text("role", _object(f"validated_roles[{index}]", raw).get("role")) for index, raw in enumerate(roles)]
    if isinstance(page_intent, str):
        lowered_roles = " ".join(role_names).lower()
        if "industry" in lowered_roles and ("rank" in lowered_roles or "ranking" in lowered_roles):
            page_type = "industry_return_ranking"
            primary_visualization = "horizontal_ranked_bar_chart"
        elif "backtest" in lowered_roles or "net_value" in lowered_roles or "drawdown" in lowered_roles:
            page_type = "backtest_performance"
            primary_visualization = "net_value_benchmark_drawdown_chart"
        elif "heatmap" in lowered_roles:
            page_type = "ranking_heatmap"
            primary_visualization = "heatmap"
        elif "comparison" in lowered_roles or "compare" in lowered_roles:
            page_type = "multi_asset_comparison"
            primary_visualization = "multi_series_comparison_chart"
        else:
            page_type = "interactive_analysis"
            primary_visualization = "primary_chart"
        page_intent = {
            "question_to_answer": query_value,
            "title_hint": _text("page_intent", page_intent),
            "recommended_page_type": page_type,
            "primary_visualization": primary_visualization,
            "required_roles": role_names,
        }
    elif isinstance(page_intent, dict):
        page_intent = dict(page_intent)
        page_intent.setdefault("question_to_answer", query_value)
        page_intent.setdefault("recommended_page_type", "interactive_analysis")
        page_intent.setdefault("primary_visualization", "primary_chart")
        page_intent.setdefault("required_roles", role_names)

    contracts = []
    outputs = []
    receipts = _normalize_validation_receipts(
        validation_receipts,
        expected_task_id=task_value,
        expected_turn_id=turn_value,
        expected_user_query=query_value,
    )
    seen_receipts = {canonical_json(item) for item in receipts}

    for index, raw in enumerate(roles):
        item = _object(f"validated_roles[{index}]", raw)
        role = _text("role", item.get("role"))
        data_id = _compact_optional(item.get("data_id"))
        if data_id:
            data_reference = {
                "schema_version": "quant_buddy_data_reference_v1",
                "provider": "quant_buddy",
                "data_id": data_id,
                "read_tool": "readData",
            }
            for field in ("index_title", "description", "date", "formula", "aggregation", "universe", "value_semantics"):
                value = _compact_optional(item.get(field))
                if value is not None:
                    data_reference[field] = value
            if item.get("window_days") is not None:
                try:
                    window_days = int(item.get("window_days"))
                except (TypeError, ValueError) as exc:
                    raise ComputationCapsuleError("INVALID_WINDOW_DAYS", f"{role} window_days 必须是正整数") from exc
                if window_days <= 0:
                    raise ComputationCapsuleError("INVALID_WINDOW_DAYS", f"{role} window_days 必须是正整数")
                data_reference["window_days"] = window_days
            contract = dict(data_reference)
            contract["reuse_semantics"] = "materialized_result_only_no_formula_recompute"
            kind = "quant_buddy_materialized_data"
        else:
            contract = _object("contract", item.get("contract"))
            kind = _compact_optional(item.get("kind")) or _compact_optional(contract.get("kind")) or _compact_optional(contract.get("type")) or "validated_contract"
        contracts.append({
            "role": role,
            "kind": kind,
            "contract": contract,
            **({"contract_fingerprint": item.get("contract_fingerprint")} if item.get("contract_fingerprint") else {}),
        })

        output = {"role": role}
        if data_id:
            output.update({
                "evidence_kind": "quant_buddy_data_id",
                "data_reference": data_reference,
                "reference_hash": hash_inline_data(data_reference),
            })
        elif str(item.get("artifact_file") or "").strip():
            output["artifact_file"] = item.get("artifact_file")
        elif "data" in item:
            output["data"] = item.get("data")
        else:
            raise ComputationCapsuleError(
                "OUTPUT_EVIDENCE_REQUIRED",
                f"validated_roles[{index}] 必须包含 artifact_file、data 或 data_id",
            )
        if "asset_count" in item and "row_count" not in item:
            output["row_count"] = item.get("asset_count")
        for field in ("row_count", "field_mapping", "data_hash", "reference_hash"):
            if field in item:
                output[field] = item.get(field)
        outputs.append(output)

        inline_receipts = _normalize_validation_receipts(
            item.get("validation_receipts"),
            expected_task_id=task_value,
            expected_turn_id=turn_value,
            expected_user_query=query_value,
        )
        receipt_files = []
        if item.get("validation_receipt_file"):
            receipt_files.append(item.get("validation_receipt_file"))
        if item.get("validation_receipt_files") is not None:
            raw_files = item.get("validation_receipt_files")
            if not isinstance(raw_files, list):
                raise ComputationCapsuleError("INVALID_VALIDATION_RECEIPT_FILES", "validation_receipt_files 必须是 JSON array")
            receipt_files.extend(raw_files)
        file_receipts = []
        for receipt_path in receipt_files:
            file_receipts.extend(_load_validation_receipt_file(
                receipt_path,
                expected_task_id=task_value,
                expected_turn_id=turn_value,
                expected_user_query=query_value,
            ))
        for receipt in [*inline_receipts, *file_receipts]:
            key = canonical_json(receipt)
            if key not in seen_receipts:
                receipts.append(receipt)
                seen_receipts.add(key)

    receipt_runtime_contract = _runtime_contract_from_receipts(receipts)
    explicit_runtime_contract = _normalize_formula_runtime_contract(formula_runtime_contract)
    if (
        explicit_runtime_contract is not None
        and receipt_runtime_contract is not None
        and explicit_runtime_contract["contract_fingerprint"] != receipt_runtime_contract["contract_fingerprint"]
    ):
        raise ComputationCapsuleError(
            "FORMULA_RUNTIME_RECEIPT_MISMATCH",
            "显式 formula_runtime_contract 与成功执行 receipt 不一致，禁止改写公式后交给 QBV",
        )
    runtime_contract = explicit_runtime_contract or receipt_runtime_contract
    _bind_materialized_outputs(outputs, receipts, runtime_contract)

    return build_computation_capsule(
        task_id=task_value,
        turn_id=turn_value,
        user_query=query_value,
        page_intent=page_intent,
        asset_resolution=asset_resolution if asset_resolution is not None else {},
        validated_contracts=contracts,
        validated_outputs=outputs,
        validated_insights=validated_insights,
        validation_receipts=receipts,
        formula_runtime_contract=runtime_contract,
    )


def build_computation_capsule(
    *,
    task_id: Any,
    turn_id: Any,
    user_query: Any,
    page_intent: Any,
    asset_resolution: Any,
    validated_contracts: Any,
    validated_outputs: Any,
    validated_insights: Any = None,
    validation_receipts: Any = None,
    formula_runtime_contract: Any = None,
) -> Dict[str, Any]:
    intent = _object("page_intent", page_intent)
    for field in ("question_to_answer", "recommended_page_type", "primary_visualization"):
        intent[field] = _text(field, intent.get(field))
    intent["required_roles"] = _normalize_roles(intent.get("required_roles") or [])
    capsule = {
        "schema_version": SCHEMA_VERSION,
        "task_id": _text("task_id", task_id),
        "turn_id": _text("turn_id", turn_id),
        "user_query": _text("user_query", user_query),
        "page_intent": intent,
        "asset_resolution": _object("asset_resolution", asset_resolution),
        "validated_contracts": _normalize_contracts(validated_contracts),
        "validated_outputs": _normalize_outputs(validated_outputs, verify_artifacts=True),
        "validated_insights": _list("validated_insights", validated_insights),
        "validation_receipts": _list("validation_receipts", validation_receipts),
    }
    normalized_runtime_contract = _normalize_formula_runtime_contract(formula_runtime_contract)
    if normalized_runtime_contract is not None:
        capsule["formula_runtime_contract"] = normalized_runtime_contract
    return capsule


def validate_computation_capsule(
    payload: Any,
    *,
    expected_task_id: Any = None,
    expected_turn_id: Any = None,
    expected_user_query: Any = None,
    verify_artifacts: bool = True,
) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ComputationCapsuleError("CAPSULE_OBJECT_REQUIRED", "computation_capsule 必须是 JSON object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ComputationCapsuleError("CAPSULE_SCHEMA_UNSUPPORTED", f"仅支持 {SCHEMA_VERSION}")
    task_id = _text("task_id", payload.get("task_id"))
    turn_id = _text("turn_id", payload.get("turn_id"))
    user_query = _text("user_query", payload.get("user_query"))
    for name, actual, expected in (
        ("task_id", task_id, expected_task_id),
        ("turn_id", turn_id, expected_turn_id),
        ("user_query", user_query, expected_user_query),
    ):
        if expected is not None and re.sub(r"\s+", " ", str(expected or "")).strip() != actual:
            raise ComputationCapsuleError("CAPSULE_LINEAGE_MISMATCH", f"computation_capsule {name} 与 Handoff 不一致")
    intent = _object("page_intent", payload.get("page_intent"))
    for field in ("question_to_answer", "recommended_page_type", "primary_visualization"):
        intent[field] = _text(field, intent.get(field))
    intent["required_roles"] = _normalize_roles(intent.get("required_roles") or [])
    normalized = {
        **dict(payload),
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "turn_id": turn_id,
        "user_query": user_query,
        "page_intent": intent,
        "asset_resolution": _object("asset_resolution", payload.get("asset_resolution")),
        "validated_contracts": _normalize_contracts(payload.get("validated_contracts")),
        "validated_outputs": _normalize_outputs(payload.get("validated_outputs"), verify_artifacts=verify_artifacts),
        "validated_insights": _list("validated_insights", payload.get("validated_insights")),
        "validation_receipts": _list("validation_receipts", payload.get("validation_receipts")),
    }
    if "formula_runtime_contract" in payload:
        normalized["formula_runtime_contract"] = _normalize_formula_runtime_contract(payload.get("formula_runtime_contract"))
    return normalized


def _read_params(args: list[str]) -> Dict[str, Any]:
    if not args:
        return {}
    token = args[0]
    if token.startswith("@"):
        return json.loads(Path(token[1:]).read_text(encoding="utf-8-sig"))
    return json.loads(token)


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(json.dumps({"code": 1, "error": "COMMAND_REQUIRED", "message": "用法: qbv_computation_capsule.py build|validate [JSON|@file]"}, ensure_ascii=False))
        return 1
    command = argv.pop(0)
    try:
        params = _read_params(argv)
        if command == "build":
            result = build_computation_capsule(**params)
        elif command == "validate":
            capsule = params.get("computation_capsule", params)
            result = validate_computation_capsule(capsule)
        else:
            raise ComputationCapsuleError("UNKNOWN_COMMAND", f"未知命令: {command}")
        print(json.dumps({"code": 0, "computation_capsule": result}, ensure_ascii=False, indent=2))
        return 0
    except (ComputationCapsuleError, OSError, json.JSONDecodeError, TypeError) as exc:
        code = exc.code if isinstance(exc, ComputationCapsuleError) else "CAPSULE_BUILD_FAILED"
        print(json.dumps({"code": 1, "error": code, "message": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
