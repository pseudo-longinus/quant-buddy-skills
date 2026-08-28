#!/usr/bin/env python3
"""为一次 quant-buddy-view 用户任务建立可贯穿后端接口的 task_id。

用法：
  python scripts/trace_context.py begin '{"user_query":"生成茅台估值活页"}'
  python scripts/trace_context.py beginTurn '{"task_id":"已有 task_id","user_query":"继续追问"}'
  python scripts/trace_context.py beginHandoff '{"handoff_file":"D:/.../handoff.json"}'

后续每个命令复用同一 task_id；每条新的用户消息先 beginTurn。QBS 并行交接使用 beginHandoff，
复用 Handoff 已有 task_id + turn_id，不创建新的用户 Turn。
"""

import json
import sys
import uuid
from pathlib import Path

import common as C
from qbs_handoff_adapter import evaluate_handoff


def _host_result(params, next_step=None):
    host = C.host_trace_context(params)
    if not host:
        return None
    previous = C.read_task_trace_context(host["task_id"])
    previous_turn_id = str(previous.get("current_turn_id") or "").strip() or None
    if previous_turn_id == host["turn_id"]:
        previous_turn_id = previous.get("previous_turn_id")
    C.configure_trace_context({
        **params,
        "task_id": host["task_id"],
        "turn_id": host["turn_id"],
        "user_query": host["user_query"],
    })
    agent_model = C.current_trace_context().get("agent_model")
    task_root = C.task_temp_dir(host["task_id"], create=True)
    if not _commit_context(
        host["task_id"], host["turn_id"], host["user_query"], previous_turn_id, agent_model
    ):
        return {"code": 1, "error": "TRACE_CONTEXT_PERSIST_FAILED"}
    result = {
        "code": 0,
        "success": True,
        "task_id": host["task_id"],
        "turn_id": host["turn_id"],
        "user_query": host["user_query"],
        "parent_turn_id": previous_turn_id,
        "created": False,
        "tracking_recorded": True,
        "tracking_owner": "claw-backend",
        "host_managed": True,
        "task_temp_dir": str(task_root),
        "instruction": "Host 已建立本轮 Turn；后续 QBV/QBS 工具必须复用当前 task_id 与 turn_id。",
    }
    if next_step:
        result["next_step"] = next_step
    return result


def _turn_payload(params, task_id, turn_id, user_query, parent_turn_id=None):
    body = {
        "task_id": task_id,
        "turn_id": turn_id,
        "user_query": user_query,
        "agent_intent": C.current_trace_context().get("agent_intent"),
    }
    message_id = str(params.get("message_id") or "").strip()
    if message_id:
        body["message_id"] = message_id
    if parent_turn_id:
        body["parent_turn_id"] = parent_turn_id
    agent_model = C.current_trace_context().get("agent_model")
    if agent_model:
        body["agent_model"] = agent_model
    return body


def _snapshot_process_context():
    return C.current_trace_context(), C._API_KEY_OVERRIDE


def _restore_process_context(snapshot):
    context, api_key_override = snapshot
    C.set_trace_context(
        context.get("task_id"), context.get("user_query"),
        api_key_override=api_key_override, agent_model=context.get("agent_model"),
        turn_id=context.get("turn_id"), previous_turn_id=context.get("previous_turn_id"),
        agent_intent=context.get("agent_intent"),
    )


def _commit_context(task_id, turn_id, user_query, previous_turn_id, agent_model, handoff_context=None,
                    agent_intent=None):
    if not C.persist_task_trace_context(
        task_id, turn_id, user_query, previous_turn_id=previous_turn_id, agent_model=agent_model,
        handoff_context=handoff_context, agent_intent=agent_intent,
    ):
        return False
    C.set_trace_context(
        task_id, user_query, api_key_override=C._API_KEY_OVERRIDE, agent_model=agent_model,
        turn_id=turn_id, previous_turn_id=previous_turn_id, agent_intent=agent_intent,
    )
    return True


def _reuse_active_handoff_turn(params, task_id, user_query):
    """Guard the QBS→QBV boundary against accidentally creating a second user Turn.

    A QBV worker entered through beginHandoff already owns a persisted QBS task_id + turn_id.
    Calling plain begin again with the same task must be a no-op; a different query/turn is a
    follow-up and must use beginTurn instead of silently overwriting the lineage.
    """
    previous = C.read_task_trace_context(task_id)
    handoff_context = previous.get("handoff_context")
    if not isinstance(handoff_context, dict):
        return None

    persisted_turn_id = str(previous.get("current_turn_id") or "").strip()
    persisted_query = str(previous.get("current_user_query") or "").strip()
    requested_turn_id = str(params.get("turn_id") or "").strip()
    conflicts = []
    if requested_turn_id and requested_turn_id != persisted_turn_id:
        conflicts.append("turn_id")
    if user_query and persisted_query and user_query != persisted_query:
        conflicts.append("user_query")
    if conflicts or not persisted_turn_id or not persisted_query:
        return {
            "code": 1,
            "error": "QBS_HANDOFF_CONTEXT_ACTIVE",
            "message": "该 task_id 已由 QBS Handoff 建立；同一轮请继续复用，新的用户消息请调用 beginTurn。",
            "conflicts": conflicts,
            "task_id": task_id,
            "turn_id": persisted_turn_id or None,
        }

    persisted_intent = C.normalize_agent_intent(previous.get("current_agent_intent"))
    context_params = {
        "task_id": task_id,
        "turn_id": persisted_turn_id,
        "user_query": persisted_query,
        "agent_intent": persisted_intent,
    }
    if "agent_model" in params:
        context_params["agent_model"] = params.get("agent_model")
    C.configure_trace_context(context_params)
    return {
        "code": 0,
        "success": True,
        "task_id": task_id,
        "turn_id": persisted_turn_id,
        "user_query": persisted_query,
        "agent_intent": persisted_intent,
        "created": False,
        "tracking_recorded": False,
        "tracking_skipped": True,
        "tracking_reason": "REUSED_QBS_HANDOFF_TURN",
        "task_temp_dir": str(C.task_temp_dir(task_id, create=True)),
        "next_step": "existing_page" if handoff_context.get("route") == "existing_page" else "templates",
        "instruction": "检测到 QBS Handoff，已复用原 task_id + turn_id；禁止再次 begin/beginTurn，继续 QBV SOP。",
    }


def cmd_begin(params):
    host_result = _host_result(params, next_step="templates")
    if host_result:
        return host_result
    task_id = str(params.get("task_id") or uuid.uuid4()).strip()
    user_query = str(params.get("user_query") or params.get("userQuery") or "").strip()
    if not user_query:
        return {"code": 1, "error": "USER_QUERY_REQUIRED", "message": "trace begin 需要 user_query（用户原始问题）"}

    handoff_reuse = _reuse_active_handoff_turn(params, task_id, user_query)
    if handoff_reuse is not None:
        return handoff_reuse

    cfg = C.load_config_require_key()
    endpoint, api_key = C.endpoint_of(cfg), cfg.get("api_key", "")
    turn_id = str(params.get("turn_id") or uuid.uuid4()).strip()
    previous_process_context = _snapshot_process_context()
    agent_intent = C.normalize_agent_intent(params.get("agent_intent"))
    context_params = {
        "task_id": task_id,
        "turn_id": turn_id,
        "user_query": user_query,
        "agent_intent": agent_intent,
    }
    if "agent_model" in params:
        context_params["agent_model"] = params.get("agent_model")
    C.configure_trace_context(context_params)
    agent_model = C.current_trace_context().get("agent_model")
    body = _turn_payload(params, task_id, turn_id, user_query)
    try:
        out = C.http_json(
            "POST", C.api_url(endpoint, "/skill/session/begin"), C.headers(api_key), body, timeout=30,
        )
    except Exception as exc:
        out = {
            "code": -1, "success": False,
            "error": {"code": "TURN_TRACKING_REQUEST_FAILED", "message": str(exc)},
        }
    tracking_recorded = bool(isinstance(out, dict) and out.get("code") == 0 and out.get("success"))
    tracking_error = None
    if tracking_recorded and out.get("task_id") in (None, "", task_id):
        # message_id 幂等重试可能返回首次写入的 canonical turn_id。
        turn_id = str(out.get("turn_id") or turn_id).strip()
        if "agent_intent" in out:
            agent_intent = C.normalize_agent_intent(out.get("agent_intent"))
    else:
        tracking_recorded = False
        C.record_turn_tracking_diagnostic(task_id, turn_id, "begin", out)
    task_root = C.task_temp_dir(task_id, create=True)
    if not _commit_context(task_id, turn_id, user_query, None, agent_model, agent_intent=agent_intent):
        _restore_process_context(previous_process_context)
        return {"code": 1, "error": "TRACE_CONTEXT_PERSIST_FAILED", "message": "服务端已创建 Turn，但本地上下文持久化失败"}
    return {
        "code": 0, "task_id": task_id, "turn_id": turn_id, "user_query": user_query,
        "agent_intent": agent_intent,
        "created": bool(out.get("created")) if tracking_recorded else False,
        "tracking_recorded": tracking_recorded, "tracking_error": tracking_error,
        "task_temp_dir": str(task_root), "next_step": "templates",
        "instruction": (
            "后续每个 quant-buddy-view 命令传入此 task_id；独立进程会自动恢复当前 turn_id。"
            "简单单一 A 股分析可直接 new_asset_page，跳过 templates/new_page；其余场景先 "
            "templates(recommend=\"all\") 判定路由。"
            "同一 Session 的下一条用户追问先调用 trace_context.py beginTurn；同一页面继续复用 page_id/URL。"
        ),
    }


def cmd_begin_turn(params):
    host_result = _host_result(params)
    if host_result:
        return host_result
    cfg = C.load_config_require_key()
    endpoint, api_key = C.endpoint_of(cfg), cfg.get("api_key", "")
    task_id = str(params.get("task_id") or "").strip()
    user_query = str(params.get("user_query") or params.get("userQuery") or "").strip()
    if not task_id or not user_query:
        missing = [name for name, value in (("task_id", task_id), ("user_query", user_query)) if not value]
        return {"code": 1, "error": "TURN_CONTEXT_REQUIRED", "missing": missing}
    previous = C.read_task_trace_context(task_id)
    parent_turn_id = str(params.get("parent_turn_id") or previous.get("current_turn_id") or "").strip() or None
    turn_id = str(params.get("turn_id") or uuid.uuid4()).strip()
    previous_process_context = _snapshot_process_context()
    agent_intent = C.normalize_agent_intent(params.get("agent_intent"))
    context_params = {
        "task_id": task_id,
        "turn_id": turn_id,
        "user_query": user_query,
        "agent_intent": agent_intent,
    }
    if "agent_model" in params:
        context_params["agent_model"] = params.get("agent_model")
    C.configure_trace_context(context_params)
    agent_model = C.current_trace_context().get("agent_model")
    body = _turn_payload(params, task_id, turn_id, user_query, parent_turn_id)
    try:
        out = C.http_json(
            "POST", C.api_url(endpoint, "/skill/session/turn"), C.headers(api_key), body, timeout=30,
        )
    except Exception as exc:
        out = {
            "code": -1, "success": False,
            "error": {"code": "TURN_TRACKING_REQUEST_FAILED", "message": str(exc)},
        }
    tracking_recorded = bool(isinstance(out, dict) and out.get("code") == 0 and out.get("success"))
    tracking_error = None
    if tracking_recorded and out.get("task_id") in (None, "", task_id):
        # message_id 幂等重试可能返回首次写入的 canonical turn_id。
        turn_id = str(out.get("turn_id") or turn_id).strip()
        if "agent_intent" in out:
            agent_intent = C.normalize_agent_intent(out.get("agent_intent"))
    else:
        tracking_recorded = False
        C.record_turn_tracking_diagnostic(task_id, turn_id, "beginTurn", out)
    if not _commit_context(
        task_id, turn_id, user_query, parent_turn_id, agent_model, agent_intent=agent_intent
    ):
        _restore_process_context(previous_process_context)
        return {"code": 1, "error": "TRACE_CONTEXT_PERSIST_FAILED"}
    return {
        "code": 0, "success": True, "task_id": task_id, "turn_id": turn_id,
        "parent_turn_id": parent_turn_id, "user_query": user_query,
        "agent_intent": agent_intent,
        "created": bool(out.get("created")) if tracking_recorded else False,
        "tracking_recorded": tracking_recorded, "tracking_error": tracking_error,
        "instruction": "本轮后续 QBV/QBS 工具会共享此 turn_id；更新既有页面时继续复用原 page_id/URL。",
    }


def _load_handoff(params):
    handoff = params.get("handoff")
    handoff_file = str(params.get("handoff_file") or "").strip()
    if isinstance(handoff, dict):
        return handoff, None
    if handoff_file:
        try:
            payload = json.loads(Path(handoff_file).read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return None, {
                "code": 1,
                "error": "HANDOFF_FILE_INVALID",
                "message": str(exc),
                "handoff_file": handoff_file,
            }
        if not isinstance(payload, dict):
            return None, {
                "code": 1,
                "error": "HANDOFF_OBJECT_REQUIRED",
                "message": "handoff_file 顶层必须是 JSON object",
                "handoff_file": handoff_file,
            }
        return payload, None
    if params.get("schema_version"):
        return dict(params), None
    return None, {
        "code": 1,
        "error": "HANDOFF_REQUIRED",
        "message": "beginHandoff 需要 handoff object、handoff_file 或顶层 Handoff 字段",
    }


def _validate_handoff(handoff):
    if not isinstance(handoff, dict):
        return {"code": 1, "error": "HANDOFF_OBJECT_REQUIRED"}
    if handoff.get("schema_version") != "qbs_qbv_handoff_v1":
        return {
            "code": 1,
            "error": "HANDOFF_SCHEMA_UNSUPPORTED",
            "expected": "qbs_qbv_handoff_v1",
        }
    route = str(handoff.get("route") or "").strip()
    if route not in {"create", "existing_page"}:
        return {
            "code": 1,
            "error": "HANDOFF_ROUTE_INVALID",
            "allowed": ["create", "existing_page"],
        }
    required = ("task_id", "turn_id", "user_query")
    missing = [name for name in required if not str(handoff.get(name) or "").strip()]
    if missing:
        return {"code": 1, "error": "HANDOFF_FIELDS_REQUIRED", "missing": missing}
    source_skill_id = str(handoff.get("source_skill_id") or "").strip() or None
    source_status = str(handoff.get("source_skill_id_status") or ("available" if source_skill_id else "unavailable")).strip()
    if source_status not in {"available", "unavailable"}:
        return {"code": 1, "error": "HANDOFF_SOURCE_STATUS_INVALID"}
    if bool(source_skill_id) != (source_status == "available"):
        return {"code": 1, "error": "HANDOFF_SOURCE_STATUS_MISMATCH"}
    if not source_skill_id and not str(handoff.get("source_skill_name") or "").strip():
        return {"code": 1, "error": "HANDOFF_SOURCE_NAME_REQUIRED"}
    for name in ("requires_persistence_confirmation", "persistence_confirmed"):
        if name in handoff and not isinstance(handoff.get(name), bool):
            return {"code": 1, "error": "HANDOFF_BOOLEAN_INVALID", "field": name}
    if handoff.get("requires_persistence_confirmation") and not handoff.get("persistence_confirmed"):
        return {
            "code": 1,
            "error": "PERSISTENCE_CONFIRMATION_REQUIRED",
            "message": "高风险持久状态尚未获得用户确认，QBV 不得开始页面写入",
        }
    for name in ("route_reason", "validated_outputs", "validation_receipts"):
        if name in handoff and not isinstance(handoff.get(name), list):
            return {"code": 1, "error": "HANDOFF_LIST_INVALID", "field": name}
    if "computation_capsule" in handoff and not isinstance(handoff.get("computation_capsule"), dict):
        return {"code": 1, "error": "HANDOFF_CAPSULE_INVALID"}
    return None


def _handoff_instruction(reuse):
    coverage = str((reuse or {}).get("coverage") or "unusable")
    covered = ", ".join((reuse or {}).get("covered_roles") or [])
    missing = ", ".join((reuse or {}).get("missing_roles") or [])
    base = (
        "已复用 QBS 的 task_id + turn_id，禁止再次 begin/beginTurn。"
        "继续执行 QBV 完整 SOP，自行判断 direct/fork/unmatched 与页面 ownership；"
    )
    if coverage == "covered":
        return base + f"计算胶囊已覆盖 [{covered}]，禁止通过 qbs_bridge 重复识别资产或重算这些角色；继续完成页面构建、运行时注册、发布和验收。"
    if coverage == "partial":
        return base + f"计算胶囊已覆盖 [{covered}]，仅可通过 qbs_bridge 补齐 [{missing}]，不得重复计算已覆盖角色。"
    return base + "计算胶囊不可用或未提供，按 QBV 原有 QBS bridge 流程正常探测和验证，不得降低现有发布门禁。"


def cmd_begin_handoff(params):
    handoff, load_error = _load_handoff(params)
    if load_error:
        return load_error
    validation_error = _validate_handoff(handoff)
    if validation_error:
        return validation_error

    task_id = str(handoff["task_id"]).strip()
    turn_id = str(handoff["turn_id"]).strip()
    user_query = str(handoff["user_query"]).strip()
    agent_intent = C.normalize_agent_intent(handoff.get("agent_intent"))
    source_skill_id = str(handoff.get("source_skill_id") or "").strip() or None
    source_skill_id_status = str(
        handoff.get("source_skill_id_status") or ("available" if source_skill_id else "unavailable")
    ).strip()
    source_skill_name = str(handoff.get("source_skill_name") or "quant-buddy-skill").strip()
    source_skill_version = str(handoff.get("source_skill_version") or "").strip() or None
    reuse = evaluate_handoff(handoff)
    previous = C.read_task_trace_context(task_id)
    previous_turn_id = str(previous.get("previous_turn_id") or "").strip() or None
    previous_process_context = _snapshot_process_context()

    context_params = {
        "task_id": task_id,
        "turn_id": turn_id,
        "user_query": user_query,
        "agent_intent": agent_intent,
    }
    if "agent_model" in params:
        context_params["agent_model"] = params.get("agent_model")
    C.configure_trace_context(context_params)
    agent_model = C.current_trace_context().get("agent_model")
    handoff_context = {
        "schema_version": handoff["schema_version"],
        "source_task_id": task_id,
        "source_turn_id": turn_id,
        "source_user_query": user_query,
        "source_agent_intent": agent_intent,
        "source_skill_id": source_skill_id,
        "source_skill_id_status": source_skill_id_status,
        "source_skill_name": source_skill_name,
        "source_skill_version": source_skill_version,
        "route": str(handoff["route"]).strip(),
        "route_reason": list(handoff.get("route_reason") or []),
        "page_reference": handoff.get("page_reference"),
        "validated_outputs": list(handoff.get("validated_outputs") or []),
        "validation_receipts": list(handoff.get("validation_receipts") or []),
        "computation_capsule": handoff.get("computation_capsule"),
        "computation_reuse": reuse,
        "requires_persistence_confirmation": bool(handoff.get("requires_persistence_confirmation")),
        "persistence_confirmed": bool(handoff.get("persistence_confirmed")),
        "handoff_file": str(params.get("handoff_file") or "").strip() or None,
    }
    if not _commit_context(
        task_id, turn_id, user_query, previous_turn_id, agent_model,
        handoff_context=handoff_context, agent_intent=agent_intent
    ):
        _restore_process_context(previous_process_context)
        return {"code": 1, "error": "TRACE_CONTEXT_PERSIST_FAILED"}

    task_root = C.task_temp_dir(task_id, create=True)
    return {
        "code": 0,
        "success": True,
        "task_id": task_id,
        "turn_id": turn_id,
        "user_query": user_query,
        "agent_intent": agent_intent,
        "source_skill_id": source_skill_id,
        "source_skill_id_status": source_skill_id_status,
        "source_skill_name": source_skill_name,
        "source_skill_version": source_skill_version,
        "route": handoff_context["route"],
        "computation_reuse": reuse,
        "tracking_recorded": False,
        "tracking_skipped": True,
        "tracking_reason": "REUSED_QBS_TURN",
        "task_temp_dir": str(task_root),
        "next_step": "existing_page" if handoff_context["route"] == "existing_page" else "templates",
        "instruction": _handoff_instruction(reuse),
    }


_COMMANDS = {
    "begin": cmd_begin,
    "beginTurn": cmd_begin_turn,
    "begin-turn": cmd_begin_turn,
    "beginHandoff": cmd_begin_handoff,
    "begin-handoff": cmd_begin_handoff,
}



def main():
    if len(sys.argv) < 2 or sys.argv[1] not in _COMMANDS:
        C.emit({"code": 1, "message": "用法: trace_context.py begin|beginTurn|beginHandoff [params]"}, out_name="trace_out.txt")
        sys.exit(1)
    params = C.read_params(sys.argv[2:], env_var="TRACE_PARAMS")
    result = _COMMANDS[sys.argv[1]](params)
    C.emit(result, out_name="trace_out.txt")
    sys.exit(0 if isinstance(result, dict) and result.get("code") == 0 else 1)


if __name__ == "__main__":
    main()
