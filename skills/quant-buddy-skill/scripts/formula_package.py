#!/usr/bin/env python3
r"""
公式任务包（Formula Package）客户端 —— 注册一组公式为任务包，凭包凭证流式取数。

对接接口文档：docs/formulaPackage 相关文档/对外接口文档.md
工具说明文档：tools/formula_package.md

两段式使用：
  1. 注册（需 API Key）：提交一组 formulas + 各产出读取模式，服务端执行校验后
     返回 package_id + signature（signature 仅此一次明文返回，请妥善保存）。
  2. 取数（无需 API Key）：凭 package_id + signature 拉取数据，SSE 流式返回，
     底层数据更新后自动重算，永远返回最新结果。

子命令：
    register  注册任务包（读 config.json 的 api_key + endpoint）
    query     取数（无需 api_key，凭 package_id + signature）
    list      列出我的任务包（需 api_key）
    revoke    撤销任务包（需 api_key）
    refresh   强制刷新/轮换签名（需 api_key）

参数传递（与 call.py / executor.py 同款，避免 PowerShell GBK 截断）：
    优先级：FP_PARAMS 环境变量 > @file > 命令行 JSON > stdin

用法示例：
    # 注册（推荐用 @file 传中文公式，Windows 必须）
    python scripts/formula_package.py register @params.json

    # 取数（package_id + signature 即可，不需要 api_key）
    FP_PARAMS='{"package_id":"pkg_xxx","signature":"a1b2..."}' \
        python scripts/formula_package.py query

    # 管理
    python scripts/formula_package.py list '{"page":1,"page_size":20}'
    python scripts/formula_package.py revoke '{"package_id":"pkg_xxx"}'
    python scripts/formula_package.py refresh '{"package_id":"pkg_xxx","rotate_signature":true}'

输出：
    结果打印到 stdout（UTF-8），并写入临时目录下 fp_out.txt（防终端缓冲吞输出）。
    register / query 成功时，包凭证额外落盘到 output/formula_packages/<package_id>.json，
    方便后续取数与 HTML 页面引用（signature 服务端不可再取出，本地不存丢失即不可恢复）。
"""

import json
import os
import sys
import tempfile
import urllib.request
import urllib.error

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(SCRIPT_DIR)

# 复用 executor.py 的配置加载、无代理 opener、skill 版本/渠道头，保持与其它工具一致
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
import executor as _ex  # noqa: E402
# 复用 call.py 的 session 读取与版本守卫，保证公式包与其它工具走同一套
# “先 newSession + 版本检查、每个请求带 task_id/user_query” 的统一流程。
# call.py 的 main() 受 __name__ 守卫，import 仅执行常量定义，无副作用。
import call as _call  # noqa: E402

# 公式包接口的统一前缀（与 fastQuery 等不同，固定带 /skill）
_PATH = {
    "register": "/skill/registerFormulaPackage",
    "query":    "/skill/queryFormulaPackage",
    "list":     "/skill/listFormulaPackages",
    "revoke":   "/skill/revokeFormulaPackage",
    "refresh":  "/skill/refreshFormulaPackage",
}

# 取数（SSE）可能等待服务端重算，给足超时
_QUERY_TIMEOUT = 1800
_DEFAULT_TIMEOUT = 600


def _emit(obj):
    """打印结果（dict→JSON，或原样字符串），并写一份到临时文件防终端吞输出。"""
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=2)
    out_file = os.path.join(tempfile.gettempdir(), "fp_out.txt")
    try:
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass
    try:
        print(text)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        sys.stdout.buffer.write((text + "\n").encode(enc, errors="replace"))
        sys.stdout.buffer.flush()


def _read_params(argv):
    """按 FP_PARAMS > @file > 命令行 JSON > stdin 优先级解析参数 dict。"""
    raw = os.environ.get("FP_PARAMS", "").strip()
    if not raw and len(argv) >= 1:
        if argv[0].startswith("@"):
            with open(argv[0][1:], "r", encoding="utf-8-sig") as f:
                raw = f.read()
        else:
            raw = " ".join(argv)
    if not raw and not sys.stdin.isatty():
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace").strip()
    raw = raw or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        _emit({"code": 1, "message": f"参数 JSON 解析失败: {e}", "raw": raw[:200]})
        sys.exit(1)


def _config(require_key):
    """加载 endpoint(+api_key)。query 子命令 require_key=False。"""
    if require_key:
        cfg = _ex.load_config()           # 缺 api_key 会抛 ValueError
    else:
        # query 不需要 api_key；只取 endpoint，api_key 缺失也不报错
        try:
            cfg = _ex.load_config()
        except ValueError:
            # 仅 endpoint 即可
            path = os.path.join(SKILL_ROOT, "config.json")
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
    endpoint = (cfg.get("endpoint") or "").rstrip("/")
    if not endpoint:
        raise ValueError("config.json 缺少 endpoint")
    return endpoint, cfg.get("api_key", "")


def _headers(api_key=None, accept=None):
    h = {
        "Content-Type": "application/json; charset=utf-8",
        "x-skill-version": _ex.SKILL_VERSION,
    }
    if _ex.SKILL_CHANNEL:
        h["x-skill-channel"] = _ex.SKILL_CHANNEL
    if api_key:
        h["Authorization"] = f"Bearer {api_key}"
    if accept:
        h["Accept"] = accept
    return h


def _http_json(method, url, headers, body=None, timeout=_DEFAULT_TIMEOUT):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with _ex._NO_PROXY_OPENER.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"code": e.code, "success": False,
                    "error": {"message": getattr(e, "reason", str(e))}}
    except Exception as e:
        return {"code": 1, "success": False, "error": {"message": str(e)}}


def _save_credential(reg):
    """注册/轮换成功后把 package_id + signature 落盘，供后续取数 / HTML 引用。"""
    pkg = reg.get("package_id")
    sig = reg.get("signature")
    if not pkg or not sig:
        return None
    out_dir = os.path.join(SKILL_ROOT, "output", "formula_packages")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{pkg}.json")
    record = {
        "package_id": pkg,
        "signature": sig,
        "outputs": reg.get("outputs"),
        "expires_at": reg.get("expires_at"),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    return path


# ────────────────────────────────────────────────
# 统一流程：session 上下文 + 版本守卫（与 call.py 同款）
# ────────────────────────────────────────────────

# 需要 api_key 的管理类子命令，必须先 newSession（与 call.py 的“先建会话”一致）
_SESSION_REQUIRED = {"register", "list", "revoke", "refresh"}


def _session_context():
    """读取当前 session 的 task_id / user_query，并做版本守卫。

    复用 call.py 的 SESSION 解析（含 QBS_SESSION_FILE / QBS_SESSION_KEY 多会话），
    保证公式包与其它工具读同一个 .session.json。

    返回 (ctx, guard)：
      ctx   = {"task_id": str|None, "user_query": str|None}
      guard = None 或版本不匹配的错误 dict（命中即应中止并提示重新 newSession）
    """
    data = _call._read_session_full()
    ctx = {"task_id": data.get("task_id"), "user_query": data.get("user_query")}

    # 版本守卫：与 call.py 行为一致 —— 仅当已有 session 且版本变化时拦截
    current = _call._read_skill_version()
    session_ver = data.get("skill_version_at_creation")
    guard = None
    if current and ctx["task_id"] and session_ver is not None and session_ver != current:
        guard = {
            "code": 1,
            "error": "SKILL_VERSION_MISMATCH",
            "current_version": current,
            "session_version": session_ver,
            "message": (
                f"检测到 skill 版本不匹配（session 创建于 {session_ver}，当前为 {current}）。"
                "请立即调用 newSession 创建新 session，然后重读 SKILL.md 后再使用公式包。"
            ),
        }
    return ctx, guard


def _inject_session(body, ctx):
    """把 session 的 task_id / user_query 注入请求体（已存在则不覆盖，空串视为未传）。"""
    if ctx.get("task_id") and not body.get("task_id"):
        body["task_id"] = ctx["task_id"]
    if ctx.get("user_query") and not body.get("user_query"):
        body["user_query"] = ctx["user_query"]
    return body


# ────────────────────────────────────────────────
# 子命令
# ────────────────────────────────────────────────

def cmd_register(params, ctx):
    endpoint, api_key = _config(require_key=True)
    formulas = params.get("formulas")
    reads = params.get("reads")
    if not isinstance(formulas, list) or not formulas:
        return {"code": 1, "message": "formulas 必须是非空数组（每条形如 \"变量名 = 表达式\"）"}
    if not isinstance(reads, list) or not reads:
        return {"code": 1, "message": "reads 必须是非空数组，指定对外产出及其 read_mode"}
    if len(formulas) > 100:
        return {"code": 1, "message": f"单包公式数 ≤ 100，当前 {len(formulas)}"}
    if len(reads) > 20:
        return {"code": 1, "message": f"单包对外产出数 ≤ 20，当前 {len(reads)}"}
    body = {"formulas": formulas, "reads": reads}
    for k in ("intents", "begin_date", "ttl_days"):
        if params.get(k) is not None:
            body[k] = params[k]
    _inject_session(body, ctx)
    reg = _http_json("POST", endpoint + _PATH["register"],
                     _headers(api_key), body, timeout=_DEFAULT_TIMEOUT)
    if reg.get("code") == 0 and reg.get("package_id"):
        saved = _save_credential(reg)
        if saved:
            reg["_saved_credential"] = saved
    return reg


def cmd_query(params, ctx):
    """取数：无需 api_key，凭 package_id + signature，逐条 SSE → 组装为 outputs dict。"""
    endpoint, _ = _config(require_key=False)
    pkg = params.get("package_id")
    sig = params.get("signature")
    # 允许只传 package_id，从本地凭证补全 signature
    if pkg and not sig:
        cred = os.path.join(SKILL_ROOT, "output", "formula_packages", f"{pkg}.json")
        if os.path.exists(cred):
            with open(cred, "r", encoding="utf-8") as f:
                sig = json.load(f).get("signature")
    if not pkg or not sig:
        return {"code": 1, "message": "query 需要 package_id + signature（signature 可由本地凭证补全）"}

    # 取数端点对第三方保持无凭证；从 skill 内调用时附带 session 上下文供服务端 audit
    _qbody = _inject_session({"package_id": pkg, "signature": sig}, ctx)
    body = json.dumps(_qbody).encode("utf-8")
    req = urllib.request.Request(endpoint + _PATH["query"], data=body,
                                 headers=_headers(accept="text/event-stream"),
                                 method="POST")
    outputs = {}
    progress = []
    done = None
    err = None
    try:
        resp = _ex._NO_PROXY_OPENER.open(req, timeout=_QUERY_TIMEOUT)
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"code": e.code, "success": False,
                    "error": {"message": getattr(e, "reason", str(e))}}
    except Exception as e:
        return {"code": 1, "success": False, "error": {"message": str(e)}}

    event_type, data_buf = None, []
    with resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            if line == "":
                if event_type and data_buf:
                    try:
                        payload = json.loads("\n".join(data_buf))
                    except json.JSONDecodeError:
                        payload = {"raw": "\n".join(data_buf)}
                    if event_type == "result":
                        outputs[payload.get("output")] = {
                            "read_mode": payload.get("read_mode"),
                            "data_id": payload.get("data_id"),
                            "data": payload.get("data"),
                        }
                        sys.stderr.write(f"  ✓ {payload.get('output')} ({payload.get('read_mode')})\n")
                        sys.stderr.flush()
                    elif event_type == "progress":
                        progress.append(payload)
                        sys.stderr.write(f"  … recomputing {payload.get('node')} "
                                         f"{payload.get('done')}/{payload.get('total')}\n")
                        sys.stderr.flush()
                    elif event_type == "done":
                        done = payload
                    elif event_type == "error":
                        err = payload
                event_type, data_buf = None, []
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                data_buf.append(line[5:].lstrip())

    if err is not None:
        return {"code": 1, "success": False, "error": err,
                "outputs": outputs, "progress": progress}
    return {"code": 0, "success": True, "package_id": pkg,
            "outputs": outputs, "progress": progress, "done": done}


def cmd_list(params, ctx):
    import urllib.parse as _up
    endpoint, api_key = _config(require_key=True)
    page = params.get("page", 1)
    page_size = params.get("page_size", 20)
    # task_id / user_query 走 query string，供服务端 audit 中间件落库
    qs_pairs = [("page", page), ("page_size", page_size)]
    if ctx.get("task_id"):
        qs_pairs.append(("task_id", ctx["task_id"]))
    if ctx.get("user_query"):
        qs_pairs.append(("user_query", ctx["user_query"]))
    url = f"{endpoint}{_PATH['list']}?" + _up.urlencode(qs_pairs)
    return _http_json("GET", url, _headers(api_key))


def cmd_revoke(params, ctx):
    endpoint, api_key = _config(require_key=True)
    if not params.get("package_id"):
        return {"code": 1, "message": "revoke 需要 package_id"}
    body = _inject_session({"package_id": params["package_id"]}, ctx)
    return _http_json("POST", endpoint + _PATH["revoke"], _headers(api_key), body)


def cmd_refresh(params, ctx):
    endpoint, api_key = _config(require_key=True)
    if not params.get("package_id"):
        return {"code": 1, "message": "refresh 需要 package_id"}
    body = {"package_id": params["package_id"],
            "rotate_signature": bool(params.get("rotate_signature", False))}
    _inject_session(body, ctx)
    res = _http_json("POST", endpoint + _PATH["refresh"], _headers(api_key), body)
    # 轮换签名时更新本地凭证
    if res.get("code") == 0 and res.get("signature"):
        cred = os.path.join(SKILL_ROOT, "output", "formula_packages",
                            f"{params['package_id']}.json")
        if os.path.exists(cred):
            try:
                with open(cred, "r", encoding="utf-8") as f:
                    rec = json.load(f)
                rec["signature"] = res["signature"]
                with open(cred, "w", encoding="utf-8") as f:
                    json.dump(rec, f, ensure_ascii=False, indent=2)
                res["_credential_updated"] = cred
            except Exception:
                pass
    return res


_COMMANDS = {
    "register": cmd_register,
    "query": cmd_query,
    "list": cmd_list,
    "revoke": cmd_revoke,
    "refresh": cmd_refresh,
}


def main():
    # 注：executor.py 在 import 时已把 stdout/stderr 重配为 UTF-8，无需重复包裹
    if len(sys.argv) < 2 or sys.argv[1] not in _COMMANDS:
        _emit({"code": 1, "message": f"用法: formula_package.py <{'|'.join(_COMMANDS)}> [params]",
               "doc": (__doc__ or "").strip()[:400]})
        sys.exit(1)
    cmd = sys.argv[1]
    params = _read_params(sys.argv[2:])

    # ── 统一流程：先做版本守卫，再带上 session 上下文 ─────────────
    ctx, guard = _session_context()
    if guard is not None:
        _emit(guard)
        sys.exit(1)
    # 管理类子命令必须先 newSession（与 call.py 的“先建会话”一致）
    if cmd in _SESSION_REQUIRED and not ctx.get("task_id"):
        _emit({
            "code": 1,
            "error": "SESSION_REQUIRED",
            "message": (
                f"`{cmd}` 需要先创建 session：请先运行 "
                "`python scripts/call.py newSession`（携带 user_query），"
                "再使用公式包。这样每个请求才会带上 task_id / user_query / 当前版本。"
            ),
        })
        sys.exit(1)

    try:
        result = _COMMANDS[cmd](params, ctx)
    except (FileNotFoundError, ValueError) as e:
        result = {"code": 1, "message": str(e)}
    _emit(result)
    sys.exit(0 if (isinstance(result, dict) and result.get("code") == 0) else 1)


if __name__ == "__main__":
    main()
