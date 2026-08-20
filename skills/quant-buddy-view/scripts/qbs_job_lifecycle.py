#!/usr/bin/env python3
"""Optional lifecycle bridge for QBS-created QBV Job records.

QBV remains standalone: when no matching ``qbs_qbv_job_v2`` record exists every
operation is a no-op.  When QBS supplied a Job, this module closes the local
queued/running/completed/failed audit state without asking the model to edit
JSON by hand.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


JOB_SCHEMA_VERSION = "qbs_qbv_job_v2"
_ACTIVE_STATUSES = {"queued", "running"}
_SKILL_URL_PATTERNS = (
    re.compile(r"/pages/(skill_[A-Za-z0-9_-]+)/(?P<page>page_[A-Za-z0-9_-]+)\.html(?:[?#]|$)"),
    re.compile(r"/playground/(skill_[A-Za-z0-9_-]+)/(?P<page>page_[A-Za-z0-9_-]+)(?:[/?#]|$)"),
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _job_root(job_dir: Any = None) -> Path:
    configured = _text(job_dir) or os.environ.get("QBS_QBV_JOB_DIR", "").strip()
    return Path(configured) if configured else Path(tempfile.gettempdir()) / "quant-buddy-qbv-jobs"


def _read_job(path: Path) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != JOB_SCHEMA_VERSION:
        return None
    return payload


def _matches(payload: Dict[str, Any], *, qbv_job_id: str, task_id: str, turn_id: str) -> bool:
    if qbv_job_id and payload.get("qbv_job_id") != qbv_job_id:
        return False
    if task_id and payload.get("task_id") != task_id:
        return False
    if turn_id and payload.get("turn_id") != turn_id:
        return False
    return True


def find_job(
    *,
    qbv_job_id: Any = None,
    task_id: Any = None,
    turn_id: Any = None,
    job_file: Any = None,
    job_dir: Any = None,
) -> Tuple[Optional[Path], Optional[Dict[str, Any]], str]:
    """Resolve one QBS Job and fail closed when identity is ambiguous."""
    job_id = _text(qbv_job_id)
    task = _text(task_id)
    turn = _text(turn_id)
    explicit = _text(job_file)

    if explicit:
        path = Path(explicit).expanduser().resolve()
        payload = _read_job(path)
        if payload is None:
            return None, None, "job_invalid"
        if not _matches(payload, qbv_job_id=job_id, task_id=task, turn_id=turn):
            return None, None, "job_identity_mismatch"
        return path, payload, "job_found"

    # A standalone QBV publish must never discover and mutate an unrelated QBS
    # Job merely because the shared job directory currently contains one file.
    # Without an explicit file, require either the Job id or the full Turn lineage.
    if not job_id and not (task and turn):
        return None, None, "job_identity_required"

    root = _job_root(job_dir)
    if not root.exists():
        return None, None, "job_not_found"
    matches = []
    for path in root.glob("*.job.json"):
        payload = _read_job(path)
        if payload is not None and _matches(payload, qbv_job_id=job_id, task_id=task, turn_id=turn):
            matches.append((path.resolve(), payload))
    if not matches:
        return None, None, "job_not_found"
    if len(matches) != 1:
        return None, None, "job_ambiguous"
    return matches[0][0], matches[0][1], "job_found"


class _JobLock:
    def __init__(self, job_path: Path, timeout: float = 5.0):
        self.path = job_path.with_suffix(job_path.suffix + ".lock")
        self.timeout = timeout
        self.fd: Optional[int] = None

    def __enter__(self):
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, f"{os.getpid()}\n".encode("ascii"))
                return self
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("QBS_QBV_JOB_LOCK_TIMEOUT")
                time.sleep(0.05)

    def __exit__(self, exc_type, exc, tb):
        if self.fd is not None:
            os.close(self.fd)
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def _atomic_write(path: Path, payload: Dict[str, Any]) -> None:
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp_path, path)


def _result(updated: bool, reason: str, path: Optional[Path], payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    result = {"updated": updated, "reason": reason}
    if path is not None:
        result["job_file"] = str(path)
    if isinstance(payload, dict):
        for key in ("qbv_job_id", "task_id", "turn_id", "status", "target_skill_id", "target_page_id", "public_url"):
            if payload.get(key) is not None:
                result[key] = payload.get(key)
    return result


def mark_job_running(
    *,
    qbv_job_id: Any = None,
    task_id: Any = None,
    turn_id: Any = None,
    job_file: Any = None,
    job_dir: Any = None,
    target_skill_id: Any = None,
) -> Dict[str, Any]:
    path, payload, reason = find_job(
        qbv_job_id=qbv_job_id,
        task_id=task_id,
        turn_id=turn_id,
        job_file=job_file,
        job_dir=job_dir,
    )
    if path is None or payload is None:
        return _result(False, reason, path, payload)
    with _JobLock(path):
        record = _read_job(path)
        if record is None:
            return _result(False, "job_invalid", path, None)
        status = record.get("status")
        if status == "running":
            return _result(False, "already_running", path, record)
        if status in {"completed", "failed"}:
            return _result(False, f"already_{status}", path, record)
        if status != "queued":
            return _result(False, "invalid_job_status", path, record)
        now = _utc_now()
        record.update({"status": "running", "updated_at": now, "started_at": record.get("started_at") or now, "failed_at": None})
        skill_id = _text(target_skill_id)
        if skill_id:
            record["target_skill_id"] = skill_id
        _atomic_write(path, record)
        return _result(True, "marked_running", path, record)


def _skill_id_from_url(public_url: Any) -> str:
    url = _text(public_url)
    for pattern in _SKILL_URL_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    return ""


def complete_job_from_publish_result(params: Dict[str, Any], publish_result: Dict[str, Any]) -> Dict[str, Any]:
    """Close a matching Job only after the publisher proves terminal success."""
    if not isinstance(publish_result, dict):
        return _result(False, "publish_result_invalid", None, None)
    if publish_result.get("code") != 0 or publish_result.get("published") is not True or publish_result.get("verified") is not True:
        return _result(False, "publish_not_verified", None, None)

    page_id = _text(publish_result.get("page_id") or params.get("page_id"))
    public_url = _text(publish_result.get("public_url"))
    target_skill_id = _text(params.get("target_skill_id")) or _skill_id_from_url(public_url)
    if not page_id or not public_url or not target_skill_id:
        return _result(False, "terminal_identity_incomplete", None, None)

    path, payload, reason = find_job(
        qbv_job_id=params.get("qbv_job_id"),
        task_id=params.get("task_id"),
        turn_id=params.get("turn_id"),
        job_file=params.get("qbv_job_file") or params.get("job_file"),
        job_dir=params.get("qbv_job_dir"),
    )
    if path is None or payload is None:
        return _result(False, reason, path, payload)

    with _JobLock(path):
        record = _read_job(path)
        if record is None:
            return _result(False, "job_invalid", path, None)
        if record.get("status") == "completed":
            same_terminal = (
                record.get("target_skill_id") == target_skill_id
                and record.get("target_page_id") == page_id
                and record.get("public_url") == public_url
                and record.get("published") is True
                and record.get("public_verified") is True
            )
            return _result(False, "already_completed" if same_terminal else "completed_identity_conflict", path, record)
        if record.get("status") == "failed":
            return _result(False, "already_failed", path, record)
        if record.get("status") not in _ACTIVE_STATUSES:
            return _result(False, "invalid_job_status", path, record)
        now = _utc_now()
        record.update({
            "status": "completed",
            "target_skill_id": target_skill_id,
            "target_page_id": page_id,
            "public_url": public_url,
            "published": True,
            "public_verified": True,
            "failure_code": None,
            "retryable": False,
            "updated_at": now,
            "started_at": record.get("started_at") or now,
            "completed_at": now,
            "failed_at": None,
        })
        _atomic_write(path, record)
        return _result(True, "marked_completed", path, record)


def fail_job(
    *,
    failure_code: Any,
    retryable: bool = False,
    qbv_job_id: Any = None,
    task_id: Any = None,
    turn_id: Any = None,
    job_file: Any = None,
    job_dir: Any = None,
) -> Dict[str, Any]:
    code = _text(failure_code)
    if not code:
        return _result(False, "failure_code_required", None, None)
    path, payload, reason = find_job(
        qbv_job_id=qbv_job_id,
        task_id=task_id,
        turn_id=turn_id,
        job_file=job_file,
        job_dir=job_dir,
    )
    if path is None or payload is None:
        return _result(False, reason, path, payload)
    with _JobLock(path):
        record = _read_job(path)
        if record is None:
            return _result(False, "job_invalid", path, None)
        if record.get("status") == "completed":
            return _result(False, "already_completed", path, record)
        if record.get("status") == "failed":
            return _result(False, "already_failed", path, record)
        if record.get("status") not in _ACTIVE_STATUSES:
            return _result(False, "invalid_job_status", path, record)
        now = _utc_now()
        record.update({
            "status": "failed",
            "failure_code": code,
            "retryable": bool(retryable),
            "updated_at": now,
            "completed_at": None,
            "failed_at": now,
        })
        _atomic_write(path, record)
        return _result(True, "marked_failed", path, record)
