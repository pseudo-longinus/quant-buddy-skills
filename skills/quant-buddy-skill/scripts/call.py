#!/usr/bin/env python3
"""
轻量调用封装器。通过环境变量传 JSON 参数，彻底绕过 PowerShell GBK 编码和双引号问题。
renderChart 自动保存 PNG 并打开（无需额外调 saveChart）。

用法（Claude 在终端执行）：

    方式1 —— 环境变量（推荐）：
    GZQ_PARAMS='{"query":"收盘价"}' python scripts/call.py searchFunctions

    方式2 —— @file 传参（跨平台备用）：
    python scripts/call.py searchFunctions @params.json

    方式3 —— 命令行传参（仅 bash/zsh）：
    python scripts/call.py searchFunctions '{"query":"收盘价"}'

    方式4 —— 管道传参（macOS/Linux）：
    echo '{"query":"收盘价"}' | python scripts/call.py searchFunctions

❌ 常见错误用法（会被前置校验立即拒绝，不要这样用）：
    ❌ python scripts/call.py @params.json          # 缺工具名：把 @file 当成了工具名
    ❌ python scripts/call.py '{"tool":"x","params":{}}'  # 把“结果 JSON 的长相”误当成输入格式
    ❌ python scripts/call.py fastquery @params.json # 工具名写错/大小写不符（正确为 fast_query）
    正确：python scripts/call.py <工具名> @params.json，工具名必须排在最前，且为已注册工具。

原理：
  1. 从 GZQ_PARAMS 环境变量读取 JSON（PowerShell 赋值字符串时不剥双引号）
  2. 调用 executor.py <tool> @tmpfile
  3. renderChart 额外处理：自动保存 PNG + 打开
  4. 打印结果到 stdout + 写入临时目录下 gzq_out.txt
  5. 清理临时文件
"""

import base64
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid

try:
    import select as _select
except Exception:  # pragma: no cover
    _select = None

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(SCRIPT_DIR)
EXECUTOR = os.path.join(SCRIPT_DIR, "executor.py")


# call.py 自身处理（不走 executor）的本地工具
_LOCAL_TOOLS = {"newSession", "saveChart", "webSearch", "buildEventStudy"}


def _known_tools():
    """工具白名单 = executor.TOOL_ROUTES 的 key（网络工具，单一事实源）
    + call.py 本地处理的工具。

    实现说明：**不 import executor**——executor.py 在模块级会重包裹
    sys.stdout/stderr（TextIOWrapper over .buffer），import 会破坏 call.py 已配置的
    stdio 并在解释器退出时抛 “I/O operation on closed file.”。
    因此改为静态解析 executor.py 源码提取 TOOL_ROUTES / SAVE_CHART_TOOL，
    既保持单一事实源、又零副作用。解析失败时退化为仅本地工具。
    """
    names = set(_LOCAL_TOOLS)
    try:
        src = open(EXECUTOR, "r", encoding="utf-8").read()
        lines = src.splitlines()
        in_routes = False
        for line in lines:
            stripped = line.strip()
            if not in_routes:
                if re.match(r"TOOL_ROUTES\s*=\s*\{", stripped):
                    in_routes = True
                continue
            # 到达独立的右花括号即结束（避免被 "/data/{id}" 占位符误判）
            if stripped.startswith("}"):
                break
            km = re.match(r'["\']([A-Za-z0-9_]+)["\']\s*:', stripped)
            if km:
                names.add(km.group(1))
        m2 = re.search(r'SAVE_CHART_TOOL\s*=\s*["\']([A-Za-z0-9_]+)["\']', src)
        if m2:
            names.add(m2.group(1))
    except Exception:
        pass
    return names


def _reject_bad_tool_name(tool_name):
    """工具名前置校验：@ 开头或未知工具立即报错退出，
    把“静默挂死读 stdin”变成“瞬时明确报错”。
    """
    known = _known_tools()
    bad_reason = None
    if tool_name.startswith("@"):
        bad_reason = (
            f"疑似把 @file 当成了工具名：'{tool_name}'。"
            "正确用法：python scripts/call.py <工具名> @params.json"
        )
    elif tool_name not in known:
        bad_reason = (
            f"未知工具名：'{tool_name}'。工具名必须排在最前，且为已注册工具。"
        )
    if bad_reason is None:
        return
    err = {
        "code": 1,
        "success": False,
        "error": "INVALID_TOOL_NAME",
        "message": bad_reason,
        "known_tools": sorted(known),
    }
    out = json.dumps(err, ensure_ascii=False, indent=2)
    try:
        out_file = os.path.join(tempfile.gettempdir(), "gzq_out.txt")
        with open(out_file, "w", encoding="utf-8") as _f:
            _f.write(out)
    except Exception:
        pass
    print(out)
    sys.exit(1)


def _read_stdin_nonblocking():
    """只在 stdin 确有数据时读取，避免 agent/CI 空管道下无限阻塞。
    - tty：直接返回 None（交互式不读）
    - POSIX：用 select 判定是否有数据；
    - Windows：select 对管道会报 WSAStartup，用 PeekNamedPipe 检查管道可读字节；
      普通重定向文件直接读取。
    返回 str 或 None。
    """
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return None
    except Exception:
        return None

    if sys.platform == "win32":
        try:
            import ctypes
            import msvcrt
            handle = msvcrt.get_osfhandle(sys.stdin.fileno())
            kernel32 = ctypes.windll.kernel32
            file_type = kernel32.GetFileType(ctypes.c_void_p(handle))
            FILE_TYPE_DISK = 0x0001
            FILE_TYPE_PIPE = 0x0003
            if file_type == FILE_TYPE_PIPE:
                available = ctypes.c_ulong(0)
                ok = kernel32.PeekNamedPipe(
                    ctypes.c_void_p(handle),
                    None,
                    0,
                    None,
                    ctypes.byref(available),
                    None,
                )
                if not ok or available.value <= 0:
                    return None
            elif file_type != FILE_TYPE_DISK:
                return None
            data = sys.stdin.buffer.read()
            return data.decode("utf-8", errors="replace").strip()
        except Exception:
            return None

    if _select is not None:
        try:
            ready, _, _ = _select.select([sys.stdin], [], [], 0)
            if not ready:
                return None
        except Exception:
            return None
    else:
        return None
    try:
        data = sys.stdin.buffer.read()
        return data.decode("utf-8", errors="replace").strip()
    except Exception:
        return None


def _configure_parent_stdio():
    """启动时把 sys.stdout/stderr 尽量重配为 UTF-8 + replace 模式，
    防止 Windows GBK 终端在遇到 emoji 等字符时直接抛 UnicodeEncodeError。
    只做 best-effort；失败不影响主流程。
    """
    for attr in ("stdout", "stderr"):
        stream = getattr(sys, attr)
        if stream is None:
            continue
        try:
            enc = getattr(stream, "encoding", None) or "utf-8"
            # 已是 utf-8 + replace，不需要重设
            if enc.lower().replace("-", "") == "utf8" and getattr(stream, "errors", None) == "replace":
                continue
            buf = getattr(stream, "buffer", None)
            if buf is not None:
                new_stream = io.TextIOWrapper(buf, encoding="utf-8", errors="replace", line_buffering=True)
                setattr(sys, attr, new_stream)
        except Exception:
            pass


def _safe_print(text: str, *, is_stderr: bool = False) -> None:
    """安全打印：先尝试正常 print；若遇到 UnicodeEncodeError，
    用当前终端编码的 replace 策略写入 buffer；
    若仍失败，至少打印一条纯 ASCII 提示，告知结果已存入 gzq_out.txt。
    """
    target = sys.stderr if is_stderr else sys.stdout
    try:
        print(text, end="", file=target)
        return
    except UnicodeEncodeError:
        pass
    # 第二层：buffer 直写 + replace
    try:
        enc = getattr(target, "encoding", None) or "utf-8"
        buf = getattr(target, "buffer", None)
        if buf is not None:
            buf.write(text.encode(enc, errors="replace"))
            buf.flush()
            return
    except Exception:
        pass
    # 第三层：纯 ASCII 提示
    out_file = os.path.join(tempfile.gettempdir(), "gzq_out.txt")
    try:
        print(
            f"[call.py] Output contains unencodable characters; "
            f"full result saved to {out_file}",
            file=target,
        )
    except Exception:
        pass


def _resolve_session_file():
    """按优先级解析 session 文件路径，支持多会话并行：
    1) QBS_SESSION_FILE 环境变量直接指定路径（最高优先级）
    2) QBS_SESSION_KEY 派生为 .session.<key>.json
    3) 默认 .session.json（向后兼容单会话场景）
    """
    explicit = os.environ.get("QBS_SESSION_FILE", "").strip()
    if explicit:
        return explicit
    key = os.environ.get("QBS_SESSION_KEY", "").strip()
    if key:
        # 仅允许字母数字、连字符、下划线，防止路径注入
        safe_key = re.sub(r"[^A-Za-z0-9_\-]", "_", key)[:64]
        return os.path.join(SKILL_ROOT, "output", f".session.{safe_key}.json")
    return os.path.join(SKILL_ROOT, "output", ".session.json")


SESSION_FILE = _resolve_session_file()

# 部分工具需要比 900s 更长的 subprocess 超时（与 executor.TOOL_TIMEOUTS 对齐）
# runMultiFormulaBatchStream 走 SSE 主路径，可能超过 5min，这里允许走完 30min
_TOOL_SUBPROCESS_TIMEOUTS = {
    "runMultiFormulaBatchStream": 1800,
}
_DEFAULT_SUBPROCESS_TIMEOUT = 900


def _cleanup_stale_sessions(max_age_days: int = 7):
    """清理 output/ 下超过 max_age_days 的 .session.*.json，best-effort，失败不抛。"""
    try:
        import glob
        import time
        cutoff = time.time() - max_age_days * 86400
        for path in glob.glob(os.path.join(SKILL_ROOT, "output", ".session.*.json")):
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
            except Exception:
                pass
    except Exception:
        pass


def _read_skill_version() -> str:
    """从 SKILL.md frontmatter 读取 version 字段；读取失败时返回空字符串。"""
    skill_md = os.path.join(SKILL_ROOT, "SKILL.md")
    try:
        with open(skill_md, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("version:"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return ""


def _parse_version_tuple(version):
    """把 4.21.2 / v4.21.2 解析为整数 tuple；解析失败返回 None。"""
    if not version:
        return None
    text = str(version).strip()
    if text.startswith(("v", "V")):
        text = text[1:]
    parts = text.split(".")
    if not parts:
        return None
    nums = []
    for part in parts:
        if not re.fullmatch(r"\d+", part):
            return None
        nums.append(int(part))
    return tuple(nums)


def _compare_versions(left, right):
    """语义版本比较：left > right 返回 1；相等 0；left < right 返回 -1；未知返回 None。"""
    lv = _parse_version_tuple(left)
    rv = _parse_version_tuple(right)
    if lv is None or rv is None:
        return None
    width = max(len(lv), len(rv))
    lv = lv + (0,) * (width - len(lv))
    rv = rv + (0,) * (width - len(rv))
    if lv > rv:
        return 1
    if lv < rv:
        return -1
    return 0


def _is_newer_version(target_version, current_version):
    relation = _compare_versions(target_version, current_version)
    if relation is None:
        return str(target_version or "") != str(current_version or "")
    return relation > 0


def _read_session():
    """读取当前 session 的 task_id，不存在则返回 None。"""
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("task_id")
    except Exception:
        return None


def _read_session_full():
    """读取当前 session 的全量字段，不存在则返回空 dict。"""
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _update_session_trace(task_id, trace_id):
    """在不丢失现有字段的前提下，将 SSE 返回的 trace_id 追加到 session。仅当
    task_id 与 session 中一致或 session 原本为空时才写，避免污染别的 session。"""
    if not trace_id:
        return
    cur = _read_session_full()
    if cur.get("task_id") and task_id and cur["task_id"] != task_id:
        return
    if cur.get("trace_id") == trace_id:
        return
    cur["trace_id"] = trace_id
    if task_id and not cur.get("task_id"):
        cur["task_id"] = task_id
    if not cur.get("skill_version_at_creation"):
        cur["skill_version_at_creation"] = _read_skill_version()
    try:
        os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False)
    except Exception:
        pass


def _write_session(task_id, user_query=None):
    """持久化 task_id（和可选的 user_query）到 .session.json，同时写入当前 skill 版本。"""
    os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
    data = {"task_id": task_id, "skill_version_at_creation": _read_skill_version()}
    if user_query is not None:
        data["user_query"] = user_query
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


SELF_UPDATE_SCRIPT = os.path.join(SCRIPT_DIR, "self_update.py")

# 自更新当日去重状态文件（output/ 受保护、跨版本共享）
SELF_UPDATE_STATE_FILE = os.path.join(SKILL_ROOT, "output", ".self_update_state.json")
VERSION_CHECK_STATE_FILE = os.path.join(SKILL_ROOT, "output", ".version_check_state.json")
# 同一天、同一 target_version 的失败上限：一次触发内已含 3 次下载重试；失败后当日不再重复下载
SELF_UPDATE_DAILY_FAIL_CAP = 1
# self_update 子进程总超时：必须 >= 下载(5min) x 重试(3) + 安装余量，否则会被外层提前杀死
SELF_UPDATE_SUBPROC_TIMEOUT = 1200  # 20min
# newSession 主动版本检查节流：默认 1 小时最多查一次；成功响应心跳只记录待更新
try:
    VERSION_CHECK_TTL_SECONDS = max(0, int(os.environ.get("QBS_VERSION_CHECK_TTL_SECONDS", "3600") or "3600"))
except ValueError:
    VERSION_CHECK_TTL_SECONDS = 3600


def _today_str():
    import time as _t
    return _t.strftime("%Y-%m-%d")


def _read_self_update_state():
    try:
        with open(SELF_UPDATE_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_self_update_state(state):
    try:
        os.makedirs(os.path.dirname(SELF_UPDATE_STATE_FILE), exist_ok=True)
        with open(SELF_UPDATE_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _read_version_check_state():
    try:
        with open(VERSION_CHECK_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_version_check_state(skill_version, version_info=None, error=None):
    import time as _t
    state = {
        "checked_at": int(_t.time()),
        "skill_version": skill_version,
        "latest_version": (version_info or {}).get("latest_version"),
        "update_required": bool((version_info or {}).get("update_required")),
        "error": error,
    }
    try:
        os.makedirs(os.path.dirname(VERSION_CHECK_STATE_FILE), exist_ok=True)
        with open(VERSION_CHECK_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _should_run_new_session_version_check(skill_version):
    """newSession 的主动版本检查只做节流补充；成功响应心跳负责记录 pending update。"""
    if os.environ.get("QBS_FORCE_VERSION_CHECK", "").strip() in ("1", "true", "TRUE", "yes", "YES"):
        return True, "forced"
    state = _read_version_check_state()
    try:
        import time as _t
        age = int(_t.time()) - int(state.get("checked_at") or 0)
    except Exception:
        age = VERSION_CHECK_TTL_SECONDS + 1
    if state.get("skill_version") != skill_version:
        return True, "skill_version_changed"
    if age >= VERSION_CHECK_TTL_SECONDS:
        return True, "ttl_expired"
    return False, "ttl_active"


# 会话内内存标记：本进程是否已对某 target_version 触发过更新（一个会话最多一次）
_SELF_UPDATE_TRIED_THIS_RUN = set()


def _self_update_target_version(self_update_info):
    """从 self_update / error 信息里尽量解析出目标版本号，作为去重键。"""
    if not isinstance(self_update_info, dict):
        return ""
    v = self_update_info.get("version") or self_update_info.get("target_version")
    if v:
        return str(v)
    args = self_update_info.get("args") or []
    if isinstance(args, list):
        for i, a in enumerate(args):
            if a == "--version" and i + 1 < len(args):
                return str(args[i + 1])
    return ""


def _self_update_gate(target_version):
    """返回 (allowed: bool, short_circuit_reason: str|None)。
    去重键 = 当日 + target_version。规则：
      - 本会话已对该 target_version 触发过 → 短路（会话内一次）
      - 同日 + 同 target_version + status=failed 且 attempts>=cap → 短路
      - status=in_progress（充当软锁）→ 短路，避免并发重复触发
      - target_version 变化或换天 → 放行
    """
    if not target_version:
        return True, None
    if target_version in _SELF_UPDATE_TRIED_THIS_RUN:
        return False, f"本会话已尝试更新到 {target_version}，不再重复触发；如需更新请新开会话(newSession)。"
    state = _read_self_update_state()
    if state.get("date") == _today_str() and state.get("target_version") == target_version:
        status = state.get("status")
        attempts = int(state.get("attempts") or 0)
        if status == "in_progress":
            return False, "更新进行中，请稍后重试。"
        if status == "failed" and attempts >= SELF_UPDATE_DAILY_FAIL_CAP:
            return False, (
                f"今日已自动更新 {attempts} 次失败（目标 {target_version}）：{state.get('last_error')}；"
                "当日不再重复下载，请手动执行 self_update 或检查网络。"
            )
    return True, None


def _self_update_mark(target_version, status, last_error=None):
    import time as _t
    state = _read_self_update_state()
    same = state.get("date") == _today_str() and state.get("target_version") == target_version
    attempts = int(state.get("attempts") or 0) if same else 0
    prev_status = state.get("status") if same else None
    if status == "failed" and prev_status != "failed":
        attempts += 1
    new_state = {
        "date": _today_str(),
        "target_version": target_version,
        "attempts": attempts,
        "status": status,
        "last_error": last_error,
        "ts": int(_t.time()),
    }
    _write_self_update_state(new_state)


def _record_pending_self_update(self_update_info, source="heartbeat"):
    """记录待更新信息，但不安装激活新版。

    长 session 中只能“发现并准备下一次 newSession 更新”，不能直接替换当前
    SKILL_ROOT，否则下一次工具调用会因 session 版本与磁盘版本不一致被本地守卫拦住。
    """
    result = {"recorded": False, "skipped": False, "reason": None, "target_version": None}
    if not isinstance(self_update_info, dict) or not self_update_info.get("available"):
        result["reason"] = "self_update not available"
        return result

    target_version = _self_update_target_version(self_update_info)
    result["target_version"] = target_version or None
    if not target_version:
        result["reason"] = "self_update target version missing"
        return result

    current_version = _read_skill_version()
    if current_version and not _is_newer_version(target_version, current_version):
        result["skipped"] = True
        result["reason"] = (
            f"target version {target_version} is not newer than current {current_version}; "
            "skip self_update to avoid downgrade."
        )
        return result

    state = _read_self_update_state()
    if state.get("target_version") == target_version and state.get("status") == "pending":
        result["skipped"] = True
        result["reason"] = "pending update already recorded"
        return result

    import time as _t
    pending_state = {
        "date": _today_str(),
        "target_version": target_version,
        "attempts": int(state.get("attempts") or 0) if state.get("target_version") == target_version else 0,
        "status": "pending",
        "last_error": None,
        "ts": int(_t.time()),
        "source": source,
        "current_version": current_version,
        "activation": "next_newSession",
        "self_update": self_update_info,
    }
    _write_self_update_state(pending_state)
    result["recorded"] = True
    return result


def _get_pending_self_update():
    state = _read_self_update_state()
    if state.get("status") != "pending":
        return None
    self_update_info = state.get("self_update")
    if not isinstance(self_update_info, dict) or not self_update_info.get("available"):
        return None
    target_version = _self_update_target_version(self_update_info)
    current_version = _read_skill_version()
    if target_version and current_version and not _is_newer_version(target_version, current_version):
        _self_update_mark(target_version, "ok")
        return None
    return self_update_info



def _attempt_self_update(self_update_info, timeout=None, skip_dedup=False):
    """根据服务端返回的 self_update 对象自动执行 scripts/self_update.py。

    self_update_info 形如：
        {"available": True, "script": "scripts/self_update.py",
         "args": ["--version","4.20.15","--url","...","--sha512","...","--zip-skill-path","..."]}

    返回 dict：
        {"attempted": bool, "ok": bool, "new_version": str|None,
         "stdout": str, "stderr": str, "error": str|None}
    """
    result = {
        "attempted": False,
        "ok": False,
        "new_version": None,
        "stdout": "",
        "stderr": "",
        "error": None,
        "skipped": False,
    }

    if timeout is None:
        timeout = SELF_UPDATE_SUBPROC_TIMEOUT

    # ── 当日去重闸门：避免逢错必重下、并发重复触发 ──
    _target_ver = _self_update_target_version(self_update_info)
    _current_ver = _read_skill_version()
    if _target_ver and _current_ver and not _is_newer_version(_target_ver, _current_ver):
        result["skipped"] = True
        result["error"] = (
            f"target version {_target_ver} is not newer than current {_current_ver}; "
            "skip self_update to avoid downgrade."
        )
        return result
    if not skip_dedup:
        _allowed, _reason = _self_update_gate(_target_ver)
        if not _allowed:
            result["skipped"] = True
            result["error"] = _reason
            return result

    if not isinstance(self_update_info, dict):
        result["error"] = "self_update info missing"
        return result
    if not self_update_info.get("available"):
        result["error"] = "self_update not available"
        return result

    args = self_update_info.get("args") or []
    if not isinstance(args, list) or not args:
        result["error"] = "self_update.args missing"
        return result
    if not os.path.exists(SELF_UPDATE_SCRIPT):
        result["error"] = f"self_update.py not found at {SELF_UPDATE_SCRIPT}"
        return result

    result["attempted"] = True
    if _target_ver:
        _SELF_UPDATE_TRIED_THIS_RUN.add(_target_ver)
        _self_update_mark(_target_ver, "in_progress")
    try:
        proc = subprocess.run(
            [sys.executable, SELF_UPDATE_SCRIPT, *[str(a) for a in args]],
            capture_output=True,
            timeout=timeout,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        result["stdout"] = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
        result["stderr"] = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
        if proc.returncode == 0:
            # self_update.py 成功时输出 JSON：{"code":0,"success":true,"package_version":"X.Y.Z",...}
            try:
                payload = json.loads(result["stdout"])
                if payload.get("success") and payload.get("code") == 0:
                    result["ok"] = True
                    result["new_version"] = payload.get("package_version")
                else:
                    result["error"] = payload.get("error") or "self_update returned non-success payload"
            except Exception as e:
                result["error"] = f"failed to parse self_update output: {e}"
        else:
            result["error"] = f"self_update exited with code {proc.returncode}"
    except subprocess.TimeoutExpired:
        result["error"] = f"self_update timed out after {timeout}s"
    except Exception as e:
        result["error"] = f"self_update launch failed: {e}"

    if _target_ver:
        if result.get("ok"):
            _self_update_mark(_target_ver, "ok")
        else:
            _self_update_mark(_target_ver, "failed", last_error=result.get("error"))
    return result


def _detect_skill_version_outdated(stdout_text):
    """解析 executor.py 的 stdout，判断是否被服务端版本拦截。
    返回 (matched: bool, error_obj: dict|None)。
    error_obj 含 self_update / latest_version 等结构化字段。
    """
    if not stdout_text:
        return False, None
    try:
        resp = json.loads(stdout_text)
    except Exception:
        return False, None
    if not isinstance(resp, dict):
        return False, None
    err = resp.get("error")
    if not isinstance(err, dict):
        return False, None
    if err.get("type") == "SKILL_VERSION_OUTDATED" or err.get("update_required") is True:
        return True, err
    return False, None


def _run_executor(tool_name, param_arg):
    """调用 executor.py，返回 (returncode, stdout_bytes, stderr_bytes)。

    对会输出流式进度的工具使用 Popen + 后台线程实时转发 stderr，
    让用户在终端能逐条看到公式/后台任务完成进度；其余工具仍走 capture_output=True。
    """
    import signal as _signal
    import threading
    # Windows: 将 executor.py 放到新进程组，防止 console Ctrl+C 广播干扰子进程
    extra_flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    # 在父进程中临时忽略 SIGINT，防止 communicate() 被残留信号中断
    try:
        old_handler = _signal.signal(_signal.SIGINT, _signal.SIG_IGN)
    except (OSError, ValueError):
        old_handler = None
    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        sub_timeout = _TOOL_SUBPROCESS_TIMEOUTS.get(tool_name, _DEFAULT_SUBPROCESS_TIMEOUT)

        # ── 流式进度工具：实时转发 stderr ──────────────
        stream_progress_tools = {"runMultiFormulaBatchStream", "resumeJob"}
        if tool_name in stream_progress_tools:
            proc = subprocess.Popen(
                [sys.executable, EXECUTOR, tool_name, param_arg],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=extra_flags,
                env=env,
            )
            stderr_chunks: list[bytes] = []

            def _stream_stderr():
                for raw in proc.stderr:
                    stderr_chunks.append(raw)
                    try:
                        sys.stderr.write(raw.decode("utf-8", errors="replace"))
                        sys.stderr.flush()
                    except Exception:
                        pass

            t = threading.Thread(target=_stream_stderr, daemon=True)
            t.start()
            try:
                stdout_bytes = proc.stdout.read()
            except Exception:
                stdout_bytes = b""
            try:
                proc.wait(timeout=sub_timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                t.join(timeout=5)
                msg = (
                    f"[call.py] tool '{tool_name}' exceeded {sub_timeout}s timeout; "
                    "subprocess killed. Consider splitting into smaller batches."
                )
                return 124, b"", msg.encode("utf-8")
            t.join(timeout=10)
            # stderr 已由线程实时打印到终端，这里返回空 bytes 避免 main() 二次输出
            return proc.returncode, stdout_bytes, b""

        # ── 其余工具：原有 capture_output 路径 ──────────────────────
        result = subprocess.run(
            [sys.executable, EXECUTOR, tool_name, param_arg],
            capture_output=True, timeout=sub_timeout,
            creationflags=extra_flags,
            env=env,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        # 子进程超时，返回明确错误码与提示，避免向上抛出导致客户端崩溃
        msg = (
            f"[call.py] tool '{tool_name}' exceeded {sub_timeout}s timeout; "
            "subprocess killed. Consider splitting into smaller batches."
        )
        return 124, b"", msg.encode("utf-8")
    except KeyboardInterrupt:
        # 捕获并重试一次（处理极端情况）
        try:
            result = subprocess.run(
                [sys.executable, EXECUTOR, tool_name, param_arg],
                capture_output=True, timeout=_TOOL_SUBPROCESS_TIMEOUTS.get(tool_name, _DEFAULT_SUBPROCESS_TIMEOUT),
                creationflags=extra_flags,
                env=env,
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            msg = (
                f"[call.py] tool '{tool_name}' exceeded subprocess timeout on retry; "
                "subprocess killed."
            )
            return 124, b"", msg.encode("utf-8")
    finally:
        if old_handler is not None:
            try:
                _signal.signal(_signal.SIGINT, old_handler)
            except (OSError, ValueError):
                pass


def _auto_save_chart(stdout_str, params):
    """renderChart 后自动保存 PNG，返回修改后的 stdout 供打印。支持 JSON 和 YAML 两种格式。"""
    # ── JSON 模式 ──
    try:
        data = json.loads(stdout_str)
        return _save_chart_from_json(data, params)
    except (json.JSONDecodeError, ValueError):
        pass
    # ── YAML 模式 ──
    return _save_chart_from_yaml(stdout_str, params)


def _save_chart_from_json(data, params):
    """从 JSON dict 提取 base64 并保存。"""
    if data.get("code") != 0:
        return json.dumps(data, indent=2, ensure_ascii=False)
    b64 = (data.get("data") or {}).get("base64", "")
    if not b64:
        return json.dumps(data, indent=2, ensure_ascii=False)
    out_path = _save_b64_to_png(b64, params)
    data["data"]["base64"] = f"<{len(b64)} chars>"
    data["data"]["saved_to"] = out_path
    data["data"]["auto_opened"] = sys.platform == "win32"
    return json.dumps(data, indent=2, ensure_ascii=False)


def _save_chart_from_yaml(stdout_str, params):
    """从 YAML 文本提取 base64 并保存。"""
    code_m = re.search(r'^code:\s*(\d+)', stdout_str, re.MULTILINE)
    if not code_m or code_m.group(1) != '0':
        return stdout_str
    # 在 YAML 行中查找 base64 字段
    b64 = None
    for line in stdout_str.split('\n'):
        stripped = line.strip()
        if stripped.startswith('base64:'):
            b64 = stripped[len('base64:'):].strip().strip("'\"")
            break
    if not b64:
        return stdout_str
    out_path = _save_b64_to_png(b64, params)
    # 替换 YAML 中的 base64 为摘要
    replacement = f"'<{len(b64)} chars, saved to {out_path}>'"
    stdout_str = stdout_str.replace(b64, replacement, 1)
    return stdout_str


def _save_b64_to_png(b64, params):
    """解码 base64 保存 JPG，返回文件路径。"""
    b64_clean = b64.split(",", 1)[1] if b64.startswith("data:") else b64
    # 修复 padding（base64 长度必须是 4 的倍数）
    b64_clean += "=" * (4 - len(b64_clean) % 4)
    name = params.get("title", params.get("name", "chart"))
    name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    output_dir = os.path.join(SKILL_ROOT, "output")
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"{name}.jpg")
    img_data = base64.b64decode(b64_clean)
    try:
        from io import BytesIO
        from PIL import Image
        img = Image.open(BytesIO(img_data)).convert("RGB")
        img.save(out_path, "JPEG", quality=90)
    except ImportError:
        # Pillow 未安装时直接写原始字节（保留服务端格式）
        with open(out_path, "wb") as f:
            f.write(img_data)
    if sys.platform == "win32":
        os.startfile(out_path)
    return out_path


# 维度标准顺序（用于重算 overall_score 时保持一致）
_DIM_ORDER = ["D1_估值", "D3_资金", "D4_波动率", "D5_宏观胜率",
              "D6_相关资产", "D7_技术形态", "D8_季节性", "D9_财务"]


def _score_to_signal(score):
    for lo, hi, label in [
        (80, 101, "强看多 ^^"), (65, 80, "偏多 ^"), (55, 65, "中性偏多 ->^"),
        (45, 55, "中性 ->"), (35, 45, "中性偏空 ->v"), (20, 35, "偏空 v"),
        (0,  20,  "强看空 vv"),
    ]:
        if lo <= score < hi:
            return label
    return "中性 ->"


def _auto_save_scan_dimensions(stdout_str, params):
    """scanDimensions 后**合并写入** output/ic_data/，返回精简摘要。

    分维度调用时（dimensions=["D1_估值"] 等），新扫描的维度覆盖旧结果，
    其他维度保留，并重算 overall_score / overall_signal / top_dimension / bottom_dimension。
    全量一次性调用与单次效果相同。
    """
    try:
        resp = json.loads(stdout_str)
    except (json.JSONDecodeError, ValueError):
        return stdout_str

    if resp.get("code") != 0:
        return stdout_str

    data = resp.get("data", {})
    # 提取资产名称（优先从请求参数取，其次从响应取）
    name = ""
    if isinstance(params.get("asset"), dict):
        name = params["asset"].get("name", "")
    if not name:
        name = (data.get("stock_name") or data.get("stock")
                or data.get("asset", {}).get("name") or "unknown")

    ic_dir = os.path.join(SKILL_ROOT, "output", "ic_data")
    os.makedirs(ic_dir, exist_ok=True)
    out_path = os.path.join(ic_dir, f"{name}_dimension_ic.json")

    # ── 合并已有文件 ─────────────────────────────────────
    merged = {}
    if os.path.exists(out_path):
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                merged = json.load(f)
        except Exception:
            merged = {}

    # 顶层字段：新数据优先（dimensions 单独处理）
    for k, v in data.items():
        if k not in ("dimensions", "overall_score", "overall_signal",
                     "top_dimension", "bottom_dimension"):
            merged[k] = v

    # 合并 dimensions：只更新本次真正被计算的维度（indicators 非空），
    # 其余保留已有结果，避免后端返回全量默认值时覆盖已有好数据。
    existing_dims = merged.get("dimensions", {})
    new_dims = data.get("dimensions", {})
    computed_dims = {k: v for k, v in new_dims.items()
                     if v.get("indicators")}   # 非空 indicators = 真正计算过
    existing_dims.update(computed_dims)
    merged["dimensions"] = existing_dims

    # ── 重算综合数值 ─────────────────────────────────────
    raw_scores = []
    dim_scores = []
    for dim in _DIM_ORDER:
        if dim not in existing_dims:
            continue
        s = existing_dims[dim].get("score", 50)
        w = 0.5 if dim == "D8_季节性" else 1.0
        dim_scores.append({"name": dim, "score": s})
        raw_scores.extend([s] * round(w * 10))

    if raw_scores:
        overall = round(sum(raw_scores) / len(raw_scores))
        merged["overall_score"] = overall
        merged["overall_signal"] = _score_to_signal(overall)
        merged["top_dimension"] = max(dim_scores, key=lambda x: x["score"])
        merged["bottom_dimension"] = min(dim_scores, key=lambda x: x["score"])

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    # ── 精简摘要（仅打印本次新扫维度） ───────────────────
    dim_summary = {}
    for dim_key in list(new_dims.keys()):
        dim_val = existing_dims.get(dim_key, {})
        if isinstance(dim_val, dict):
            dim_summary[dim_key] = {
                "score": dim_val.get("score"),
                "signal": dim_val.get("signal"),
                "indicators": [
                    {"label": ind.get("label") or ind.get("name"),
                     "current": ind.get("current_value"),
                     "ic_ir": ind.get("ic_ir")}
                    for ind in (dim_val.get("indicators") or [])[:3]
                ]
            }

    summary = {
        "code": 0,
        "data": {
            "asset": params.get("asset", {"name": name}),
            "scan_date": merged.get("scan_date"),
            "overall_score": merged.get("overall_score"),
            "overall_signal": merged.get("overall_signal"),
            "new_dimensions": sorted(new_dims.keys()),
            "file_has_dimensions": sorted(existing_dims.keys()),
            "new_dim_results": dim_summary,
            "saved_to": out_path,
            "note": (
                f"新增/更新 {len(new_dims)} 个维度，"
                f"文件已含 {len(existing_dims)}/8 个维度。"
                + ("" if len(existing_dims) >= 8 else
                   f" 剩余未扫：{sorted(set(_DIM_ORDER) - set(existing_dims.keys()))}")
            )
        },
        "task_id": resp.get("task_id")
    }
    return json.dumps(summary, indent=2, ensure_ascii=False)


def _auto_save_csv(stdout_str, params):
    """downloadData 后自动保存 CSV 到 output/，打印摘要而非原文。"""
    try:
        data = json.loads(stdout_str)
    except (json.JSONDecodeError, ValueError):
        # 后端直接返回 CSV 文本（Content-Type: text/csv）时 executor 已包一层 JSON
        return stdout_str

    if data.get("code") != 0:
        return json.dumps(data, indent=2, ensure_ascii=False)

    inner = data.get("data", {})
    # format=json 路径：inner 包含 labels/values
    # format=csv 路径：inner 是 CSV 字符串
    if isinstance(inner, str):
        # executor 把 CSV 文本放在 data 字段
        csv_text = inner
        data_name = params.get("id", "download")
        total_rows = len(csv_text.strip().split('\n')) - 1
    elif isinstance(inner, dict) and "labels" in inner:
        # json 路径：重新组装 CSV
        labels = inner.get("labels", [])
        values = inner.get("values", [])
        csv_text = "date,value\n" + "\n".join(
            f"{lbl},{'' if v is None else v}" for lbl, v in zip(labels, values)
        )
        data_name = inner.get("data_name", params.get("id", "download"))
        total_rows = len(labels)
    else:
        return json.dumps(data, indent=2, ensure_ascii=False)

    # 保存到 output/
    name = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(data_name))
    output_dir = os.path.join(SKILL_ROOT, "output")
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"{name}.csv")
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(csv_text)

    summary = {
        "code": 0,
        "data": {
            "saved_to": out_path,
            "total_rows": total_rows,
            "data_name": data_name,
        }
    }
    if isinstance(inner, dict):
        for k in ("provider", "dimension", "begin_date", "end_date"):
            if k in inner:
                summary["data"][k] = inner[k]
    return json.dumps(summary, indent=2, ensure_ascii=False)


def _auto_summarize_read_data(stdout_str, params):
    """readData last_column_full 模式：为布尔掩码数据注入 matched_names 平铺列表。

    触发条件：mode=last_column_full 且数据为布尔型（signature.is_bool=true 或值域仅含 0/1）。
    效果：注入 matched_count + matched_names（value=1 的命中名单），便于 LLM 直接读取，
    无需遍历 values 列表（如 5000 行只需读 matched_names 的 75 个名字）。

    零值过滤由后端 allow_zero_values 参数控制，此处不再重复过滤：
    - allow_zero_values=false（默认）：后端已过滤零值，values 仅含命中行
    - allow_zero_values=true：后端保留零值，values 含全部行，matched_names 仍仅含命中名单
    非布尔型数据原样返回，不做任何修改。
    """
    if params.get("mode") != "last_column_full":
        return stdout_str

    try:
        resp = json.loads(stdout_str)
    except (json.JSONDecodeError, ValueError):
        return stdout_str

    if resp.get("code") != 0:
        return stdout_str

    outer_data = resp.get("data", {})
    if not isinstance(outer_data, dict):
        return stdout_str

    inner_list = outer_data.get("data", [])
    if not isinstance(inner_list, list) or not inner_list:
        return stdout_str

    modified = False
    for item in inner_list:
        if not isinstance(item, dict):
            continue
        lcf = item.get("last_column_full")
        if not isinstance(lcf, dict):
            continue

        values = lcf.get("values", [])
        if not isinstance(values, list) or not values:
            continue

        # 判断是否为布尔型：优先读 signature.is_bool，其次抽样检测值域
        sig = item.get("signature") or {}
        is_bool = sig.get("is_bool", False)
        if not is_bool:
            sample = [v.get("value") for v in values[:200] if v.get("value") is not None]
            if sample and all(v in (0, 1, 0.0, 1.0) for v in sample):
                is_bool = True

        if not is_bool:
            continue

        # 布尔型：注入 matched_count + matched_names（仅统计命中=1的行）
        # values 列表本身不修改（已由后端按 allow_zero_values 控制）
        matched = [v for v in values if v.get("value") in (1, 1.0)]
        lcf["matched_count"] = len(matched)
        lcf["matched_names"] = [v.get("name", "") for v in matched if v.get("name")]
        modified = True

    if not modified:
        return stdout_str
    return json.dumps(resp, indent=2, ensure_ascii=False)


def _process_run_multi_formula_batch(stdout_str):
    """runMultiFormulaBatchStream 后处理：data.success=false 时把失败摘要提升到顶层。

    设计原则（方案 B）：
    - 不篡改服务端 code（保持 0），避免与服务端协议（成功 0 / 业务错误 -1）冲突
    - 不改进程 rc（HTTP 层确实成功）
    - 在顶层注入 success / errors / message，调用方只需看顶层字段即可识别失败
    - 区分「全部失败」和「部分成功」两种语义，避免部分成功结果被忽视
    """
    try:
        resp = json.loads(stdout_str)
    except (json.JSONDecodeError, ValueError):
        return stdout_str

    if resp.get("code") != 0:
        return stdout_str

    data = resp.get("data", {})
    if not isinstance(data, dict):
        return stdout_str

    # 仅在 success=false 时介入；success=true 或缺失（旧版本）时原样透传
    if data.get("success") is not False:
        return stdout_str

    errors = data.get("errors") or []
    dep = data.get("dependency_analysis") or {}
    total = data.get("total", len(errors))
    error_count = data.get("errorCount", len(errors))
    success_count = data.get("successCount", max(total - error_count, 0))

    resp["success"] = False
    resp["errors"] = [
        {
            "formula": e.get("formula"),
            "leftName": e.get("leftName"),
            "error": e.get("error"),
            "errorType": e.get("errorType"),
        }
        for e in errors
    ]

    if success_count == 0:
        resp["message"] = (
            f"runMultiFormulaBatchStream 全部失败（{error_count}/{total} 条），详见 errors 数组。"
        )
    else:
        resp["message"] = (
            f"runMultiFormulaBatchStream 部分失败（成功 {success_count}/{total}，失败 {error_count}/{total}），"
            f"成功结果仍在 data.data 中，失败详情见 errors。"
        )

    can_retry = dep.get("can_incremental_retry", False)
    if can_retry:
        resp["can_incremental_retry"] = True
        if dep.get("incremental_retry_suggestion"):
            resp["incremental_retry_suggestion"] = dep["incremental_retry_suggestion"]

    return json.dumps(resp, indent=2, ensure_ascii=False)


def _maybe_abort_on_client_validation(params):
    """若 _normalize_params 注入了客户端校验错误，立即输出并退出，避免无效远程调用。"""
    if isinstance(params, dict) and "__client_validation_error__" in params:
        msg = params.pop("__client_validation_error__")
        print(json.dumps({"code": 1, "message": msg}, ensure_ascii=False))
        sys.exit(1)


def _abort_on_run_multi_formula_missing_params(tool_name, params):
    if tool_name != "runMultiFormulaBatchStream":
        return
    if not isinstance(params, dict):
        print(json.dumps({"code": 1, "message": "runMultiFormulaBatchStream 参数必须是 JSON object。"}, ensure_ascii=False))
        sys.exit(1)
    if not params.get("task_id"):
        print(json.dumps({
            "code": 1,
            "message": (
                "task_id 必填。请先调用 newSession 获取 task_id；"
                "若通过 call.py 调用，请确认 GZQ_PARAMS、@file 或命令行 JSON 中包含有效参数。"
            ),
        }, ensure_ascii=False))
        sys.exit(1)
    formulas = params.get("formulas")
    if not isinstance(formulas, list) or not formulas:
        print(json.dumps({
            "code": 1,
            "message": (
                "formulas 必须是非空数组。"
                "请检查 GZQ_PARAMS、@file 或命令行 JSON 中是否包含至少一条公式字符串。"
            ),
        }, ensure_ascii=False))
        sys.exit(1)


def _normalize_params(tool_name, params):
    """常见参数名错误自动修正，减少 LLM 调用失败率。"""
    if not isinstance(params, dict):
        return params

    # runMultiFormulaBatchStream: formulas 元素必须是字符串，不能是对象
    if tool_name == "runMultiFormulaBatchStream" and "formulas" in params:
        fixed = []
        for item in params["formulas"]:
            if isinstance(item, str):
                fixed.append(item)
            elif isinstance(item, dict):
                # 尝试从对象中提取公式字符串
                f = item.get("formula") or item.get("expression") or item.get("value") or ""
                if f:
                    fixed.append(f)
        params["formulas"] = fixed

    # confirmDataMulti: 把常见错误参数名归一化到 data_desc
    # 错误形式：{"queries": ["A", "B"]} / {"query": "A"} / {"descriptions": [...]}
    # 正确形式：{"data_desc": "A,B"}（字符串，逗号分隔）
    if tool_name == "confirmDataMulti" and "data_desc" not in params:
        for alias in ("queries", "query", "descriptions", "description", "names", "data_descs"):
            if alias in params:
                v = params.pop(alias)
                if isinstance(v, list):
                    params["data_desc"] = ",".join(str(x).strip() for x in v if str(x).strip())
                else:
                    params["data_desc"] = str(v)
                break

    # readData: 检测中文/变量名形式的 ids 误用，返回明确错误而非传到服务端
    # 也把 variable_names / variable_name / index_title 这类常见错误参数名归一化
    if tool_name == "readData":
        for alias in ("variable_names", "variable_name", "index_title", "index_titles", "name", "names"):
            if alias in params and "ids" not in params:
                v = params.pop(alias)
                if isinstance(v, list):
                    params["ids"] = v
                else:
                    params["ids"] = [v]
                break
        # 进一步校验 ids 必须是 hex data_id（24 字符 16 进制），否则提前拦截
        ids = params.get("ids")
        if isinstance(ids, list) and ids:
            import re as _re
            bad = [x for x in ids if not (isinstance(x, str) and _re.fullmatch(r"[0-9a-fA-F]{24}", x))]
            if bad:
                # 直接把校验信息塞回参数，由 executor 后续上抛——不擅自调用，避免参数被 server 误吞
                params["__client_validation_error__"] = (
                    "readData 的 ids 必须是 runMultiFormulaBatchStream 返回的 24 位 hex data_id；"
                    f"以下值不是合法 data_id：{bad}。如需读取本批某个变量，请先在 runMultiFormulaBatchStream 返回的 results 中找到该变量的 _id，再传入 ids。"
                )

    return params


def main():
    _configure_parent_stdio()

    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    tool_name = sys.argv[1]

    # 工具名前置校验：非法/缺失立即报错，杜绝“静默挂死读 stdin”
    _reject_bad_tool_name(tool_name)

    # ── newSession：生成新 task_id 并持久化 ──────────────────────
    if tool_name == "newSession":
        new_id = str(uuid.uuid4())

        # 顺手清理超过 7 天的旧 session 文件，避免 output/ 累积垃圾
        _cleanup_stale_sessions()

        # 尝试解析 user_query 参数（用于服务端 trace 分析，失败不影响主流程）
        _raw_params = os.environ.get("GZQ_PARAMS", "").strip()
        if not _raw_params and len(sys.argv) >= 3:
            if sys.argv[2].startswith("@"):
                try:
                    with open(sys.argv[2][1:], "r", encoding="utf-8") as _f:
                        _raw_params = _f.read()
                except Exception:
                    pass
            else:
                _raw_params = " ".join(sys.argv[2:])
        _ns_params = {}
        try:
            _ns_params = json.loads(_raw_params or "{}")
        except Exception:
            pass
        user_query = _ns_params.get("user_query") or None
        user_id = _ns_params.get("user_id") or None
        # 当前模型：由上层 Agent 在 newSession 时传入，作为 body 参数随 session/begin 上报，
        # 供服务端在 newSession 这条日志上单独落库（与请求头来源相互独立、互不影响）。
        agent_model = (_ns_params.get("agent_model") or "").strip() or None

        # 在覆写 session 文件之前，先读取旧版本号（用于检测版本变更）
        _prev_version = None
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as _sf:
                _prev_version = json.load(_sf).get("skill_version_at_creation")
        except Exception:
            pass

        _write_session(new_id, user_query=user_query)
        _current_ver = _read_skill_version()
        _version_changed = bool(_prev_version and _prev_version != _current_ver)

        # 在 try 之外预初始化，避免 try 内异常导致后续引用 NameError
        _endpoint = ""
        _api_key = ""
        _channel = ""

        # Fire-and-forget：把原始问题上报给服务端，供 trace 分析用
        # 读取 config 获取 endpoint / api_key
        try:
            import urllib.request
            _cfg_path = os.path.join(SKILL_ROOT, "config.json")
            with open(_cfg_path, "r", encoding="utf-8") as _f:
                _cfg = json.load(_f)
            _local_cfg_path = os.path.join(SKILL_ROOT, "config.local.json")
            if os.path.exists(_local_cfg_path):
                with open(_local_cfg_path, "r", encoding="utf-8") as _f:
                    _local = json.load(_f)
                for k, v in _local.items():
                    if v not in (None, ""):
                        _cfg[k] = v
            _env_key = os.environ.get("QUANT_BUDDY_API_KEY", "").strip()
            if _env_key:
                _cfg["api_key"] = _env_key
            _endpoint = _cfg.get("endpoint", "").rstrip("/")
            _api_key = _cfg.get("api_key", "")
            _channel = _cfg.get("_channel", "")
            if _endpoint and _api_key:
                _payload_dict = {"task_id": new_id, "user_query": user_query}
                if user_id:
                    _payload_dict["user_id"] = user_id
                if agent_model:
                    _payload_dict["agent_model"] = agent_model
                _payload = json.dumps(_payload_dict,
                                      ensure_ascii=False).encode("utf-8")
                _headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {_api_key}",
                    "x-skill-version": _current_ver,
                }
                if _channel:
                    _headers["x-skill-channel"] = _channel
                _req = urllib.request.Request(
                    f"{_endpoint}/skill/session/begin",
                    data=_payload,
                    headers=_headers,
                    method="POST",
                )
                urllib.request.urlopen(_req, timeout=3)
        except Exception:
            pass  # 上报失败不影响 session 创建

        # 主动查询服务端版本：作为成功响应心跳之外的补充，按 TTL 节流，避免每次 newSession 都打服务端
        _ver_info = {}
        _version_check_state = {}
        _should_check_version, _version_check_reason = _should_run_new_session_version_check(_current_ver)
        if _should_check_version:
            try:
                import urllib.request as _u2  # noqa: PLC0415
                import urllib.parse as _up2  # noqa: PLC0415
                if _endpoint and _api_key:
                    _vc_headers = {
                        "Authorization": f"Bearer {_api_key}",
                        "x-skill-version": _current_ver,
                    }
                    if _channel:
                        _vc_headers["x-skill-channel"] = _channel
                    # 把 task_id / user_query 拼到 query string，供服务端 audit 中间件落库追踪
                    _vc_qs_pairs = [("task_id", new_id)]
                    if user_query:
                        _vc_qs_pairs.append(("user_query", user_query))
                    _vc_url = f"{_endpoint}/skill/version/check?" + _up2.urlencode(_vc_qs_pairs)
                    _vc_req = _u2.Request(
                        _vc_url,
                        headers=_vc_headers,
                        method="GET",
                    )
                    with _u2.urlopen(_vc_req, timeout=3) as _vc_resp:
                        _vc_body = _vc_resp.read().decode("utf-8")
                        _vc_data = json.loads(_vc_body)
                        if _vc_data.get("code") == 0 and _vc_data.get("success"):
                            _ver_info = _vc_data
                            _write_version_check_state(_current_ver, _ver_info)
            except Exception as _vc_exc:
                _write_version_check_state(_current_ver, error=str(_vc_exc))
        else:
            _version_check_state = _read_version_check_state()

        _version_check_latest = _ver_info.get("latest_version") or _version_check_state.get("latest_version")
        _version_check_update_required = bool(_ver_info.get("update_required") or _version_check_state.get("update_required"))
        _version_check_server_update_required = _version_check_update_required
        _version_check_ignored_reason = None
        _version_check_target = _version_check_latest or _self_update_target_version(_ver_info.get("self_update"))
        if (
            _version_check_update_required
            and _version_check_target
            and _current_ver
            and not _is_newer_version(_version_check_target, _current_ver)
        ):
            _version_check_update_required = False
            _version_check_ignored_reason = (
                f"server target version {_version_check_target} is not newer than current {_current_ver}; "
                "ignore to avoid downgrade."
            )
            if _ver_info:
                _ver_info = dict(_ver_info)
                _ver_info["update_required"] = False

        _result_obj = {
            "code": 0,
            "task_id": new_id,
            "skill_version": _current_ver,
            "version_changed_from_last_session": _version_changed,
            "previous_skill_version": _prev_version if _version_changed else None,
            "message": (
                f"新 session 已创建（skill {_current_ver}）。"
                + (f"检测到 skill 从 {_prev_version} 升级到 {_current_ver}，"
                   "旧上下文中的工具签名/参数可能已失效，必须先重读 SKILL.md 再继续。"
                   if _version_changed else
                   "task_id 已保存到 .session.json，后续调用自动注入。")
            ),
            "version_check": {
                "attempted": bool(_should_check_version and _endpoint and _api_key),
                "reason": _version_check_reason,
                "ttl_seconds": VERSION_CHECK_TTL_SECONDS,
                "latest_version": _version_check_latest,
                "update_required": _version_check_update_required,
                "server_update_required": _version_check_server_update_required,
            },
        }
        if _version_check_ignored_reason:
            _result_obj["version_check"]["ignored_reason"] = _version_check_ignored_reason
        _pending_self_update = None
        _pending_target_version = None
        if not _ver_info.get("update_required"):
            _pending_self_update = _get_pending_self_update()
            _pending_target_version = _self_update_target_version(_pending_self_update)

        _activation_self_update = None
        _activation_latest_version = None
        _activation_source = None
        if _ver_info.get("update_required"):
            _activation_self_update = _ver_info.get("self_update")
            _activation_latest_version = _ver_info.get("latest_version")
            _activation_source = "version_check"
            _result_obj["update_required"] = True
            _result_obj["latest_version"] = _ver_info.get("latest_version")
            _result_obj["package"] = _ver_info.get("package")
            _result_obj["self_update"] = _ver_info.get("self_update")
            _result_obj["try_order"] = _ver_info.get("try_order")
            _result_obj["reload_files"] = _ver_info.get("reload_files")
            _result_obj["update_message"] = _ver_info.get("message")
        elif _pending_self_update:
            _activation_self_update = _pending_self_update
            _activation_latest_version = _pending_target_version
            _activation_source = "pending_next_newSession"
            _result_obj["update_required"] = True
            _result_obj["latest_version"] = _pending_target_version
            _result_obj["self_update"] = _pending_self_update
            _result_obj["update_message"] = "检测到上一个 session 记录的待更新版本，正在 newSession 阶段安装新版。"

        if _activation_self_update:
            # 自动尝试本地 self_update（不依赖 Agent 阅读提示词），失败时保留升级元信息供上层兜底
            # newSession = 切换新会话：在上下文边界安装/激活新版，但仍遵守当日去重闸门
            _result_obj["auto_upgrade_source"] = _activation_source
            _upgrade = _attempt_self_update(_activation_self_update)
            if _upgrade.get("skipped"):
                _result_obj["auto_upgrade_attempted"] = False
                _result_obj["auto_upgrade_skipped"] = True
                _result_obj["auto_upgrade_skip_reason"] = _upgrade.get("error")
            elif _upgrade.get("attempted"):
                _result_obj["auto_upgrade_attempted"] = True
                if _upgrade.get("ok"):
                    # 升级成功后，当前 call.py / executor.py 已被新版本覆盖；
                    # 不在原进程继续执行原业务工具（避免新旧代码混跑），但本次 newSession 已写入新版 session。
                    _new_ver = _upgrade.get("new_version") or _activation_latest_version
                    _old_ver = _current_ver
                    try:
                        _write_session(new_id, user_query=user_query)
                        _new_ver = _read_skill_version() or _new_ver
                    except Exception:
                        pass
                    _result_obj["auto_upgrade_ok"] = True
                    _result_obj["previous_skill_version"] = _old_ver
                    _result_obj["skill_version"] = _new_ver
                    _result_obj["new_skill_version"] = _new_ver
                    _result_obj["version_changed_from_last_session"] = True
                    _result_obj["message"] = (
                        f"skill 已自动升级（{_old_ver} → {_new_ver}）。"
                        "本次 newSession 已切到新版 session；"
                        "请按 reload_files 重读上下文后重跑原始任务。"
                    )
                    # 保留 reload_files 供 Agent 使用；清理其他“升级前才有意义”的元信息
                    for _k in ("update_required", "latest_version", "package",
                               "self_update", "try_order", "update_message"):
                        _result_obj.pop(_k, None)
                else:
                    _result_obj["auto_upgrade_ok"] = False
                    _result_obj["auto_upgrade_error"] = _upgrade.get("error")
                    _result_obj["auto_upgrade_stderr"] = (_upgrade.get("stderr") or "")[-2000:]
        result = json.dumps(_result_obj, ensure_ascii=False, indent=2)
        out_file = os.path.join(tempfile.gettempdir(), "gzq_out.txt")
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(result)
        _safe_print(result)
        sys.exit(0)

    # ── 事件研究本地工具（不走 executor / 平台 API）───────────────
    if tool_name in ("webSearch", "buildEventStudy"):
        from event_study_local import bocha_web_search, build_event_study

        # 解析参数（复用与下方相同的优先级逻辑）
        _raw = os.environ.get("GZQ_PARAMS", "").strip()
        if not _raw and len(sys.argv) >= 3:
            if sys.argv[2].startswith("@"):
                with open(sys.argv[2][1:], "r", encoding="utf-8") as _f:
                    _raw = _f.read()
            else:
                _raw = " ".join(sys.argv[2:])
        if not _raw:
            _stdin = _read_stdin_nonblocking()
            if _stdin:
                _raw = _stdin
        _params = json.loads(_raw or "{}")

        try:
            if tool_name == "webSearch":
                _result = bocha_web_search(
                    query=_params.get("query", ""),
                    freshness_months=int(_params.get("freshness_months", 36)),
                    count=_params.get("count"),
                )
            else:
                _result = build_event_study(_params)
        except Exception as _exc:
            _result = {"code": 1, "error": str(_exc)}

        _output = json.dumps(_result, ensure_ascii=False, indent=2)
        out_file = os.path.join(tempfile.gettempdir(), "gzq_out.txt")
        with open(out_file, "w", encoding="utf-8") as _f:
            _f.write(_output)
        _safe_print(_output)
        sys.exit(0)

    # ── 版本守卫：检测旧会话与当前 skill 版本是否匹配 ─────────────
    current_version = _read_skill_version()
    if current_version:
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as _sf:
                _session_data = json.load(_sf)
            session_version = _session_data.get("skill_version_at_creation")
            if session_version is None or session_version != current_version:
                _mismatch_result = json.dumps({
                    "error": "SKILL_VERSION_MISMATCH",
                    "current_version": current_version,
                    "session_version": session_version,
                    "message": (
                        f"检测到 skill 版本不匹配（session 创建于 {session_version}，当前为 {current_version}）。"
                        "请立即调用 newSession 创建新 session，"
                        "然后强制重读 SKILL.md 及当前 workflow 后再继续。"
                    ),
                }, ensure_ascii=False, indent=2)
                out_file = os.path.join(tempfile.gettempdir(), "gzq_out.txt")
                with open(out_file, "w", encoding="utf-8") as _of:
                    _of.write(_mismatch_result)
                _safe_print(_mismatch_result)
                sys.exit(0)
        except FileNotFoundError:
            # 尚未创建过 session，不阻断（模型可能正要新建）
            pass
        except Exception:
            pass

    # ── 解析参数来源 ──────────────────────────────────────────────
    # 优先级: GZQ_PARAMS 环境变量 > @file > 命令行 argv > stdin
    raw = None
    at_file = None

    env_params = os.environ.get("GZQ_PARAMS", "").strip()
    if env_params:
        raw = env_params
    elif len(sys.argv) >= 3 and sys.argv[2].startswith("@"):
        at_file = sys.argv[2]          # @/path/to/file.json
    elif len(sys.argv) >= 3:
        raw = " ".join(sys.argv[2:])
    else:
        _stdin = _read_stdin_nonblocking()
        if _stdin:
            raw = _stdin

    if not at_file and not raw:
        raw = "{}"

    # ── 准备参数文件 ──────────────────────────────────────────────
    tmp_path = None
    params = {}
    try:
        if at_file:
            # @file：读取以解析 params（用于 renderChart 后处理），原文件直接转发
            file_path = at_file[1:]    # 去掉 @
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    params = json.load(f)
            except Exception:
                params = {}
            # 自动修正常见参数名错误
            params = _normalize_params(tool_name, params)
            _maybe_abort_on_client_validation(params)
            # 如果参数被修正了，需要重写文件
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(params, f, ensure_ascii=False)
            except Exception:
                pass
            param_arg = at_file
        else:
            # 解析 + 写临时文件
            try:
                params = json.loads(raw)
            except json.JSONDecodeError as e:
                print(json.dumps({
                    "code": 1,
                    "message": f"JSON 解析失败: {e}\n原始输入: {raw[:200]}"
                }, ensure_ascii=False))
                sys.exit(1)

            # 自动修正常见参数名错误
            params = _normalize_params(tool_name, params)
            _maybe_abort_on_client_validation(params)

            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="gzq_")
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(params, f, ensure_ascii=False)
            param_arg = f"@{tmp_path}"

        # ── 自动注入 session 字段（task_id、user_query）──────────────
        session_task_id = _read_session()
        _needs_rewrite = False
        if session_task_id and "task_id" not in params:
            params["task_id"] = session_task_id
            _needs_rewrite = True
        # 注入 user_query（供服务端 skill_call_logs trace 用）
        # 空串也视为“未传”，避免 Agent 误传空串导致后续工具 user_query 全部丢失
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as _sf:
                _uq = json.load(_sf).get("user_query")
            if _uq and not params.get("user_query"):
                params["user_query"] = _uq
                _needs_rewrite = True
        except Exception:
            pass
        if _needs_rewrite:
            rewrite_path = tmp_path or (at_file[1:] if at_file else None)
            if rewrite_path:
                with open(rewrite_path, "w", encoding="utf-8") as f:
                    json.dump(params, f, ensure_ascii=False)

        _abort_on_run_multi_formula_missing_params(tool_name, params)

        # ── 调用 executor.py ──────────────────────────────────────
        rc, stdout_bytes, stderr_bytes = _run_executor(tool_name, param_arg)

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        # ── 服务端版本拦截 → 自动 self_update（不依赖 Agent 阅读提示词）──
        _outdated, _err_obj = _detect_skill_version_outdated(stdout)
        if _outdated and _err_obj is not None:
            # 会话内（工具调用）路径：**不阻塞**当前调用。
            # 旧服务端若仍返回版本拦截错误，这里只记录 pending update，不在当前 session 激活新版。
            _pending = _record_pending_self_update(_err_obj.get("self_update"), source="version_outdated")
            try:
                _resp = json.loads(stdout)
            except Exception:
                _resp = None
            if isinstance(_resp, dict):
                if _pending.get("recorded"):
                    _resp["auto_upgrade"] = "pending_next_newSession"
                    _resp["auto_upgrade_note"] = (
                        "已记录待更新版本，不会在当前 session 中激活新版；"
                        "下一次 newSession 时会安装并切换到新版。"
                    )
                    if _pending.get("target_version"):
                        _resp["auto_upgrade_target_version"] = _pending["target_version"]
                elif _pending.get("skipped"):
                    _resp["auto_upgrade_skipped"] = True
                    _resp["auto_upgrade_skip_reason"] = _pending.get("reason")
                else:
                    _resp["auto_upgrade_attempted"] = False
                    _resp["auto_upgrade_error"] = _pending.get("reason")
                stdout = json.dumps(_resp, ensure_ascii=False, indent=2)

        # ── 版本心跳（4.4）：成功响应携带 skill_update_available 时，记录待更新 ──
        # 服务端在“版本通过”的成功响应里带 skill_latest_version / skill_update_available
        # (+ skill_self_update)。同一 session 内不激活新版；下一次 newSession 再安装切换。
        elif rc == 0:
            try:
                _resp_hb = json.loads(stdout)
            except Exception:
                _resp_hb = None
            if isinstance(_resp_hb, dict) and _resp_hb.get("skill_update_available") is True:
                _hb_info = _resp_hb.get("skill_self_update")
                _hb_target = _self_update_target_version(_hb_info) or _resp_hb.get("skill_latest_version")
                _hb_current = _read_skill_version()
                if _hb_target and _hb_current and not _is_newer_version(_hb_target, _hb_current):
                    _resp_hb["skill_update_available"] = False
                    _resp_hb["skill_update_ignored_reason"] = (
                        f"server target version {_hb_target} is not newer than current {_hb_current}; "
                        "ignore to avoid downgrade."
                    )
                    _resp_hb.pop("skill_self_update", None)
                    stdout = json.dumps(_resp_hb, ensure_ascii=False, indent=2)
                elif isinstance(_hb_info, dict) and _hb_info.get("available"):
                    _pending = _record_pending_self_update(_hb_info, source="heartbeat")
                    if _pending.get("recorded"):
                        _resp_hb["auto_upgrade"] = "pending_next_newSession"
                        _resp_hb["auto_upgrade_note"] = (
                            "检测到新版本，已记录待更新；当前 session 继续使用现有上下文，"
                            "下一次 newSession 时安装并启用新版。"
                        )
                        stdout = json.dumps(_resp_hb, ensure_ascii=False, indent=2)

        # renderChart / renderKLine 自动保存
        if tool_name in ("renderChart", "renderKLine") and rc == 0:
            stdout = _auto_save_chart(stdout, params)

        # downloadData CSV 自动落盘 output/
        if tool_name == "downloadData" and rc == 0:
            stdout = _auto_save_csv(stdout, params)
        # scanDimensions 自动保存 JSON 到 output/ic_data/
        if tool_name == "scanDimensions" and rc == 0:
            stdout = _auto_save_scan_dimensions(stdout, params)
        # readData last_column_full 布尔掩码：注入 matched_names
        if tool_name == "readData" and rc == 0:
            stdout = _auto_summarize_read_data(stdout, params)
        # runMultiFormulaBatchStream：code=0 但 data.success=false 时提升 errors
        if tool_name == "runMultiFormulaBatchStream" and rc == 0:
            stdout = _process_run_multi_formula_batch(stdout)
        # ── 从响应中捕获 task_id，更新 session（服务端生成的UUID优先）──
        if rc == 0:
            try:
                resp = json.loads(stdout)
                resp_task_id = resp.get("task_id") or (resp.get("data") or {}).get("task_id")
                if resp_task_id and resp_task_id != _read_session():
                    _write_session(resp_task_id)
                # runMultiFormulaBatchStream SSE 返回会在顶层/data 中携带 trace_id
                # 持久化到 session 供后续手工续传/调试，然后从输出中剥离避免泄露给 LLM
                # 例外：deferred 响应（research_24h）按 spec 必须把 trace_id / stream_url 暴露给 LLM
                if tool_name == "runMultiFormulaBatchStream" and isinstance(resp, dict):
                    sse_trace_id = resp.get("trace_id") or (
                        resp.get("data", {}) if isinstance(resp.get("data"), dict) else {}
                    ).get("trace_id")
                    if sse_trace_id:
                        _update_session_trace(
                            resp_task_id or _read_session(),
                            sse_trace_id,
                        )
                        if not resp.get("_deferred"):
                            # 剥离 trace_id（成功路径不暴露给 LLM）
                            resp.pop("trace_id", None)
                            if isinstance(resp.get("data"), dict):
                                resp["data"].pop("trace_id", None)
                    # 内部标记不应外泄
                    resp.pop("_deferred", None)
                    stdout = json.dumps(resp, indent=2, ensure_ascii=False)
            except Exception:
                pass

        # ── 始终写输出到固定文件，解决 VS Code 终端缓冲吞 stdout 的问题 ──
        # 必须在 print 之前写入，因为 print 可能因 GBK 编码崩溃（如 ✅ emoji）
        out_file = os.path.join(tempfile.gettempdir(), "gzq_out.txt")
        with open(out_file, "w", encoding="utf-8") as f:
            if stdout:
                f.write(stdout)
            if stderr:
                f.write(stderr)

        try:
            if stdout:
                print(stdout, end="")
            if stderr:
                print(stderr, end="", file=sys.stderr)
        except UnicodeEncodeError:
            # GBK 终端无法打印 emoji 等字符；改用 buffer 直写并以 ? 替换不可编码字符，
            # 确保 Agent 始终能从 stdout 读到结果，不依赖回读 gzq_out.txt。
            enc = getattr(sys.stdout, 'encoding', None) or 'utf-8'
            if stdout:
                sys.stdout.buffer.write(stdout.encode(enc, errors='replace'))
                sys.stdout.buffer.flush()
            enc_err = getattr(sys.stderr, 'encoding', None) or 'utf-8'
            if stderr:
                sys.stderr.buffer.write(stderr.encode(enc_err, errors='replace'))
                sys.stderr.buffer.flush()

        sys.exit(rc)

    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


if __name__ == "__main__":
    main()
