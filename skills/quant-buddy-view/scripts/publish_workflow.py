#!/usr/bin/env python3
"""Deterministic QBV workflow: validate packages, register credentials, bind HTML, publish once."""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import common as C
import data_grant as DG
import formula_package as FP
import fork_runtime_contract as FRC
import reply_data_evidence as RDE
import static_page as SP


SCRIPT_DIR = Path(__file__).resolve().parent
BRIDGE = SCRIPT_DIR / "qbs_bridge.py"
VERIFY_PAGE = SCRIPT_DIR / "verify_page.mjs"
DEFAULT_FORMULA_BEGIN_DATE = 20150101
CARD_RUNTIME_MARKERS = (
    "data-qb-card-template",
    "data-qb-card-style",
    "data-qb-card-manifest",
    "data-qb-card-runtime",
)
PREFLIGHT_IMAGE_DATA_URI = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="


def _failure(error, message, **extra):
    return {"code": 1, "error": error, "message": message, **extra}


def _marker_values(value, label):
    values = value if isinstance(value, list) else [value]
    if not values:
        raise ValueError(f"{label} 必须是非空 marker 或非空 marker 数组")
    normalized = []
    for index, item in enumerate(values):
        marker = str(item or "").strip()
        item_label = f"{label}[{index}]" if isinstance(value, list) else label
        if not marker:
            raise ValueError(f"{item_label} 缺失")
        normalized.append((item_label, marker))
    return normalized


def _marker_specs(packages, grants, images=None):
    specs = []
    for index, item in enumerate(packages):
        markers = item.get("markers") if isinstance(item, dict) else None
        if not isinstance(markers, dict):
            raise ValueError(f"packages[{index}].markers 必须是对象")
        specs.extend(_marker_values(markers.get("package_id"), f"packages[{index}].markers.package_id"))
        specs.extend(_marker_values(markers.get("signature"), f"packages[{index}].markers.signature"))
        if "package_references" in markers:
            specs.extend(_marker_values(markers.get("package_references"), f"packages[{index}].markers.package_references"))
    for index, item in enumerate(grants):
        markers = item.get("markers") if isinstance(item, dict) else None
        if not isinstance(markers, dict):
            raise ValueError(f"grants[{index}].markers 必须是对象")
        specs.extend(_marker_values(markers.get("grant_id"), f"grants[{index}].markers.grant_id"))
        specs.extend(_marker_values(markers.get("signature"), f"grants[{index}].markers.signature"))
        if "grant_references" in markers:
            specs.extend(_marker_values(markers.get("grant_references"), f"grants[{index}].markers.grant_references"))
    for index, item in enumerate(images or []):
        if not isinstance(item, dict):
            raise ValueError(f"images[{index}] 必须是对象")
        specs.append((f"images[{index}].marker", item.get("marker")))
    normalized = []
    seen = set()
    for label, value in specs:
        marker = str(value or "").strip()
        if not marker or marker in seen:
            raise ValueError(f"{label} 缺失或与其他 marker 重复")
        seen.add(marker)
        normalized.append((label, marker))
    return normalized


def _run_qbs_package_set(task_id, user_query, packages, template_ref=""):
    payload = {
        "task_id": task_id,
        "user_query": user_query,
        "template_ref": template_ref,
        "packages": [
            {
                "name": str(item.get("name") or "").strip(),
                **dict(item.get("contract") or item.get("validation") or {}),
            }
            for item in packages
        ],
    }
    fd, params_file = tempfile.mkstemp(prefix="qbv_package_set_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        completed = subprocess.run(
            [sys.executable, str(BRIDGE), "validate_package_set", f"@{params_file}"],
            cwd=SCRIPT_DIR.parent,
            env=dict(os.environ),
            capture_output=True,
            check=False,
        )
        try:
            result = json.loads(completed.stdout.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return _failure("QBS_INVALID_RESPONSE", f"package-set 验证未返回合法 JSON: {exc}")
        if completed.returncode != 0 or not isinstance(result, dict) or result.get("code") != 0:
            return result if isinstance(result, dict) else _failure("QBS_PACKAGE_SET_FAILED", "package-set 验证失败")
        return result
    finally:
        try:
            os.unlink(params_file)
        except OSError:
            pass



def _run_qbs_grant_set(task_id, user_query, grants, template_ref=""):
    payload = {
        "task_id": task_id,
        "user_query": user_query,
        "template_ref": template_ref,
        "grants": [
            {
                "name": str(item.get("name") or item.get("role_id") or "").strip(),
                "contract": dict(item.get("contract") or {}),
                "contract_fingerprint": str(item.get("contract_fingerprint") or ""),
            }
            for item in grants
        ],
    }
    fd, params_file = tempfile.mkstemp(prefix="qbv_grant_set_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        completed = subprocess.run(
            [sys.executable, str(BRIDGE), "validate_grant_set", f"@{params_file}"],
            cwd=SCRIPT_DIR.parent,
            env=dict(os.environ),
            capture_output=True,
            check=False,
        )
        try:
            result = json.loads(completed.stdout.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return _failure("QBS_INVALID_RESPONSE", f"grant-set 验证未返回合法 JSON: {exc}")
        if completed.returncode != 0 or not isinstance(result, dict) or result.get("code") != 0:
            return result if isinstance(result, dict) else _failure("QBS_GRANT_SET_FAILED", "grant-set 验证失败")
        return result
    finally:
        try:
            os.unlink(params_file)
        except OSError:
            pass


_GRANT_FETCH_CALL_RE = re.compile(r"queryDataGrant", re.I)


def _grant_credential_is_consumed(html, item):
    if not _GRANT_FETCH_CALL_RE.search(str(html or "")):
        return False
    markers = (item.get("markers") or {}) if isinstance(item, dict) else {}
    for values in markers.values():
        for marker in values if isinstance(values, list) else [values]:
            if marker and str(marker) in str(html or ""):
                return True
    return False


def _apply_grant_degradation(grants, html, validation):
    failed = validation.get("failed_grants") if isinstance(validation, dict) else []
    if not failed:
        return grants, [], html, None
    blocking = [item for item in failed if item.get("error_class") != "data"]
    if blocking:
        return grants, failed, html, _failure(
            "GRANT_SET_VALIDATION_FAILED", "Grant 验证含系统级失败，禁止降级。", validation=validation,
        )
    dropped_names = {str(item.get("name") or "") for item in failed}
    unsafe = [
        item for item in grants
        if str(item.get("name") or item.get("role_id") or "") in dropped_names
        and _grant_credential_is_consumed(html, item)
    ]
    if unsafe:
        return grants, failed, html, _failure(
            "GRANT_DEGRADATION_UNSAFE",
            "失败 Grant 仍被页面 queryDataGrant 无条件消费；清空凭证会打断整条取数链，拒绝降级。",
            unsafe_grants=[str(x.get("name") or x.get("role_id") or "") for x in unsafe],
            validation=validation,
        )
    kept = [x for x in grants if str(x.get("name") or x.get("role_id") or "") not in dropped_names]
    for item in grants:
        if str(item.get("name") or item.get("role_id") or "") not in dropped_names:
            continue
        markers = item.get("markers") or {}
        for key in ("grant_id", "signature", "grant_references"):
            if key not in markers:
                continue
            for _, marker in _marker_values(markers.get(key), f"{key}.marker"):
                html = html.replace(marker, "")
    return kept, failed, html, None

def _normalize_v1_grants(grants):
    normalized = []
    for index, raw in enumerate(grants or []):
        if not isinstance(raw, dict):
            raise ValueError(f"grants[{index}] 必须是对象")
        item = dict(raw)
        registration = item.get("registration") if isinstance(item.get("registration"), dict) else {}
        contract = item.get("contract") if isinstance(item.get("contract"), dict) else {}
        if not contract and registration.get("kind") and isinstance(registration.get("payload"), dict):
            contract = {"kind": registration["kind"], "payload": dict(registration["payload"])}
        if not contract:
            raise ValueError(f"grants[{index}] 缺少 contract 或 registration.kind/payload")
        item["contract"] = contract
        item["contract_fingerprint"] = str(item.get("contract_fingerprint") or FRC.contract_fingerprint(contract))
        normalized.append(item)
    return normalized


def _validation_route_items(items, validation_items, receipt_files, *, kind):
    by_name = {
        str(item.get("name") or ""): item
        for item in (validation_items or [])
        if isinstance(item, dict)
    }
    results = []
    for index, item in enumerate(items or []):
        name = str(item.get("name") or item.get("role_id") or f"{kind}_{index}").strip()
        validated = dict(by_name.get(name) or {})
        validated.setdefault("name", name)
        validated.setdefault("role", str(item.get("role") or item.get("role_id") or name))
        validated.setdefault("validation_receipt_file", receipt_files[index] if index < len(receipt_files) else "")
        if kind == "grant":
            contract = item.get("contract") if isinstance(item.get("contract"), dict) else {}
            validated.setdefault("kind", str(contract.get("kind") or item.get("kind") or ""))
            validated.setdefault("contract_fingerprint", str(item.get("contract_fingerprint") or ""))
        results.append(validated)
    return results


def _infer_route_asset(explicit_asset, grant_items):
    if str(explicit_asset or "").strip():
        return str(explicit_asset).strip()
    assets = []
    for item in grant_items or []:
        contract = item.get("contract") if isinstance(item, dict) and isinstance(item.get("contract"), dict) else {}
        payload = contract.get("payload") if isinstance(contract.get("payload"), dict) else {}
        values = payload.get("assets") if isinstance(payload.get("assets"), list) else [payload.get("asset")]
        for value in values:
            token = str(value or "").strip()
            if token and token not in assets:
                assets.append(token)
    return assets[0] if len(assets) == 1 else ""


def _write_live_route_receipt(task_id, asset, package_results, grant_results):
    attempts = []
    selected_routes = []
    required_roles = []
    for index, item in enumerate(package_results or []):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or item.get("name") or f"formula_{index}").strip()
        receipt_file = str(item.get("validation_receipt_file") or "").strip()
        if role not in required_roles:
            required_roles.append(role)
        attempts.append({"role": role, "route": "formula_batch", "status": "success"})
        selected_routes.append({"role": role, "kind": "formula", "receipt_file": receipt_file})
    for index, item in enumerate(grant_results or []):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or item.get("name") or f"grant_{index}").strip()
        kind = str(item.get("kind") or "").strip()
        receipt_file = str(item.get("validation_receipt_file") or "").strip()
        fingerprint = str(item.get("contract_fingerprint") or "").strip()
        if role not in required_roles:
            required_roles.append(role)
        route_name = "stock_profile" if kind == "stock_profile" else (
            f"fast_query_{item.get('query_type')}" if kind == "fast_query" and item.get("query_type") else kind or "data_grant"
        )
        attempts.append({"role": role, "route": route_name, "status": "success"})
        selected = {"role": role, "kind": kind, "receipt_file": receipt_file, "contract_fingerprint": fingerprint}
        if item.get("query_type"):
            selected["query_type"] = item.get("query_type")
        selected_routes.append(selected)
    payload = {
        "schema": "live_data_route_receipt_v1",
        "version": "live_data_route_receipt_v1",
        "task_id": str(task_id or "").strip(),
        "asset": str(asset or "").strip(),
        "status": "live" if required_roles else "incomplete",
        "required_roles": required_roles,
        "attempted_roles": list(required_roles),
        "attempts": attempts,
        "selected_routes": selected_routes,
        "required_roles_complete": bool(required_roles),
        "static_fallback_allowed": False,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    root = SCRIPT_DIR.parent / "output" / "live_data_route_receipts"
    root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    path = root / f"{digest}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(path)

def _replace_once(html, marker, value, label):
    count = html.count(marker)
    if count != 1:
        raise ValueError(f"{label} 必须在 HTML 中恰好出现一次，当前 {count} 次")
    return html.replace(marker, str(value), 1)


def _replace_marker_field(html, marker_value, replacement, label):
    for marker_label, marker in _marker_values(marker_value, label):
        html = _replace_once(html, marker, replacement, marker_label)
    return html


def _has_card_runtime_artifact(html):
    return any(marker in html for marker in CARD_RUNTIME_MARKERS)


def _card_runtime_preview_html(html, packages, grants, images):
    preview = html
    for index, item in enumerate(packages):
        markers = item["markers"]
        preview = _replace_marker_field(
            preview,
            markers.get("package_id"),
            f"pkg_qbv_preflight_{index}",
            f"packages[{index}].markers.package_id",
        )
        preview = _replace_marker_field(
            preview,
            markers.get("signature"),
            f"sig_qbv_preflight_{index}",
            f"packages[{index}].markers.signature",
        )
        if "package_references" in markers:
            preview = _replace_marker_field(
                preview,
                markers.get("package_references"),
                f"pkg_qbv_preflight_{index}",
                f"packages[{index}].markers.package_references",
            )
    for index, item in enumerate(grants):
        markers = item["markers"]
        preview = _replace_marker_field(
            preview,
            markers.get("grant_id"),
            f"grant_qbv_preflight_{index}",
            f"grants[{index}].markers.grant_id",
        )
        preview = _replace_marker_field(
            preview,
            markers.get("signature"),
            f"grant_sig_qbv_preflight_{index}",
            f"grants[{index}].markers.signature",
        )
        if "grant_references" in markers:
            preview = _replace_marker_field(
                preview,
                markers.get("grant_references"),
                f"grant_qbv_preflight_{index}",
                f"grants[{index}].markers.grant_references",
            )
    for index, item in enumerate(images or []):
        preview = _replace_once(
            preview,
            str(item.get("marker") or "").strip(),
            PREFLIGHT_IMAGE_DATA_URI,
            f"images[{index}].marker",
        )
    return preview


def _run_card_runtime_preflight(html):
    if not _has_card_runtime_artifact(html):
        return {"code": 0, "skipped": True, "reason": "HTML 未包含 Card Runtime artifact"}
    fd, preview_file = tempfile.mkstemp(prefix="qbv_card_runtime_preflight_", suffix=".html")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(html)
        try:
            completed = subprocess.run(
                ["node", str(VERIFY_PAGE), preview_file, "--card-runtime-structure-only"],
                cwd=SCRIPT_DIR.parent,
                env=dict(os.environ),
                capture_output=True,
                check=False,
                timeout=60,
            )
        except FileNotFoundError:
            return _failure("NODE_REQUIRED", "Card Runtime 发布前结构预检需要 Node.js")
        except subprocess.TimeoutExpired:
            return _failure("CARD_RUNTIME_PREFLIGHT_TIMEOUT", "Card Runtime 发布前结构预检超时")
        try:
            result = json.loads(completed.stdout.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return _failure("CARD_RUNTIME_PREFLIGHT_INVALID_RESPONSE", f"结构预检未返回合法 JSON: {exc}")
        if completed.returncode != 0 or not isinstance(result, dict) or result.get("code") != 0:
            return result if isinstance(result, dict) else _failure("CARD_RUNTIME_PREFLIGHT_FAILED", "Card Runtime 结构预检失败")
        return result
    finally:
        try:
            os.unlink(preview_file)
        except OSError:
            pass


def _begin_date(value, label):
    if value is None or str(value).strip() == "":
        return DEFAULT_FORMULA_BEGIN_DATE
    if isinstance(value, bool):
        raise ValueError(f"{label} 必须是 YYYYMMDD 整数")
    try:
        normalized = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} 必须是 YYYYMMDD 整数") from exc
    if normalized < 20050104 or normalized > 20991231 or len(str(normalized)) != 8:
        raise ValueError(f"{label} 必须是 20050104..20991231 的 YYYYMMDD 整数")
    return normalized


def _normalize_package_begin_dates(packages, workflow_begin_date=None):
    default_begin_date = _begin_date(workflow_begin_date, "begin_date")
    normalized = []
    for index, item in enumerate(packages):
        if not isinstance(item, dict):
            raise ValueError(f"packages[{index}] 必须是对象")
        package = dict(item)
        validation = dict(package.get("validation") or {})
        registration = dict(package.get("registration") or {})
        validation_raw = validation.get("begin_date")
        registration_raw = registration.get("begin_date")
        if validation_raw is not None and registration_raw is not None:
            validation_date = _begin_date(validation_raw, f"packages[{index}].validation.begin_date")
            registration_date = _begin_date(registration_raw, f"packages[{index}].registration.begin_date")
            if validation_date != registration_date:
                raise ValueError(
                    f"packages[{index}] validation.begin_date 与 registration.begin_date 必须一致"
                )
            begin_date = validation_date
        else:
            begin_date = _begin_date(
                validation_raw if validation_raw is not None else registration_raw,
                f"packages[{index}].begin_date",
            ) if validation_raw is not None or registration_raw is not None else default_begin_date
        validation["begin_date"] = begin_date
        registration["begin_date"] = begin_date
        package["validation"] = validation
        package["registration"] = registration
        normalized.append(package)
    return normalized


def _run_workflow_v1(params):
    params = dict(params or {})
    task_id = str(params.get("task_id") or "").strip()
    user_query = str(params.get("user_query") or "").strip()
    packages = params.get("packages")
    grants = params.get("grants") or []
    images = params.get("images") or []
    publish_params = params.get("publish_verified")
    if not task_id or not user_query:
        return _failure("QBV_TRACE_CONTEXT_REQUIRED", "task_id 和 user_query 必填")
    if not isinstance(packages, list):
        return _failure("INVALID_PACKAGES", "packages 必须是数组")
    if not isinstance(grants, list):
        return _failure("INVALID_GRANTS", "grants 必须是数组")
    if not packages and not grants:
        return _failure("LIVE_ROUTES_REQUIRED", "packages 和 grants 至少需要一个实时通道")
    if not isinstance(images, list):
        return _failure("INVALID_IMAGES", "images 必须是数组")
    if not isinstance(publish_params, dict) or not publish_params.get("page_id"):
        return _failure("PUBLISH_PARAMS_REQUIRED", "publish_verified.page_id 必填")

    try:
        packages = _normalize_package_begin_dates(packages, params.get("begin_date"))
        grants = _normalize_v1_grants(grants)
    except ValueError as exc:
        return _failure("PACKAGE_BEGIN_DATE_INVALID", str(exc))

    template_file = Path(str(params.get("html_template_file") or "")).resolve()
    prepared_file = Path(str(params.get("prepared_html_file") or "")).resolve()
    if not template_file.is_file() or not str(params.get("prepared_html_file") or "").strip():
        return _failure("HTML_FILES_REQUIRED", "html_template_file 必须存在，prepared_html_file 必填")
    if template_file == prepared_file:
        return _failure("SOURCE_HTML_IMMUTABLE", "prepared_html_file 不能覆盖 html_template_file")

    try:
        html = template_file.read_text(encoding="utf-8")
        marker_specs = _marker_specs(packages, grants, images)
        for label, marker in marker_specs:
            if html.count(marker) != 1:
                return _failure("HTML_MARKER_INVALID", f"{label} 必须在 HTML 中恰好出现一次")
        prepared_images = []
        for index, item in enumerate(images):
            logical_name = str(item.get("logical_name") or item.get("name") or "").strip()
            if not logical_name:
                return _failure("IMAGE_PREFLIGHT_FAILED", f"images[{index}].logical_name 必填")
            path, image_error = SP._resolve_local_image_file(item)
            if image_error:
                return _failure("IMAGE_PREFLIGHT_FAILED", image_error.get("message") or f"images[{index}] 图片预检失败", failed_index=index)
            prepared_images.append({**item, "logical_name": logical_name, "resolved_image_file": path})
        preview_html = _card_runtime_preview_html(html, packages, grants, images)
        card_runtime_preflight = _run_card_runtime_preflight(preview_html)
        if not isinstance(card_runtime_preflight, dict) or card_runtime_preflight.get("code") != 0:
            return _failure(
                "CARD_RUNTIME_PREFLIGHT_FAILED",
                "Card Runtime 发布前结构预检失败；尚未执行公式验证或任何注册",
                card_runtime_preflight=card_runtime_preflight,
            )
    except (OSError, ValueError) as exc:
        return _failure("WORKFLOW_PREFLIGHT_FAILED", str(exc))

    # configure_trace_context（不是 set_trace_context）：本次调用没带 api_key 字段时会保留
    # 当前进程已生效的覆盖，不会把顶层 params 里传入的用户 api_key 悄悄清空——publish_workflow.py
    # 中途多次切换 task_id/user_query 上下文，覆盖必须原样带到 package/grant 注册和最终 publish。
    C.configure_trace_context({"task_id": task_id, "user_query": user_query})
    validation = (
        _run_qbs_package_set(task_id, user_query, packages)
        if packages else {"code": 0, "validation_receipt_files": [], "packages": []}
    )
    if not isinstance(validation, dict) or validation.get("code") != 0:
        return _failure("PACKAGE_SET_VALIDATION_FAILED", "QBS package-set 验证失败", validation=validation)
    receipts = validation.get("validation_receipt_files") or []
    if len(receipts) != len(packages):
        return _failure("PACKAGE_SET_RECEIPTS_INCOMPLETE", "package-set 收据数量与公式包数量不一致", validation=validation)
    grant_validation = (
        _run_qbs_grant_set(task_id, user_query, grants)
        if grants else {"code": 0, "validation_receipt_files": [], "grants": []}
    )
    if not isinstance(grant_validation, dict):
        return _failure("GRANT_SET_VALIDATION_FAILED", "QBS grant-set 验证失败", validation=grant_validation)
    grants, dropped_grants, html, degradation_error = _apply_grant_degradation(grants, html, grant_validation)
    if degradation_error:
        return degradation_error
    if grant_validation.get("code") != 0:
        return _failure("GRANT_SET_VALIDATION_FAILED", "QBS grant-set 验证失败", validation=grant_validation)
    grant_receipts = grant_validation.get("validation_receipt_files") or []
    if len(grant_receipts) != len(grants):
        return _failure("GRANT_SET_RECEIPTS_INCOMPLETE", "grant-set 收据数量与 Grant 数量不一致", validation=grant_validation)
    grant_validation_by_name = {item.get("name"): item for item in grant_validation.get("grants") or [] if isinstance(item, dict)}
    for grant in grants:
        validated = grant_validation_by_name.get(grant.get("name")) or {}
        if validated.get("contract_fingerprint") != grant.get("contract_fingerprint"):
            return _failure("GRANT_FINGERPRINT_MISMATCH", f"Grant验证与注册合同不一致: {grant.get('name')}")
    package_route_results = _validation_route_items(packages, validation.get("packages"), receipts, kind="formula")
    grant_route_results = _validation_route_items(grants, grant_validation.get("grants"), grant_receipts, kind="grant")
    route_asset = _infer_route_asset(publish_params.get("asset") or params.get("asset"), grants)
    route_receipt_file = _write_live_route_receipt(
        task_id,
        route_asset,
        package_route_results,
        grant_route_results,
    )

    registered_packages = []
    for index, item in enumerate(packages):
        registration = dict(item.get("registration") or {})
        registration.update({"task_id": task_id, "user_query": user_query})
        result = FP.cmd_register(registration)
        if not (isinstance(result, dict) and result.get("code") == 0 and result.get("package_id") and result.get("signature")):
            return _failure("PACKAGE_REGISTER_FAILED", f"公式包注册失败: {item.get('name') or index}", failed_index=index, registered_packages=registered_packages)
        markers = item["markers"]
        html = _replace_marker_field(html, markers["package_id"], result["package_id"], f"packages[{index}].package_id")
        html = _replace_marker_field(html, markers["signature"], result["signature"], f"packages[{index}].signature")
        if "package_references" in markers:
            html = _replace_marker_field(html, markers["package_references"], result["package_id"], f"packages[{index}].package_references")
        registered_packages.append({"name": str(item.get("name") or index), "package_id": result["package_id"]})

    registered_grants = []
    for index, item in enumerate(grants):
        registration = dict(item.get("registration") or {})
        registration.update({"task_id": task_id, "user_query": user_query})
        result = DG.cmd_register(registration)
        if not (isinstance(result, dict) and result.get("code") == 0 and result.get("grant_id") and result.get("signature")):
            return _failure("GRANT_REGISTER_FAILED", f"数据授权注册失败: {item.get('name') or index}", failed_index=index, registered_packages=registered_packages, registered_grants=registered_grants)
        markers = item["markers"]
        html = _replace_marker_field(html, markers["grant_id"], result["grant_id"], f"grants[{index}].grant_id")
        html = _replace_marker_field(html, markers["signature"], result["signature"], f"grants[{index}].signature")
        if "grant_references" in markers:
            html = _replace_marker_field(html, markers["grant_references"], result["grant_id"], f"grants[{index}].grant_references")
        registered_grants.append({"name": str(item.get("name") or index), "grant_id": result["grant_id"]})

    uploaded_images = []
    for index, item in enumerate(prepared_images):
        result = SP.cmd_image_upload({
            "task_id": task_id,
            "page_id": publish_params["page_id"],
            "image_file": item["resolved_image_file"],
            "logical_name": item["logical_name"],
        })
        image_url = result.get("url") if isinstance(result, dict) else ""
        if not (isinstance(result, dict) and result.get("code") == 0 and result.get("asset_id") and image_url):
            return _failure(
                "IMAGE_UPLOAD_FAILED",
                f"正文图片上传失败: {item.get('name') or index}",
                failed_index=index,
                registered_packages=registered_packages,
                registered_grants=registered_grants,
                uploaded_images=uploaded_images,
                image_result=result,
            )
        html = _replace_once(html, item["marker"], image_url, f"images[{index}].marker")
        uploaded_images.append({
            "name": str(item.get("name") or item["logical_name"]),
            "logical_name": item["logical_name"],
            "asset_id": result["asset_id"],
            "url": image_url,
            "sha256": result.get("sha256"),
        })

    prepared_file.parent.mkdir(parents=True, exist_ok=True)
    prepared_file.write_text(html, encoding="utf-8", newline="\n")
    verified_params = dict(publish_params)
    verified_params.update({
        "task_id": task_id,
        "user_query": user_query,
        "html_file": str(prepared_file),
        "asset": route_asset,
        "live_data_mode": "live",
        "route_receipt_file": route_receipt_file,
        "validation_receipt_files": receipts,
        "grant_validation_receipt_files": grant_receipts,
        "_via_publish_workflow": SP._VIA_PUBLISH_WORKFLOW_SENTINEL,
    })
    published = SP.cmd_publish_verified(verified_params)
    return {
        "code": published.get("code", 1) if isinstance(published, dict) else 1,
        "success": bool(isinstance(published, dict) and published.get("code") == 0),
        "task_id": task_id,
        "package_count": len(registered_packages),
        "grant_count": len(registered_grants),
        "image_count": len(uploaded_images),
        "registered_packages": registered_packages,
        "registered_grants": registered_grants,
        "uploaded_images": uploaded_images,
        "card_runtime_preflight": card_runtime_preflight,
        "validation_receipt_files": receipts,
        "grant_validation_receipt_files": grant_receipts,
        "route_receipt_file": route_receipt_file,
        "prepared_html_file": str(prepared_file),
        "publish_verified": published,
    }



def _read_json_file(path, label):
    resolved = Path(str(path or "")).resolve()
    if not resolved.is_file():
        raise ValueError(f"{label} 不存在: {resolved}")
    payload = json.loads(resolved.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} 必须是 JSON 对象")
    return resolved, payload


def _sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _validate_review_receipt(params, manifest_path, review_path, template_file, manifest):
    receipt_file = str(params.get("review_receipt_file") or "").strip()
    receipt_sha256 = str(params.get("review_receipt_sha256") or "").strip()
    if not receipt_file or not receipt_sha256:
        return None, _failure(
            "FORK_REVIEW_RECEIPT_REQUIRED",
            "publish_workflow_v2 必须由 fork_review_update 生成 review_receipt_file 与 review_receipt_sha256",
        )
    try:
        receipt_path, receipt = _read_json_file(receipt_file, "review_receipt_file")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return None, _failure("FORK_REVIEW_RECEIPT_INVALID", str(exc))
    if _sha256_file(receipt_path) != receipt_sha256:
        return None, _failure("FORK_REVIEW_RECEIPT_INVALID", "review receipt 文件哈希不匹配")
    if receipt.get("version") != FRC.REVIEW_RECEIPT_VERSION:
        return None, _failure("FORK_REVIEW_RECEIPT_INVALID", f"review receipt.version 必须是 {FRC.REVIEW_RECEIPT_VERSION}")
    if receipt.get("status") != "complete":
        return None, _failure("FORK_REVIEW_INCOMPLETE", "review receipt 尚未完成")
    publish_params = params.get("publish_verified") or {}
    expected = {
        "task_id": str(params.get("task_id") or ""),
        "page_id": str(publish_params.get("page_id") or ""),
        "source_template_id": str(manifest.get("source_template_id") or publish_params.get("source_template_id") or ""),
        "manifest_sha256": _sha256_file(manifest_path),
        "review_sha256": _sha256_file(review_path),
        "working_html_sha256": _sha256_file(template_file),
        "review_base_sha256": str(manifest.get("review_base_sha256") or ""),
    }
    stale = {
        key: {"expected": value, "actual": str(receipt.get(key) or "")}
        for key, value in expected.items()
        if value != str(receipt.get(key) or "")
    }
    if stale:
        return None, _failure(
            "FORK_REVIEW_STALE",
            "review receipt 与当前 task/page/manifest/review/HTML 不一致",
            stale_fields=stale,
        )
    return receipt, None


def _run_workflow_v2(params):
    params = dict(params or {})
    if any(key in params for key in ("packages", "grants", "markers", "runtime_markers")):
        return _failure(
            "MANUAL_RUNTIME_BINDINGS_FORBIDDEN",
            "fork_manifest_v2 禁止手工传入 packages、grants 或 runtime markers",
        )
    task_id = str(params.get("task_id") or "").strip()
    user_query = str(params.get("user_query") or "").strip()
    publish_params = params.get("publish_verified")
    if not task_id or not user_query:
        return _failure("QBV_TRACE_CONTEXT_REQUIRED", "task_id 和 user_query 必填")
    if not isinstance(publish_params, dict) or not str(publish_params.get("page_id") or "").strip():
        return _failure("PUBLISH_PARAMS_REQUIRED", "publish_verified.page_id 必填；fork_prepare 时应传 target_page_id")
    reply_template = publish_params.get("agent_reply_template") if isinstance(publish_params.get("agent_reply_template"), dict) else {}
    template_ref = str(reply_template.get("template_ref") or "").strip()

    timings = {}
    stages = {}
    started = time.perf_counter()
    try:
        manifest_path, manifest = _read_json_file(params.get("fork_manifest_file"), "fork_manifest_file")
        review_path, review = _read_json_file(params.get("fork_review_file"), "fork_review_file")
        template_file = Path(str(params.get("html_template_file") or "")).resolve()
        prepared_file = Path(str(params.get("prepared_html_file") or "")).resolve()
        if not template_file.is_file() or not str(params.get("prepared_html_file") or "").strip():
            return _failure("HTML_FILES_REQUIRED", "html_template_file 必须存在，prepared_html_file 必填")
        if template_file == prepared_file:
            return _failure("SOURCE_HTML_IMMUTABLE", "prepared_html_file 不能覆盖 html_template_file")
        html = template_file.read_text(encoding="utf-8")
        review_receipt, receipt_error = _validate_review_receipt(
            params, manifest_path, review_path, template_file, manifest
        )
        if receipt_error:
            return receipt_error
        stages["manifest"] = FRC.validate_manifest_html(manifest, html)
        resolved = FRC.resolve_review(manifest, review, html, intent_profile=manifest.get("intent_profile"))
        resolved_contract_sha256 = FRC.contract_fingerprint({
            "packages": resolved["packages"],
            "grants": resolved["grants"],
            "html_sha256": hashlib.sha256(resolved["html"].encode("utf-8")).hexdigest(),
        })
        if review_receipt.get("resolved_contract_sha256") != resolved_contract_sha256:
            return _failure("FORK_REVIEW_STALE", "review receipt 的已解析合同哈希已过期")
        html = resolved["html"]
        stages["contracts"] = FRC.validate_resolved_contracts(manifest, resolved)
        packages = resolved["packages"]
        grants = resolved["grants"]
        images = params.get("images") or []
        if not isinstance(images, list):
            return _failure("INVALID_IMAGES", "images 必须是数组")
        marker_specs = _marker_specs(packages, grants, images)
        for label, marker in marker_specs:
            if html.count(marker) != 1:
                raise ValueError(f"{label} 必须在 HTML 中恰好出现一次")
        prepared_images = []
        for index, item in enumerate(images):
            logical_name = str(item.get("logical_name") or item.get("name") or "").strip()
            if not logical_name:
                raise ValueError(f"images[{index}].logical_name 必填")
            path, image_error = SP._resolve_local_image_file(item)
            if image_error:
                raise ValueError(image_error.get("message") or f"images[{index}] 图片预检失败")
            prepared_images.append({**item, "logical_name": logical_name, "resolved_image_file": path})
        preview_html = _card_runtime_preview_html(html, packages, grants, images)
        card_runtime_preflight = _run_card_runtime_preflight(preview_html)
        if not isinstance(card_runtime_preflight, dict) or card_runtime_preflight.get("code") != 0:
            return _failure(
                "CARD_RUNTIME_PREFLIGHT_FAILED",
                "Card Runtime 发布前结构预检失败；尚未执行公式/Grant验证或任何注册",
                card_runtime_preflight=card_runtime_preflight,
                timing=timings,
            )
        stages["card_runtime"] = card_runtime_preflight
    except (OSError, ValueError, json.JSONDecodeError, FRC.ForkRuntimeError) as exc:
        if isinstance(exc, FRC.ForkRuntimeError):
            return exc.as_dict()
        return _failure("WORKFLOW_PREFLIGHT_FAILED", str(exc))
    timings["manifest_preflight_ms"] = round((time.perf_counter() - started) * 1000)

    # configure_trace_context（不是 set_trace_context）：本次调用没带 api_key 字段时会保留
    # 当前进程已生效的覆盖，不会把顶层 params 里传入的用户 api_key 悄悄清空——publish_workflow.py
    # 中途多次切换 task_id/user_query 上下文，覆盖必须原样带到 package/grant 注册和最终 publish。
    C.configure_trace_context({"task_id": task_id, "user_query": user_query})
    started = time.perf_counter()
    package_validation = (
        _run_qbs_package_set(task_id, user_query, packages, template_ref)
        if packages else {"code": 0, "validation_receipt_files": [], "packages": []}
    )
    timings["package_validation_ms"] = round((time.perf_counter() - started) * 1000)
    if not isinstance(package_validation, dict) or package_validation.get("code") != 0:
        return _failure("PACKAGE_SET_VALIDATION_FAILED", "QBS package-set 验证失败", validation=package_validation, timing=timings)
    receipts = package_validation.get("validation_receipt_files") or []
    if len(receipts) != len(packages):
        return _failure("PACKAGE_SET_RECEIPTS_INCOMPLETE", "package-set 收据数量与公式包数量不一致", timing=timings)

    started = time.perf_counter()
    grant_validation = (
        _run_qbs_grant_set(task_id, user_query, grants, template_ref)
        if grants else {"code": 0, "validation_receipt_files": [], "grants": []}
    )
    timings["grant_validation_ms"] = round((time.perf_counter() - started) * 1000)
    if not isinstance(grant_validation, dict):
        return _failure("GRANT_SET_VALIDATION_FAILED", "QBS grant-set 验证失败", validation=grant_validation, timing=timings)
    grants, dropped_grants, html, degradation_error = _apply_grant_degradation(grants, html, grant_validation)
    if degradation_error:
        degradation_error["timing"] = timings
        return degradation_error
    if grant_validation.get("code") != 0:
        return _failure("GRANT_SET_VALIDATION_FAILED", "QBS grant-set 验证失败", validation=grant_validation, timing=timings)
    if dropped_grants:
        stages["grant_degradation"] = {"dropped_grants": dropped_grants, "surviving_grant_count": len(grants)}
    grant_validation_by_name = {item.get("name"): item for item in grant_validation.get("grants") or []}
    for grant in grants:
        receipt = grant_validation_by_name.get(grant.get("name")) or {}
        if receipt.get("contract_fingerprint") != grant.get("contract_fingerprint"):
            return _failure("GRANT_FINGERPRINT_MISMATCH", f"Grant验证与注册合同不一致: {grant.get('name')}", timing=timings)
    grant_receipts = grant_validation.get("validation_receipt_files") or []
    if len(grant_receipts) != len(grants):
        return _failure("GRANT_SET_RECEIPTS_INCOMPLETE", "grant-set 收据数量与 Grant 数量不一致", timing=timings)
    package_route_results = _validation_route_items(packages, package_validation.get("packages"), receipts, kind="formula")
    grant_route_results = _validation_route_items(grants, grant_validation.get("grants"), grant_receipts, kind="grant")
    route_asset = _infer_route_asset(publish_params.get("asset") or params.get("asset"), grants)
    route_receipt_file = _write_live_route_receipt(
        task_id,
        route_asset,
        package_route_results,
        grant_route_results,
    )

    reply_evidence_contract = {}
    if RDE.get_policy(template_ref):
        started = time.perf_counter()
        evidence_stats = dict(package_validation.get("reply_evidence_stats") or {})
        evidence_stats.update({
            "formula_read_batch_count": evidence_stats.get("batch_count", 0),
            "formula_read_success_count": evidence_stats.get("success_field_count", 0),
            "formula_read_failure_count": evidence_stats.get("failed_field_count", 0),
            "grant_validation_result_count": len(grant_validation.get("grants") or []),
            "extra_package_query_count": 0,
            "extra_grant_query_count": 0,
            "formula_recompute_count": 0,
        })
        try:
            reply_evidence_contract = RDE.build_from_validations(
                task_id, template_ref, package_validation, grant_validation, stats=evidence_stats
            ) or {}
        except (OSError, ValueError, TypeError) as exc:
            return _failure("REPLY_EVIDENCE_FAILED", str(exc), timing=timings)
        timings["reply_evidence_ms"] = evidence_stats.get("read_elapsed_ms", 0) + round((time.perf_counter() - started) * 1000)
        if not reply_evidence_contract.get("reply_data_evidence_file"):
            return _failure("REPLY_EVIDENCE_FAILED", "严格回复模板未生成证据产物", timing=timings)
        stages["reply_evidence"] = reply_evidence_contract.get("reply_data_availability") or {}

    registered_packages = []
    registered_grants = []
    started = time.perf_counter()
    for index, item in enumerate(packages):
        registration = dict(item["contract"])
        registration.update({"task_id": task_id, "user_query": user_query})
        result = FP.cmd_register(registration)
        if not (isinstance(result, dict) and result.get("code") == 0 and result.get("package_id") and result.get("signature")):
            return _failure("PACKAGE_REGISTER_FAILED", f"公式包注册失败: {item.get('name') or index}", failed_index=index, timing=timings)
        markers = item["markers"]
        html = _replace_marker_field(html, markers["package_id"], result["package_id"], f"packages[{index}].package_id")
        html = _replace_marker_field(html, markers["signature"], result["signature"], f"packages[{index}].signature")
        if "package_references" in markers:
            html = _replace_marker_field(html, markers["package_references"], result["package_id"], f"packages[{index}].package_references")
        registered_packages.append({"name": item["name"], "package_id": result["package_id"], "contract_fingerprint": item["contract_fingerprint"]})
    timings["package_registration_ms"] = round((time.perf_counter() - started) * 1000)

    started = time.perf_counter()
    for index, item in enumerate(grants):
        contract = item["contract"]
        registration = {"kind": contract["kind"], "payload": contract["payload"], "task_id": task_id, "user_query": user_query}
        result = DG.cmd_register(registration)
        if not (isinstance(result, dict) and result.get("code") == 0 and result.get("grant_id") and result.get("signature")):
            return _failure("GRANT_REGISTER_FAILED", f"数据授权注册失败: {item.get('name') or index}", failed_index=index, timing=timings)
        markers = item["markers"]
        html = _replace_marker_field(html, markers["grant_id"], result["grant_id"], f"grants[{index}].grant_id")
        html = _replace_marker_field(html, markers["signature"], result["signature"], f"grants[{index}].signature")
        if "grant_references" in markers:
            html = _replace_marker_field(html, markers["grant_references"], result["grant_id"], f"grants[{index}].grant_references")
        registered_grants.append({"name": item["name"], "grant_id": result["grant_id"], "contract_fingerprint": item["contract_fingerprint"]})
    timings["grant_registration_ms"] = round((time.perf_counter() - started) * 1000)

    uploaded_images = []
    started = time.perf_counter()
    for index, item in enumerate(prepared_images):
        result = SP.cmd_image_upload({
            "task_id": task_id,
            "page_id": publish_params["page_id"],
            "image_file": item["resolved_image_file"],
            "logical_name": item["logical_name"],
        })
        image_url = result.get("url") if isinstance(result, dict) else ""
        if not (isinstance(result, dict) and result.get("code") == 0 and result.get("asset_id") and image_url):
            return _failure("IMAGE_UPLOAD_FAILED", f"正文图片上传失败: {item.get('name') or index}", failed_index=index, timing=timings)
        html = _replace_once(html, item["marker"], image_url, f"images[{index}].marker")
        uploaded_images.append({"name": item["logical_name"], "asset_id": result["asset_id"], "url": image_url})
    timings["image_upload_ms"] = round((time.perf_counter() - started) * 1000)

    prepared_file.parent.mkdir(parents=True, exist_ok=True)
    prepared_file.write_text(html, encoding="utf-8", newline="\n")
    verified_params = dict(publish_params)
    verified_params.update({
        "task_id": task_id,
        "user_query": user_query,
        "html_file": str(prepared_file),
        "asset": route_asset,
        "fork_manifest_file": str(manifest_path),
        "live_data_mode": "live",
        "route_receipt_file": route_receipt_file,
        "validation_receipt_files": receipts,
        "grant_validation_receipt_files": grant_receipts,
        "_via_publish_workflow": SP._VIA_PUBLISH_WORKFLOW_SENTINEL,
    })
    verified_params.update(reply_evidence_contract)
    started = time.perf_counter()
    published = SP.cmd_publish_verified(verified_params)
    timings["publish_verified_total_ms"] = round((time.perf_counter() - started) * 1000)
    publish_timing = published.get("timing") if isinstance(published, dict) and isinstance(published.get("timing"), dict) else {}
    timings["browser_validation_ms"] = publish_timing.get("local_browser_ms", 0)
    timings["publish_ms"] = publish_timing.get("publish_final_ms", 0)
    timings["public_smoke_ms"] = publish_timing.get("public_smoke_ms", 0)
    return {
        "code": published.get("code", 1) if isinstance(published, dict) else 1,
        "success": bool(isinstance(published, dict) and published.get("code") == 0),
        "workflow_version": FRC.PLAN_VERSION,
        "task_id": task_id,
        "package_count": len(registered_packages),
        "grant_count": len(registered_grants),
        "image_count": len(uploaded_images),
        "registered_packages": registered_packages,
        "registered_grants": registered_grants,
        "uploaded_images": uploaded_images,
        "validation_receipt_files": receipts,
        "grant_validation_receipt_files": grant_receipts,
        "route_receipt_file": route_receipt_file,
        "card_runtime_preflight": card_runtime_preflight,
        "timing": timings,
        "stages": stages,
        "prepared_html_file": str(prepared_file),
        "publish_verified": published,
        "manifest_file": str(manifest_path),
        "review_file": str(review_path),
        "reply_data_evidence_file": reply_evidence_contract.get("reply_data_evidence_file"),
        "reply_data_evidence_sha256": reply_evidence_contract.get("reply_data_evidence_sha256"),
        "reply_data_availability": reply_evidence_contract.get("reply_data_availability"),
    }


def run_workflow(params):
    params = dict(params or {})
    if params.get("version") == FRC.PLAN_VERSION:
        return _run_workflow_v2(params)
    manifest_file = params.get("fork_manifest_file")
    if manifest_file:
        try:
            _, manifest = _read_json_file(manifest_file, "fork_manifest_file")
        except (OSError, ValueError, json.JSONDecodeError):
            manifest = {}
        if manifest.get("version") == FRC.MANIFEST_VERSION and any(key in params for key in ("packages", "grants", "markers", "runtime_markers")):
            return _failure("MANUAL_RUNTIME_BINDINGS_FORBIDDEN", "fork_manifest_v2 禁止手工传入 runtime bindings")
    return _run_workflow_v1(params)


def _persist_workflow_report(result, task_id):
    path = C.task_temp_path(task_id, "publish-workflow-report.json", create_parent=True)
    persisted_result = SP._redact_persisted_secrets(result)
    path.write_text(json.dumps(persisted_result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return str(path), hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    params = C.read_params(sys.argv[1:], env_var="QBV_WORKFLOW_PARAMS")
    try:
        result = run_workflow(params)
    except (FileNotFoundError, OSError, ValueError) as exc:
        result = _failure("WORKFLOW_ERROR", str(exc))
    try:
        report_file, report_sha256 = _persist_workflow_report(result, params.get("task_id"))
    except OSError as exc:
        report_file, report_sha256 = "", ""
        result.setdefault("report_warning", str(exc))
    emitted = {
        "code": result.get("code", 1),
        "success": bool(result.get("success")),
        "workflow_version": result.get("workflow_version") or "publish_workflow_v1",
        "task_id": result.get("task_id") or params.get("task_id"),
        "package_count": result.get("package_count", 0),
        "grant_count": result.get("grant_count", 0),
        "image_count": result.get("image_count", 0),
        "timing": result.get("timing") or {},
        "report_file": report_file,
        "report_sha256": report_sha256,
    }
    if result.get("error"):
        emitted.update({"error": result.get("error"), "message": result.get("message")})
    if isinstance(result.get("publish_verified"), dict):
        emitted["publish_verified"] = SP._publish_verified_cli_result(result["publish_verified"], params.get("task_id"))
    C.emit(emitted, out_name="qbv_publish_workflow_out.txt")
    raise SystemExit(0 if result.get("code") == 0 else 1)

if __name__ == "__main__":
    main()
