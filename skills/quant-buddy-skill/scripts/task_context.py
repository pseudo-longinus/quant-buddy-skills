"""Shared task/turn context rules for quant-buddy-skill entry points."""

import json
import os
import re
import time
import uuid


TASK_MODE_STANDALONE = "standalone"
TASK_MODE_INHERIT = "inherit"
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TURN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MAX_AGENT_INTENT_CHARS = 300
_TURN_SESSION_KEYS = (
    "current_turn_id",
    "previous_turn_id",
)


def record_turn_tracking_diagnostic(session_file, operation, task_id, turn_id, detail):
    """Best-effort local audit detail that is never returned to the Agent-facing response."""
    try:
        target = os.environ.get("QBS_TRACKING_DIAGNOSTIC_FILE", "").strip()
        if not target:
            target = f"{session_file}.tracking.jsonl"
        parent = os.path.dirname(os.path.abspath(target))
        if parent:
            os.makedirs(parent, exist_ok=True)
        if isinstance(detail, str):
            detail_text = detail
        else:
            try:
                detail_text = json.dumps(detail, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                detail_text = str(detail)
        payload = {
            "timestamp_ms": int(time.time() * 1000),
            "source": "quant-buddy-skill",
            "operation": str(operation or "turnTracking"),
            "task_id": str(task_id or "").strip() or None,
            "turn_id": str(turn_id or "").strip() or None,
            "detail": detail_text[:8000],
        }
        with open(target, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return True
    except (OSError, TypeError, ValueError):
        return False


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


def _validate_turn_id(value):
    turn_id = str(value or "").strip()
    if not turn_id or not _TURN_ID_RE.fullmatch(turn_id):
        raise TaskContextError(
            "INVALID_TURN_ID",
            "turn_id 需要为 1-128 位字母、数字、点、下划线、冒号或短横线",
        )
    return turn_id


def normalize_agent_intent(value):
    """Normalize optional per-Turn intent without deriving it from user_query."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized[:_MAX_AGENT_INTENT_CHARS] or None


def tracking_reason_code(detail, default="TURN_TRACKING_FAILED"):
    """Extract a stable tracking reason without exposing diagnostic text."""
    if isinstance(detail, dict):
        direct = detail.get("reason_code")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        error = detail.get("error")
        if isinstance(error, dict):
            nested = error.get("code")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
        if isinstance(error, str) and error.strip():
            return error.strip()
    code = getattr(detail, "code", None)
    if isinstance(code, str) and code.strip():
        return code.strip()
    return default


def tracking_result_outcome(result, expected_task_id, attempted_turn_id):
    """Return (recorded, canonical_turn_id, canonical_intent, reason_code)."""
    if not isinstance(result, dict):
        return False, None, None, "TURN_TRACKING_RESPONSE_INVALID"
    if result.get("code") != 0 or result.get("success") is False or result.get("tracking_recorded") is False:
        return False, None, None, tracking_reason_code(result)
    if result.get("task_id") not in (None, "", expected_task_id):
        return False, None, None, "TURN_TASK_CONTEXT_MISMATCH"
    canonical_turn_id = str(result.get("turn_id") or "").strip()
    if not canonical_turn_id:
        return False, None, None, "TURN_ID_MISSING"
    canonical_intent = normalize_agent_intent(
        result.get("agent_intent") if "agent_intent" in result else None
    )
    return True, canonical_turn_id, canonical_intent, None


def build_turn_context(session, params=None, uuid_factory=None):
    """Build one immutable user-turn context without mutating the session."""
    session = session if isinstance(session, dict) else {}
    params = params if isinstance(params, dict) else {}
    task_id = str(params.get("task_id") or session.get("task_id") or "").strip()
    if not task_id:
        raise TaskContextError("TASK_ID_REQUIRED", "beginTurn 前必须先调用 newSession")
    session_task_id = str(session.get("task_id") or "").strip()
    if session_task_id and task_id != session_task_id:
        raise TaskContextError(
            "TASK_ID_CONTEXT_MISMATCH",
            f"当前 session 的 task_id={session_task_id}，拒绝为 {task_id} 创建 Turn",
        )
    user_query = str(params.get("user_query") or "").strip()
    if not user_query:
        raise TaskContextError("USER_QUERY_REQUIRED", "beginTurn 需要本轮用户原话 user_query")
    factory = uuid_factory or uuid.uuid4
    requested_turn_id = params.get("turn_id")
    turn_id = _validate_turn_id(requested_turn_id) if requested_turn_id else str(factory())
    parent_turn_id = str(
        params.get("parent_turn_id") or session.get("current_turn_id") or ""
    ).strip() or None
    message_id = str(params.get("message_id") or "").strip() or None
    return {
        "task_id": task_id,
        "turn_id": turn_id,
        "user_query": user_query,
        "agent_intent": normalize_agent_intent(params.get("agent_intent")),
        "message_id": message_id,
        "parent_turn_id": parent_turn_id,
    }


def turn_session_fields(turn_context, previous_session=None):
    """Return the non-overwriting session projection for a committed Turn."""
    previous_session = previous_session if isinstance(previous_session, dict) else {}
    initial = previous_session.get("initial_user_query")
    if initial is None:
        initial = turn_context.get("user_query")
    if "initial_agent_intent" in previous_session:
        initial_agent_intent = normalize_agent_intent(previous_session.get("initial_agent_intent"))
    elif previous_session.get("current_turn_id"):
        # Legacy sessions did not record the first Turn intent; do not invent one from a follow-up.
        initial_agent_intent = None
    else:
        initial_agent_intent = normalize_agent_intent(turn_context.get("agent_intent"))
    return {
        "current_turn_id": turn_context.get("turn_id"),
        "current_turn_trusted": True,
        "current_user_query": turn_context.get("user_query"),
        "current_agent_intent": normalize_agent_intent(turn_context.get("agent_intent")),
        "previous_turn_id": turn_context.get("parent_turn_id"),
        "initial_user_query": initial,
        "initial_agent_intent": initial_agent_intent,
    }


def clear_turn_session_context(session, user_query=None, agent_intent=None):
    """Remove any propagatable Turn while retaining the real business context."""
    session = session if isinstance(session, dict) else {}
    had_initial_query = bool(session.get("initial_user_query"))
    for key in _TURN_SESSION_KEYS:
        session.pop(key, None)
    session["current_turn_trusted"] = False
    if user_query is not None:
        query = str(user_query).strip()
        session["user_query"] = query
        session["current_user_query"] = query
        if not had_initial_query:
            session["initial_user_query"] = query
    session["current_agent_intent"] = normalize_agent_intent(agent_intent)
    if "initial_agent_intent" not in session and not had_initial_query:
        session["initial_agent_intent"] = normalize_agent_intent(agent_intent)
    return session


def inject_or_validate_turn_context(session, params, warnings=None, suppress_session_turn=False):
    """Best-effort Turn injection; tracing drift never blocks a business tool."""
    session = session if isinstance(session, dict) else {}
    params = params if isinstance(params, dict) else {}
    warnings = warnings if isinstance(warnings, list) else []
    turn_id = str(session.get("current_turn_id") or "").strip()
    turn_trusted = (
        bool(turn_id)
        and session.get("current_turn_trusted") is not False
        and not suppress_session_turn
    )
    current_query = str(session.get("current_user_query") or session.get("user_query") or "").strip()
    request_turn_id = str(params.get("turn_id") or "").strip()
    request_query = str(params.get("user_query") or params.get("userQuery") or "").strip()

    if not turn_trusted:
        changed = "turn_id" in params
        params.pop("turn_id", None)
        if request_query and "user_query" not in params:
            params["user_query"] = request_query
            params.pop("userQuery", None)
            changed = True
        elif current_query and not request_query:
            params["user_query"] = current_query
            changed = True
        return changed

    turn_mismatch = bool(request_turn_id and request_turn_id != turn_id)
    query_mismatch = bool(current_query and request_query and request_query != current_query)
    if turn_mismatch or query_mismatch:
        warnings.append({
            "code": "TURN_CONTEXT_MISMATCH",
            "message": (
                f"Turn 上下文不一致，已取消 Turn 关联并继续业务调用："
                f"session_turn={turn_id or '-'}, request_turn={request_turn_id or '-'}"
            ),
        })
        # Preserve the caller's real question, but never send a stale/mismatched
        # turn_id that could attach this tool call to another Session.
        changed = "turn_id" in params
        params.pop("turn_id", None)
        if request_query and "user_query" not in params:
            params["user_query"] = request_query
            params.pop("userQuery", None)
            changed = True
        return changed

    changed = False
    if turn_id and not request_turn_id:
        params["turn_id"] = turn_id
        changed = True
    if current_query and not request_query:
        params["user_query"] = current_query
        changed = True
    elif request_query and "user_query" not in params:
        params["user_query"] = request_query
        params.pop("userQuery", None)
        changed = True
    return changed
