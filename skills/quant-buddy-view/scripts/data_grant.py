#!/usr/bin/env python3
r"""
数据授权（Data Grant）客户端 —— 把一次直取数请求钉死成签名凭证，页面凭证免 key 反复取数。

对接接口文档：skill_server/docs/dataGrant相关文档/数据授权-技术设计文档.md
工具说明文档：tools/data_grant.md

两段式使用：
  1. 注册（需 API Key）：提交 kind + payload（一次 fastQuery / stockProfile /
     selectByComposition 请求），服务端先「试跑」确认命中/出数、校验白名单，
     再落库返回 grant_id + signature（signature 仅此一次明文返回，请妥善保存）。
  2. 取数（无需 API Key）：凭 grant_id + signature 取数，普通 JSON 返回（非 SSE，
     不重算）——钉死的是"查什么"，底层数据更新后取数永远拿最新结果。

子命令：
    register  注册数据授权（读 config.json 的 api_key + endpoint）
    query     取数（无需 api_key，凭 grant_id + signature）
    list      列出我的数据授权（需 api_key）
    revoke    撤销数据授权（需 api_key）
    refresh   重新试跑校验仍可用，可选轮换签名（需 api_key）

参数传递（规避 PowerShell GBK 截断中文）：
    优先级：DG_PARAMS 环境变量 > @file > 命令行 JSON > stdin

用法示例：
    # 注册（推荐用 @file 传参）
    python scripts/data_grant.py register @params.json

    # 取数（grant_id + signature 即可，不需要 api_key；signature 可由本地凭证补全）
    DG_PARAMS='{"grant_id":"dg_xxx"}' python scripts/data_grant.py query

    # 管理
    python scripts/data_grant.py list '{"page":1,"page_size":20}'
    python scripts/data_grant.py revoke '{"grant_id":"dg_xxx"}'
    python scripts/data_grant.py refresh '{"grant_id":"dg_xxx","rotate_signature":true}'

输出：
    结果打印到 stdout（UTF-8），并写入临时目录下 dg_out.txt（防终端缓冲吞输出）。
    register / refresh(rotate) 成功时，凭证额外落盘到 output/data_grants/<grant_id>.json，
    方便后续取数与 build_dashboard 引用（signature 服务端不可再取出，本地不存丢失即不可恢复）。

认证：register/list/revoke/refresh 凭 config.json 的 api_key（Bearer）认身份；query 以 grant_id + signature
为能力凭证，CLI 本地有 api_key 时会可选附带用于审计归因，浏览器无 Key 取数仍兼容。活页任务通过参数复用 trace_context.py begin 返回的 task_id，
公共 headers() 会自动透传 x-task-id 供后端聚合调用链。
"""

import json
import os
import sys

import common as C

SKILL_ROOT = C.SKILL_ROOT

# 数据授权接口前缀固定带 /skill（服务端 router 同时挂在 / 与 /skill，endpoint 带不带 /skill 均可解析）
_PATH = {
    "register": "/skill/registerDataGrant",
    "query":    "/skill/queryDataGrant",
    "list":     "/skill/listDataGrants",
    "revoke":   "/skill/revokeDataGrant",
    "refresh":  "/skill/refreshDataGrant",
}

_DEFAULT_TIMEOUT = 600
import grant_capabilities as GC
import runtime_credentials as RC
import execution_plan as EP

_ALLOWED_KINDS = frozenset(GC.TOOL_BY_KIND)
_CRED_DIR = os.path.join(SKILL_ROOT, "output", "data_grants")


def _config(require_key):
    """加载 endpoint(+api_key)。query 子命令 require_key=False（取数无需 api_key）。"""
    cfg = C.load_config_require_key() if require_key else C.load_config()
    return C.endpoint_of(cfg), cfg.get("api_key", "")


def _save_credential(reg):
    if not reg.get("grant_id") or not reg.get("signature"):
        return None
    return RC.save_legacy("grant", reg, _CRED_DIR)


def load_credential(grant_id, task_id=None):
    return RC.load("grant", grant_id, _CRED_DIR, task=task_id)


def _preflight_register_params(params):
    details = GC.contract_errors(params)
    return {"ok": not details, "errors": [item["message"] for item in details], "details": details}


# ────────────────────────────────────────────────
# 子命令
# ────────────────────────────────────────────────

def cmd_register(params):
    preflight = _preflight_register_params(params)
    if not preflight["ok"]:
        return {
            "code": 1,
            "error": "PREFLIGHT_FAILED",
            "message": "数据授权注册参数预检失败",
            "_preflight": preflight,
        }
    endpoint, api_key = _config(require_key=True)
    body = {"kind": params.get("kind"), "payload": params.get("payload")}
    for k in ("ttl_days", "task_id", "user_query"):
        if params.get(k) is not None:
            body[k] = params[k]
    try:
        reg = RC.register("grant", params, {"kind": body["kind"], "payload": body["payload"]}, endpoint, api_key,
                          lambda: C.http_json("POST", C.api_url(endpoint, _PATH["register"]), C.headers(api_key), body, timeout=_DEFAULT_TIMEOUT), _CRED_DIR)
        reg["_preflight"] = preflight
        return reg
    except EP.PlanError as exc:
        return exc.as_dict()
    except OSError:
        return {"code": 1, "error": "REGISTRATION_PERSIST_FAILED", "retryable": False, "next_action": "registration_status"}


def query_grant(endpoint, grant_id, signature, api_key=""):
    """取数核心：普通 JSON POST（非 SSE，不重算）。供 build_dashboard 复用。"""
    body = {"grant_id": grant_id, "signature": signature}
    res = C.http_json("POST", C.api_url(endpoint, _PATH["query"]),
                      C.headers(api_key), body, timeout=_DEFAULT_TIMEOUT)
    # 外层统一带 grant_id；失败时服务端返回 code:1 + error:{code,message}（见 tools/data_grant.md）
    if isinstance(res, dict) and "grant_id" not in res:
        res["grant_id"] = grant_id
    return res


def cmd_query(params):
    """取数：无需 api_key，凭 grant_id + signature（signature 可由本地凭证补全）。"""
    endpoint, api_key = _config(require_key=False)
    gid = params.get("grant_id")
    sig = params.get("signature")
    if gid and not sig:
        cred = load_credential(gid, task_id=params["task_id"]) if params.get("task_id") else load_credential(gid)
        if cred:
            sig = cred.get("signature")
    if not gid or not sig:
        return {"code": 1, "message": "query 需要 grant_id + signature（signature 可由本地凭证补全）"}
    return query_grant(endpoint, gid, sig, api_key=api_key)


def cmd_list(params):
    import urllib.parse as _up
    endpoint, api_key = _config(require_key=True)
    page = params.get("page", 1)
    page_size = params.get("page_size", 20)
    qs_pairs = [("page", page), ("page_size", page_size)]
    url = C.api_url(endpoint, _PATH["list"]) + "?" + _up.urlencode(qs_pairs)
    return C.http_json("GET", url, C.headers(api_key))


def _manage(params, operation):
    endpoint, api_key = _config(require_key=True)
    if not params.get("grant_id"):
        return {"code": 1, "message": operation + "需要grant_id"}
    body = {"grant_id": params["grant_id"]}
    if operation == "refresh": body["rotate_signature"] = bool(params.get("rotate_signature", False))
    try:
        result = RC.mutate("grant", params, endpoint, api_key,
                           lambda: C.http_json("POST", C.api_url(endpoint, _PATH[operation]), C.headers(api_key), body), _CRED_DIR, operation)
        if operation == "refresh" and params.get("rotate_signature") and result.get("code") == 0:
            result["warning"] = "签名已轮换，需重新构建并验收所有引用该Grant的页面；未自动修改公开页面。"
        return result
    except EP.PlanError as exc:
        return exc.as_dict()


def cmd_revoke(params): return _manage(params, "revoke")
def cmd_refresh(params): return _manage(params, "refresh")


def cmd_registration_status(params):
    try: return RC.status("grant", params)
    except EP.PlanError as exc: return exc.as_dict()


_COMMANDS = {
    "register": cmd_register,
    "query": cmd_query,
    "list": cmd_list,
    "revoke": cmd_revoke,
    "refresh": cmd_refresh,
    "registration_status": cmd_registration_status,
}

def main():
    # 注：common 在 import 时已把 stdout/stderr 重配为 UTF-8，无需重复包裹
    if len(sys.argv) < 2 or sys.argv[1] not in _COMMANDS:
        C.emit({"code": 1, "message": f"用法: data_grant.py <{'|'.join(_COMMANDS)}> [params]",
                "doc": (__doc__ or "").strip()[:400]}, out_name="dg_out.txt")
        sys.exit(1)
    cmd = sys.argv[1]
    params = C.read_params(sys.argv[2:], env_var="DG_PARAMS")

    try:
        result = _COMMANDS[cmd](params)
    except (FileNotFoundError, ValueError) as e:
        result = {"code": 1, "message": str(e)}
    C.emit(result, out_name="dg_out.txt")
    sys.exit(0 if (isinstance(result, dict) and result.get("code") == 0) else 1)


if __name__ == "__main__":
    main()
