#!/usr/bin/env python3
"""任务终态埋点：把「这次任务做完了、页面在这里」上报给后端。

用法：
  python scripts/session_complete.py report '{"task_id":"...","public_url":"https://...","user_query":"..."}'

通常不需要手工调用——`validate_agent_reply.py` 在 `valid=true` 后会自动调 `report()`。

这里只上报 Agent 本来就知道的 task_id / public_url / user_query / operation；用户身份由后端用
api_key 反查补齐，skill 侧既拿不到也不需要。

**best-effort 契约**：本模块任何失败（网络不通、后端 5xx、配置缺失）都必须被吞掉，
返回值不参与任何门禁判断，绝不影响发布流程或最终回复。
"""

import sys

import common as C

_TIMEOUT = 10


def report(task_id, public_url="", user_query="", operation=""):
    """上报一次任务终态。永不抛异常，返回是否成功送达（仅供调试，不参与门禁）。"""
    try:
        if C.host_managed_lifecycle():
            return True
        task_id = str(task_id or "").strip()
        if not task_id:
            return False
        cfg = C.load_config_require_key()
        body = {"task_id": task_id}
        for key, value in (("public_url", public_url), ("user_query", user_query), ("operation", operation)):
            value = str(value or "").strip()
            if value:
                body[key] = value
        out = C.http_json(
            "POST",
            C.api_url(C.endpoint_of(cfg), "/skill/session/complete"),
            C.headers(cfg.get("api_key", "")),
            body,
            timeout=_TIMEOUT,
        )
        return isinstance(out, dict) and out.get("code") == 0
    except Exception:
        return False


def cmd_report(params):
    ok = report(
        params.get("task_id"),
        params.get("public_url"),
        params.get("user_query"),
        params.get("operation"),
    )
    return {
        "code": 0,
        "reported": ok,
        "host_managed": C.host_managed_lifecycle(),
        "tracking_owner": "claw-backend" if C.host_managed_lifecycle() else "quant-buddy-view",
    }


_COMMANDS = {"report": cmd_report}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in _COMMANDS:
        C.emit({"code": 1, "message": "用法: session_complete.py report [params]"}, out_name="session_complete_out.txt")
        sys.exit(1)
    params = C.read_params(sys.argv[2:], env_var="SESSION_COMPLETE_PARAMS")
    C.emit(_COMMANDS[sys.argv[1]](params), out_name="session_complete_out.txt")
    sys.exit(0)


if __name__ == "__main__":
    main()
