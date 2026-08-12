#!/usr/bin/env python3
"""Run a quant-buddy-skill tool inside the current QBV task context."""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import common as C
import fork_runtime_contract as FRC
import reply_data_evidence as RDE

QBV_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FORMULA_BEGIN_DATE = 20150101
MAX_PACKAGE_FORMULAS = 100
MAX_VALIDATION_BATCH_FORMULAS = 20


def _read_params(argv):
    if not argv:
        raw = os.environ.get("QBS_BRIDGE_PARAMS", "").strip()
    elif len(argv) == 1 and argv[0].startswith("@"):
        raw = Path(argv[0][1:]).read_text(encoding="utf-8-sig")
    else:
        raw = " ".join(argv)
    params = json.loads(raw or "{}")
    if not isinstance(params, dict):
        raise ValueError("参数必须是 JSON 对象")
    return params


def _qbs_root():
    override = os.environ.get("QBS_SKILL_ROOT", "").strip()
    return Path(override).resolve() if override else (QBV_ROOT.parent / "quant-buddy-skill").resolve()


def _forward_api_key(env):
    """把 QBV 侧「这次调用用哪个 key」翻译成 QBS 侧的同档变量，原地改 env。

    两边优先级链是对称的（params.api_key > QBV_API_KEY / QBS_API_KEY > config.json > QUANT_BUDDY_API_KEY），
    只是变量名不同。不覆盖已显式设好的 QBS_API_KEY——调用方直接指定 qbs 身份时那个更权威。
    注意不能退回 QUANT_BUDDY_API_KEY：那是最低优先级兜底，config.json 有值时根本不生效。
    """
    if env.get("QBS_API_KEY", "").strip():
        return env
    api_key = env.get("QBV_API_KEY", "").strip()
    if api_key:
        env["QBS_API_KEY"] = api_key
    return env


def _session_key(task_id):
    return re.sub(r"[^0-9A-Za-z._-]+", "_", task_id).strip("._-")


def _session_path(qbs_root, session_key):
    return qbs_root / "output" / f".session.{session_key}.json"


def _read_session(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _session_ready(path, task_id):
    data = _read_session(path)
    return data.get("task_id") == task_id and data.get("task_id_locked") is True


def _invoke(call_script, tool_name, params, env):
    fd, path = tempfile.mkstemp(prefix="qbv_qbs_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(params, handle, ensure_ascii=False)
        return subprocess.run(
            [sys.executable, str(call_script), tool_name, f"@{path}"],
            cwd=call_script.parent.parent,
            env=env,
            capture_output=True,
            check=False,
        )
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _invoke_payload(call_script, tool_name, params, env):
    completed = _invoke(call_script, tool_name, params, env)
    try:
        payload = json.loads(completed.stdout.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, {
            "code": 1,
            "error": "QBS_INVALID_RESPONSE",
            "message": f"{tool_name} 未返回合法 JSON: {exc}",
        }
    if completed.returncode != 0 or not isinstance(payload, dict):
        return None, payload if isinstance(payload, dict) else {
            "code": 1,
            "error": "QBS_CALL_FAILED",
            "message": f"{tool_name} 调用失败",
        }
    return payload, None


def _payload_status(payload):
    if not isinstance(payload, dict):
        return ""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return str(payload.get("status") or data.get("status") or "").strip().lower()


def _begin_date(value, label):
    if value is None or str(value).strip() == "":
        return DEFAULT_FORMULA_BEGIN_DATE
    if isinstance(value, bool):
        raise ValueError(f"{label} 必须是 YYYYMMDD 整数")
    try:
        normalized = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} 必须是 YYYYMMDD 整数") from exc
    if normalized < 20050104 or normalized > 20991231 or len(str(normalized)) != 8:
        raise ValueError(f"{label} 必须是 20050104..20991231 的 YYYYMMDD 整数")
    return normalized


def _formula_validation_batches(formulas, requested_force_reusable=None):
    """Split one package contract into QBS-safe batches without changing package boundaries."""
    requested = {
        str(value).strip() for value in (requested_force_reusable or [])
        if str(value or "").strip()
    }
    chunks = [
        list(formulas[start:start + MAX_VALIDATION_BATCH_FORMULAS])
        for start in range(0, len(formulas), MAX_VALIDATION_BATCH_FORMULAS)
    ]
    batches = []
    for index, chunk in enumerate(chunks):
        outputs = FRC.formula_outputs(chunk)
        force_reusable = []
        if index < len(chunks) - 1:
            force_reusable.extend(outputs)
        force_reusable.extend(output for output in outputs if output in requested)
        batches.append({
            "formulas": chunk,
            "force_reusable_array": list(dict.fromkeys(force_reusable)),
        })
    return batches


def _file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_completed_formula_receipt(path, task_id):
    receipt = json.loads(Path(path).read_text(encoding="utf-8"))
    if (
        not isinstance(receipt, dict)
        or receipt.get("version") != "qb_validation_receipt_v1"
        or str(receipt.get("task_id") or "") != task_id
        or receipt.get("status") != "completed"
        or receipt.get("success") is not True
        or receipt.get("failures")
    ):
        raise ValueError(f"invalid child validation receipt: {path}")
    return receipt


def _write_package_validation_receipt(task_id, item, child_receipt_files):
    contract = {
        "formulas": list(item.get("formulas") or []),
        "reads": list(item.get("reads") or []),
        "begin_date": item.get("begin_date"),
    }
    fingerprint = FRC.contract_fingerprint(contract)
    child_entries = []
    outputs = []
    for raw_path in child_receipt_files:
        child_path = str(Path(raw_path).resolve())
        child = _read_completed_formula_receipt(child_path, task_id)
        child_entries.append({"file": child_path, "sha256": _file_sha256(child_path)})
        outputs.extend(item for item in child.get("outputs") or [] if isinstance(item, dict))
    digest_source = json.dumps(outputs, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload = {
        "version": "qb_validation_receipt_v1",
        "task_id": task_id,
        "tool_name": "validate_package_set",
        "status": "completed",
        "success": True,
        "failures": [],
        "outputs": outputs,
        "outputs_sha256": hashlib.sha256(digest_source.encode("utf-8")).hexdigest(),
        "package_name": item.get("name"),
        "contract_fingerprint": fingerprint,
        "batch_count": len(child_entries),
        "batch_receipts": child_entries,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    root = QBV_ROOT / "output" / "formula_validation_receipts"
    root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(f"{task_id}:{item.get('name')}:{fingerprint}".encode("utf-8")).hexdigest()
    path = root / f"{digest}.json"
    fd, temp_path = tempfile.mkstemp(prefix=".receipt-", suffix=".json", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_path, path)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise
    return str(path), fingerprint

def _package_reply_evidence(call_script, env, task_id, user_query, template_ref, packages, results):
    started = time.perf_counter()
    if not RDE.get_policy(template_ref):
        return {"batch_count": 0, "requested_field_count": 0, "success_field_count": 0, "failed_field_count": 0, "read_elapsed_ms": 0}, []
    pending = []
    by_name = {item.get("name"): item for item in results}
    for package in packages:
        result = by_name.get(package.get("name")) or {}
        output_ids = {
            str(item.get("variable_name") or item.get("leftName") or item.get("output_name") or item.get("output") or "").strip():
                str(item.get("data_id") or item.get("indexinfo_id") or "").strip()
            for item in result.get("validation_outputs") or []
            if isinstance(item, dict)
        }
        for read in package.get("reads") or []:
            output = str(read.get("output") or "").strip()
            data_id = output_ids.get(output) or ""
            if not output or not data_id or not RDE.formula_output_needed(template_ref, output):
                continue
            read_params = RDE.read_data_params(read.get("read_mode"), read.get("mode_params"))
            pending.append({
                "package": package.get("name"),
                "output": output,
                "data_id": data_id,
                "read_mode": read.get("read_mode"),
                "read_params": read_params,
            })
    groups = {}
    for item in pending:
        key = json.dumps(item["read_params"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        groups.setdefault(key, []).append(item)
    warnings = []
    batch_count = 0
    success_count = 0
    failed_count = 0
    for key, items in groups.items():
        base_params = json.loads(key)
        for start in range(0, len(items), 10):
            batch = items[start:start + 10]
            batch_count += 1
            read_params = {
                **base_params,
                "task_id": task_id,
                "user_query": user_query,
                "ids": [item["data_id"] for item in batch],
            }
            payload, error = _invoke_payload(call_script, "readData", read_params, env)
            if error or not isinstance(payload, dict) or payload.get("code") not in (0, None):
                failed_count += len(batch)
                warnings.append({
                    "code": "REPLY_READ_DATA_FAILED",
                    "outputs": [item["output"] for item in batch],
                    "message": (error or payload or {}).get("message") if isinstance(error or payload, dict) else "readData failed",
                })
                continue
            response_items = RDE.extract_read_data_items(payload)
            by_id = {
                str(item.get("id") or item.get("data_id") or item.get("indexinfo_id") or "").strip(): item
                for item in response_items
                if isinstance(item, dict)
            }
            for index, request in enumerate(batch):
                response = by_id.get(request["data_id"])
                if response is None and len(response_items) == len(batch):
                    response = response_items[index]
                if response is None:
                    failed_count += 1
                    warnings.append({"code": "REPLY_READ_DATA_ITEM_MISSING", "output": request["output"]})
                    continue
                package_result = by_name.get(request["package"])
                package_result.setdefault("reply_evidence_outputs", []).append(
                    RDE.compact_formula_read(request["output"], request["data_id"], request["read_mode"], response)
                )
                success_count += 1
    return {
        "batch_count": batch_count,
        "requested_field_count": len(pending),
        "success_field_count": success_count,
        "failed_field_count": failed_count,
        "read_elapsed_ms": round((time.perf_counter() - started) * 1000),
    }, warnings


def _validate_package_set(call_script, params, env):
    packages = params.get("packages")
    if not isinstance(packages, list) or not packages:
        return {"code": 1, "error": "PACKAGES_REQUIRED", "message": "packages 必须是非空数组"}

    task_id = str(params.get("task_id") or "").strip()
    user_query = str(params.get("user_query") or "").strip()
    try:
        default_begin_date = _begin_date(params.get("begin_date"), "begin_date")
    except ValueError as exc:
        return {"code": 1, "error": "INVALID_BEGIN_DATE", "message": str(exc)}
    names = set()
    normalized = []
    for index, item in enumerate(packages):
        if not isinstance(item, dict):
            return {"code": 1, "error": "INVALID_PACKAGE", "message": f"packages[{index}] 必须是对象"}
        name = str(item.get("name") or "").strip()
        formulas = item.get("formulas")
        reads = item.get("reads") if isinstance(item.get("reads"), list) else []
        if not name or name in names:
            return {"code": 1, "error": "INVALID_PACKAGE_NAME", "message": f"packages[{index}].name 缺失或重复"}
        if not isinstance(formulas, list) or not formulas or len(formulas) > MAX_PACKAGE_FORMULAS or not all(isinstance(value, str) and value.strip() for value in formulas):
            return {
                "code": 1,
                "error": "INVALID_PACKAGE_FORMULAS",
                "message": f"packages[{index}].formulas 必须是 1..{MAX_PACKAGE_FORMULAS} 条非空字符串",
            }
        force_reusable = item.get("force_reusable_array")
        if force_reusable is not None and (
            not isinstance(force_reusable, list)
            or not all(isinstance(value, str) and value.strip() for value in force_reusable)
        ):
            return {"code": 1, "error": "INVALID_FORCE_REUSABLE", "message": f"packages[{index}].force_reusable_array 必须是字符串数组"}
        try:
            begin_date = _begin_date(
                item.get("begin_date", default_begin_date),
                f"packages[{index}].begin_date",
            )
        except ValueError as exc:
            return {"code": 1, "error": "INVALID_BEGIN_DATE", "message": str(exc)}
        names.add(name)
        contract = {"formulas": formulas, "reads": reads, "begin_date": begin_date}
        normalized.append({
            "name": name,
            "formulas": formulas,
            "force_reusable_array": force_reusable,
            "begin_date": begin_date,
            "reads": reads,
            "contract_fingerprint": FRC.contract_fingerprint(contract),
        })

    results = []
    receipts = []
    total_batch_count = 0
    for item in normalized:
        validation_outputs = []
        batch_receipts = []
        batch_summaries = []
        trace_ids = []
        job_ids = []
        batches = _formula_validation_batches(item["formulas"], item["force_reusable_array"])
        for batch_index, batch in enumerate(batches):
            total_batch_count += 1
            batch_params = {
                "task_id": task_id,
                "user_query": user_query,
                "formulas": batch["formulas"],
                "begin_date": item["begin_date"],
                "output_mode": "summary",
            }
            if batch["force_reusable_array"]:
                batch_params["force_reusable_array"] = batch["force_reusable_array"]
            payload, error = _invoke_payload(call_script, "runMultiFormulaBatchStream", batch_params, env)
            if error:
                return {
                    **error,
                    "success": False,
                    "task_id": task_id,
                    "failed_package": item["name"],
                    "failed_batch_index": batch_index,
                    "packages": results,
                }
            if payload.get("code") not in (0, None) or payload.get("success") is False:
                return {
                    "code": 1,
                    "error": "PACKAGE_VALIDATION_FAILED",
                    "success": False,
                    "task_id": task_id,
                    "failed_package": item["name"],
                    "failed_batch_index": batch_index,
                    "result": payload,
                    "packages": results,
                }

            trace_id = str(payload.get("trace_id") or (payload.get("data") or {}).get("trace_id") or "").strip()
            job_id = str(payload.get("job_id") or (payload.get("data") or {}).get("job_id") or "").strip()
            if trace_id:
                trace_ids.append(trace_id)
            if job_id:
                job_ids.append(job_id)
            if _payload_status(payload) == "deferred" or payload.get("_deferred"):
                if not trace_id:
                    return {
                        "code": 1,
                        "error": "DEFERRED_CONTINUATION_MISSING",
                        "success": False,
                        "task_id": task_id,
                        "failed_package": item["name"],
                        "failed_batch_index": batch_index,
                        "packages": results,
                    }
                payload, error = _invoke_payload(call_script, "resumeJob", {
                    "task_id": task_id,
                    "user_query": user_query,
                    "trace_id": trace_id,
                    "output_mode": "summary",
                }, env)
                if error:
                    return {
                        **error,
                        "success": False,
                        "task_id": task_id,
                        "failed_package": item["name"],
                        "failed_batch_index": batch_index,
                        "packages": results,
                    }

            receipt = str(payload.get("validation_receipt_file") or "").strip()
            if payload.get("code") not in (0, None) or payload.get("success") is False or not receipt:
                return {
                    "code": 1,
                    "error": "PACKAGE_VALIDATION_INCOMPLETE",
                    "success": False,
                    "task_id": task_id,
                    "failed_package": item["name"],
                    "failed_batch_index": batch_index,
                    "result": payload,
                    "packages": results,
                }
            batch_receipts.append(receipt)
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            batch_summaries.append(data.get("summary") if isinstance(data.get("summary"), dict) else {})
            validation_outputs.extend(data.get("results") if isinstance(data.get("results"), list) else [])

        package_receipt = batch_receipts[0]
        contract_fingerprint = item["contract_fingerprint"]
        if len(batch_receipts) > 1:
            try:
                package_receipt, aggregate_fingerprint = _write_package_validation_receipt(task_id, item, batch_receipts)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                return {
                    "code": 1,
                    "error": "PACKAGE_VALIDATION_RECEIPT_INVALID",
                    "success": False,
                    "task_id": task_id,
                    "failed_package": item["name"],
                    "message": str(exc),
                    "packages": results,
                }
            if aggregate_fingerprint != contract_fingerprint:
                return {
                    "code": 1,
                    "error": "PACKAGE_CONTRACT_FINGERPRINT_MISMATCH",
                    "success": False,
                    "task_id": task_id,
                    "failed_package": item["name"],
                    "packages": results,
                }
        receipts.append(package_receipt)
        results.append({
            "name": item["name"],
            "status": "completed",
            "formula_count": len(item["formulas"]),
            "begin_date": item["begin_date"],
            "batch_count": len(batches),
            "trace_id": trace_ids[0] if len(trace_ids) == 1 else None,
            "job_id": job_ids[0] if len(job_ids) == 1 else None,
            "trace_ids": trace_ids,
            "job_ids": job_ids,
            "contract_fingerprint": contract_fingerprint,
            "validation_receipt_file": package_receipt,
            "batch_validation_receipt_files": batch_receipts,
            "summary": batch_summaries[-1] if batch_summaries else {},
            "batch_summaries": batch_summaries,
            "validation_outputs": validation_outputs,
        })
    evidence_stats, evidence_warnings = _package_reply_evidence(
        call_script, env, task_id, user_query, str(params.get("template_ref") or ""), normalized, results
    )
    return {
        "code": 0,
        "success": True,
        "task_id": task_id,
        "package_count": len(results),
        "batch_count": total_batch_count,
        "validation_receipt_files": receipts,
        "packages": results,
        "reply_evidence_stats": evidence_stats,
        "reply_evidence_warnings": evidence_warnings,
    }

_DATA_ERROR_CODES = {
    "ASSET_NOT_FOUND",
    "DATA_UNAVAILABLE",
    "EMPTY_PROFILE",
    "EMPTY_RESULT",
    "TARGET_ASSET_MISSING",
    "ASSET_ERROR",
    "FIELD_ERROR",
    "REQUIRED_FIELD_MISSING",
    "REQUIRED_OUTPUT_MISSING",
    "NO_DATA",
}


def _normalized_token(value):
    # 必须保留 CJK：只留 [0-9A-Z] 会把「特斯拉」「贵州茅台」这类中文资产名归一成空串，
    # 于是 _asset_matches 永远返回 False，所有中文名资产都被误判成 TARGET_ASSET_MISSING。
    return re.sub(r"[^0-9A-Z\u3400-\u4dbf\u4e00-\u9fff]+", "", str(value or "").upper())


def _is_meaningful_value(value):
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    if isinstance(value, float):
        return value == value and value not in (float("inf"), float("-inf"))
    return True


def _error_code(payload):
    if not isinstance(payload, dict):
        return "UNKNOWN_ERROR"
    candidates = [
        payload.get("error"), payload.get("error_code"), payload.get("code_name"),
        payload.get("reason_code"), payload.get("message"),
    ]
    nested = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    candidates.extend([nested.get("error"), nested.get("error_code"), nested.get("message")])
    for value in candidates:
        token = str(value or "").strip()
        if token:
            upper = token.upper()
            for code in _DATA_ERROR_CODES:
                if code in upper:
                    return code
            return re.sub(r"[^0-9A-Z_]+", "_", upper).strip("_")[:80] or "UNKNOWN_ERROR"
    return "UNKNOWN_ERROR"


def _classify_route_error(payload):
    code = _error_code(payload)
    if code in _DATA_ERROR_CODES:
        return "data", code
    text = json.dumps(payload, ensure_ascii=False, default=str).upper() if isinstance(payload, dict) else str(payload or "").upper()
    data_markers = (
        "ASSET_NOT_FOUND", "DATA_UNAVAILABLE", "NO DATA", "NO_DATA", "EMPTY RESULT",
        "EMPTY_PROFILE", "FIELD_ERROR", "ASSET_ERROR", "REQUIRED_FIELD_MISSING",
    )
    if any(marker in text for marker in data_markers):
        return "data", code
    # Fail closed: authentication, quota, task/session, transport, protocol, service,
    # and any unknown backend exception are system-level blockers.
    return "system", code


def _asset_matches(value, asset):
    left = _normalized_token(value)
    right = _normalized_token(asset)
    return bool(left and right and (left == right or left.endswith(right) or right.endswith(left)))


def _entry_asset(entry):
    if not isinstance(entry, dict):
        return ""
    for key in ("asset", "ticker", "code", "symbol", "wind_code", "security_code"):
        value = entry.get(key)
        if isinstance(value, dict):
            value = value.get("ticker") or value.get("code") or value.get("symbol")
        if str(value or "").strip():
            return str(value).strip()
    return ""


def _matching_error_entries(entries, asset):
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        return []
    matched = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        item_asset = _entry_asset(item)
        # A single-asset request may receive a global error without an asset field.
        if not item_asset or _asset_matches(item_asset, asset):
            matched.append(item)
    return matched


def _field_error_names(entries):
    if isinstance(entries, dict):
        entries = [entries]
    names = set()
    for item in entries or []:
        if not isinstance(item, dict):
            continue
        value = item.get("field") or item.get("field_name") or item.get("name") or item.get("indicator")
        if str(value or "").strip():
            names.add(str(value).strip())
    return names


def _find_nested_field(payload, field):
    wanted = str(field or "").strip()
    if not wanted:
        return None
    stack = [payload]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            if wanted in current and _is_meaningful_value(current.get(wanted)):
                return current.get(wanted)
            label = current.get("name") or current.get("field") or current.get("indicator")
            if str(label or "").strip() == wanted:
                for key in ("latest_value", "value", "data", "result"):
                    if _is_meaningful_value(current.get(key)):
                        return current.get(key)
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return None


def _evaluate_stock_profile_result(asset, required_fields, result):
    if not isinstance(result, dict):
        return {"success": False, "error_class": "system", "error_code": "INVALID_RESPONSE", "missing_fields": list(required_fields or [])}
    if result.get("code") not in (0, None) or result.get("success") is False:
        error_class, error_code = _classify_route_error(result)
        return {"success": False, "error_class": error_class, "error_code": error_code, "missing_fields": list(required_fields or [])}
    data = result.get("data") if isinstance(result.get("data"), dict) else result
    asset_data = data.get("asset") if isinstance(data.get("asset"), dict) else {}
    target = _entry_asset(asset_data) or _entry_asset(data)
    if not target or not _asset_matches(target, asset):
        return {"success": False, "error_class": "data", "error_code": "TARGET_ASSET_MISSING", "missing_fields": list(required_fields or [])}
    dimensions = data.get("dimensions")
    indicators_count = data.get("indicators_count")
    try:
        count_ok = int(indicators_count or 0) > 0
    except (TypeError, ValueError):
        count_ok = False
    if not count_ok or not isinstance(dimensions, dict) or not dimensions:
        return {"success": False, "error_class": "data", "error_code": "EMPTY_PROFILE", "missing_fields": list(required_fields or [])}
    missing = [field for field in (required_fields or []) if _find_nested_field(data, field) is None]
    if missing:
        return {"success": False, "error_class": "data", "error_code": "REQUIRED_FIELD_MISSING", "missing_fields": missing}
    return {"success": True, "covered_fields": list(required_fields or []), "missing_fields": []}


def _fast_query_target(results, asset):
    candidates = []
    if isinstance(results, dict):
        for key, value in results.items():
            if isinstance(value, dict):
                candidates.append((key, value))
    elif isinstance(results, list):
        candidates.extend(("", value) for value in results if isinstance(value, dict))
    for key, row in candidates:
        if _asset_matches(_entry_asset(row), asset) or _asset_matches(key, asset):
            return row
    return None


def _evaluate_fast_query_result(asset, required_fields, optional_fields, result):
    required_fields = list(required_fields or [])
    optional_fields = list(optional_fields or [])
    if not isinstance(result, dict):
        return {"success": False, "error_class": "system", "error_code": "INVALID_RESPONSE", "missing_fields": required_fields, "warnings": []}
    if result.get("code") not in (0, None) or result.get("success") is False:
        error_class, error_code = _classify_route_error(result)
        return {"success": False, "error_class": error_class, "error_code": error_code, "missing_fields": required_fields, "warnings": []}
    # fastQuery 的业务字段包在 {code, data:{...}} 信封里（与上面 stock_profile 评估器同款解包）；
    # 不解包就永远读不到 results，任何资产都会被误判成 TARGET_ASSET_MISSING。
    body = result.get("data") if isinstance(result.get("data"), dict) else result
    asset_errors = _matching_error_entries(body.get("asset_errors"), asset)
    if asset_errors:
        error_class, error_code = _classify_route_error(asset_errors[0])
        return {"success": False, "error_class": error_class, "error_code": error_code or "ASSET_ERROR", "missing_fields": required_fields, "warnings": []}
    row = _fast_query_target(body.get("results"), asset)
    if row is None:
        return {"success": False, "error_class": "data", "error_code": "TARGET_ASSET_MISSING", "missing_fields": required_fields, "warnings": []}
    field_errors = _field_error_names(body.get("field_errors"))
    required_error_fields = [field for field in required_fields if field in field_errors]
    missing = [field for field in required_fields if field in required_error_fields or not _is_meaningful_value(row.get(field))]
    warnings = []
    for field in optional_fields:
        if field in field_errors or not _is_meaningful_value(row.get(field)):
            warnings.append({"field": field, "warning": "OPTIONAL_FIELD_UNAVAILABLE"})
    if missing:
        return {"success": False, "error_class": "data", "error_code": "REQUIRED_FIELD_MISSING", "missing_fields": missing, "warnings": warnings}
    return {"success": True, "covered_fields": required_fields, "missing_fields": [], "warnings": warnings, "row": row}


def _evaluate_formula_result(required_outputs, result):
    required_outputs = list(required_outputs or [])
    if not isinstance(result, dict) or result.get("code") not in (0, None) or result.get("success") is False:
        error_class, error_code = _classify_route_error(result)
        return {"success": False, "error_class": error_class, "error_code": error_code, "missing_fields": required_outputs}
    packages = result.get("packages") if isinstance(result.get("packages"), list) else []
    receipts = result.get("validation_receipt_files") if isinstance(result.get("validation_receipt_files"), list) else []
    if len(packages) != 1 or len(receipts) != 1 or not str(receipts[0] or "").strip():
        return {"success": False, "error_class": "system", "error_code": "FORMULA_RECEIPT_MISSING", "missing_fields": required_outputs}
    package = packages[0]
    if str(package.get("status") or "").strip().lower() == "deferred":
        return {"success": False, "error_class": "system", "error_code": "FORMULA_DEFERRED", "missing_fields": required_outputs}
    outputs = package.get("validation_outputs") if isinstance(package.get("validation_outputs"), list) else []
    available = set()
    for item in outputs:
        if not isinstance(item, dict):
            continue
        name = str(item.get("variable_name") or item.get("leftName") or item.get("output_name") or item.get("output") or "").strip()
        value = item.get("data_id") or item.get("indexinfo_id") or item.get("value") or item.get("latest_value")
        if name and _is_meaningful_value(value):
            available.add(name)
    missing = [name for name in required_outputs if name not in available]
    if missing:
        return {"success": False, "error_class": "data", "error_code": "REQUIRED_OUTPUT_MISSING", "missing_fields": missing}
    return {"success": True, "covered_fields": required_outputs, "receipt_file": str(receipts[0])}


def _write_live_data_route_receipt(payload):
    root = QBV_ROOT / "output" / "live_data_route_receipts"
    root.mkdir(parents=True, exist_ok=True)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    path = root / f"{digest}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(path)


def _formula_output_names(formulas):
    names = []
    for formula in formulas or []:
        left = str(formula or "").split("=", 1)[0].strip()
        if left and left not in names:
            names.append(left)
    return names


def _resolve_asset_data(call_script, params, env):
    task_id = str(params.get("task_id") or "").strip()
    user_query = str(params.get("user_query") or "").strip()
    asset = str(params.get("asset") or "").strip()
    required = params.get("required_roles") if isinstance(params.get("required_roles"), dict) else {}
    required_by_role = {}
    for role in ("profile", "snapshot", "report", "formula"):
        values = required.get(role)
        if not isinstance(values, list) or not all(isinstance(value, str) and value.strip() for value in values):
            return {"code": 1, "error": "INVALID_REQUIRED_ROLES", "message": f"required_roles.{role} 必须是字符串数组"}
        required_by_role[role] = [value.strip() for value in values]
    optional_fields = params.get("optional_fields")
    if not isinstance(optional_fields, list) or not all(isinstance(value, str) and value.strip() for value in optional_fields):
        return {"code": 1, "error": "INVALID_OPTIONAL_FIELDS", "message": "optional_fields 必须是字符串数组"}
    optional_fields = [value.strip() for value in optional_fields]
    if not task_id or not user_query or not asset:
        return {"code": 1, "error": "RESOLVE_CONTEXT_REQUIRED", "missing": [key for key, value in (("task_id", task_id), ("user_query", user_query), ("asset", asset)) if not value]}

    required_roles = [role for role in ("profile", "snapshot", "report", "formula") if required_by_role[role]]
    attempts = []
    selected_routes = []
    grants = []
    formula_packages = []
    warnings = []
    successful_required = set()
    failed_required = set()
    attempted_required = set()
    blocked = False

    def record_failure(role, route, evaluation):
        nonlocal blocked
        attempts.append({
            "role": role,
            "route": route,
            "status": "failed" if evaluation.get("error_class") == "data" else "blocked",
            "error_class": evaluation.get("error_class") or "system",
            "error_code": evaluation.get("error_code") or "UNKNOWN_ERROR",
            **({"missing_fields": evaluation.get("missing_fields")} if evaluation.get("missing_fields") else {}),
        })
        if role in required_roles:
            attempted_required.add(role)
            failed_required.add(role)
        if evaluation.get("error_class") != "data":
            blocked = True

    profile_payload = {"task_id": task_id, "user_query": user_query, "asset": asset, "result_mode": "inline"}
    profile_result, profile_error = _invoke_payload(call_script, "stockProfile", profile_payload, env)
    profile_eval = _evaluate_stock_profile_result(asset, required_by_role["profile"], profile_error or profile_result)
    if profile_eval.get("success"):
        attempts.append({"role": "profile", "route": "stock_profile", "status": "success", "covered_fields": profile_eval.get("covered_fields") or []})
        if required_by_role["profile"]:
            attempted_required.add("profile")
            successful_required.add("profile")
            contract = {"kind": "stock_profile", "payload": {"asset": asset, "result_mode": "inline", "required_fields": required_by_role["profile"]}}
            fingerprint = FRC.contract_fingerprint(contract)
            receipt = _grant_validation_receipt(task_id, "profile", "stock_profile", fingerprint)
            grant = {"name": "profile", "role": "profile", "kind": "stock_profile", "contract": contract, "contract_fingerprint": fingerprint, "validation_receipt_file": receipt}
            grants.append(grant)
            selected_routes.append({"role": "profile", "kind": "stock_profile", "receipt_file": receipt, "contract_fingerprint": fingerprint})
    else:
        record_failure("profile", "stock_profile", profile_eval)

    for role in ("snapshot", "report"):
        if blocked or not required_by_role[role]:
            continue
        attempted_required.add(role)
        fields = list(dict.fromkeys(required_by_role[role] + optional_fields))
        query_payload = {
            "task_id": task_id,
            "user_query": user_query,
            "assets": [asset],
            "fields": fields,
            "query_type": role,
            # fastQuery 只接受 value/series；传 inline 会被 layer-1 判成 INVALID_RESULT_MODE，
            # 使每个资产实时页探测都退化为 system 级 blocked，static 回退与 live 发布双双走不通。
            "result_mode": "value",
        }
        result, error = _invoke_payload(call_script, "fast_query", query_payload, env)
        evaluation = _evaluate_fast_query_result(asset, required_by_role[role], optional_fields, error or result)
        warnings.extend({"role": role, **item} for item in evaluation.get("warnings") or [])
        route_name = f"fast_query_{role}"
        if evaluation.get("success"):
            successful_required.add(role)
            attempts.append({"role": role, "route": route_name, "status": "success", "covered_fields": evaluation.get("covered_fields") or []})
            contract_payload = {"assets": [asset], "fields": fields, "query_type": role, "result_mode": "value"}
            contract = {"kind": "fast_query", "payload": contract_payload}
            fingerprint = FRC.contract_fingerprint(contract)
            receipt = _grant_validation_receipt(task_id, role, "fast_query", fingerprint)
            grant = {"name": role, "role": role, "kind": "fast_query", "query_type": role, "contract": contract, "contract_fingerprint": fingerprint, "validation_receipt_file": receipt}
            grants.append(grant)
            selected_routes.append({"role": role, "kind": "fast_query", "query_type": role, "receipt_file": receipt, "contract_fingerprint": fingerprint})
        else:
            record_failure(role, route_name, evaluation)

    formulas = required_by_role["formula"]
    if not blocked and formulas:
        attempted_required.add("formula")
        package_contract = {"formulas": formulas, "begin_date": _begin_date(params.get("begin_date"), "begin_date")}
        package_result = _validate_package_set(call_script, {
            "task_id": task_id,
            "user_query": user_query,
            "packages": [{"name": "formula", **package_contract}],
            "begin_date": package_contract["begin_date"],
        }, env)
        outputs = _formula_output_names(formulas)
        evaluation = _evaluate_formula_result(outputs, package_result)
        if evaluation.get("success"):
            successful_required.add("formula")
            receipt = evaluation["receipt_file"]
            attempts.append({"role": "formula", "route": "formula_batch", "status": "success", "covered_fields": outputs})
            package = {"name": "formula", "role": "formula", "kind": "formula", "contract": package_contract, "validation_receipt_file": receipt}
            formula_packages.append(package)
            selected_routes.append({"role": "formula", "kind": "formula", "receipt_file": receipt})
        else:
            record_failure("formula", "formula_batch", evaluation)

    complete = bool(required_roles) and set(required_roles).issubset(successful_required)
    all_required_attempted = set(required_roles).issubset(attempted_required)
    all_required_failed_data = (
        bool(required_roles)
        and all_required_attempted
        and not successful_required
        and set(required_roles).issubset(failed_required)
        and all(item.get("error_class") == "data" for item in attempts if item.get("role") in required_roles)
    )
    if blocked:
        status = "blocked"
    elif complete:
        status = "live"
    elif all_required_failed_data:
        status = "static_fallback_allowed"
    else:
        status = "incomplete"
    receipt_payload = {
        "schema": "live_data_route_receipt_v1",
        "version": "live_data_route_receipt_v1",
        "task_id": task_id,
        "asset": asset,
        "status": status,
        "required_roles": required_roles,
        "attempted_roles": [role for role in required_roles if role in attempted_required],
        "attempts": attempts,
        "selected_routes": selected_routes,
        "required_roles_complete": complete,
        "static_fallback_allowed": status == "static_fallback_allowed",
        "warnings": warnings,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    receipt_file = _write_live_data_route_receipt(receipt_payload)
    return {
        "code": 0 if status in ("live", "static_fallback_allowed") else 1,
        "success": status == "live",
        "status": status,
        "task_id": task_id,
        "asset": asset,
        "attempts": attempts,
        "grants": grants,
        "formula_packages": formula_packages,
        "warnings": warnings,
        "route_receipt_file": receipt_file,
        "required_roles_complete": complete,
        "static_fallback_allowed": status == "static_fallback_allowed",
    }


def _grant_validation_receipt(task_id, role_name, kind, fingerprint):
    root = QBV_ROOT / "output" / "grant_validation_receipts"
    root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(f"{task_id}:{role_name}:{fingerprint}".encode("utf-8")).hexdigest()
    path = root / f"{digest}.json"
    payload = {
        "version": "grant_validation_receipt_v1",
        "task_id": task_id,
        "role": role_name,
        "kind": kind,
        "contract_fingerprint": fingerprint,
        "status": "completed",
        "success": True,
        "validated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(path)


def _validate_grant_set(call_script, params, env):
    grants = params.get("grants")
    if not isinstance(grants, list):
        return {"code": 1, "error": "INVALID_GRANTS", "message": "grants 必须是数组"}
    task_id = str(params.get("task_id") or "").strip()
    user_query = str(params.get("user_query") or "").strip()
    tool_by_kind = {
        "fast_query": "fast_query",
        "stock_profile": "stockProfile",
        "composition_select": "selectByComposition",
    }
    names = set()
    results = []
    receipts = []
    for index, item in enumerate(grants):
        if not isinstance(item, dict):
            return {"code": 1, "error": "INVALID_GRANT", "message": f"grants[{index}] 必须是对象"}
        name = str(item.get("name") or item.get("role_id") or "").strip()
        contract = item.get("contract") if isinstance(item.get("contract"), dict) else {}
        kind = str(contract.get("kind") or "").strip()
        payload = contract.get("payload")
        fingerprint = str(item.get("contract_fingerprint") or "").strip()
        actual_fingerprint = FRC.contract_fingerprint(contract)
        if not name or name in names:
            return {"code": 1, "error": "INVALID_GRANT_NAME", "message": f"grants[{index}].name 缺失或重复"}
        if kind not in tool_by_kind or not isinstance(payload, dict) or not payload:
            return {"code": 1, "error": "INVALID_GRANT_CONTRACT", "message": f"grants[{index}] kind/payload 无效"}
        if fingerprint != actual_fingerprint:
            return {"code": 1, "error": "GRANT_FINGERPRINT_MISMATCH", "message": f"grants[{index}] fingerprint 不一致"}
        names.add(name)
        validation_payload = dict(payload)
        validation_payload.update({"task_id": task_id, "user_query": user_query})
        result, error = _invoke_payload(call_script, tool_by_kind[kind], validation_payload, env)
        if error:
            return {**error, "success": False, "failed_grant": name, "grants": results}
        if kind == "fast_query":
            assets = payload.get("assets") if isinstance(payload.get("assets"), list) else []
            asset = str((assets or [payload.get("asset") or ""])[0] or "").strip()
            required_fields = payload.get("required_fields") if isinstance(payload.get("required_fields"), list) else payload.get("fields") or []
            optional = payload.get("optional_fields") if isinstance(payload.get("optional_fields"), list) else []
            evaluation = _evaluate_fast_query_result(asset, required_fields, optional, result)
        elif kind == "stock_profile":
            asset = str(payload.get("asset") or "").strip()
            required_fields = payload.get("required_fields") if isinstance(payload.get("required_fields"), list) else payload.get("fields") or payload.get("dimensions") or []
            evaluation = _evaluate_stock_profile_result(asset, required_fields, result)
        else:
            if result.get("code") not in (0, None) or result.get("success") is False or not any(_is_meaningful_value(result.get(key)) for key in ("data", "results")):
                error_class, error_code = _classify_route_error(result)
                evaluation = {"success": False, "error_class": error_class, "error_code": error_code}
            else:
                evaluation = {"success": True}
        if not evaluation.get("success"):
            return {
                "code": 1,
                "error": "GRANT_VALIDATION_FAILED",
                "success": False,
                "failed_grant": name,
                "error_class": evaluation.get("error_class"),
                "error_code": evaluation.get("error_code"),
                "missing_fields": evaluation.get("missing_fields") or [],
                "result": result,
                "grants": results,
            }
        receipt = _grant_validation_receipt(task_id, name, kind, fingerprint)
        receipts.append(receipt)
        results.append({
            "name": name,
            "role": str(item.get("role") or name),
            "kind": kind,
            "status": _payload_status(result) or "completed",
            "contract_fingerprint": fingerprint,
            "validation_receipt_file": receipt,
            "reply_evidence": RDE.compact_grant_result(kind, result),
        })
    return {
        "code": 0,
        "success": True,
        "task_id": task_id,
        "grant_count": len(results),
        "validation_receipt_files": receipts,
        "grants": results,
    }

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"code": 1, "error": "TOOL_REQUIRED", "message": "用法: qbs_bridge.py <tool> [@params.json]"}, ensure_ascii=False))
        return 1
    tool_name = sys.argv[1]
    if tool_name == "newSession":
        print(json.dumps({"code": 1, "error": "BRIDGE_OWNS_SESSION", "message": "qbs_bridge 自动继承 QBV task_id，不接受 newSession"}, ensure_ascii=False))
        return 1
    try:
        params = _read_params(sys.argv[2:])
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"code": 1, "error": "INPUT_ERROR", "message": str(exc)}, ensure_ascii=False))
        return 1

    task_id = str(params.get("task_id") or "").strip()
    context_params = dict(params)
    context = C.configure_trace_context(context_params)
    task_id = str(context.get("task_id") or task_id).strip()
    turn_id = str(context.get("turn_id") or "").strip()
    user_query = str(context.get("user_query") or "").strip()
    if not task_id or not turn_id or not user_query:
        missing = [key for key, value in (("task_id", task_id), ("turn_id", turn_id), ("user_query", user_query)) if not value]
        print(json.dumps({"code": 1, "error": "QBV_TRACE_CONTEXT_REQUIRED", "missing": missing}, ensure_ascii=False))
        return 1

    qbs_root = _qbs_root()
    call_script = qbs_root / "scripts" / "call.py"
    if not call_script.is_file():
        print(json.dumps({"code": 1, "error": "QBS_NOT_FOUND", "message": str(call_script)}, ensure_ascii=False))
        return 1

    session_key = _session_key(task_id)
    if not session_key:
        print(json.dumps({"code": 1, "error": "INVALID_TASK_ID"}, ensure_ascii=False))
        return 1
    agent_model = context.get("agent_model")

    env = dict(os.environ)
    env["QBS_SESSION_KEY"] = session_key
    env.setdefault("PYTHONUTF8", "1")
    # 身份跨 skill 传递：两边的「本次调用用哪个 key」通道同档但不同名（QBV_API_KEY / QBS_API_KEY），
    # 光靠继承 os.environ 传不过去——qbs 不认识 QBV_API_KEY，会一路兜底到它自己 config.json 里的
    # 默认账号，于是用户的取数调用被记到那个账号名下（计费归错账，终态推送也显示错用户）。
    # 桥接层是唯一同时知道两套变量名的地方，翻译责任在这里。
    _forward_api_key(env)

    bootstrapped = False
    if not _session_ready(_session_path(qbs_root, session_key), task_id):
        bootstrap_params = {
            "task_mode": "inherit",
            "task_id": task_id,
            "task_source": "quant-buddy-view",
            "turn_id": turn_id,
            "user_query": user_query,
        }
        if agent_model:
            bootstrap_params["agent_model"] = agent_model
        bootstrap = _invoke(call_script, "newSession", bootstrap_params, env)
        if bootstrap.returncode != 0:
            sys.stdout.buffer.write(bootstrap.stdout)
            sys.stderr.buffer.write(bootstrap.stderr)
            return bootstrap.returncode or 1
        bootstrapped = True

    qbs_session = _read_session(_session_path(qbs_root, session_key))
    if not bootstrapped and str(qbs_session.get("current_turn_id") or "") != turn_id:
        sync_params = {
            "task_id": task_id, "turn_id": turn_id, "user_query": user_query,
            "parent_turn_id": context.get("previous_turn_id"),
        }
        sync_params = {key: value for key, value in sync_params.items() if value}
        sync = _invoke(call_script, "beginTurn", sync_params, env)
        if sync.returncode != 0:
            sys.stdout.buffer.write(sync.stdout)
            sys.stderr.buffer.write(sync.stderr)
            return sync.returncode or 1

    params["task_id"] = task_id
    params["turn_id"] = turn_id
    params["user_query"] = user_query
    if tool_name == "validate_package_set":
        payload = _validate_package_set(call_script, params, env)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("code") == 0 else 1
    if tool_name == "validate_grant_set":
        payload = _validate_grant_set(call_script, params, env)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("code") == 0 else 1
    if tool_name == "resolve_asset_data":
        payload = _resolve_asset_data(call_script, params, env)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("code") == 0 else 1
    result = _invoke(call_script, tool_name, params, env)
    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
