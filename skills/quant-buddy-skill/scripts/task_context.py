"""Shared task-id context rules for quant-buddy-skill entry points."""

import re
import uuid


TASK_MODE_STANDALONE = "standalone"
TASK_MODE_INHERIT = "inherit"
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class TaskContextError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _validate_task_id(value):
    task_id = str(value or "").strip()
    if not task_id or not _TASK_ID_RE.fullmatch(task_id):
        raise TaskContextError(
            "INVALID_INHERITED_TASK_ID",
            "inherit 模式需要合法 task_id（1-128 位字母、数字、点、下划线、冒号或短横线）",
        )
    return task_id


def build_new_session_context(params=None, uuid_factory=None):
    """Resolve standalone generation vs explicit upstream inheritance."""
    params = params if isinstance(params, dict) else {}
    mode = str(params.get("task_mode") or TASK_MODE_STANDALONE).strip().lower()
    if mode not in {TASK_MODE_STANDALONE, TASK_MODE_INHERIT}:
        raise TaskContextError(
            "INVALID_TASK_MODE",
            "task_mode 仅支持 standalone 或 inherit",
        )

    requested_task_id = params.get("task_id")
    if mode == TASK_MODE_INHERIT:
        task_id = _validate_task_id(requested_task_id)
        source = str(params.get("task_source") or "upstream").strip() or "upstream"
        return {
            "task_id": task_id,
            "task_mode": TASK_MODE_INHERIT,
            "task_id_source": "inherited",
            "task_source": source[:64],
            "task_id_locked": True,
            "report_session_begin": False,
        }

    if requested_task_id not in (None, ""):
        raise TaskContextError(
            "TASK_MODE_INHERIT_REQUIRED",
            "newSession 传入已有 task_id 时必须显式设置 task_mode=inherit",
        )
    factory = uuid_factory or uuid.uuid4
    return {
        "task_id": str(factory()),
        "task_mode": TASK_MODE_STANDALONE,
        "task_id_source": "generated",
        "task_source": "quant-buddy-skill",
        "task_id_locked": False,
        "report_session_begin": True,
    }


def session_context_fields(context):
    return {
        key: context[key]
        for key in ("task_mode", "task_id_source", "task_source", "task_id_locked")
        if key in context
    }


def inject_or_validate_task_id(session, params):
    """Inject the session id, and fail closed on inherited-session drift."""
    session = session if isinstance(session, dict) else {}
    params = params if isinstance(params, dict) else {}
    session_task_id = str(session.get("task_id") or "").strip()
    request_task_id = str(params.get("task_id") or "").strip()

    if (
        session.get("task_id_locked") is True
        and session_task_id
        and request_task_id
        and request_task_id != session_task_id
    ):
        raise TaskContextError(
            "TASK_ID_CONTEXT_MISMATCH",
            f"当前继承 session 已锁定 task_id={session_task_id}，拒绝切换到 {request_task_id}",
        )
    if session_task_id and not request_task_id:
        params["task_id"] = session_task_id
        return True
    return False


def may_replace_session_task_id(session, response_task_id):
    session = session if isinstance(session, dict) else {}
    current = str(session.get("task_id") or "").strip()
    incoming = str(response_task_id or "").strip()
    if not incoming or incoming == current:
        return False
    return not (session.get("task_id_locked") is True and current)
