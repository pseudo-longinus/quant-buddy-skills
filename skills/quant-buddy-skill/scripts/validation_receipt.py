import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone


VERSION = "qb_validation_receipt_v1"
FORMULA_RUNTIME_SCHEMA_VERSION = "qbs_formula_runtime_contract_v1"
CONTINUATION_CONTEXT_VERSION = "qbs_formula_continuation_context_v1"
SUPPORTED_TOOLS = {"runMultiFormulaBatchStream", "resumeJob"}


def _payload_data(payload):
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else payload


_TOPN_RE = re.compile(
    r'^\s*取前\(\s*"([^"]+)"\s*,\s*(\d+)\s*(?:,\s*(返回数值)\s*)?\)\s*$'
)
_TOPN_MINUS_REF_RE = re.compile(
    r'^\s*取前\(\s*"([^"]+)"\s*,\s*(\d+)\s*(?:,\s*(返回数值)\s*)?\)'
    r'\s*-\s*"([^"]+)"\s*$'
)
_QUOTED_REF_RE = re.compile(r'"([^"]+)"')


def _formula_assignments(formulas):
    assignments = {}
    for formula in formulas:
        if "=" not in formula:
            return None
        left, right = formula.split("=", 1)
        left = left.strip()
        if not left or left in assignments:
            return None
        assignments[left] = right.strip()
    return assignments


def _bounded_output_sizes(formulas):
    """Infer only output cardinalities that are provably bounded by formula shape.

    Formula Package ``last_day_stats`` returns at most ten ranked values.  It is
    therefore safe only when the QBS formula itself proves that an output has at
    most ten non-zero assets.  The supported shapes deliberately stay narrow:
    direct ``取前`` outputs, a difference between nested prefixes from the same
    source (Top20 - Top10), and a metric multiplied by such a bounded mask.
    Unknown shapes remain without a runtime contract instead of guessing.
    """
    assignments = _formula_assignments(formulas)
    if assignments is None:
        return {}

    topn = {}
    for name, right in assignments.items():
        match = _TOPN_RE.fullmatch(right)
        if match:
            topn[name] = {
                "source": match.group(1),
                "size": int(match.group(2)),
                "returns_value": bool(match.group(3)),
            }

    memo = {}
    visiting = set()

    def infer(name):
        if name in memo:
            return memo[name]
        if name in visiting or name not in assignments:
            return None
        visiting.add(name)
        result = None
        direct = topn.get(name)
        if direct is not None:
            result = direct["size"]
        else:
            right = assignments[name]
            refs = _QUOTED_REF_RE.findall(right)
            inline_difference = _TOPN_MINUS_REF_RE.fullmatch(right)
            if inline_difference:
                larger = {
                    "source": inline_difference.group(1),
                    "size": int(inline_difference.group(2)),
                    "returns_value": bool(inline_difference.group(3)),
                }
                smaller = topn.get(inline_difference.group(4))
                if (
                    smaller is not None
                    and larger["source"] == smaller["source"]
                    and larger["returns_value"] == smaller["returns_value"]
                    and larger["size"] >= smaller["size"]
                ):
                    result = larger["size"] - smaller["size"]
            elif "-" in right and len(refs) == 2:
                larger = topn.get(refs[0])
                smaller = topn.get(refs[1])
                if (
                    larger is not None
                    and smaller is not None
                    and larger["source"] == smaller["source"]
                    and larger["returns_value"] == smaller["returns_value"]
                    and larger["size"] >= smaller["size"]
                ):
                    result = larger["size"] - smaller["size"]
            if result is None and "*" in right:
                bounds = [infer(ref) for ref in refs]
                bounds = [bound for bound in bounds if isinstance(bound, int) and bound > 0]
                if bounds:
                    result = min(bounds)
        visiting.remove(name)
        memo[name] = result
        return result

    for name in assignments:
        infer(name)
    return memo


def _safe_runtime_reads(formulas, reusable):
    if not reusable:
        return None
    bounds = _bounded_output_sizes(formulas)
    if any(not isinstance(bounds.get(output), int) or not 1 <= bounds[output] <= 10 for output in reusable):
        return None
    return [{"output": output, "read_mode": "last_day_stats"} for output in reusable]


def _formula_runtime_contract(tool_name, params):
    if tool_name != "runMultiFormulaBatchStream" or not isinstance(params, dict):
        return None
    raw_formulas = params.get("formulas")
    if not isinstance(raw_formulas, list) or not raw_formulas:
        return None
    formulas = []
    for raw in raw_formulas:
        if not isinstance(raw, str) or not raw.strip():
            return None
        formulas.append(raw)

    raw_reusable = params.get("force_reusable_array")
    if raw_reusable is None:
        raw_reusable = []
    if not isinstance(raw_reusable, list):
        return None
    reusable = []
    for raw in raw_reusable:
        if not isinstance(raw, str) or not raw.strip():
            return None
        output = raw.strip()
        if output not in reusable:
            reusable.append(output)

    reads = _safe_runtime_reads(formulas, reusable)
    if reads is None:
        return None

    contract = {
        "schema_version": FORMULA_RUNTIME_SCHEMA_VERSION,
        "formulas": formulas,
        "include_description": bool(params.get("include_description", False)),
        "use_minute_data": bool(params.get("use_minute_data", False)),
        "force_reusable_array": reusable,
        "reads": reads,
    }
    if params.get("begin_date") is not None:
        contract["begin_date"] = params.get("begin_date")
    digest_source = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    contract["contract_fingerprint"] = "sha256:" + hashlib.sha256(digest_source.encode("utf-8")).hexdigest()
    return contract


def _runtime_formulas_by_output(runtime_contract):
    if not isinstance(runtime_contract, dict):
        return {}
    formulas = runtime_contract.get("formulas")
    if not isinstance(formulas, list):
        return {}
    result = {}
    for formula in formulas:
        if not isinstance(formula, str) or "=" not in formula:
            continue
        output = formula.split("=", 1)[0].strip()
        if output:
            result[output] = formula
    return result


def _bind_receipt_outputs_to_runtime(receipt):
    runtime_contract = receipt.get("runtime_contract") if isinstance(receipt, dict) else None
    formulas_by_output = _runtime_formulas_by_output(runtime_contract)
    outputs = receipt.get("outputs") if isinstance(receipt, dict) else None
    if not formulas_by_output or not isinstance(outputs, list):
        return receipt

    formulas = runtime_contract.get("formulas") if isinstance(runtime_contract, dict) else None
    ordered_names = []
    if isinstance(formulas, list):
        ordered_names = [
            formula.split("=", 1)[0].strip()
            for formula in formulas
            if isinstance(formula, str) and "=" in formula
        ]
    positional_binding_allowed = len(ordered_names) == len(outputs) and len(ordered_names) == len(formulas_by_output)

    for index, item in enumerate(outputs):
        if not isinstance(item, dict):
            continue
        index_title = str(item.get("index_title") or "").strip()
        if not index_title:
            expression_id = str(item.get("expression_id") or "").strip()
            if expression_id in formulas_by_output:
                index_title = expression_id
            elif positional_binding_allowed:
                # QBS summary/resume responses may replace formula left names with
                # opaque expression IDs. The backend preserves submitted formula
                # order; bind only when the result count exactly matches the
                # runtime contract, mirroring QBV qbs_bridge's strict seam.
                index_title = ordered_names[index]
            if index_title:
                item["index_title"] = index_title
        formula = formulas_by_output.get(index_title)
        if formula:
            item["formula"] = formula
    digest_source = json.dumps(outputs, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    receipt["outputs_sha256"] = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()
    return receipt


def build_receipt(tool_name, params, payload):
    if tool_name not in SUPPORTED_TOOLS or not isinstance(payload, dict):
        return None
    data = _payload_data(payload)
    task_id = str(payload.get("task_id") or params.get("task_id") or data.get("task_id") or "").strip()
    results = data.get("results") if isinstance(data.get("results"), list) else []
    status = str(data.get("status") or payload.get("status") or "").lower()
    success = payload.get("code") == 0 and payload.get("success") is True
    if status not in {"ok", "done", "completed"}:
        success = False
    if not task_id or not success or payload.get("errors"):
        return None
    if any(not isinstance(item, dict) or item.get("status") != "success" for item in results):
        return None

    outputs = []
    for item in results:
        index_info = item.get("index_info") if isinstance(item.get("index_info"), dict) else {}
        index_title = str(item.get("leftName") or index_info.get("index_title") or "").strip()
        output = {
            "expression_id": item.get("expression_id") or item.get("leftName") or "",
            "data_id": item.get("data_id") or item.get("indexinfo_id") or "",
            "status": "success",
        }
        if index_title:
            output["index_title"] = index_title
        outputs.append(output)
    digest_source = json.dumps(outputs, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    receipt = {
        "version": VERSION,
        "task_id": task_id,
        "tool_name": tool_name,
        "status": "completed",
        "success": True,
        "failures": [],
        "outputs": outputs,
        "outputs_sha256": hashlib.sha256(digest_source.encode("utf-8")).hexdigest(),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    runtime_contract = _formula_runtime_contract(tool_name, params)
    if runtime_contract is not None:
        receipt["runtime_contract"] = runtime_contract
    return _bind_receipt_outputs_to_runtime(receipt)


def _receipt_root():
    override = str(os.environ.get("QBS_VALIDATION_RECEIPT_DIR") or "").strip()
    if override:
        return os.path.abspath(override)
    skill_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(skill_root, "output", "validation_receipts")


def _continuation_root():
    override = str(os.environ.get("QBS_FORMULA_CONTINUATION_DIR") or "").strip()
    if override:
        return os.path.abspath(override)
    return os.path.join(_receipt_root(), "_continuations")


def _continuation_ids(params, payload):
    params = params if isinstance(params, dict) else {}
    payload = payload if isinstance(payload, dict) else {}
    data = _payload_data(payload)
    task_id = str(payload.get("task_id") or params.get("task_id") or data.get("task_id") or "").strip()
    trace_id = str(payload.get("trace_id") or params.get("trace_id") or data.get("trace_id") or "").strip()
    return task_id, trace_id


def _continuation_path(task_id, trace_id):
    identity = json.dumps([task_id, trace_id], ensure_ascii=False, separators=(",", ":"))
    filename = hashlib.sha256(identity.encode("utf-8")).hexdigest() + ".json"
    return os.path.join(_continuation_root(), filename)


def _write_json_atomic(path, value, prefix):
    root = os.path.dirname(path)
    os.makedirs(root, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=prefix, suffix=".json", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_path, path)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def _runtime_contract_is_valid(contract):
    if not isinstance(contract, dict) or contract.get("schema_version") != FORMULA_RUNTIME_SCHEMA_VERSION:
        return False
    fingerprint = str(contract.get("contract_fingerprint") or "")
    unsigned = {key: value for key, value in contract.items() if key != "contract_fingerprint"}
    digest_source = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    expected = "sha256:" + hashlib.sha256(digest_source.encode("utf-8")).hexdigest()
    return fingerprint == expected


def _is_deferred(payload):
    if not isinstance(payload, dict):
        return False
    data = _payload_data(payload)
    status = str(payload.get("status") or data.get("status") or "").strip().lower()
    return payload.get("_deferred") is True or status == "deferred"


def _record_deferred_runtime_contract(tool_name, params, payload):
    if tool_name != "runMultiFormulaBatchStream" or not _is_deferred(payload):
        return None
    contract = _formula_runtime_contract(tool_name, params)
    task_id, trace_id = _continuation_ids(params, payload)
    if contract is None or not task_id or not trace_id:
        return None
    context = {
        "version": CONTINUATION_CONTEXT_VERSION,
        "task_id": task_id,
        "trace_id": trace_id,
        "runtime_contract": contract,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    path = _continuation_path(task_id, trace_id)
    _write_json_atomic(path, context, ".continuation-")
    return path


def _load_deferred_runtime_contract(tool_name, params, payload):
    if tool_name != "resumeJob":
        return None
    task_id, trace_id = _continuation_ids(params, payload)
    if not task_id or not trace_id:
        return None
    path = _continuation_path(task_id, trace_id)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            context = json.load(handle)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(context, dict) or context.get("version") != CONTINUATION_CONTEXT_VERSION:
        return None
    if context.get("task_id") != task_id or context.get("trace_id") != trace_id:
        return None
    contract = context.get("runtime_contract")
    return contract if _runtime_contract_is_valid(contract) else None


def write_receipt(tool_name, params, payload):
    params = params or {}
    _record_deferred_runtime_contract(tool_name, params, payload)
    receipt = build_receipt(tool_name, params, payload)
    if receipt is None:
        return None
    if "runtime_contract" not in receipt:
        runtime_contract = _load_deferred_runtime_contract(tool_name, params, payload)
        if runtime_contract is not None:
            receipt["runtime_contract"] = runtime_contract
    _bind_receipt_outputs_to_runtime(receipt)
    root = _receipt_root()
    os.makedirs(root, exist_ok=True)
    task_hash = hashlib.sha256(receipt["task_id"].encode("utf-8")).hexdigest()[:16]
    filename = f"{task_hash}-{receipt['outputs_sha256'][:16]}.json"
    path = os.path.join(root, filename)
    _write_json_atomic(path, receipt, ".receipt-")
    return path


def apply_output_mode(payload, mode="full"):
    if not isinstance(payload, dict):
        return payload
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    status = str(payload.get("status") or data.get("status") or "").strip().lower()
    is_deferred = payload.get("_deferred") is True or status == "deferred"
    if is_deferred:
        missing = [key for key in ("task_id", "trace_id") if not (payload.get(key) or data.get(key))]
        if missing:
            return {
                "code": 1,
                "success": False,
                "error": "DEFERRED_CONTINUATION_MISSING",
                "message": "deferred 响应缺少续传所需 task_id/trace_id，禁止重新提交原批次",
                "missing": missing,
                "status": "deferred",
                "task_id": payload.get("task_id") or data.get("task_id"),
            }
    if mode != "summary":
        return payload
    compact = {
        key: payload[key]
        for key in (
            "code",
            "success",
            "status",
            "task_id",
            "trace_id",
            "job_id",
            "stream_url",
            "execution_profile",
            "queue",
            "_deferred",
            "message",
            "validation_receipt_file",
        )
        if key in payload
    }
    results = data.get("results") if isinstance(data.get("results"), list) else []
    compact["data"] = {
        "status": data.get("status"),
        "summary": data.get("summary") or {},
        "results": [
            {key: item.get(key) for key in ("expression_id", "data_id", "indexinfo_id", "status", "errorCode", "message") if item.get(key) is not None}
            for item in results if isinstance(item, dict)
        ],
    }
    if payload.get("errors"):
        compact["errors"] = payload["errors"]
    return compact
