#!/usr/bin/env python3
r"""
quant-buddy-view 共享底座（self-contained，不依赖 quant-buddy-skill 的 call.py/executor.py）。

把原 quant-buddy-skill 里散落在 executor.py / call.py 的几样基础能力收敛到一处，
让本 skill 的三个工具（formula_package / static_page / build_dashboard）共用同一套：

  - 配置加载            load_config()  /  endpoint_of(cfg)
  - 版本 & 渠道请求头    SKILL_VERSION / SKILL_CHANNEL / headers()
  - 无代理 HTTP          _NO_PROXY_OPENER / http_json()
  - 入参解析 & 输出       read_params() / emit()

认证模型：register/list/revoke/refresh 与 static_page 凭 config.json 的 api_key（Bearer）
认身份；query 取数以 package/grant + signature 为能力凭证，CLI 本地有 api_key 时会可选附带用于审计归因。
每次用户任务先由
trace_context.py begin 建立 task_id，后续脚本通过入参复用，headers() 自动透传 x-task-id。
"""

import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

SKILL_NAME = "quant-buddy-view"

# ── 跳过 Windows 注册表代理检测（proxy_bypass_registry 在某些环境极慢）──
# 空 ProxyHandler() 完全绕过系统代理。
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(SCRIPT_DIR)

# QBV 与 QBS 都可能由 WorkBuddy/SkillHub 安装。逻辑 slug 不是可靠的物理目录名：
# SkillHub 的活动目录带 __skillhub 后缀，而历史备份也可能在同级。只接受下面的精确候选，
# 严禁 glob/递归扫描，以免把 backup 当成可执行 skill。
QBS_SKILL_DIR_CANDIDATES = ("quant-buddy-skill", "quant-buddy-skill__skillhub")


def resolve_qbs_skill_root(qbv_skill_root=None, environ=None):
    """Resolve the active QBS root without ever scanning backup directories.

    Resolution order is intentionally fixed: explicit QBS_SKILL_ROOT, then the
    traditional sibling directory, then the SkillHub sibling directory.  A root
    is valid only when scripts/call.py exists.  The diagnostic payload is kept
    structured so every QBV consumer can report exactly what deployment paths
    were checked.
    """
    env = os.environ if environ is None else environ
    root = Path(qbv_skill_root or SKILL_ROOT).resolve()
    override = str(env.get("QBS_SKILL_ROOT", "") or "").strip()
    if override:
        candidates = [Path(override).expanduser().resolve()]
    else:
        skills_root = root.parent
        candidates = [(skills_root / name).resolve() for name in QBS_SKILL_DIR_CANDIDATES]
    searched_roots = [str(candidate) for candidate in candidates]
    for candidate in candidates:
        call_script = candidate / "scripts" / "call.py"
        if call_script.is_file():
            return {
                "root": candidate,
                "call_script": call_script,
                "searched_roots": searched_roots,
                "used_env_override": bool(override),
            }
    final_call_script = (candidates[-1] / "scripts" / "call.py") if candidates else None
    return {
        "root": None,
        "call_script": final_call_script,
        "searched_roots": searched_roots,
        "used_env_override": bool(override),
    }


# ────────────────────────────────────────────────
# 版本 / 渠道（打包时注入）
# ────────────────────────────────────────────────

def _read_skill_version() -> str:
    """从 SKILL.md frontmatter 读取 version 字段；失败返回空字符串。"""
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


def _read_skill_channel() -> str:
    """从 config.json 读取 _channel 字段（打包时注入）；失败返回空字符串。"""
    cfg = os.path.join(SKILL_ROOT, "config.json")
    try:
        with open(cfg, "r", encoding="utf-8") as f:
            return json.load(f).get("_channel", "")
    except Exception:
        pass
    return ""


SKILL_VERSION = _read_skill_version()
SKILL_CHANNEL = _read_skill_channel()

# ── Windows 下强制 stdout/stderr 使用 UTF-8，避免服务端返回 emoji 时崩溃 ──
# line_buffering=True：每次 print 立即 flush，避免 PowerShell 首次读到空输出。
# 必须在任何 print 之前设置。
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)


# ────────────────────────────────────────────────
# 配置
# ────────────────────────────────────────────────

def load_config():
    """加载 config.json，叠加 config.local.json 覆盖；env var 兜底；params 里的 api_key 优先级最高。

    优先级（高到低）：调用方 params 里的 api_key（见 configure_trace_context）> config.json /
    config.local.json > QUANT_BUDDY_API_KEY 环境变量（仅前两者都为空时兜底，不常规依赖）。
    缺 endpoint 抛 FileNotFoundError/ValueError；api_key 缺失只在需要时由调用方决定是否报错。
    """
    config_path = os.path.join(SKILL_ROOT, "config.json")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"找不到配置文件: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    local_path = os.path.join(SKILL_ROOT, "config.local.json")
    if os.path.exists(local_path):
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                for k, v in (json.load(f) or {}).items():
                    if v not in (None, ""):
                        cfg[k] = v
        except Exception:
            pass
    if not cfg.get("api_key"):
        env_key = os.environ.get("QUANT_BUDDY_API_KEY", "").strip()
        if env_key:
            cfg["api_key"] = env_key
    if _API_KEY_OVERRIDE:
        cfg["api_key"] = _API_KEY_OVERRIDE
    return cfg


def load_config_require_key():
    """加载配置并强制 api_key 非空（注册/上传/列表/撤销等写操作用）。"""
    cfg = load_config()
    if not cfg.get("api_key"):
        raise ValueError(
            "api_key 为空。请设置环境变量 QUANT_BUDDY_API_KEY，或在 config.json / "
            "config.local.json 中填入 api_key（从 https://www.quantbuddy.cn/login 获取）"
        )
    return cfg


def endpoint_of(cfg):
    """Return the configured QuantBuddy API endpoint."""
    endpoint = (cfg.get("endpoint") or "").rstrip("/")
    if not endpoint:
        raise ValueError("config.json 缺少 endpoint")
    return endpoint


def api_url(endpoint, path):
    """Join endpoint and API path without duplicating /skill.

    config.endpoint may be either a site root (https://host) or the skill root
    (https://host/skill). Most server paths are documented as /skill/xxx; this
    helper keeps both endpoint forms producing exactly one /skill segment.
    """
    endpoint = (endpoint or "").rstrip("/")
    if not endpoint:
        raise ValueError("endpoint 为空")
    path = "/" + str(path or "").lstrip("/")
    if endpoint.endswith("/skill") and path.startswith("/skill/"):
        path = path[len("/skill"):]
    return endpoint + path


# ────────────────────────────────────────────────
# HTTP
# ────────────────────────────────────────────────

_TRACE_TASK_ID = None
_TRACE_TURN_ID = None
_TRACE_USER_QUERY = None
_TRACE_AGENT_INTENT = None
_TRACE_PREVIOUS_TURN_ID = None
_TRACE_AGENT_MODEL = None
_API_KEY_OVERRIDE = None  # 调用方（如 Playground）本次调用传入的 api_key，仅本进程生效，不落盘
_TRACE_CONTEXT_FILE_NAME = ".trace_context.json"


def host_managed_lifecycle():
    return str(os.environ.get("QB_HOST_MANAGED_LIFECYCLE") or "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def host_trace_context(params=None):
    if not host_managed_lifecycle():
        return None
    params = params if isinstance(params, dict) else {}
    host = {
        "task_id": str(os.environ.get("QB_HOST_TASK_ID") or "").strip(),
        "turn_id": str(os.environ.get("QB_HOST_TURN_ID") or "").strip(),
        "user_query": str(os.environ.get("QB_HOST_USER_QUERY") or "").strip(),
        "message_id": str(os.environ.get("QB_HOST_MESSAGE_ID") or "").strip() or None,
    }
    missing = [key for key in ("task_id", "turn_id", "user_query") if not host[key]]
    if missing:
        raise ValueError(f"Host Trace Context 缺少字段: {', '.join(missing)}")
    aliases = {
        "task_id": ("task_id",),
        "turn_id": ("turn_id",),
        "user_query": ("user_query", "userQuery"),
        "message_id": ("message_id",),
    }
    for field, names in aliases.items():
        supplied = next((str(params.get(name) or "").strip() for name in names if params.get(name)), "")
        if supplied and host.get(field) and supplied != host[field]:
            raise ValueError(f"Host 模式 {field} 已锁定为 {host[field]}，拒绝使用 {supplied}")
    return host


def _normalize_agent_model(value):
    """模型名仅做空白归一化；未知或空值保持 None，绝不猜测。"""
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def normalize_agent_intent(value):
    """规范化可选的每轮 Agent 意图；不从 user_query 推导。"""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized[:300] or None


def set_trace_context(task_id=None, user_query=None, api_key_override=None, agent_model=None,
                      turn_id=None, previous_turn_id=None, agent_intent=None):
    """设置当前进程的 Trace Context；供 read_params / trace_context.py 共用。"""
    global _TRACE_TASK_ID, _TRACE_TURN_ID, _TRACE_USER_QUERY, _TRACE_AGENT_INTENT
    global _TRACE_PREVIOUS_TURN_ID, _TRACE_AGENT_MODEL, _API_KEY_OVERRIDE
    _TRACE_TASK_ID = str(task_id).strip() if task_id else None
    _TRACE_TURN_ID = str(turn_id).strip() if turn_id else None
    _TRACE_USER_QUERY = str(user_query).strip() if user_query else None
    _TRACE_AGENT_INTENT = normalize_agent_intent(agent_intent)
    _TRACE_PREVIOUS_TURN_ID = str(previous_turn_id).strip() if previous_turn_id else None
    _TRACE_AGENT_MODEL = _normalize_agent_model(agent_model)
    _API_KEY_OVERRIDE = str(api_key_override).strip() if api_key_override else None
    return {
        "task_id": _TRACE_TASK_ID,
        "turn_id": _TRACE_TURN_ID,
        "user_query": _TRACE_USER_QUERY,
        "agent_intent": _TRACE_AGENT_INTENT,
        "previous_turn_id": _TRACE_PREVIOUS_TURN_ID,
        "agent_model": _TRACE_AGENT_MODEL,
    }


def configure_trace_context(params=None):
    """从参数或环境变量恢复本次任务上下文，不使用会互相覆盖的全局 session 文件。"""
    params = params if isinstance(params, dict) else {}
    nested = params.get("trace_context") if isinstance(params.get("trace_context"), dict) else {}
    host = host_trace_context(params)
    task_id = (host or {}).get("task_id") or params.get("task_id") or nested.get("task_id") or os.environ.get("QBV_TASK_ID")
    persisted = read_task_trace_context(task_id) if task_id else {}
    turn_id = ((host or {}).get("turn_id") or params.get("turn_id") or nested.get("turn_id") or os.environ.get("QBV_TURN_ID")
               or persisted.get("current_turn_id"))
    user_query = ((host or {}).get("user_query") or params.get("user_query") or params.get("userQuery") or nested.get("user_query")
                  or os.environ.get("QBV_USER_QUERY") or persisted.get("current_user_query"))
    previous_turn_id = (params.get("previous_turn_id") or nested.get("previous_turn_id")
                        or persisted.get("previous_turn_id"))
    if "agent_intent" in params:
        agent_intent = normalize_agent_intent(params.get("agent_intent"))
    elif "agent_intent" in nested:
        agent_intent = normalize_agent_intent(nested.get("agent_intent"))
    elif os.environ.get("QBV_AGENT_INTENT") is not None:
        agent_intent = normalize_agent_intent(os.environ.get("QBV_AGENT_INTENT"))
    else:
        agent_intent = normalize_agent_intent(persisted.get("current_agent_intent"))
    explicit_agent_model = params.get("agent_model") if "agent_model" in params else nested.get("agent_model")
    agent_model = _normalize_agent_model(explicit_agent_model)
    if not agent_model:
        agent_model = _normalize_agent_model(os.environ.get("QBV_AGENT_MODEL"))
    if not agent_model and task_id:
        agent_model = read_task_agent_model(task_id)
    # 调用方可在 params 里附带 api_key，本次调用临时覆盖 config.json，优先级最高；pop 掉避免
    # 混进后续以 params 为请求体转发的调用里。这次调用没提 api_key 字段（跟"显式传空值清空"不是一回事）
    # 时优先保留当前已生效的覆盖，不清空——避免同一进程内的重入调用（如 cmd_direct_deliver 内部临时切
    # task_id）把本次任务已经生效的 api_key 覆盖悄悄冲掉，导致同一个任务后半段悄悄改用 config.json 的
    # 默认身份。
    #
    # QBV_API_KEY 环境变量：跟 QBV_TASK_ID/QBV_USER_QUERY 同一档，是"这次调用要用哪个 key"的显式覆盖
    # 通道——调用方如果拿到一大份 @file 形式的既有参数（比如 publish_workflow.py 的 publish-plan.json,
    # 按设计不含凭证）、不方便/不想现改这份文件去塞 api_key，可以直接用这个环境变量传，效果等价于在
    # 顶层参数里传了 api_key，不会被 config.json 里已有的默认 key 悄悄盖掉。
    # 只在进程内还没有任何已生效覆盖时读取一次（当前调用/更早调用如果已经显式定了覆盖，那个更权威，不会
    # 被这里覆盖回环境变量的值）。
    #
    # 注意区分：这跟仅作最低优先级兜底的 QUANT_BUDDY_API_KEY（只在 config.json 也为空时才生效，见
    # load_config()）是两回事——不要混用，也不要因为加了这个就误以为改了 QUANT_BUDDY_API_KEY 的语义。
    if "api_key" in params or "api_key" in nested:
        api_key_override = params.pop("api_key", None) or nested.get("api_key")
    elif _API_KEY_OVERRIDE:
        api_key_override = _API_KEY_OVERRIDE
    else:
        api_key_override = os.environ.get("QBV_API_KEY", "").strip() or None
    return set_trace_context(
        task_id, user_query, api_key_override, agent_model,
        turn_id=turn_id, previous_turn_id=previous_turn_id, agent_intent=agent_intent,
    )


def current_trace_context():
    return {
        "task_id": _TRACE_TASK_ID,
        "turn_id": _TRACE_TURN_ID,
        "user_query": _TRACE_USER_QUERY,
        "agent_intent": _TRACE_AGENT_INTENT,
        "previous_turn_id": _TRACE_PREVIOUS_TURN_ID,
        "agent_model": _TRACE_AGENT_MODEL,
    }


def safe_task_id(task_id):
    """Return the filesystem-safe task id used by all QBV temporary artifacts."""
    return re.sub(r"[^0-9A-Za-z._-]+", "_", str(task_id or "")).strip("._-")


def task_temp_dir(task_id, create=False):
    """Return this task's isolated cross-platform system temporary directory."""
    safe_task = safe_task_id(task_id)
    if not safe_task:
        raise ValueError("task_id 不能为空")
    path = Path(tempfile.gettempdir()).resolve() / f"qbv_{safe_task}"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def task_temp_path(task_id, name, create_parent=False):
    """Return a contained path below task_temp_dir; absolute/traversal names are rejected."""
    relative = Path(str(name or ""))
    if not str(name or "").strip() or relative.is_absolute() or ".." in relative.parts:
        raise ValueError("任务临时文件名必须是 task_temp_dir 下的相对路径")
    root = task_temp_dir(task_id, create=create_parent)
    path = (root / relative).resolve()
    if path != root and root not in path.parents:
        raise ValueError("任务临时文件路径越界")
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def record_turn_tracking_diagnostic(task_id, turn_id, operation, detail):
    """Best-effort local audit detail that is never returned to Agent-facing JSON."""
    try:
        path = task_temp_path(task_id, ".turn_tracking_diagnostics.jsonl", create_parent=True)
        if isinstance(detail, str):
            detail_text = detail
        else:
            try:
                detail_text = json.dumps(detail, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                detail_text = str(detail)
        payload = {
            "timestamp_ms": int(time.time() * 1000),
            "source": "quant-buddy-view",
            "operation": str(operation or "turnTracking"),
            "task_id": str(task_id or "").strip() or None,
            "turn_id": str(turn_id or "").strip() or None,
            "detail": detail_text[:8000],
        }
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return True
    except (OSError, ValueError, TypeError):
        return False


def read_task_trace_context(task_id):
    """Best-effort 读取 task-scoped Turn 上下文，供独立 Python 进程恢复。"""
    try:
        path = task_temp_path(task_id, _TRACE_CONTEXT_FILE_NAME)
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if str(payload.get("task_id") or "").strip() != str(task_id or "").strip():
            return {}
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def read_task_agent_model(task_id):
    return _normalize_agent_model(read_task_trace_context(task_id).get("agent_model"))


def persist_task_trace_context(task_id, turn_id, user_query, previous_turn_id=None, agent_model=None,
                               handoff_context=None, agent_intent=None):
    """原子保存当前 Turn；可附带 QBS Handoff lineage，供独立 QBV 进程恢复。"""
    if not task_id or not turn_id or not str(user_query or "").strip():
        return False
    temp_path = None
    try:
        path = task_temp_path(task_id, _TRACE_CONTEXT_FILE_NAME, create_parent=True)
        previous = read_task_trace_context(task_id)
        if "initial_agent_intent" in previous:
            initial_agent_intent = normalize_agent_intent(previous.get("initial_agent_intent"))
        elif previous.get("current_turn_id"):
            initial_agent_intent = None
        else:
            initial_agent_intent = normalize_agent_intent(agent_intent)
        payload = {
            "version": "qbv_trace_context_v2",
            "task_id": str(task_id).strip(),
            "current_turn_id": str(turn_id).strip(),
            "current_user_query": str(user_query).strip(),
            "current_agent_intent": normalize_agent_intent(agent_intent),
            "previous_turn_id": str(previous_turn_id).strip() if previous_turn_id else None,
            "initial_user_query": previous.get("initial_user_query") or str(user_query).strip(),
            "initial_agent_intent": initial_agent_intent,
            "agent_model": _normalize_agent_model(agent_model) or _normalize_agent_model(previous.get("agent_model")),
        }
        effective_handoff = handoff_context if isinstance(handoff_context, dict) else previous.get("handoff_context")
        if isinstance(effective_handoff, dict):
            payload["handoff_context"] = effective_handoff
        fd, temp_path = tempfile.mkstemp(prefix=".trace-context-", suffix=".json", dir=str(path.parent))
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_path, path)
        return True
    except (OSError, ValueError, TypeError):
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        return False


def persist_task_agent_model(task_id, agent_model):
    """兼容旧调用：保留已有 Turn 字段，仅更新 task-scoped 模型名。"""
    model = _normalize_agent_model(agent_model)
    if not task_id or not model:
        return False
    existing = read_task_trace_context(task_id)
    if existing.get("current_turn_id") and existing.get("current_user_query"):
        return persist_task_trace_context(
            task_id, existing["current_turn_id"], existing["current_user_query"],
            existing.get("previous_turn_id"), model,
            agent_intent=existing.get("current_agent_intent"),
        )
    temp_path = None
    try:
        path = task_temp_path(task_id, _TRACE_CONTEXT_FILE_NAME, create_parent=True)
        payload = {"version": "qbv_trace_context_v2", "task_id": str(task_id).strip(), "agent_model": model}
        fd, temp_path = tempfile.mkstemp(prefix=".trace-context-", suffix=".json", dir=str(path.parent))
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_path, path)
        return True
    except (OSError, ValueError, TypeError):
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        return False

def cleanup_task_temp_files(task_id):
    """删除任务目录，并兼容清理旧版平铺 qbv_<task_id>_*.json/.md 文件。"""
    safe_task = safe_task_id(task_id)
    if not safe_task:
        return []
    temp_root = os.path.realpath(tempfile.gettempdir())
    deleted = []
    task_root = os.path.realpath(os.path.join(temp_root, f"qbv_{safe_task}"))
    if os.path.dirname(task_root) == temp_root and os.path.isdir(task_root):
        try:
            shutil.rmtree(task_root)
            deleted.append(task_root)
        except OSError:
            pass
    for name in os.listdir(temp_root):
        if not (name.startswith(f"qbv_{safe_task}_") and os.path.splitext(name)[1].lower() in {".json", ".md"}):
            continue
        path = os.path.realpath(os.path.join(temp_root, name))
        if os.path.dirname(path) != temp_root:
            continue
        try:
            os.remove(path)
            deleted.append(path)
        except OSError:
            continue
    return deleted


EXPIRED_TEMP_MAX_AGE_SECONDS = int(os.environ.get("QBV_EXPIRED_TEMP_MAX_AGE_SECONDS", str(24 * 3600)) or str(24 * 3600))
EXPIRED_TEMP_CHECK_TTL_SECONDS = int(os.environ.get("QBV_EXPIRED_TEMP_CHECK_TTL_SECONDS", "3600") or "3600")
EXPIRED_TEMP_CHECK_STATE_FILE = os.path.join(SKILL_ROOT, "output", ".expired_temp_clean_state.json")


def cleanup_expired_task_temp_files(max_age_seconds=None):
    """Best-effort 清理系统临时目录下超过 TTL 的 qbv_* 任务目录与旧版平铺文件。

    只扫根目录（不递归）、只按前缀+后缀白名单匹配、realpath 校验不逃逸出 temp 根目录、
    任何异常都吞掉不向上抛——这是给任务中断/异常退出兜底的最后一道清理，不依赖具体 task_id。
    """
    max_age = EXPIRED_TEMP_MAX_AGE_SECONDS if max_age_seconds is None else max_age_seconds
    deleted = []
    try:
        temp_root = os.path.realpath(tempfile.gettempdir())
        now = time.time()
        for name in os.listdir(temp_root):
            if not name.startswith("qbv_"):
                continue
            path = os.path.realpath(os.path.join(temp_root, name))
            if os.path.dirname(path) != temp_root:
                continue
            is_task_dir = os.path.isdir(path)
            is_legacy_file = os.path.isfile(path) and os.path.splitext(name)[1].lower() in {".json", ".md"}
            if not (is_task_dir or is_legacy_file):
                continue
            try:
                age = now - os.path.getmtime(path)
            except OSError:
                continue
            if age < max_age:
                continue
            try:
                if is_task_dir:
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                deleted.append(path)
            except OSError:
                continue
    except Exception:
        pass
    return deleted


def _should_run_expired_temp_clean() -> bool:
    if _truthy_env("QBV_FORCE_EXPIRED_TEMP_CLEAN"):
        return True
    st = _read_json_file(EXPIRED_TEMP_CHECK_STATE_FILE)
    try:
        age = time.time() - float(st.get("ts") or 0)
    except Exception:
        age = EXPIRED_TEMP_CHECK_TTL_SECONDS + 1
    return age >= EXPIRED_TEMP_CHECK_TTL_SECONDS


def maybe_cleanup_expired_task_temp_files() -> None:
    """每次工具运行的入口钩子之一：节流后台扫描系统临时目录，清理超期 qbv_* 残留。

    任何异常都吞掉，永不影响当前命令；用 TTL 状态文件节流，避免每条命令都全量 os.listdir。
    """
    try:
        if _truthy_env("QBV_DISABLE_EXPIRED_TEMP_CLEAN"):
            return
        if not _should_run_expired_temp_clean():
            return
        _write_json_file(EXPIRED_TEMP_CHECK_STATE_FILE, {"ts": int(time.time())})
        cleanup_expired_task_temp_files()
    except Exception:
        pass


def require_trace_context():
    if _TRACE_TASK_ID:
        return None
    return {
        "code": 1,
        "error": "TRACE_CONTEXT_REQUIRED",
        "message": (
            "发布/更新活页前必须先运行 scripts/trace_context.py begin，"
            "并把返回的 task_id 传给本次任务的每个 quant-buddy-view 命令。"
            "begin 本身也是后端写入调用，必须带和后续命令相同的身份"
            "（QBV_API_KEY 环境变量，或参数里的 api_key）——重试时别只补 begin 而漏掉它的 key，"
            "否则这条记录会归到 config.json 的默认账号。"
        ),
    }

def headers(api_key=None, accept=None):
    h = {
        "Content-Type": "application/json; charset=utf-8",
        "x-skill-version": SKILL_VERSION,
        "x-skill-name": SKILL_NAME,
    }
    if SKILL_CHANNEL:
        h["x-skill-channel"] = SKILL_CHANNEL
    if _TRACE_TASK_ID:
        h["x-task-id"] = _TRACE_TASK_ID
    if _TRACE_TURN_ID:
        h["x-turn-id"] = _TRACE_TURN_ID
    if _TRACE_AGENT_MODEL:
        h["x-agent-model"] = _TRACE_AGENT_MODEL
    if api_key:
        h["Authorization"] = f"Bearer {api_key}"
    if accept:
        h["Accept"] = accept
    return h


def http_json(method, url, hdrs, body=None, timeout=600):
    """发一个 JSON 请求并把响应解析为 dict；HTTP 错误体也尽量解析为 dict 返回。"""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with _NO_PROXY_OPENER.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"code": e.code, "success": False,
                    "error": {"message": getattr(e, "reason", str(e))}}
    except Exception as e:
        return {"code": 1, "success": False, "error": {"message": str(e)}}


# ────────────────────────────────────────────────
# 静默自更新：每次使用时按 GitHub tag 检查新版本，有则后台静默更新
#   发现走 GitHub tags API；应用复用 scripts/self_update.py（--trust-tls）。
#   全程 best-effort：任何异常都不得影响当前工具命令。
# ────────────────────────────────────────────────

SELF_UPDATE_SCRIPT = os.path.join(SCRIPT_DIR, "self_update.py")
VERSION_CHECK_STATE_FILE = os.path.join(SKILL_ROOT, "output", ".version_check_state.json")
SELF_UPDATE_STATE_FILE = os.path.join(SKILL_ROOT, "output", ".self_update_state.json")
MANAGED_INSTALL_FILE = os.path.join(SKILL_ROOT, ".managed-install.json")
GITHUB_TAGS_API = "https://api.github.com/repos/pseudo-longinus/quant-buddy-view/tags"
# 匿名 GitHub API 限流 60 次/小时/IP：默认 1 小时才检查一次
VERSION_CHECK_TTL = int(os.environ.get("QBV_VERSION_CHECK_TTL_SECONDS", "3600") or "3600")
VERSION_CHECK_HTTP_TIMEOUT = 4          # GitHub 请求短超时，避免拖慢当前命令
SELF_UPDATE_DAILY_FAIL_CAP = 1          # 同版本当日失败上限，超过则当天不再下载

# 进程内内存标记：本次运行是否已对某 target_version 触发过（一个进程最多一次）
_SELF_UPDATE_TRIED_THIS_RUN = set()


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _today_str() -> str:
    return time.strftime("%Y-%m-%d")


def _cmp_version(target: str, current: str) -> bool:
    """target 是否比 current 新（语义化按点分数字比较，容忍前缀 v）。"""
    def parse(v):
        if not v:
            return None
        t = str(v).strip().lstrip("vV")
        parts = t.split(".")
        nums = []
        for p in parts:
            if not re.fullmatch(r"\d+", p):
                return None
            nums.append(int(p))
        return tuple(nums)

    a, b = parse(target), parse(current)
    if a is None or b is None:
        return str(target or "").lstrip("vV") != str(current or "").lstrip("vV")
    w = max(len(a), len(b))
    a = a + (0,) * (w - len(a))
    b = b + (0,) * (w - len(b))
    return a > b


def _read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _write_json_file(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _is_qbs_managed_install() -> bool:
    """Return whether this QBV directory is owned by the QBS companion manager."""
    marker = _read_json_file(MANAGED_INSTALL_FILE)
    return (
        marker.get("manager") == "quant-buddy-skill"
        and marker.get("channel") == "companion"
    )


def _in_dev_checkout() -> bool:
    """SKILL_ROOT 处于 git 工作副本（上溯存在 .git）时视为源码/调试目录，跳过自更新，
    避免把开发中的仓库副本静默覆盖（与 SKILL.md「源码 checkout 调试不要 bundle 覆盖」一致）。
    先 realpath 解析 junction/symlink：全局安装若是指向 git 源码仓库的 junction，也能识别并跳过。"""
    try:
        d = os.path.realpath(SKILL_ROOT)
    except Exception:
        d = SKILL_ROOT
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return True
        parent = os.path.dirname(d)
        if parent == d:
            return False
        d = parent


def _should_run_version_check() -> bool:
    """TTL 节流：未强制、且距上次检查不足 TTL、且版本未变 → 不检查。
    决定检查后立刻写回时间戳，使失败也照样被节流。"""
    if _truthy_env("QBV_FORCE_VERSION_CHECK"):
        return True
    st = _read_json_file(VERSION_CHECK_STATE_FILE)
    if st.get("skill_version") != SKILL_VERSION:
        return True
    try:
        age = time.time() - float(st.get("ts") or 0)
    except Exception:
        age = VERSION_CHECK_TTL + 1
    return age >= VERSION_CHECK_TTL


def _fetch_latest_tag():
    """拉 GitHub tags，返回 (version_without_v, zipball_url) 里语义最大的一个；失败返回 (None, None)。"""
    req = urllib.request.Request(
        GITHUB_TAGS_API,
        headers={"User-Agent": "quant-buddy-view-self-update", "Accept": "application/vnd.github+json"},
    )
    with _NO_PROXY_OPENER.open(req, timeout=VERSION_CHECK_HTTP_TIMEOUT) as resp:
        tags = json.loads(resp.read().decode("utf-8"))
    best_name, best_url = None, None
    for t in tags if isinstance(tags, list) else []:
        name = (t or {}).get("name") or ""
        url = (t or {}).get("zipball_url") or ""
        if not name or not url:
            continue
        if best_name is None or _cmp_version(name, best_name):
            best_name, best_url = name, url
    if not best_name:
        return None, None
    return best_name.lstrip("vV"), best_url


def _self_update_gate(target_version: str) -> bool:
    """去重 + 当日失败上限：本进程已试过、或同日同版本失败已达上限 → 不触发。"""
    if not target_version:
        return False
    if target_version in _SELF_UPDATE_TRIED_THIS_RUN:
        return False
    st = _read_json_file(SELF_UPDATE_STATE_FILE)
    if st.get("date") == _today_str() and st.get("target_version") == target_version:
        if st.get("status") == "failed" and int(st.get("attempts") or 0) >= SELF_UPDATE_DAILY_FAIL_CAP:
            return False
    return True


def _spawn_self_update(target_version: str, zip_url: str) -> None:
    """后台、静默、不阻塞地触发 self_update.py（--trust-tls）。子进程会自行写 .self_update_state.json。"""
    if not os.path.exists(SELF_UPDATE_SCRIPT):
        return
    cmd = [
        sys.executable, SELF_UPDATE_SCRIPT,
        "--url", zip_url,
        "--version", target_version,
        "--trust-tls",
        "--skill-root", SKILL_ROOT,
    ]
    kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        # DETACHED_PROCESS | CREATE_NO_WINDOW：脱离当前控制台、无窗口
        kwargs["creationflags"] = 0x00000008 | 0x08000000
        kwargs["close_fds"] = True
    else:
        kwargs["start_new_session"] = True
        kwargs["close_fds"] = True
    subprocess.Popen(cmd, **kwargs)
    _SELF_UPDATE_TRIED_THIS_RUN.add(target_version)


def maybe_check_update() -> None:
    """每次工具运行的入口钩子：静默检查 GitHub 新 tag，有则后台自更新。任何异常都吞掉。"""
    try:
        if _truthy_env("QBV_DISABLE_SELF_UPDATE"):
            return
        # Companion-managed installations are reconciled only by QBS during
        # newSession. Do not race the standalone GitHub-tag updater.
        if _is_qbs_managed_install():
            return
        if not SKILL_VERSION:
            return
        if _in_dev_checkout():
            return
        if not _should_run_version_check():
            return
        # 记录本次检查时间戳（无论后续成败），保证 TTL 节流
        _write_json_file(VERSION_CHECK_STATE_FILE, {"skill_version": SKILL_VERSION, "ts": int(time.time())})
        latest, zip_url = _fetch_latest_tag()
        if not latest or not zip_url:
            return
        if not _cmp_version(latest, SKILL_VERSION):
            return
        if not _self_update_gate(latest):
            return
        _spawn_self_update(latest, zip_url)
    except Exception:
        # 自更新永不影响当前工具命令
        pass


# ────────────────────────────────────────────────
# 入参 / 输出
# ────────────────────────────────────────────────

def _coerce(v):
    """把命令行字符串值还原成 JSON 直觉类型：整数 / 浮点 / 布尔 / 其余原样字符串。"""
    low = v.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def _parse_flags(argv):
    """把命令行直觉写法 `--key value` / `--key=value` / `--flag` 解析成 dict。

    仅作为命令行 JSON 解析失败时的兜底——让 `list --scope test_all` 这类第一反应写法也能用。
    argv 里夹杂非 --flag 的散字时返回 None，交回上层按 JSON 报错（避免把 JSON 笔误误判成 flag）。
    """
    if not argv or not any(a.startswith("--") for a in argv):
        return None
    out = {}

    def put(key, value):
        normalized = key.replace("-", "_")
        if normalized in out and out[normalized] != value:
            raise ValueError(f"命令行参数冲突: --{key} 与同名参数的值不一致")
        out[normalized] = value

    i, n = 0, len(argv)
    while i < n:
        tok = argv[i]
        if not tok.startswith("--"):
            return None
        key = tok[2:]
        if "=" in key:
            key, val = key.split("=", 1)
            put(key, _coerce(val))
            i += 1
        elif i + 1 < n and not argv[i + 1].startswith("--"):
            put(key, _coerce(argv[i + 1]))
            i += 2
        else:  # 末尾或后接另一个 --flag：当布尔开关
            put(key, True)
            i += 1
    return out or None


def read_params(argv, env_var="VIEW_PARAMS"):
    """按 <env_var> > @file > 命令行 > stdin 优先级解析参数 dict。

    与 quant-buddy-skill 同款，规避 PowerShell GBK 命令行截断中文：优先用环境变量或 @file。
    命令行优先按 JSON 字符串解析；解析失败时兜底支持 `--key value` / `--key=value` 写法。
    """
    maybe_check_update()  # 每次工具运行时静默检查/触发自更新（best-effort，永不阻塞或报错）
    maybe_cleanup_expired_task_temp_files()  # 节流清理系统临时目录里超期的 qbv_* 残留（best-effort）
    from_argv = False
    raw = os.environ.get(env_var, "").strip()
    if not raw and len(argv) >= 1:
        if argv[0].startswith("@"):
            with open(argv[0][1:], "r", encoding="utf-8-sig") as f:
                raw = f.read()
        else:
            raw = " ".join(argv)
            from_argv = True
    if not raw and not sys.stdin.isatty():
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace").strip()
    raw = raw or "{}"
    try:
        params = json.loads(raw)
        configure_trace_context(params)
        return params
    except json.JSONDecodeError as e:
        if from_argv:
            try:
                flags = _parse_flags(argv)
            except ValueError as conflict:
                emit({"code": 1, "message": str(conflict)})
                sys.exit(1)
            if flags is not None:
                configure_trace_context(flags)
                return flags
        emit({"code": 1, "message": f"参数 JSON 解析失败: {e}", "raw": raw[:200],
              "hint": "参数用单个 JSON 字符串，如 list '{\"scope\":\"test_all\"}'；命令行也支持 --scope test_all"})
        sys.exit(1)


def emit(obj, out_name="view_out.txt"):
    """打印结果（dict→JSON，或原样字符串），并写一份到临时文件防终端缓冲吞输出。"""
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=2)
    out_file = os.path.join(tempfile.gettempdir(), out_name)
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
