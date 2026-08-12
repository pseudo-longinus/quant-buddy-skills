#!/usr/bin/env python3
"""为一次 quant-buddy-view 用户任务建立可贯穿后端接口的 task_id。

用法：
  python scripts/trace_context.py begin '{"user_query":"生成茅台估值活页"}'
  python scripts/trace_context.py beginTurn '{"task_id":"已有 task_id","user_query":"继续追问"}'

后续每个命令复用同一 task_id；每条新的用户消息先 beginTurn。
"""

import sys
import uuid

import common as C


def _turn_payload(params, task_id, turn_id, user_query, parent_turn_id=None):
    body = {"task_id": task_id, "turn_id": turn_id, "user_query": user_query}
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
    )


def _commit_context(task_id, turn_id, user_query, previous_turn_id, agent_model):
    if not C.persist_task_trace_context(
        task_id, turn_id, user_query, previous_turn_id=previous_turn_id, agent_model=agent_model
    ):
        return False
    C.set_trace_context(
        task_id, user_query, api_key_override=C._API_KEY_OVERRIDE, agent_model=agent_model,
        turn_id=turn_id, previous_turn_id=previous_turn_id,
    )
    return True


def cmd_begin(params):
    cfg = C.load_config_require_key()
    endpoint, api_key = C.endpoint_of(cfg), cfg.get("api_key", "")
    task_id = str(params.get("task_id") or uuid.uuid4()).strip()
    turn_id = str(params.get("turn_id") or uuid.uuid4()).strip()
    user_query = str(params.get("user_query") or params.get("userQuery") or "").strip()
    if not user_query:
        return {"code": 1, "error": "USER_QUERY_REQUIRED", "message": "trace begin 需要 user_query（用户原始问题）"}

    previous_process_context = _snapshot_process_context()
    context_params = {"task_id": task_id, "turn_id": turn_id, "user_query": user_query}
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
    else:
        tracking_recorded = False
        tracking_error = out
    task_root = C.task_temp_dir(task_id, create=True)
    if not _commit_context(task_id, turn_id, user_query, None, agent_model):
        _restore_process_context(previous_process_context)
        return {"code": 1, "error": "TRACE_CONTEXT_PERSIST_FAILED", "message": "服务端已创建 Turn，但本地上下文持久化失败"}
    return {
        "code": 0, "task_id": task_id, "turn_id": turn_id, "user_query": user_query,
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
    context_params = {"task_id": task_id, "turn_id": turn_id, "user_query": user_query}
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
    else:
        tracking_recorded = False
        tracking_error = out
    if not _commit_context(task_id, turn_id, user_query, parent_turn_id, agent_model):
        _restore_process_context(previous_process_context)
        return {"code": 1, "error": "TRACE_CONTEXT_PERSIST_FAILED"}
    return {
        "code": 0, "success": True, "task_id": task_id, "turn_id": turn_id,
        "parent_turn_id": parent_turn_id, "user_query": user_query,
        "created": bool(out.get("created")) if tracking_recorded else False,
        "tracking_recorded": tracking_recorded, "tracking_error": tracking_error,
        "instruction": "本轮后续 QBV/QBS 工具会共享此 turn_id；更新既有页面时继续复用原 page_id/URL。",
    }


_COMMANDS = {"begin": cmd_begin, "beginTurn": cmd_begin_turn, "begin-turn": cmd_begin_turn}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in _COMMANDS:
        C.emit({"code": 1, "message": "用法: trace_context.py begin|beginTurn [params]"}, out_name="trace_out.txt")
        sys.exit(1)
    params = C.read_params(sys.argv[2:], env_var="TRACE_PARAMS")
    result = _COMMANDS[sys.argv[1]](params)
    C.emit(result, out_name="trace_out.txt")
    sys.exit(0 if isinstance(result, dict) and result.get("code") == 0 else 1)


if __name__ == "__main__":
    main()
