#!/usr/bin/env python3
"""QBS -> QBV live-page routing, handoff, and local job idempotency.

This module is intentionally independent from the market-data execution path.  A
routing or registry failure must never turn a valid QBS answer into a hard
business failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from qbv_computation_capsule import (
    ComputationCapsuleError,
    build_computation_capsule,
    build_computation_capsule_from_validated_roles,
    validate_computation_capsule,
)


SCHEMA_VERSION = "qbs_qbv_handoff_v1"
JOB_SCHEMA_VERSION = "qbs_qbv_job_v2"
ROUTES = {"none", "suggest", "create", "existing_page"}
HANDOFF_ROUTES = {"create", "existing_page"}
TERMINAL_STATUSES = {"completed", "failed"}
JOB_STATUSES = {"queued", "running", *TERMINAL_STATUSES}
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_PAGE_ID_RE = re.compile(r"\bpage_[A-Za-z0-9_-]{6,}\b", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s<>\]\[\"']+", re.IGNORECASE)


_SKILL_ROOT = Path(__file__).resolve().parents[1]


def _resolve_session_file() -> Path:
    explicit = os.environ.get("QBS_SESSION_FILE", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    key = os.environ.get("QBS_SESSION_KEY", "").strip()
    if key:
        safe_key = re.sub(r"[^A-Za-z0-9_\-]", "_", key)[:64]
        return _SKILL_ROOT / "output" / f".session.{safe_key}.json"
    return _SKILL_ROOT / "output" / ".session.json"


def _load_current_session() -> Dict[str, Any]:
    path = _resolve_session_file()
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise LivePageRoutingError("QBS_SESSION_REQUIRED", f"缺少当前 QBS session: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise LivePageRoutingError("QBS_SESSION_INVALID", f"当前 QBS session 无法读取: {path}") from exc
    if not isinstance(payload, dict):
        raise LivePageRoutingError("QBS_SESSION_INVALID", f"当前 QBS session 不是 JSON object: {path}")
    return payload


def _read_source_skill_version() -> str:
    skill_md = _SKILL_ROOT / "SKILL.md"
    try:
        for line in skill_md.read_text(encoding="utf-8-sig").splitlines():
            if line.strip().startswith("version:"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return ""


def _resolve_prepare_lineage(task_id: Any, turn_id: Any, user_query: Any) -> tuple[str, str, str]:
    supplied = {
        "task_id": _compact_text(task_id),
        "turn_id": _compact_text(turn_id),
        "user_query": _compact_text(user_query),
    }
    if all(supplied.values()):
        return supplied["task_id"], supplied["turn_id"], supplied["user_query"]
    session = _load_current_session()
    session_values = {
        "task_id": _compact_text(session.get("task_id")),
        "turn_id": _compact_text(session.get("current_turn_id") or session.get("turn_id")),
        "user_query": _compact_text(session.get("current_user_query") or session.get("user_query")),
    }
    for field, explicit in supplied.items():
        current = session_values[field]
        if explicit and current and explicit != current:
            raise LivePageRoutingError("QBS_LINEAGE_MISMATCH", f"显式 {field} 与当前 QBS session 不一致")
    resolved = {field: supplied[field] or session_values[field] for field in supplied}
    missing = [field for field, value in resolved.items() if not value]
    if missing:
        raise LivePageRoutingError("QBS_SESSION_LINEAGE_INCOMPLETE", f"当前 QBS session 缺少: {', '.join(missing)}")
    return resolved["task_id"], resolved["turn_id"], resolved["user_query"]


class LivePageRoutingError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


_EXPLICIT_STATIC_PATTERNS = (
    "只要png", "只要 png", "仅png", "仅 png", "png就行", "png 就行",
    "本地图片", "不要网页", "不要页面", "不需要网页", "不需要活页", "不要活页",
    "只发图片", "只要图片", "导出图片", "不要画图", "不用画图", "不需要图",
    "无需图", "只要表格", "仅要表格", "只看表格",
)
_EXPLICIT_NO_VISUAL_RE = re.compile(
    r"(?:不要|不用|不需要|无需)[^。！？\n]{0,20}(?:画|绘制|生成|做)?[^。！？\n]{0,20}(?:图表|图|曲线)",
    re.IGNORECASE,
)
_STRONG_VISUAL_PATTERNS = (
    "k线图", "k 线图", "k线", "k 线", "分时图", "价格走势图", "行情走势图",
    "收益曲线", "收益对比曲线", "净值曲线", "基准对比", "回撤曲线", "多资产对比图", "资产对比图",
    "指标曲线", "排名图", "排行榜图", "热力图", "动态看板", "实时看板", "每日看板",
    "周度看板", "月度看板", "画个图", "画一张图", "生成图表", "交互图表",
)
_STRONG_PAGE_CAPABILITIES = (
    "可刷新", "自动刷新", "实时更新", "可交互", "交互式", "可分享", "公开链接",
    "持续跟踪", "长期跟踪", "每天更新", "每日更新", "定期更新", "看板", "活页",
)
_WEAK_DURABLE_PATTERNS = (
    "以后关注", "以后跟踪", "后续跟踪", "长期关注", "持续关注", "想做个页面",
    "想做一个页面", "整理成页面", "沉淀一下", "留着以后看",
)
_HIGH_RISK_PATTERNS = (
    "持仓", "仓位", "成本价", "持仓成本", "买入成本", "买入价", "股数", "持股数量",
    "止损", "止盈", "减仓", "加仓", "调仓", "自动化规则", "自动交易", "触发条件",
)
_PAGE_REFERENCE_HINTS = ("page_id", "page id", "活页链接", "这个活页", "现有活页", "已有活页")
_VISUAL_COMPOSITION_RES = (
    re.compile(r"(?:画|绘制)(?:成|为)?(?:一张|同一张|同一个)?[^。！？\n]{0,48}(?:图表|图|曲线)", re.IGNORECASE),
    re.compile(r"(?:放在|放到|放进)[^。！？\n]{0,40}(?:一张|同一张|同一个)?图(?:里|中)?", re.IGNORECASE),
    re.compile(r"(?:做成|制成|生成|展示为)[^。！？\n]{0,32}(?:图表|图|曲线)", re.IGNORECASE),
    re.compile(r"(?:同图|同一张图|同一个图|一张图)(?:里|中)?[^。！？\n]{0,24}(?:对比|比较|展示|查看|看)", re.IGNORECASE),
    re.compile(r"(?:放在一起|放到一起|放一起)[^。！？\n]{0,24}(?:画|绘制|做成图|制成图)", re.IGNORECASE),
)
_DURABLE_FACTOR_SCREEN_RES = (
    # 高频且结构稳定的价值质量榜单：即使用户没有说“图/页面”，结果天然适合
    # 排序、筛选、刷新和每日复用。显式“只要表格/不要网页”仍由上方静态规则拦截。
    re.compile(
        r"(?=.*(?:选股|筛选|排行|排名))(?=.*(?:top\s*\d+|前\s*\d+))"
        r"(?=.*(?:低\s*(?:pe|市盈率)|低估值))(?=.*(?:高\s*roe|高净资产收益率|高盈利))",
        re.IGNORECASE,
    ),
)


def _compact_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _match_any(text: str, patterns: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(pattern.lower() in lowered for pattern in patterns)


def _is_explicit_static_request(text: str) -> bool:
    return _match_any(text, _EXPLICIT_STATIC_PATTERNS) or bool(_EXPLICIT_NO_VISUAL_RE.search(text))


def _is_explicit_visual_request(text: str) -> bool:
    if _match_any(text, _STRONG_VISUAL_PATTERNS):
        return True
    return any(pattern.search(text) for pattern in _VISUAL_COMPOSITION_RES)


def _is_durable_factor_screen(text: str) -> bool:
    return any(pattern.search(text) for pattern in _DURABLE_FACTOR_SCREEN_RES)


def normalize_page_reference(value: Any) -> Optional[str]:
    text = _compact_text(value)
    if not text:
        return None
    page_match = _PAGE_ID_RE.search(text)
    if page_match:
        return page_match.group(0)
    url_match = _URL_RE.search(text)
    if url_match:
        return url_match.group(0).rstrip(".,;，。；）)")
    return text


def extract_page_reference(user_query: str) -> Optional[str]:
    query = _compact_text(user_query)
    page_match = _PAGE_ID_RE.search(query)
    if page_match:
        return page_match.group(0)
    url_match = _URL_RE.search(query)
    if url_match and _match_any(query, _PAGE_REFERENCE_HINTS + ("quantbuddy", "pages.")):
        return url_match.group(0).rstrip(".,;，。；）)")
    return None


def route_live_page(
    user_query: Any,
    page_reference: Any = None,
    persistence_confirmed: bool = False,
) -> Dict[str, Any]:
    """Return a deterministic QBS-side routing decision.

    The classifier is deliberately conservative: ordinary analysis remains in
    QBS; only explicit visual/page capabilities create a page automatically.
    """
    query = _compact_text(user_query)
    reference = normalize_page_reference(page_reference) or extract_page_reference(query)
    if reference:
        return {
            "route": "existing_page",
            "route_reason": ["existing_page_reference"],
            "page_reference": reference,
            "requires_persistence_confirmation": False,
        }

    if _is_explicit_static_request(query):
        return {
            "route": "none",
            "route_reason": ["static_image_only"],
            "page_reference": None,
            "requires_persistence_confirmation": False,
        }

    high_risk = _match_any(query, _HIGH_RISK_PATTERNS)
    strong_visual = _is_explicit_visual_request(query)
    strong_page = _match_any(query, _STRONG_PAGE_CAPABILITIES)
    durable_factor_screen = _is_durable_factor_screen(query)

    # "看看走势/分析走势" is intentionally weak unless the user also names a
    # concrete chart/page capability caught above.
    weak_trend_only = (
        ("走势" in query and not strong_visual and not strong_page)
        or query in {"看看走势", "看下走势", "分析一下走势", "最近走势", "走势怎么样"}
    )
    if weak_trend_only:
        return {
            "route": "none",
            "route_reason": ["weak_visual_expression"],
            "page_reference": None,
            "requires_persistence_confirmation": False,
        }

    if strong_visual or strong_page or durable_factor_screen:
        reasons = []
        if strong_visual:
            reasons.append("visualization_required")
        if strong_page:
            reasons.append("durable_interactive_page")
        if durable_factor_screen:
            reasons.append("structured_factor_screening_ranking")
        if high_risk and not persistence_confirmed:
            reasons.append("persistence_confirmation_required")
            return {
                "route": "suggest",
                "route_reason": reasons,
                "page_reference": None,
                "requires_persistence_confirmation": True,
            }
        return {
            "route": "create",
            "route_reason": reasons,
            "page_reference": None,
            "requires_persistence_confirmation": False,
        }

    if _match_any(query, _WEAK_DURABLE_PATTERNS):
        return {
            "route": "suggest",
            "route_reason": ["durable_value_but_schema_unclear"],
            "page_reference": None,
            "requires_persistence_confirmation": high_risk and not persistence_confirmed,
        }

    return {
        "route": "none",
        "route_reason": ["one_off_qbs_answer"],
        "page_reference": None,
        "requires_persistence_confirmation": False,
    }


def _required_id(name: str, value: Any) -> str:
    text = _compact_text(value)
    if not text or not _ID_RE.fullmatch(text):
        raise LivePageRoutingError(
            f"INVALID_{name.upper()}",
            f"{name} 需要为 1-128 位字母、数字、点、下划线、冒号或短横线",
        )
    return text


def _required_text(name: str, value: Any) -> str:
    text = _compact_text(value)
    if not text:
        raise LivePageRoutingError(f"{name.upper()}_REQUIRED", f"{name} 不能为空")
    return text


def _json_list(value: Any, name: str) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        raise LivePageRoutingError(f"INVALID_{name.upper()}", f"{name} 必须是 JSON array")
    return value


def _has_explicit_validation_receipt(validated_roles: Any, validation_receipts: Any) -> bool:
    if isinstance(validation_receipts, list) and validation_receipts:
        return True
    if not isinstance(validated_roles, list):
        return False
    for raw in validated_roles:
        if not isinstance(raw, dict):
            continue
        if raw.get("validation_receipt_file"):
            return True
        if isinstance(raw.get("validation_receipt_files"), list) and raw["validation_receipt_files"]:
            return True
        if isinstance(raw.get("validation_receipts"), list) and raw["validation_receipts"]:
            return True
    return False


def _validated_role_data_ids(validated_roles: Any) -> set[str]:
    if not isinstance(validated_roles, list):
        return set()
    return {
        str(item.get("data_id")).strip()
        for item in validated_roles
        if isinstance(item, dict) and str(item.get("data_id") or "").strip()
    }


def _validation_receipt_root() -> Path:
    override = _compact_text(os.environ.get("QBS_VALIDATION_RECEIPT_DIR"))
    if override:
        return Path(override).expanduser().resolve()
    return (_SKILL_ROOT / "output" / "validation_receipts").resolve()


def _discover_formula_validation_receipt(
    *,
    task_id: str,
    validated_roles: Any,
) -> tuple[list[Dict[str, Any]], str, Optional[str]]:
    """Find one exact successful formula receipt for the current materialized roles.

    Automatic reuse is deliberately fail-closed: a candidate must belong to the
    same task and contain every materialized ``data_id``.  Partial intersections
    are ignored because they cannot prove that one exact formula batch produced
    the complete page input.  Multiple exact matches are allowed only when they
    carry the same runtime-contract fingerprint.
    """
    expected_ids = _validated_role_data_ids(validated_roles)
    if not expected_ids:
        return [], "no_matching_receipt", None
    root = _validation_receipt_root()
    if not root.is_dir():
        return [], "no_matching_receipt", None

    exact_matches = []
    for path in sorted(root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if _compact_text(payload.get("task_id")) != task_id:
            continue
        if payload.get("tool_name") != "runMultiFormulaBatchStream":
            continue
        if payload.get("success") is not True or payload.get("status") != "completed":
            continue
        runtime_contract = payload.get("runtime_contract")
        if not isinstance(runtime_contract, dict):
            continue
        fingerprint = _compact_text(runtime_contract.get("contract_fingerprint"))
        if not fingerprint:
            continue
        output_ids = {
            str(item.get("data_id") or item.get("indexinfo_id") or "").strip()
            for item in payload.get("outputs", [])
            if isinstance(item, dict)
        }
        output_ids.discard("")
        if not expected_ids.issubset(output_ids):
            continue
        exact_matches.append((path.resolve(), payload, fingerprint))

    if not exact_matches:
        return [], "no_matching_receipt", None
    fingerprints = {item[2] for item in exact_matches}
    if len(fingerprints) != 1:
        raise LivePageRoutingError(
            "AMBIGUOUS_VALIDATION_RECEIPT_CONTRACT",
            "同一 task_id 与 data_id 命中多个不同公式合同，禁止猜测后交给 QBV",
        )

    selected_path, selected_payload, _ = sorted(
        exact_matches,
        key=lambda item: (_compact_text(item[1].get("created_at")), str(item[0])),
        reverse=True,
    )[0]
    receipt = dict(selected_payload)
    receipt["receipt_file"] = str(selected_path)
    receipt["receipt_sha256"] = "sha256:" + hashlib.sha256(selected_path.read_bytes()).hexdigest()
    return [receipt], "matched_by_task_and_data_ids", str(selected_path)


def build_qbv_handoff(
    *,
    task_id: Any,
    turn_id: Any,
    source_skill_id: Any = None,
    source_skill_id_status: Any = None,
    source_skill_name: Any = "quant-buddy-skill",
    source_skill_version: Any = None,
    user_query: Any,
    route: Any,
    route_reason: Any = None,
    page_reference: Any = None,
    validated_outputs: Any = None,
    validation_receipts: Any = None,
    computation_capsule: Any = None,
    requires_persistence_confirmation: bool = False,
    persistence_confirmed: bool = False,
) -> Dict[str, Any]:
    route_value = _compact_text(route)
    if route_value not in HANDOFF_ROUTES:
        raise LivePageRoutingError(
            "HANDOFF_ROUTE_NOT_ALLOWED",
            "只有 create 或 existing_page 可以生成 QBV Handoff",
        )
    if requires_persistence_confirmation and not persistence_confirmed:
        raise LivePageRoutingError(
            "PERSISTENCE_CONFIRMATION_REQUIRED",
            "高风险状态未经确认，不得生成 QBV Handoff 或入队",
        )
    reference = normalize_page_reference(page_reference)
    if route_value == "existing_page" and not reference:
        raise LivePageRoutingError(
            "PAGE_REFERENCE_REQUIRED",
            "existing_page 路由必须提供 page_reference",
        )
    reasons = _json_list(route_reason, "route_reason")
    if not all(isinstance(item, str) and item.strip() for item in reasons):
        raise LivePageRoutingError("INVALID_ROUTE_REASON", "route_reason 只能包含非空字符串")
    source_id_text = _compact_text(source_skill_id)
    source_id = _required_id("source_skill_id", source_id_text) if source_id_text else None
    source_status = _compact_text(source_skill_id_status) or ("available" if source_id else "unavailable")
    if source_status not in {"available", "unavailable"}:
        raise LivePageRoutingError(
            "INVALID_SOURCE_SKILL_ID_STATUS",
            "source_skill_id_status 只能是 available 或 unavailable",
        )
    if bool(source_id) != (source_status == "available"):
        raise LivePageRoutingError(
            "SOURCE_SKILL_ID_STATUS_MISMATCH",
            "source_skill_id 与 source_skill_id_status 不一致",
        )
    source_name = _required_id("source_skill_name", source_skill_name or "quant-buddy-skill")
    source_version_text = _compact_text(source_skill_version)
    source_version = _required_id("source_skill_version", source_version_text) if source_version_text else None
    task_value = _required_id("task_id", task_id)
    turn_value = _required_id("turn_id", turn_id)
    query_value = _required_text("user_query", user_query)
    capsule = None
    if computation_capsule is not None:
        capsule = validate_computation_capsule(
            computation_capsule,
            expected_task_id=task_value,
            expected_turn_id=turn_value,
            expected_user_query=query_value,
        )
    handoff = {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_value,
        "turn_id": turn_value,
        "source_skill_id": source_id,
        "source_skill_id_status": source_status,
        "source_skill_name": source_name,
        "source_skill_version": source_version,
        "user_query": query_value,
        "route": route_value,
        "route_reason": [item.strip() for item in reasons],
        "page_reference": reference,
        "validated_outputs": _json_list(validated_outputs, "validated_outputs"),
        "validation_receipts": _json_list(validation_receipts, "validation_receipts"),
        "requires_persistence_confirmation": bool(requires_persistence_confirmation),
        "persistence_confirmed": bool(persistence_confirmed),
    }
    if capsule is not None:
        handoff["computation_capsule"] = capsule
    return handoff


def validate_qbv_handoff(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise LivePageRoutingError("INVALID_HANDOFF", "Handoff 必须是 JSON object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise LivePageRoutingError("UNSUPPORTED_HANDOFF_SCHEMA", f"仅支持 {SCHEMA_VERSION}")
    forbidden = {"update_owned", "copy_to_owned", "direct", "fork", "unmatched"}
    if any(key in payload for key in forbidden):
        raise LivePageRoutingError("QBV_SOP_LEAKED_INTO_QBS", "QBS Handoff 不得包含页面归属或 QBV 路由动作")
    return build_qbv_handoff(
        task_id=payload.get("task_id"),
        turn_id=payload.get("turn_id"),
        source_skill_id=payload.get("source_skill_id"),
        source_skill_id_status=payload.get("source_skill_id_status"),
        source_skill_name=payload.get("source_skill_name", "quant-buddy-skill"),
        source_skill_version=payload.get("source_skill_version"),
        user_query=payload.get("user_query"),
        route=payload.get("route"),
        route_reason=payload.get("route_reason"),
        page_reference=payload.get("page_reference"),
        validated_outputs=payload.get("validated_outputs"),
        validation_receipts=payload.get("validation_receipts"),
        computation_capsule=payload.get("computation_capsule"),
        requires_persistence_confirmation=payload.get("requires_persistence_confirmation", False),
        persistence_confirmed=payload.get("persistence_confirmed", False),
    )


def idempotency_key_for(handoff: Dict[str, Any]) -> str:
    valid = validate_qbv_handoff(handoff)
    source = "\n".join((
        valid["task_id"],
        valid["turn_id"],
        valid["route"],
        normalize_page_reference(valid.get("page_reference")) or "",
    ))
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value: Any) -> datetime:
    text = _compact_text(value)
    if not text:
        raise LivePageRoutingError("INVALID_JOB_TIMESTAMP", "Job 时间戳不能为空")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LivePageRoutingError("INVALID_JOB_TIMESTAMP", f"无法解析 Job 时间戳: {text}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _worker_timeout_seconds(value: Any = None) -> int:
    raw = value
    if raw is None or raw == "":
        raw = os.environ.get("QBS_QBV_WORKER_TIMEOUT_SECONDS", "900")
    try:
        seconds = int(raw)
    except (TypeError, ValueError) as exc:
        raise LivePageRoutingError("INVALID_WORKER_TIMEOUT", "worker_timeout_seconds 必须是正整数") from exc
    if not 1 <= seconds <= 86400:
        raise LivePageRoutingError("INVALID_WORKER_TIMEOUT", "worker_timeout_seconds 必须在 1 到 86400 之间")
    return seconds


def _job_root(job_dir: Any = None) -> Path:
    configured = _compact_text(job_dir) or os.environ.get("QBS_QBV_JOB_DIR", "").strip()
    root = Path(configured) if configured else Path(tempfile.gettempdir()) / "quant-buddy-qbv-jobs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp_path, path)


class _RegistryLock:
    def __init__(self, path: Path, timeout: float = 5.0):
        self.path = path
        self.timeout = timeout
        self.fd = None

    def __enter__(self):
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, f"{os.getpid()}\n".encode("ascii"))
                return self
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise LivePageRoutingError("JOB_REGISTRY_LOCK_TIMEOUT", "QBV Job registry 正忙")
                time.sleep(0.05)

    def __exit__(self, exc_type, exc, tb):
        if self.fd is not None:
            os.close(self.fd)
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def prepare_qbv_job(
    handoff: Any,
    *,
    target_skill_id: Any = None,
    job_dir: Any = None,
    retry_failed: bool = False,
) -> Dict[str, Any]:
    valid = validate_qbv_handoff(handoff)
    key = idempotency_key_for(valid)
    root = _job_root(job_dir)
    job_path = root / f"{key}.job.json"
    handoff_path = root / f"{key}.handoff.json"
    lock_path = root / f"{key}.lock"
    now = _utc_now()
    with _RegistryLock(lock_path):
        existing = None
        if job_path.exists():
            existing = json.loads(job_path.read_text(encoding="utf-8"))
        if existing:
            status = existing.get("status")
            if status == "failed" and existing.get("retryable") is True and retry_failed:
                existing.update({
                    "status": "queued",
                    "failure_code": None,
                    "retryable": False,
                    "updated_at": now,
                    "attempt": int(existing.get("attempt") or 1) + 1,
                    "started_at": None,
                    "expires_at": None,
                    "completed_at": None,
                    "failed_at": None,
                    "published": False,
                    "public_verified": False,
                    "target_page_id": None,
                    "public_url": None,
                })
                _atomic_write_json(handoff_path, valid)
                _atomic_write_json(job_path, existing)
                return {**existing, "created": False, "reused": True, "should_spawn": True,
                        "handoff_file": str(handoff_path), "job_file": str(job_path)}
            return {**existing, "created": False, "reused": True, "should_spawn": False,
                    "handoff_file": str(handoff_path), "job_file": str(job_path)}

        target = _compact_text(target_skill_id) or None
        if target is not None:
            target = _required_id("target_skill_id", target)
        record = {
            "schema_version": JOB_SCHEMA_VERSION,
            "qbv_job_id": f"qbvjob_{key[:24]}",
            "idempotency_key": key,
            "task_id": valid["task_id"],
            "turn_id": valid["turn_id"],
            "source_skill_id": valid["source_skill_id"],
            "source_skill_id_status": valid["source_skill_id_status"],
            "source_skill_name": valid["source_skill_name"],
            "source_skill_version": valid["source_skill_version"],
            "target_skill_id": target,
            "route": valid["route"],
            "normalized_page_reference": normalize_page_reference(valid.get("page_reference")),
            "status": "queued",
            "delegation_tool": None,
            "delegation_id": None,
            "spawn_run_id": None,
            "child_session_key": None,
            "source_page_id": valid.get("page_reference") if valid["route"] == "existing_page" and str(valid.get("page_reference") or "").startswith("page_") else None,
            "target_page_id": None,
            "public_url": None,
            "failure_code": None,
            "retryable": False,
            "published": False,
            "public_verified": False,
            "worker_timeout_seconds": _worker_timeout_seconds(),
            "attempt": 1,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "expires_at": None,
            "completed_at": None,
            "failed_at": None,
        }
        _atomic_write_json(handoff_path, valid)
        _atomic_write_json(job_path, record)
        return {**record, "created": True, "reused": False, "should_spawn": True,
                "handoff_file": str(handoff_path), "job_file": str(job_path)}



def _fast_query_field_mapping(fields: list[str]) -> Dict[str, str]:
    mapping: Dict[str, str] = {"date": "date"}
    semantic_names = (
        (("收盘", "股价", "价格", "close"), "price"),
        (("成交量", "volume"), "volume"),
        (("成交额", "amount", "turnover"), "amount"),
        (("市盈率", "pe", "pe_ttm"), "pe"),
        (("市净率", "pb"), "pb"),
    )
    for field in fields:
        lowered = field.lower()
        for aliases, semantic in semantic_names:
            if any(alias.lower() in lowered for alias in aliases):
                mapping.setdefault(semantic, field)
                break
    return mapping


def _artifact_summary(artifact_file: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(artifact_file.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {"row_count": 0, "validation_receipts": []}
    summary = payload.get("summary") if isinstance(payload, dict) else None
    row_count = 0
    if isinstance(summary, dict):
        try:
            row_count = max(0, int(summary.get("total_data_points") or 0))
        except (TypeError, ValueError):
            row_count = 0
    receipts = []
    if isinstance(payload, dict) and isinstance(payload.get("pairwise_analysis"), list):
        receipts.append({
            "kind": "fast_query_pairwise_analysis",
            "pairwise_analysis": payload["pairwise_analysis"],
        })
    return {"row_count": row_count, "validation_receipts": receipts}


def prepare_fast_query_page(
    *,
    task_id: Any,
    turn_id: Any,
    user_query: Any,
    source_skill_version: Any,
    asset_id: Any,
    asset_name: Any,
    fields: Any,
    window_days: Any,
    artifact_file: Any,
    source_skill_id: Any = None,
    job_dir: Any = None,
    target_skill_id: Any = None,
    retry_failed: bool = False,
) -> Dict[str, Any]:
    """Create a hash-bound capsule, Handoff, and idempotent QBV Job in one call.

    This is the narrow adapter for a single-asset, multi-field ``fast_query``
    visual request.  It does not run any QBV page SOP and does not wait for page
    generation; it only prepares the independent Job for delegation.
    """
    route_result = route_live_page(user_query)
    if route_result["route"] != "create":
        raise LivePageRoutingError(
            "FAST_QUERY_PAGE_REQUIRES_CREATE",
            f"prepare-fast-query-page 仅接受 create 路由，当前为 {route_result['route']}",
        )
    if route_result.get("requires_persistence_confirmation"):
        raise LivePageRoutingError(
            "PERSISTENCE_CONFIRMATION_REQUIRED",
            "高风险持久状态未经确认，不得准备 QBV Job",
        )
    if isinstance(fields, str):
        field_list = [item.strip() for item in fields.split(",") if item.strip()]
    elif isinstance(fields, list):
        field_list = [_compact_text(item) for item in fields if _compact_text(item)]
    else:
        raise LivePageRoutingError("INVALID_FAST_QUERY_FIELDS", "fields 必须是数组或逗号分隔字符串")
    if not 2 <= len(field_list) <= 4:
        raise LivePageRoutingError("INVALID_FAST_QUERY_FIELDS", "窄快路径只接受 2 到 4 个标准历史字段")
    try:
        days = int(window_days)
    except (TypeError, ValueError) as exc:
        raise LivePageRoutingError("INVALID_WINDOW_DAYS", "window_days 必须是正整数") from exc
    if days <= 0:
        raise LivePageRoutingError("INVALID_WINDOW_DAYS", "window_days 必须是正整数")

    artifact = Path(str(artifact_file or "")).expanduser().resolve()
    if not artifact.is_file():
        raise LivePageRoutingError("ARTIFACT_FILE_MISSING", f"artifact_file 不存在: {artifact}")
    asset_id_text = _required_text("asset_id", asset_id)
    asset_name_text = _required_text("asset_name", asset_name)
    artifact_meta = _artifact_summary(artifact)
    validated_output = {
        "role": "main_series",
        "artifact_file": str(artifact),
        "row_count": artifact_meta["row_count"],
        "field_mapping": _fast_query_field_mapping(field_list),
    }
    contract = {
        "kind": "fast_query",
        "payload": {
            "assets": [asset_id_text],
            "query_type": "window",
            "fields": field_list,
            "window_days": days,
        },
    }
    capsule = build_computation_capsule(
        task_id=task_id,
        turn_id=turn_id,
        user_query=user_query,
        page_intent={
            "question_to_answer": _required_text("user_query", user_query),
            "recommended_page_type": "single_asset_multi_metric_timeseries",
            "primary_visualization": "price_volume_valuation_timeseries",
            "required_roles": ["main_series"],
        },
        asset_resolution={
            "query": asset_name_text,
            "canonical_name": asset_name_text,
            "canonical_id": asset_id_text,
        },
        validated_contracts=[{
            "role": "main_series",
            "kind": "fast_query",
            "contract": contract,
        }],
        validated_outputs=[validated_output],
        validated_insights=[],
        validation_receipts=artifact_meta["validation_receipts"],
    )
    handoff = build_qbv_handoff(
        task_id=task_id,
        turn_id=turn_id,
        source_skill_id=source_skill_id,
        source_skill_version=source_skill_version,
        user_query=user_query,
        route="create",
        route_reason=route_result["route_reason"],
        validated_outputs=capsule["validated_outputs"],
        validation_receipts=capsule["validation_receipts"],
        computation_capsule=capsule,
    )
    job = prepare_qbv_job(
        handoff,
        target_skill_id=target_skill_id,
        job_dir=job_dir,
        retry_failed=retry_failed,
    )
    return {
        **job,
        "route": "create",
        "route_reason": route_result["route_reason"],
        "source_skill_id_status": handoff["source_skill_id_status"],
        "computation_coverage": "main_series",
        "artifact_file": str(artifact),
        "artifact_sha256": capsule["validated_outputs"][0]["data_hash"],
    }


def prepare_validated_page(
    *,
    task_id: Any = None,
    turn_id: Any = None,
    user_query: Any = None,
    source_skill_version: Any = None,
    page_intent: Any,
    validated_roles: Any,
    route: Any = None,
    page_reference: Any = None,
    asset_resolution: Any = None,
    validated_insights: Any = None,
    validation_receipts: Any = None,
    formula_runtime_contract: Any = None,
    source_skill_id: Any = None,
    target_skill_id: Any = None,
    job_dir: Any = None,
    retry_failed: bool = False,
    persistence_confirmed: bool = False,
) -> Dict[str, Any]:
    """Prepare Capsule + Handoff + idempotent Job from compact validated roles.

    This is the generic counterpart to ``prepare-fast-query-page``.  It is used
    after QBS has already produced and validated structured artifacts for ranking,
    comparison, backtest, heatmap, or other page-worthy analysis.  It deliberately
    stops before any QBV routing, ownership, rendering, publishing, or acceptance.
    """
    task_id, turn_id, user_query = _resolve_prepare_lineage(task_id, turn_id, user_query)
    source_skill_version = _compact_text(source_skill_version) or _read_source_skill_version()
    if not source_skill_version:
        raise LivePageRoutingError("SOURCE_SKILL_VERSION_REQUIRED", "无法从 SKILL.md 解析 source_skill_version")
    route_result = route_live_page(
        user_query,
        page_reference=page_reference,
        persistence_confirmed=bool(persistence_confirmed),
    )
    requested_route = _compact_text(route) or route_result["route"]
    if route_result.get("requires_persistence_confirmation"):
        raise LivePageRoutingError(
            "PERSISTENCE_CONFIRMATION_REQUIRED",
            "高风险持久状态未经确认，不得准备 QBV Job",
        )
    if requested_route not in HANDOFF_ROUTES:
        raise LivePageRoutingError(
            "VALIDATED_PAGE_REQUIRES_HANDOFF_ROUTE",
            f"prepare-validated-page 仅接受 create/existing_page，当前为 {requested_route}",
        )
    if requested_route != route_result["route"]:
        raise LivePageRoutingError(
            "ROUTE_DECISION_MISMATCH",
            f"请求 route={requested_route} 与分类器 route={route_result['route']} 不一致",
        )

    receipt_discovery = "explicit" if _has_explicit_validation_receipt(
        validated_roles, validation_receipts
    ) else "no_matching_receipt"
    discovered_receipt_file = None
    effective_validation_receipts = validation_receipts
    if receipt_discovery != "explicit":
        (
            discovered_receipts,
            receipt_discovery,
            discovered_receipt_file,
        ) = _discover_formula_validation_receipt(
            task_id=task_id,
            validated_roles=validated_roles,
        )
        if discovered_receipts:
            effective_validation_receipts = discovered_receipts

    capsule = build_computation_capsule_from_validated_roles(
        task_id=task_id,
        turn_id=turn_id,
        user_query=user_query,
        page_intent=page_intent,
        asset_resolution=asset_resolution,
        validated_roles=validated_roles,
        validated_insights=validated_insights,
        validation_receipts=effective_validation_receipts,
        formula_runtime_contract=formula_runtime_contract,
    )
    handoff = build_qbv_handoff(
        task_id=task_id,
        turn_id=turn_id,
        source_skill_id=source_skill_id,
        source_skill_version=source_skill_version,
        user_query=user_query,
        route=requested_route,
        route_reason=route_result["route_reason"],
        page_reference=route_result.get("page_reference"),
        validated_outputs=capsule["validated_outputs"],
        validation_receipts=capsule["validation_receipts"],
        computation_capsule=capsule,
        requires_persistence_confirmation=False,
        persistence_confirmed=bool(persistence_confirmed),
    )
    job = prepare_qbv_job(
        handoff,
        target_skill_id=target_skill_id,
        job_dir=job_dir,
        retry_failed=bool(retry_failed),
    )
    artifacts = [
        {
            "role": item["role"],
            "artifact_file": item.get("artifact_file"),
            "data_hash": item.get("data_hash"),
            "row_count": item.get("row_count"),
        }
        for item in capsule["validated_outputs"]
    ]
    return {
        **job,
        "route": requested_route,
        "route_reason": route_result["route_reason"],
        "source_skill_id_status": handoff["source_skill_id_status"],
        "computation_coverage": [item["role"] for item in capsule["validated_outputs"]],
        "artifacts": artifacts,
        "validation_receipt_count": len(capsule["validation_receipts"]),
        "validation_receipt_discovery": receipt_discovery,
        "formula_runtime_contract_attached": bool(capsule.get("formula_runtime_contract")),
        **(
            {"discovered_validation_receipt_file": discovered_receipt_file}
            if discovered_receipt_file
            else {}
        ),
        "handoff_ready_at": job.get("updated_at") or job.get("created_at"),
    }


def prepare_industry_ranking_page(
    *,
    data_id: Any,
    index_title: Any,
    window_days: Any,
    asset_count: Any,
    as_of_date: Any = None,
    formula: Any = None,
    task_id: Any = None,
    turn_id: Any = None,
    user_query: Any = None,
    source_skill_version: Any = None,
    source_skill_id: Any = None,
    target_skill_id: Any = None,
    job_dir: Any = None,
    retry_failed: bool = False,
) -> Dict[str, Any]:
    """Prepare a deterministic QBV handoff from an already materialized industry ranking.

    The command is intentionally narrow: QBS has already executed and validated the
    industry aggregation formula, so this function only binds the existing data_id,
    refresh formula, page intent, lineage, and idempotent QBV Job.  It never renders
    a static chart or reruns the formula.
    """
    task_id, turn_id, user_query = _resolve_prepare_lineage(task_id, turn_id, user_query)
    data_id_value = _required_id("data_id", data_id)
    index_title_value = _required_text("index_title", index_title)
    try:
        window_days_value = int(window_days)
    except (TypeError, ValueError) as exc:
        raise LivePageRoutingError("INVALID_WINDOW_DAYS", "window_days 必须是正整数") from exc
    if not 1 <= window_days_value <= 2500:
        raise LivePageRoutingError("INVALID_WINDOW_DAYS", "window_days 必须在 1 到 2500 之间")
    try:
        asset_count_value = int(asset_count)
    except (TypeError, ValueError) as exc:
        raise LivePageRoutingError("INVALID_ASSET_COUNT", "asset_count 必须是正整数") from exc
    if not 1 <= asset_count_value <= 5000:
        raise LivePageRoutingError("INVALID_ASSET_COUNT", "asset_count 必须在 1 到 5000 之间")

    as_of_date_value = _compact_text(as_of_date)
    if as_of_date_value and not re.fullmatch(r"\d{8}", as_of_date_value):
        raise LivePageRoutingError("INVALID_AS_OF_DATE", "as_of_date 必须是 YYYYMMDD")
    formula_value = _compact_text(formula) or (
        f'行业近{window_days_value}日涨跌幅='
        f'成分平均汇总(涨跌幅("全市场每日收盘价",{window_days_value}),"申万资产所属指数")'
    )
    role = {
        "role": "industry_aggregation_ranking",
        "data_id": data_id_value,
        "index_title": index_title_value,
        "description": (
            f"申万一级行业成分股近{window_days_value}个交易日区间收益的算术平均排名"
        ),
        "asset_count": asset_count_value,
        "field_mapping": {
            "industry_code": "asset",
            "industry_name": "name",
            "return_value": "value",
            "as_of_date": "date",
        },
        "formula": formula_value,
        "window_days": window_days_value,
        "aggregation": "arithmetic_mean_of_constituent_window_returns",
        "universe": "申万一级行业",
        "value_semantics": "decimal_return",
    }
    if as_of_date_value:
        role["date"] = as_of_date_value

    return prepare_validated_page(
        task_id=task_id,
        turn_id=turn_id,
        user_query=user_query,
        source_skill_version=source_skill_version,
        page_intent={
            "question_to_answer": _compact_text(user_query),
            "title_hint": f"申万一级行业近{window_days_value}个交易日涨跌幅排名",
            "recommended_page_type": "industry_return_ranking",
            "primary_visualization": "horizontal_ranked_bar_chart",
            "required_roles": ["industry_aggregation_ranking"],
            "interaction_requirements": ["sort", "positive_negative_color", "hover_detail", "refresh"],
            "display_contract": {
                "positive_color": "red",
                "negative_color": "green",
                "zero_axis": True,
                "show_methodology": True,
            },
        },
        validated_roles=[role],
        asset_resolution={
            "universe": "申万一级行业",
            "asset_count": asset_count_value,
            "classification": "SW_L1",
        },
        source_skill_id=source_skill_id,
        target_skill_id=target_skill_id,
        job_dir=job_dir,
        retry_failed=bool(retry_failed),
    )


def _find_job_path(qbv_job_id: Any, job_dir: Any = None) -> Path:
    job_id = _required_id("qbv_job_id", qbv_job_id)
    root = _job_root(job_dir)
    matches = []
    for path in root.glob("*.job.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("qbv_job_id") == job_id:
            matches.append(path)
    if not matches:
        raise LivePageRoutingError("QBV_JOB_NOT_FOUND", f"未找到 {job_id}")
    if len(matches) > 1:
        raise LivePageRoutingError("QBV_JOB_DUPLICATED", f"{job_id} 对应多个 Job 文件")
    return matches[0]


def update_qbv_job(
    qbv_job_id: Any,
    *,
    status: Any,
    job_dir: Any = None,
    target_skill_id: Any = None,
    delegation_tool: Any = None,
    delegation_id: Any = None,
    spawn_run_id: Any = None,
    child_session_key: Any = None,
    source_page_id: Any = None,
    target_page_id: Any = None,
    public_url: Any = None,
    failure_code: Any = None,
    retryable: bool = False,
    published: Any = None,
    public_verified: Any = None,
    worker_timeout_seconds: Any = None,
) -> Dict[str, Any]:
    status_value = _compact_text(status)
    if status_value not in JOB_STATUSES:
        raise LivePageRoutingError("INVALID_JOB_STATUS", f"status 仅支持 {sorted(JOB_STATUSES)}")
    job_path = _find_job_path(qbv_job_id, job_dir)
    lock_path = job_path.with_suffix(job_path.suffix + ".lock")
    with _RegistryLock(lock_path):
        record = json.loads(job_path.read_text(encoding="utf-8"))
        current = record.get("status")
        allowed = {
            "queued": {"queued", "running", "failed"},
            "running": {"running", "completed", "failed"},
            "completed": {"completed"},
            "failed": {"failed", "queued"},
        }
        if status_value not in allowed.get(current, set()):
            raise LivePageRoutingError(
                "INVALID_JOB_TRANSITION",
                f"不允许 QBV Job 从 {current} 变为 {status_value}",
            )
        updates = {
            "status": status_value,
            "updated_at": _utc_now(),
        }
        optional_ids = {
            "target_skill_id": target_skill_id,
            "delegation_tool": delegation_tool,
            "delegation_id": delegation_id,
            "spawn_run_id": spawn_run_id,
            "child_session_key": child_session_key,
            "source_page_id": source_page_id,
            "target_page_id": target_page_id,
        }
        for name, value in optional_ids.items():
            text = _compact_text(value)
            if text:
                updates[name] = _required_id(name, text)
        url = _compact_text(public_url)
        if url:
            if not re.match(r"^https?://", url, re.IGNORECASE):
                raise LivePageRoutingError("INVALID_PUBLIC_URL", "public_url 必须是 http(s) URL")
            updates["public_url"] = url
        failure = _compact_text(failure_code)
        now = updates["updated_at"]
        if status_value == "running":
            timeout_seconds = _worker_timeout_seconds(
                worker_timeout_seconds if worker_timeout_seconds is not None
                else record.get("worker_timeout_seconds")
            )
            started_at = record.get("started_at") or now
            expires_at = (
                _parse_utc(started_at) + timedelta(seconds=timeout_seconds)
            ).isoformat().replace("+00:00", "Z")
            updates.update({
                "worker_timeout_seconds": timeout_seconds,
                "started_at": started_at,
                "expires_at": expires_at,
                "failed_at": None,
            })
        if status_value == "completed":
            target_page = updates.get("target_page_id") or record.get("target_page_id")
            target_skill = updates.get("target_skill_id") or record.get("target_skill_id")
            final_url = url or record.get("public_url")
            final_published = bool(published) if published is not None else bool(record.get("published"))
            final_verified = bool(public_verified) if public_verified is not None else bool(record.get("public_verified"))
            if not target_skill:
                raise LivePageRoutingError("TARGET_SKILL_ID_REQUIRED", "completed Job 必须记录真实 target_skill_id")
            if not target_page:
                raise LivePageRoutingError("TARGET_PAGE_ID_REQUIRED", "completed Job 必须记录 target_page_id")
            if not final_url:
                raise LivePageRoutingError("PUBLIC_URL_REQUIRED", "completed Job 必须记录 public_url")
            if not final_published:
                raise LivePageRoutingError("PUBLISHED_REQUIRED", "completed Job 必须确认 published=true")
            if not final_verified:
                raise LivePageRoutingError("PUBLIC_VERIFIED_REQUIRED", "completed Job 必须确认 public_verified=true")
            updates.update({
                "published": True,
                "public_verified": True,
                "failure_code": None,
                "retryable": False,
                "completed_at": now,
                "failed_at": None,
            })
        elif status_value == "failed":
            if not failure:
                raise LivePageRoutingError("FAILURE_CODE_REQUIRED", "failed Job 必须记录 failure_code")
            updates.update({
                "failure_code": failure,
                "retryable": bool(retryable),
                "failed_at": now,
                "completed_at": None,
            })
        record.update(updates)
        _atomic_write_json(job_path, record)
        return record


def expire_stale_qbv_job(
    qbv_job_id: Any,
    job_dir: Any = None,
    *,
    max_age_seconds: Any = None,
    now: Any = None,
) -> Dict[str, Any]:
    """Fail a stale queued/running Job so it cannot remain non-terminal forever.

    A scheduler/parent callback still has to invoke this watchdog; the Skill repo
    does not pretend to own a production background queue.
    """
    record = get_qbv_job(qbv_job_id, job_dir)
    if record.get("status") not in {"queued", "running"}:
        return {**record, "expired": False}
    timeout_seconds = _worker_timeout_seconds(
        max_age_seconds if max_age_seconds is not None
        else record.get("worker_timeout_seconds")
    )
    anchor = record.get("started_at") or record.get("updated_at") or record.get("created_at")
    current = _parse_utc(now) if now is not None else datetime.now(timezone.utc)
    age_seconds = max(0.0, (current - _parse_utc(anchor)).total_seconds())
    if age_seconds < timeout_seconds:
        return {**record, "expired": False, "age_seconds": age_seconds}
    failure_code = "QBV_WORKER_TIMEOUT" if record.get("status") == "running" else "QBV_QUEUE_TIMEOUT"
    failed = update_qbv_job(
        qbv_job_id,
        status="failed",
        job_dir=job_dir,
        failure_code=failure_code,
        retryable=True,
    )
    return {**failed, "expired": True, "age_seconds": age_seconds}


def mark_delegation_unavailable(qbv_job_id: Any, job_dir: Any = None) -> Dict[str, Any]:
    """Write the mandatory retryable terminal state when no delegation tool exists."""
    return update_qbv_job(
        qbv_job_id,
        status="failed",
        job_dir=job_dir,
        failure_code="DELEGATION_UNAVAILABLE",
        retryable=True,
    )


def get_qbv_job(qbv_job_id: Any, job_dir: Any = None) -> Dict[str, Any]:
    path = _find_job_path(qbv_job_id, job_dir)
    return json.loads(path.read_text(encoding="utf-8"))


def _read_params(args: list[str]) -> Dict[str, Any]:
    if not args:
        return {}
    token = args[0]
    if token.startswith("@"):
        return json.loads(Path(token[1:]).read_text(encoding="utf-8-sig"))
    return json.loads(token)


def _read_route_params(args: list[str]) -> Dict[str, Any]:
    """Accept JSON/@file or a PowerShell-safe --user-query form."""
    if not args or args[0] != "--user-query":
        return _read_params(args)
    if len(args) < 2 or not _compact_text(args[1]):
        raise LivePageRoutingError("USER_QUERY_REQUIRED", "--user-query 后必须提供用户本轮原话")
    params: Dict[str, Any] = {"user_query": args[1]}
    index = 2
    while index < len(args):
        flag = args[index]
        if flag == "--persistence-confirmed":
            params["persistence_confirmed"] = True
            index += 1
            continue
        if flag == "--page-reference":
            if index + 1 >= len(args):
                raise LivePageRoutingError("PAGE_REFERENCE_REQUIRED", "--page-reference 后必须提供页面引用")
            params["page_reference"] = args[index + 1]
            index += 2
            continue
        raise LivePageRoutingError("INVALID_ROUTE_ARGUMENT", f"不支持的 route 参数: {flag}")
    return params



def _read_job_id_params(args: list[str]) -> Dict[str, Any]:
    if not args or not args[0].startswith("--"):
        return _read_params(args)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--qbv-job-id", required=True)
    parser.add_argument("--job-dir")
    parser.add_argument("--max-age-seconds", type=int)
    try:
        namespace = parser.parse_args(args)
    except SystemExit as exc:
        raise LivePageRoutingError("INVALID_JOB_ARGUMENT", "必须提供 --qbv-job-id") from exc
    return vars(namespace)


def _read_prepare_fast_query_params(args: list[str]) -> Dict[str, Any]:
    if not args or not args[0].startswith("--"):
        return _read_params(args)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--turn-id", required=True)
    parser.add_argument("--user-query", required=True)
    parser.add_argument("--source-skill-version", required=True)
    parser.add_argument("--source-skill-id")
    parser.add_argument("--asset-id", required=True)
    parser.add_argument("--asset-name", required=True)
    parser.add_argument("--fields", required=True)
    parser.add_argument("--window-days", required=True, type=int)
    parser.add_argument("--artifact-file", required=True)
    parser.add_argument("--job-dir")
    parser.add_argument("--target-skill-id")
    parser.add_argument("--retry-failed", action="store_true")
    try:
        namespace = parser.parse_args(args)
    except SystemExit as exc:
        raise LivePageRoutingError("INVALID_FAST_QUERY_PAGE_ARGUMENT", "prepare-fast-query-page 参数不完整") from exc
    return vars(namespace)


def _read_prepare_industry_ranking_params(args: list[str]) -> Dict[str, Any]:
    if not args or not args[0].startswith("--"):
        return _read_params(args)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--data-id", required=True)
    parser.add_argument("--index-title", required=True)
    parser.add_argument("--window-days", required=True, type=int)
    parser.add_argument("--asset-count", required=True, type=int)
    parser.add_argument("--as-of-date")
    parser.add_argument("--formula")
    parser.add_argument("--task-id")
    parser.add_argument("--turn-id")
    parser.add_argument("--user-query")
    parser.add_argument("--source-skill-version")
    parser.add_argument("--source-skill-id")
    parser.add_argument("--target-skill-id")
    parser.add_argument("--job-dir")
    parser.add_argument("--retry-failed", action="store_true")
    try:
        namespace = parser.parse_args(args)
    except SystemExit as exc:
        raise LivePageRoutingError(
            "INVALID_INDUSTRY_RANKING_PAGE_ARGUMENT",
            "prepare-industry-ranking-page 参数不完整",
        ) from exc
    return vars(namespace)

def _emit(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        _emit({"code": 1, "error": "COMMAND_REQUIRED", "message": "用法: live_page_routing.py route [JSON|@file|--user-query TEXT] | prepare-fast-query-page [flags|JSON|@file] | prepare-industry-ranking-page [flags|JSON|@file] | prepare-validated-page [JSON|@file] | mark-delegation-unavailable --qbv-job-id ID | expire-stale --qbv-job-id ID [--max-age-seconds N] | handoff|prepare|update|get [JSON|@file]"})
        return 1
    command = argv.pop(0)
    try:
        params = (
            _read_route_params(argv) if command == "route"
            else _read_prepare_fast_query_params(argv) if command == "prepare-fast-query-page"
            else _read_prepare_industry_ranking_params(argv) if command == "prepare-industry-ranking-page"
            else _read_job_id_params(argv) if command in {"mark-delegation-unavailable", "expire-stale"}
            else _read_params(argv)
        )
        if command == "route":
            result = route_live_page(
                params.get("user_query"), params.get("page_reference"),
                bool(params.get("persistence_confirmed", False)),
            )
        elif command == "handoff":
            result = build_qbv_handoff(**params)
        elif command == "prepare-fast-query-page":
            result = prepare_fast_query_page(**params)
        elif command == "prepare-industry-ranking-page":
            result = prepare_industry_ranking_page(**params)
        elif command == "prepare-validated-page":
            result = prepare_validated_page(**params)
        elif command == "prepare":
            handoff = params.get("handoff")
            if handoff is None and params.get("handoff_file"):
                handoff = json.loads(Path(params["handoff_file"]).read_text(encoding="utf-8-sig"))
            result = prepare_qbv_job(
                handoff,
                target_skill_id=params.get("target_skill_id"),
                job_dir=params.get("job_dir"),
                retry_failed=bool(params.get("retry_failed", False)),
            )
        elif command == "update":
            fields = dict(params)
            job_id = fields.pop("qbv_job_id", None)
            result = update_qbv_job(job_id, **fields)
        elif command == "mark-delegation-unavailable":
            result = mark_delegation_unavailable(params.get("qbv_job_id"), params.get("job_dir"))
        elif command == "expire-stale":
            result = expire_stale_qbv_job(
                params.get("qbv_job_id"), params.get("job_dir"),
                max_age_seconds=params.get("max_age_seconds"),
            )
        elif command == "get":
            result = get_qbv_job(params.get("qbv_job_id"), params.get("job_dir"))
        else:
            raise LivePageRoutingError("UNKNOWN_COMMAND", f"未知命令: {command}")
        _emit({"code": 0, **result})
        return 0
    except (LivePageRoutingError, ComputationCapsuleError, OSError, json.JSONDecodeError, TypeError) as exc:
        code = exc.code if isinstance(exc, (LivePageRoutingError, ComputationCapsuleError)) else "LIVE_PAGE_ROUTING_FAILED"
        _emit({"code": 1, "error": code, "message": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
