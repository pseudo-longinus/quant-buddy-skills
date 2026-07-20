import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone


VERSION = "qb_validation_receipt_v1"
SUPPORTED_TOOLS = {"runMultiFormulaBatchStream", "resumeJob"}


def _payload_data(payload):
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else payload


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
        outputs.append({
            "expression_id": item.get("expression_id") or item.get("leftName") or "",
            "data_id": item.get("data_id") or item.get("indexinfo_id") or "",
            "status": "success",
        })
    digest_source = json.dumps(outputs, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
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


def _receipt_root():
    override = str(os.environ.get("QBS_VALIDATION_RECEIPT_DIR") or "").strip()
    if override:
        return os.path.abspath(override)
    skill_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(skill_root, "output", "validation_receipts")


def write_receipt(tool_name, params, payload):
    receipt = build_receipt(tool_name, params or {}, payload)
    if receipt is None:
        return None
    root = _receipt_root()
    os.makedirs(root, exist_ok=True)
    task_hash = hashlib.sha256(receipt["task_id"].encode("utf-8")).hexdigest()[:16]
    filename = f"{task_hash}-{receipt['outputs_sha256'][:16]}.json"
    path = os.path.join(root, filename)
    fd, temp_path = tempfile.mkstemp(prefix=".receipt-", suffix=".json", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(receipt, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_path, path)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise
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
