#!/usr/bin/env python3
"""Pure helpers for manifest-driven QBV forks.

This module deliberately has no network or credential-registration side effects. It turns a
source template plus template metadata into a markerized HTML document, a private runtime
manifest, and a credential-free review projection for the Agent.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone


MANIFEST_VERSION = "fork_manifest_v2"
REVIEW_VERSION = "fork_review_v1"
REVIEW_RECEIPT_VERSION = "fork_review_receipt_v1"
PLAN_VERSION = "publish_workflow_v2"
DEFAULT_BEGIN_DATE = 20150101
MAX_PACKAGE_FORMULAS = 100

_PACKAGE_ID_RE = re.compile(r"^pkg_[0-9A-Za-z._-]+$")
_GRANT_ID_RE = re.compile(r"^(?:dg|grant)_[0-9A-Za-z._-]+$")
_ASSET_ARG_RE = re.compile(
    r"(?:取出|收盘价|开盘价|最高价|最低价|涨跌幅|成交额|成交量|换手率|总市值|流通市值)"
    r"\(\s*([^()]{1,80}?)\s*\)"
)
_LONG_PAIR_RE = re.compile(
    r"(?:[\"']?(?P<id_key>package_id|packageId|grant_id|grantId)[\"']?)\s*:\s*"
    r"(?P<id_quote>[\"'])(?P<credential_id>[^\"']+)(?P=id_quote)"
    r"(?P<middle>[\s\S]{0,1800}?)"
    r"(?:[\"']?signature[\"']?)\s*:\s*(?P<sig_quote>[\"'])(?P<signature>[^\"']+)(?P=sig_quote)",
    re.I,
)
_SHORT_PAIR_RE = re.compile(
    r"(?<![0-9A-Za-z_])(?:[\"']?id[\"']?)\s*:\s*(?P<id_quote>[\"'])(?P<credential_id>(?:pkg|dg|grant)_[^\"']+)(?P=id_quote)"
    r"(?P<middle>[\s\S]{0,1800}?)"
    r"(?<![0-9A-Za-z_])(?:[\"']?sig[\"']?)\s*:\s*(?P<sig_quote>[\"'])(?P<signature>[^\"']+)(?P=sig_quote)",
    re.I,
)
_CONST_CREDENTIAL_ID_RE = re.compile(
    r"\b(?:const|let|var)\s+(?P<prefix>[A-Za-z0-9_]*)(?P<credential_kind>PACKAGE|GRANT)_ID\s*=\s*"
    r"(?P<id_quote>[\"'])(?P<credential_id>(?:pkg|dg|grant)_[^\"']+)(?P=id_quote)",
    re.I,
)


class ForkRuntimeError(ValueError):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code = code
        self.details = details

    def as_dict(self):
        return {"code": 1, "error": self.code, "message": str(self), **self.details}


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def contract_fingerprint(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def build_required_decisions(review):
    """Describe only the business decisions still required from the Agent."""
    required = []
    if not isinstance(review, dict):
        return [{"decision_id": "review", "kind": "review_object", "message": "fork review 必须是对象"}]
    main_review = review.get("main_asset_review") or {}
    if main_review and main_review.get("confirmed") is not True:
        required.append({"decision_id": "main_asset_confirmed", "kind": "confirmation", "message": "确认主资产替换"})
    for role in review.get("roles") or []:
        if not isinstance(role, dict):
            continue
        role_id = str(role.get("role_id") or "")
        review_type = role.get("review_type")
        if review_type == "peer_slot_mapping":
            slots = role.get("target_slots")
            if not isinstance(slots, dict):
                required.append({"decision_id": f"roles.{role_id}.target_slots", "kind": "peer_slot_mapping", "role_id": role_id, "message": "填写目标同业映射"})
            else:
                for source, target in slots.items():
                    if not str(target or "").strip():
                        required.append({
                            "decision_id": f"roles.{role_id}.target_slots.{source}",
                            "kind": "peer_asset",
                            "role_id": role_id,
                            "source": str(source),
                            "message": f"选择 {source} 对应的目标同业",
                        })
        elif review_type == "manual_formula_rewrite" and not [
            value for value in role.get("target_formulas") or [] if str(value or "").strip()
        ]:
            required.append({
                "decision_id": f"roles.{role_id}.target_formulas",
                "kind": "target_formulas",
                "role_id": role_id,
                "message": "填写完整目标公式",
            })
        overrides = role.get("contract_overrides") or {}
        if overrides and not str(role.get("contract_change_reason") or "").strip():
            required.append({
                "decision_id": f"roles.{role_id}.contract_change_reason",
                "kind": "contract_change_reason",
                "role_id": role_id,
                "message": "说明 Grant 合同覆盖原因",
            })
    return required


def build_decisions_skeleton(review):
    """Nested skeleton matching apply_review_decisions()'s accepted shape, pre-populated
    with role_id keys so the Agent only fills placeholder values instead of inventing the
    top-level nesting (required_decisions' flat dotted decision_id is not a submission key)."""
    skeleton = {"roles": {}}
    required = build_required_decisions(review)
    if any(item.get("decision_id") == "main_asset_confirmed" for item in required):
        skeleton["main_asset_confirmed"] = False
    required_role_ids = {item.get("role_id") for item in required if item.get("role_id")}
    role_by_id = {str(role.get("role_id") or ""): role for role in review.get("roles") or [] if isinstance(role, dict)}
    for role_id in required_role_ids:
        role = role_by_id.get(role_id) or {}
        role_skeleton = {}
        if role.get("review_type") == "peer_slot_mapping":
            slots = role.get("target_slots") or {}
            role_skeleton["target_slots"] = {
                str(source): str(target) if str(target or "").strip() else ""
                for source, target in slots.items()
            }
        if role.get("review_type") == "manual_formula_rewrite":
            role_skeleton["target_formulas"] = []
        overrides = role.get("contract_overrides") or {}
        if overrides and not str(role.get("contract_change_reason") or "").strip():
            role_skeleton["contract_change_reason"] = ""
        if role_skeleton:
            skeleton["roles"][role_id] = role_skeleton
    return skeleton


def apply_review_decisions(review, decisions):
    """Apply a narrow structured payload without exposing runtime bindings."""
    if not isinstance(review, dict) or review.get("version") != REVIEW_VERSION:
        raise ForkRuntimeError("FORK_REVIEW_INVALID", f"fork review.version 必须是 {REVIEW_VERSION}")
    if not isinstance(decisions, dict):
        raise ForkRuntimeError("FORK_REVIEW_DECISIONS_INVALID", "decisions 必须是对象")
    allowed_top = {"main_asset_confirmed", "roles", "page_label_replacements"}
    unknown_top = sorted(set(decisions) - allowed_top)
    if unknown_top:
        raise ForkRuntimeError("FORK_REVIEW_DECISIONS_INVALID", f"不允许的 review decision 字段: {', '.join(unknown_top)}")
    updated = copy.deepcopy(review)
    if "main_asset_confirmed" in decisions:
        updated.setdefault("main_asset_review", {})["confirmed"] = decisions["main_asset_confirmed"] is True
    labels = decisions.get("page_label_replacements")
    if labels is not None:
        if not isinstance(labels, dict) or any(not str(key or "") for key in labels):
            raise ForkRuntimeError("FORK_REVIEW_DECISIONS_INVALID", "page_label_replacements 必须是非空来源键对象")
        updated["page_label_replacements"] = {str(key): str(value or "") for key, value in labels.items()}
    role_updates = decisions.get("roles") or {}
    if not isinstance(role_updates, dict):
        raise ForkRuntimeError("FORK_REVIEW_DECISIONS_INVALID", "decisions.roles 必须是 role_id 到决策对象的映射")
    role_index = {str(item.get("role_id") or ""): item for item in updated.get("roles") or [] if isinstance(item, dict)}
    allowed_role = {"target_slots", "target_formulas", "asset_scope", "contract_overrides", "contract_change_reason"}
    for role_id, values in role_updates.items():
        if role_id not in role_index or not isinstance(values, dict):
            raise ForkRuntimeError("FORK_REVIEW_DECISIONS_INVALID", f"未知或无效 role decision: {role_id}")
        unknown = sorted(set(values) - allowed_role)
        if unknown:
            raise ForkRuntimeError("FORK_REVIEW_DECISIONS_INVALID", f"{role_id} 不允许的字段: {', '.join(unknown)}")
        for key, value in values.items():
            role_index[role_id][key] = copy.deepcopy(value)
    if "__QBV_" in canonical_json(updated):
        raise ForkRuntimeError("FORK_REVIEW_DECISIONS_INVALID", "review decision 不得包含 runtime Marker")
    return updated


def review_state(manifest, review, html):
    required = build_required_decisions(review)
    if required:
        return {"status": "decisions_required", "required_decisions": required}
    resolved = resolve_review(manifest, review, html)
    return {
        "status": "complete",
        "required_decisions": [],
        "resolved_contract_sha256": contract_fingerprint({
            "packages": resolved["packages"],
            "grants": resolved["grants"],
            "html_sha256": hashlib.sha256(resolved["html"].encode("utf-8")).hexdigest(),
        }),
    }


def build_review_receipt(**values):
    return {
        "version": REVIEW_RECEIPT_VERSION,
        "status": "complete",
        "task_id": str(values.get("task_id") or ""),
        "page_id": str(values.get("page_id") or ""),
        "source_template_id": str(values.get("source_template_id") or ""),
        "manifest_sha256": str(values.get("manifest_sha256") or ""),
        "review_sha256": str(values.get("review_sha256") or ""),
        "working_html_sha256": str(values.get("working_html_sha256") or ""),
        "review_base_sha256": str(values.get("review_base_sha256") or ""),
        "resolved_contract_sha256": str(values.get("resolved_contract_sha256") or ""),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def formula_output(formula):
    if not isinstance(formula, str) or "=" not in formula:
        return ""
    output = formula.split("=", 1)[0].strip().strip("\"'")
    return output if output and re.match(r"^[^()\s+\-*/]+$", output) else ""


def formula_outputs(formulas):
    out = []
    for formula in formulas or []:
        value = formula_output(formula)
        if value and value not in out:
            out.append(value)
    return out


def formula_asset_refs(formula):
    return _unique_strings(
        match.strip().strip("\"'")
        for match in _ASSET_ARG_RE.findall(str(formula or ""))
    )


def apply_replacements(text, replacements):
    result = str(text or "")
    for source, target in sorted((replacements or {}).items(), key=lambda item: len(str(item[0])), reverse=True):
        source_text = str(source or "")
        if source_text:
            result = result.replace(source_text, str(target or ""))
    return result

def apply_replacements_value(value, replacements):
    if isinstance(value, str):
        return apply_replacements(value, replacements)
    if isinstance(value, list):
        return [apply_replacements_value(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: apply_replacements_value(item, replacements) for key, item in value.items()}
    return copy.deepcopy(value)


def _unique_strings(values):
    out = []
    seen = set()
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _safe_role_name(value, fallback):
    text = re.sub(r"[^0-9A-Za-z]+", "_", str(value or "").strip()).strip("_").lower()
    return text or fallback


def _credential_kind(credential_id, id_key=""):
    if str(id_key).lower().startswith("package") or _PACKAGE_ID_RE.match(credential_id or ""):
        return "package"
    if str(id_key).lower().startswith("grant") or _GRANT_ID_RE.match(credential_id or ""):
        return "grant"
    return ""


def _constant_credential_pairs(html):
    """Pair bespoke JS constants by their full variable-name prefix.

    Supported shapes include PACKAGE_ID + SIGNATURE,
    ROSTER_PACKAGE_ID + ROSTER_SIGNATURE, and
    FUND_GRANT_ID + FUND_GRANT_SIGNATURE.
    """
    text = str(html or "")
    pairs = []
    for match in _CONST_CREDENTIAL_ID_RE.finditer(text):
        prefix = str(match.group("prefix") or "")
        declared_kind = str(match.group("credential_kind") or "").upper()
        kind = "package" if declared_kind == "PACKAGE" else "grant"
        signature_variable = f"{prefix}SIGNATURE" if kind == "package" else f"{prefix}GRANT_SIGNATURE"
        signature_re = re.compile(
            rf"\b(?:const|let|var)\s+{re.escape(signature_variable)}\s*=\s*"
            r"(?P<sig_quote>[\"'])(?P<signature>[^\"']+)(?P=sig_quote)",
            re.I,
        )
        for signature_match in signature_re.finditer(text):
            pairs.append({
                "kind": kind,
                "credential_id": str(match.group("credential_id") or "").strip(),
                "signature": str(signature_match.group("signature") or "").strip(),
            })
    return pairs


def discover_credential_pairs(html, *, reject_ambiguous=True):
    """Return unique active credential pairs while optionally rejecting ambiguity."""
    pairs = []
    seen = set()
    id_to_signatures = defaultdict(set)
    signature_to_ids = defaultdict(set)
    candidates = []
    for pattern in (_LONG_PAIR_RE, _SHORT_PAIR_RE):
        for match in pattern.finditer(html or ""):
            credential_id = str(match.group("credential_id") or "").strip()
            signature = str(match.group("signature") or "").strip()
            kind = _credential_kind(credential_id, match.groupdict().get("id_key") or "")
            candidates.append({"kind": kind, "credential_id": credential_id, "signature": signature})
    candidates.extend(_constant_credential_pairs(html))
    for candidate in candidates:
        credential_id = str(candidate.get("credential_id") or "").strip()
        signature = str(candidate.get("signature") or "").strip()
        kind = str(candidate.get("kind") or "").strip()
        if not kind or not credential_id or not signature:
            continue
        key = (kind, credential_id, signature)
        id_to_signatures[(kind, credential_id)].add(signature)
        signature_to_ids[signature].add((kind, credential_id))
        if key not in seen:
            seen.add(key)
            pairs.append({"kind": kind, "credential_id": credential_id, "signature": signature})
    ambiguous = [
        {"kind": kind, "credential_id": credential_id, "signature_count": len(signatures)}
        for (kind, credential_id), signatures in id_to_signatures.items() if len(signatures) > 1
    ]
    shared_signatures = [
        {"signature_sha256": hashlib.sha256(signature.encode("utf-8")).hexdigest(), "credential_count": len(ids)}
        for signature, ids in signature_to_ids.items() if len(ids) > 1
    ]
    if reject_ambiguous and (ambiguous or shared_signatures):
        raise ForkRuntimeError(
            "SOURCE_CREDENTIAL_AMBIGUOUS",
            "来源 HTML 存在一个 ID 对应多个 signature，或同一 signature 对应多个凭证",
            ambiguous_credentials=ambiguous,
            shared_signatures=shared_signatures,
        )
    return pairs
def _contract_indexes(template_record):
    packages = {}
    grants = {}
    for index, item in enumerate((template_record or {}).get("packages") or []):
        if not isinstance(item, dict):
            continue
        credential_id = str(item.get("package_id") or "").strip()
        if credential_id:
            packages[credential_id] = (index, item)
    for index, item in enumerate((template_record or {}).get("grants") or []):
        if not isinstance(item, dict):
            continue
        credential_id = str(item.get("grant_id") or "").strip()
        if credential_id:
            grants[credential_id] = (index, item)
    return packages, grants


def _marker_prefix(role_id):
    return re.sub(r"[^0-9A-Za-z]+", "_", role_id).strip("_").upper()


def _replace_all_with_markers(html, value, marker_factory):
    count = str(html or "").count(value)
    if count < 1:
        return html, []
    parts = str(html).split(value)
    markers = [marker_factory(index + 1) for index in range(count)]
    out = []
    for index, part in enumerate(parts[:-1]):
        out.extend((part, markers[index]))
    out.append(parts[-1])
    return "".join(out), markers


def _surface_hints(html, credential_id):
    hints = []
    cursor = 0
    text = str(html or "")
    while True:
        index = text.find(credential_id, cursor)
        if index < 0:
            break
        before = text[max(0, index - 1200):index]
        surface = "card" if "data-qb-card-manifest" in before or "data-qb-card-template" in before else "page"
        hints.append({"surface": surface, "ordinal": len(hints) + 1})
        cursor = index + len(credential_id)
    return hints



def normalize_begin_date(value):
    raw = DEFAULT_BEGIN_DATE if value is None or str(value).strip() == "" else value
    if isinstance(raw, bool):
        raise ForkRuntimeError("SOURCE_RUNTIME_CONTRACT_MISSING", "来源 package begin_date 必须是 YYYYMMDD 整数")
    try:
        normalized = int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise ForkRuntimeError("SOURCE_RUNTIME_CONTRACT_MISSING", "来源 package begin_date 必须是 YYYYMMDD 整数") from exc
    if normalized < 20050104 or normalized > 20991231 or len(str(normalized)) != 8:
        raise ForkRuntimeError("SOURCE_RUNTIME_CONTRACT_MISSING", "来源 package begin_date 超出有效范围")
    return normalized


def source_package_nodes(item):
    """Preserve template API nodes, with a reads-only compatibility fallback."""
    raw_nodes = item.get("nodes") if isinstance(item, dict) else None
    if isinstance(raw_nodes, list) and raw_nodes:
        return copy.deepcopy(raw_nodes)

    raw_reads = item.get("reads") if isinstance(item, dict) else None
    if not isinstance(raw_reads, list):
        return []
    nodes = []
    for value in raw_reads:
        if not isinstance(value, dict):
            continue
        node = {
            "output_name": str(value.get("output") or value.get("output_name") or "").strip(),
            "read_mode": str(value.get("read_mode") or "").strip(),
        }
        if "mode_params" in value:
            node["mode_params"] = copy.deepcopy(value.get("mode_params"))
        nodes.append(node)
    return nodes


def normalize_package_reads(item):
    """Derive target registration reads from template API nodes."""
    reads = []
    for value in source_package_nodes(item):
        if not isinstance(value, dict):
            continue
        read = {
            "output": str(value.get("output_name") or value.get("output") or "").strip(),
            "read_mode": str(value.get("read_mode") or "").strip(),
        }
        if "mode_params" in value:
            read["mode_params"] = copy.deepcopy(value.get("mode_params"))
        reads.append(read)
    return reads


def _package_contracts(item, replacements, primary_sources):
    source_formulas = [str(value) for value in item.get("formulas") or [] if isinstance(value, str) and value.strip()]
    proposed_formulas = [apply_replacements(value, replacements) for value in source_formulas]
    nodes = source_package_nodes(item)
    reads = normalize_package_reads(item)
    begin_date = normalize_begin_date(item.get("begin_date"))
    primary = {str(value).strip() for value in primary_sources if str(value).strip()}
    cross_refs = _unique_strings(
        ref
        for formula in source_formulas
        for ref in formula_asset_refs(formula)
        if ref not in primary
    )
    return (
        {"formulas": source_formulas, "nodes": nodes},
        {"formulas": proposed_formulas, "reads": reads, "begin_date": begin_date},
        {"outputs": formula_outputs(source_formulas), "cross_asset_refs": cross_refs},
    )


def _target_package_contract(role):
    target = role.get("target_registration_contract") if isinstance(role, dict) else None
    if isinstance(target, dict):
        return target
    source = role.get("source_contract") if isinstance(role, dict) else {}
    return {
        "formulas": copy.deepcopy(source.get("proposed_formulas") or source.get("formulas") or []),
        "reads": copy.deepcopy(source.get("reads") or []),
        "begin_date": source.get("begin_date") or DEFAULT_BEGIN_DATE,
    }


def _role_fingerprint_source(role):
    source = role.get("source_contract") or {}
    target = role.get("target_registration_contract")
    if role.get("kind") == "package" and isinstance(target, dict):
        return {"source_contract": source, "target_registration_contract": target}
    return {
        key: value for key, value in source.items()
        if key not in ("proposed_formulas", "target_payload", "asset_scope")
    }

def _grant_contract(item, replacements):
    payload = copy.deepcopy(item.get("payload") if isinstance(item.get("payload"), dict) else {})
    target_payload = copy.deepcopy(payload)
    asset_scope = []
    declared_scope = _unique_strings(item.get("allowed_asset_scope_fields") or item.get("asset_scope_fields"))
    candidate_scope = _unique_strings(declared_scope + [
        "asset", "assets", "symbol", "symbols", "universe", "benchmark",
        "peer_assets", "components", "industry_members",
    ])
    for field in candidate_scope:
        if field not in payload:
            continue
        source_value = copy.deepcopy(payload[field])
        target_value = apply_replacements_value(source_value, replacements)
        target_payload[field] = target_value
        asset_scope.append({"field": field, "source": source_value, "target": copy.deepcopy(target_value)})
    return {
        "kind": item.get("kind"),
        "payload": payload,
        "allowed_asset_scope_fields": [entry["field"] for entry in asset_scope],
        "target_payload": target_payload,
        "asset_scope": asset_scope,
        "response_shape": copy.deepcopy(item.get("response_shape")),
    }


def _is_peer_matrix(formulas, cross_refs):
    if len(cross_refs) < 2:
        return False
    counts = Counter()
    for formula in formulas:
        refs = [ref for ref in formula_asset_refs(formula) if ref in cross_refs]
        if len(refs) > 1:
            return False
        if refs:
            counts[refs[0]] += 1
    return bool(counts) and set(counts) == set(cross_refs) and len(set(counts.values())) == 1


def _package_review(role):
    source_contract = role["source_contract"]
    target_contract = _target_package_contract(role)
    analysis = role.get("formula_analysis") or source_contract
    cross_refs = analysis.get("cross_asset_refs") or []
    base = {
        "role_id": role["role_id"],
        "kind": "package",
        "required_outputs": list(role.get("required_outputs") or []),
        "readonly_output_contract": [
            {
                "output": read.get("output"),
                "read_mode": read.get("read_mode"),
                "mode_params": copy.deepcopy(read.get("mode_params")),
            }
            for read in target_contract.get("reads") or []
        ],
    }
    if not cross_refs:
        return {
            **base,
            "review_type": "auto_formula_replace",
            "source_formulas": list(source_contract.get("formulas") or []),
            "target_formulas": list(target_contract.get("formulas") or []),
            "review_complete": True,
        }
    if _is_peer_matrix(source_contract.get("formulas") or [], cross_refs):
        return {
            **base,
            "review_type": "peer_slot_mapping",
            "source_formulas": list(source_contract.get("formulas") or []),
            "formula_templates": list(target_contract.get("formulas") or []),
            "source_asset_refs": list(cross_refs),
            "target_slots": {source: None for source in cross_refs},
            "review_complete": False,
        }
    return {
        **base,
        "review_type": "manual_formula_rewrite",
        "source_formulas": list(source_contract.get("formulas") or []),
        "cross_asset_refs": list(cross_refs),
        "target_formulas": [],
        "review_complete": False,
    }

def _grant_review(role):
    contract = role["source_contract"]
    payload = contract.get("payload") or {}
    # Review只投影理解来源响应合同所必需的字段；完整 payload 留在私有 manifest。
    # 这样 Agent能确认 CSV/inline、维度和窗口等继承关系，但不会接触任意底层参数。
    immutable_summary = {
        key: copy.deepcopy(payload[key])
        for key in ("query_type", "fields", "dimensions", "window_days", "result_mode", "mode")
        if key in payload
    }
    if contract.get("response_shape") is not None:
        immutable_summary["response_shape"] = copy.deepcopy(contract.get("response_shape"))
    return {
        "role_id": role["role_id"],
        "kind": "grant",
        "grant_kind": contract.get("kind"),
        "review_type": "asset_scope" if contract.get("asset_scope") else "inherited_grant",
        "readonly_contract_summary": immutable_summary,
        "asset_scope": copy.deepcopy(contract.get("asset_scope") or []),
        "contract_overrides": {},
        "contract_change_reason": "",
        "review_complete": True,
    }


def build_runtime_artifacts(html, template_record, replacements=None, primary_sources=None):
    """Discover active roles, markerize credentials, and create manifest/review fragments."""
    replacements = dict(replacements or {})
    primary_sources = list(primary_sources or replacements.keys())
    pairs = discover_credential_pairs(html)
    package_index, grant_index = _contract_indexes(template_record or {})
    working = str(html or "")
    roles = []
    role_names = set()
    for ordinal, pair in enumerate(pairs, start=1):
        kind = pair["kind"]
        credential_id = pair["credential_id"]
        signature = pair["signature"]
        contract_index = package_index if kind == "package" else grant_index
        if credential_id not in contract_index:
            raise ForkRuntimeError(
                "SOURCE_RUNTIME_CONTRACT_MISSING",
                f"来源 HTML 的 {kind} 凭证没有模板运行合同: {credential_id}",
                credential_kind=kind,
                credential_id=credential_id,
            )
        index, source_item = contract_index[credential_id]
        fallback = f"{kind}_{index + 1:03d}"
        base_name = _safe_role_name(source_item.get("name") or source_item.get("role"), fallback)
        role_id = f"{kind}.{base_name}"
        suffix = 2
        while role_id in role_names:
            role_id = f"{kind}.{base_name}_{suffix}"
        if kind == "package":
            normalized_reads = normalize_package_reads(source_item)
            if (
                not isinstance(source_item.get("formulas"), list)
                or not source_item.get("formulas")
                or not normalized_reads
                or any(not read.get("output") or not read.get("read_mode") for read in normalized_reads)
            ):
                raise ForkRuntimeError(
                    "SOURCE_RUNTIME_CONTRACT_MISSING",
                    f"来源公式包缺少完整 formulas/nodes 合同: {credential_id}",
                )
        if kind == "grant" and (
            not str(source_item.get("kind") or "").strip()
            or not isinstance(source_item.get("payload"), dict)
            or not source_item.get("payload")
        ):
            raise ForkRuntimeError("SOURCE_RUNTIME_CONTRACT_MISSING", f"来源 Grant 缺少 kind/payload 合同: {credential_id}")
            suffix += 1
        role_names.add(role_id)
        id_count = working.count(credential_id)
        sig_count = working.count(signature)
        if id_count != sig_count or id_count < 1:
            raise ForkRuntimeError(
                "SOURCE_CREDENTIAL_UNPAIRED",
                f"来源 {kind} 凭证 ID/signature 出现次数不一致",
                credential_id=credential_id,
                id_count=id_count,
                signature_count=sig_count,
            )
        prefix = _marker_prefix(role_id)
        occurrences = _surface_hints(working, credential_id)
        working, id_markers = _replace_all_with_markers(
            working,
            credential_id,
            lambda number: f"__QBV_{prefix}_ID_{number:03d}__",
        )
        working, signature_markers = _replace_all_with_markers(
            working,
            signature,
            lambda number: f"__QBV_{prefix}_SIG_{number:03d}__",
        )
        if kind == "package":
            source_contract, target_contract, formula_analysis = _package_contracts(
                source_item, replacements, primary_sources
            )
            required_outputs = _unique_strings(read.get("output") for read in target_contract.get("reads") or [])
        else:
            source_contract = _grant_contract(source_item, replacements)
            target_contract = None
            formula_analysis = None
            required_outputs = []
        role = {
            "role_id": role_id,
            "kind": kind,
            "source_credential_id": credential_id,
            "source_signature_sha256": hashlib.sha256(signature.encode("utf-8")).hexdigest(),
            "source_contract": source_contract,
            "required_outputs": required_outputs,
            "allowed_modifications": (
                {"formulas": True, "reads": False, "begin_date": False}
                if kind == "package" else {"asset_scope_fields": source_contract.get("allowed_asset_scope_fields", [])}
            ),
            "markers": {
                "package_id" if kind == "package" else "grant_id": id_markers,
                "signature": signature_markers,
            },
            "occurrences": occurrences,
        }
        if kind == "package":
            role["target_registration_contract"] = target_contract
            role["formula_analysis"] = formula_analysis
        role["contract_fingerprint"] = contract_fingerprint(_role_fingerprint_source(role))
        roles.append(role)
    source_ids = [role["source_credential_id"] for role in roles]
    source_hashes = [role["source_signature_sha256"] for role in roles]
    leaked_ids = [value for value in source_ids if value in working]
    if leaked_ids:
        raise ForkRuntimeError(
            "FORK_MARKERIZE_INCOMPLETE",
            "自动 Marker 化后仍含来源凭证",
            leaked_credentials=leaked_ids,
        )
    marker_values = []
    for role in roles:
        for value in role["markers"].values():
            marker_values.extend(value)
    duplicate_markers = [marker for marker, count in Counter(marker_values).items() if count != 1]
    invalid_markers = [marker for marker in marker_values if working.count(marker) != 1]
    if duplicate_markers or invalid_markers:
        raise ForkRuntimeError(
            "FORK_MARKERIZE_INCOMPLETE",
            "自动生成的 Marker 不唯一或未在 HTML 中恰好出现一次",
            duplicate_markers=duplicate_markers,
            invalid_markers=invalid_markers,
        )
    review_roles = [
        _package_review(role) if role["kind"] == "package" else _grant_review(role)
        for role in roles
    ]
    review = {
        "main_asset_review": {
            "replacements": [{"source": str(source), "target": str(target)} for source, target in replacements.items()],
            "status": "auto_applied" if replacements else "not_required",
            "confirmed": True,
        },
        "version": REVIEW_VERSION,
        "instructions": "只填写同业槽位、复杂目标公式和允许的资产范围；不要添加凭证、Marker、reads 或完整 Grant payload。",
        "roles": review_roles,
        "page_label_replacements": {},
    }
    return {
        "working_html": working,
        "runtime_roles": roles,
        "review": review,
        "source_package_ids": [role["source_credential_id"] for role in roles if role["kind"] == "package"],
        "source_grant_ids": [role["source_credential_id"] for role in roles if role["kind"] == "grant"],
        "source_signature_sha256": source_hashes,
    }


def resolve_review(manifest, review, html):
    """Resolve Agent decisions into target contracts and final editable HTML."""
    if not isinstance(review, dict) or review.get("version") != REVIEW_VERSION:
        raise ForkRuntimeError("FORK_REVIEW_INVALID", f"fork review.version 必须是 {REVIEW_VERSION}")
    main_review = review.get("main_asset_review") or {}
    if main_review and main_review.get("confirmed") is not True:
        raise ForkRuntimeError("FORK_REVIEW_INCOMPLETE", "主资产替换尚未确认")
    serialized_review = canonical_json(review)
    if "__QBV_" in serialized_review:
        raise ForkRuntimeError("FORK_REVIEW_INVALID", "fork review 不得包含 runtime Marker")
    leaked_credentials = [
        str(role.get("source_credential_id") or "")
        for role in manifest.get("runtime_roles") or []
        if str(role.get("source_credential_id") or "") in serialized_review
    ]
    if leaked_credentials:
        raise ForkRuntimeError("FORK_REVIEW_INVALID", "fork review 不得包含来源凭证")
    source_signature_hashes = {
        str(role.get("source_signature_sha256") or "")
        for role in manifest.get("runtime_roles") or []
    }
    review_signature_hashes = {
        hashlib.sha256(value.encode("utf-8")).hexdigest()
        for value in re.findall(r'"(?:signature|sig)"\s*:\s*"([^"]+)"', serialized_review, flags=re.I)
    }
    if source_signature_hashes & review_signature_hashes:
        raise ForkRuntimeError("FORK_REVIEW_INVALID", "fork review 不得包含来源 signature")
    review_by_role = {
        str(item.get("role_id") or ""): item
        for item in review.get("roles") or [] if isinstance(item, dict)
    }
    packages = []
    grants = []
    rendered_html = str(html or "")
    for role in manifest.get("runtime_roles") or []:
        role_id = str(role.get("role_id") or "")
        decision = review_by_role.get(role_id)
        if not decision:
            raise ForkRuntimeError("FORK_REVIEW_INCOMPLETE", f"fork review 缺少角色: {role_id}")
        if role.get("kind") == "package":
            review_type = decision.get("review_type")
            if review_type == "peer_slot_mapping":
                slots = decision.get("target_slots")
                if not isinstance(slots, dict) or any(not str(value or "").strip() for value in slots.values()):
                    raise ForkRuntimeError("FORK_REVIEW_INCOMPLETE", f"同业槽位尚未填写完整: {role_id}")
                formulas = list(decision.get("formula_templates") or [])
                for source, target in slots.items():
                    formulas = [formula.replace(str(source), str(target)) for formula in formulas]
                    rendered_html = rendered_html.replace(str(source), str(target))
            else:
                formulas = list(decision.get("target_formulas") or [])
                if not formulas:
                    raise ForkRuntimeError("FORK_REVIEW_INCOMPLETE", f"目标公式尚未填写: {role_id}")
            target_contract = _target_package_contract(role)
            contract = {
                "formulas": formulas,
                "reads": copy.deepcopy(target_contract.get("reads") or []),
                "begin_date": target_contract.get("begin_date") or DEFAULT_BEGIN_DATE,
            }
            packages.append({
                "name": role_id,
                "role_id": role_id,
                "contract": contract,
                "contract_fingerprint": contract_fingerprint(contract),
                "required_outputs": list(role.get("required_outputs") or []),
                "markers": copy.deepcopy(role.get("markers") or {}),
            })
        else:
            source_contract = role.get("source_contract") or {}
            payload = copy.deepcopy(source_contract.get("target_payload") or source_contract.get("payload") or {})
            scope = decision.get("asset_scope") or []
            allowed_fields = {item.get("field") for item in source_contract.get("asset_scope") or []}
            for item in scope:
                if not isinstance(item, dict) or item.get("field") not in allowed_fields:
                    raise ForkRuntimeError("GRANT_CONTRACT_MISMATCH", f"Grant包含未授权资产范围字段: {role_id}")
                payload[item["field"]] = copy.deepcopy(item.get("target"))
            overrides = decision.get("contract_overrides") or {}
            reason = str(decision.get("contract_change_reason") or "").strip()
            if overrides and not reason:
                raise ForkRuntimeError("GRANT_CONTRACT_MISMATCH", f"Grant合同覆盖必须说明原因: {role_id}")
            if not isinstance(overrides, dict):
                raise ForkRuntimeError("GRANT_CONTRACT_MISMATCH", f"Grant合同覆盖必须是对象: {role_id}")
            payload.update(copy.deepcopy(overrides))
            contract = {"kind": source_contract.get("kind"), "payload": payload}
            grants.append({
                "name": role_id,
                "role_id": role_id,
                "contract": contract,
                "contract_change_reason": reason,
                "contract_fingerprint": contract_fingerprint(contract),
                "source_contract_fingerprint": role.get("contract_fingerprint"),
                "markers": copy.deepcopy(role.get("markers") or {}),
            })
    for source, target in (review.get("page_label_replacements") or {}).items():
        if source:
            rendered_html = rendered_html.replace(str(source), str(target or ""))
    return {"html": rendered_html, "packages": packages, "grants": grants}


def build_publish_plan(*, task_id, user_query, manifest_file, review_file, working_html_file,
                       prepared_html_file, target_page_id="", images=None, publish_verified=None,
                       review_receipt_file="", review_receipt_sha256=""):
    """Create a credential-free workflow plan. Runtime contracts stay in the private manifest."""
    verified = dict(publish_verified or {})
    if target_page_id:
        verified.setdefault("page_id", str(target_page_id))
    verified.setdefault("fork_manifest_file", str(manifest_file))
    return {
        "version": PLAN_VERSION,
        "task_id": str(task_id or ""),
        "user_query": str(user_query or ""),
        "fork_manifest_file": str(manifest_file),
        "fork_review_file": str(review_file),
        "html_template_file": str(working_html_file),
        "prepared_html_file": str(prepared_html_file),
        "review_receipt_file": str(review_receipt_file or ""),
        "review_receipt_sha256": str(review_receipt_sha256 or ""),
        "images": copy.deepcopy(images or []),
        "publish_verified": verified,
    }


def validate_manifest_html(manifest, html):
    if not isinstance(manifest, dict) or manifest.get("version") != MANIFEST_VERSION:
        raise ForkRuntimeError("FORK_MANIFEST_INVALID", f"fork manifest.version 必须是 {MANIFEST_VERSION}")
    roles = manifest.get("runtime_roles")
    if not isinstance(roles, list):
        raise ForkRuntimeError("FORK_MANIFEST_INVALID", "fork manifest.runtime_roles 必须是数组")
    role_ids = [str(role.get("role_id") or "") for role in roles if isinstance(role, dict)]
    if len(role_ids) != len(roles) or any(not value for value in role_ids) or len(set(role_ids)) != len(role_ids):
        raise ForkRuntimeError("FORK_MANIFEST_INVALID", "runtime role ID 缺失或重复")
    all_markers = []
    for role in roles:
        kind = role.get("kind")
        if kind not in ("package", "grant"):
            raise ForkRuntimeError("FORK_MANIFEST_INVALID", f"runtime role kind 无效: {role.get('role_id')}")
        source_contract = role.get("source_contract")
        if not isinstance(source_contract, dict):
            raise ForkRuntimeError("FORK_MANIFEST_INVALID", f"runtime role 缺少 source_contract: {role.get('role_id')}")
        if kind == "package" and isinstance(role.get("target_registration_contract"), dict):
            target_contract = role["target_registration_contract"]
            source_formulas = source_contract.get("formulas")
            source_nodes = source_contract.get("nodes")
            target_reads = target_contract.get("reads")
            if not isinstance(source_formulas, list) or not source_formulas or not isinstance(source_nodes, list) or not source_nodes:
                raise ForkRuntimeError("FORK_MANIFEST_INVALID", f"package来源合同缺少 formulas/nodes: {role.get('role_id')}")
            if not isinstance(target_reads, list) or not target_reads:
                raise ForkRuntimeError("FORK_MANIFEST_INVALID", f"package目标注册合同缺少 reads: {role.get('role_id')}")
            if any(isinstance(read, dict) and "data_id" in read for read in target_reads):
                raise ForkRuntimeError("FORK_MANIFEST_INVALID", f"package目标注册合同不得继承来源 data_id: {role.get('role_id')}")
        if role.get("contract_fingerprint") != contract_fingerprint(_role_fingerprint_source(role)):
            raise ForkRuntimeError("FORK_MANIFEST_INVALID", f"runtime role 合同指纹不一致: {role.get('role_id')}")
        markers = role.get("markers")
        id_key = "package_id" if kind == "package" else "grant_id"
        if not isinstance(markers, dict):
            raise ForkRuntimeError("FORK_MANIFEST_INVALID", f"runtime role 缺少 markers: {role.get('role_id')}")
        id_markers = markers.get(id_key)
        sig_markers = markers.get("signature")
        if not isinstance(id_markers, list) or not isinstance(sig_markers, list) or not id_markers or len(id_markers) != len(sig_markers):
            raise ForkRuntimeError("FORK_MARKER_INVALID", f"runtime role ID/signature Marker 数量不一致: {role.get('role_id')}")
        all_markers.extend(id_markers)
        all_markers.extend(sig_markers)
        source_id = str(role.get("source_credential_id") or "")
        if source_id and source_id in str(html or ""):
            raise ForkRuntimeError("SOURCE_CREDENTIAL_LEAK", "working HTML 仍含来源凭证")
    expected_manifest_fingerprint = str(manifest.get("contract_fingerprint") or "")
    if expected_manifest_fingerprint:
        actual_manifest_fingerprint = contract_fingerprint([
            {"role_id": role["role_id"], "fingerprint": role["contract_fingerprint"]}
            for role in roles
        ])
        if expected_manifest_fingerprint != actual_manifest_fingerprint:
            raise ForkRuntimeError("FORK_MANIFEST_INVALID", "fork manifest 总合同指纹不一致")
    duplicate_markers = [marker for marker, count in Counter(all_markers).items() if count != 1]
    invalid_markers = [marker for marker in all_markers if not marker or str(html or "").count(marker) != 1]
    if duplicate_markers or invalid_markers:
        raise ForkRuntimeError(
            "FORK_MARKER_INVALID",
            "runtime Marker 必须全局唯一并在 HTML 中恰好出现一次",
            duplicate_markers=duplicate_markers,
            invalid_markers=invalid_markers,
        )
    source_signature_hashes = set(_unique_strings(manifest.get("source_signature_sha256")))
    current_signature_hashes = {
        hashlib.sha256(value.encode("utf-8")).hexdigest()
        for value in re.findall(r"(?:['\"]?(?:signature|sig)['\"]?)\s*:\s*['\"]([^'\"]+)['\"]", str(html or ""), flags=re.I)
    }
    if source_signature_hashes & current_signature_hashes:
        raise ForkRuntimeError("SOURCE_CREDENTIAL_LEAK", "working HTML 仍含来源 signature")
    return {
        "role_count": len(roles),
        "package_count": sum(role.get("kind") == "package" for role in roles),
        "grant_count": sum(role.get("kind") == "grant" for role in roles),
        "marker_count": len(all_markers),
    }


def _validate_percentile_semantics(output, formula, role_id):
    normalized = re.sub(r"\s+", "", str(formula or ""))
    output_key = str(output or "").lower()
    if not any(key in output_key for key in ("pe_pctile", "pb_pctile")):
        return
    if not re.search(r"(?:排序水位|数值水位)\([^,]+,[1-9]\d*\)", normalized):
        raise ForkRuntimeError(
            "FORMULA_SEMANTIC_INVALID",
            f"{role_id}.{output} 必须使用带明确正整数窗口的排序水位或数值水位公式",
        )


def validate_resolved_contracts(manifest, resolved):
    packages = resolved.get("packages") if isinstance(resolved, dict) else None
    grants = resolved.get("grants") if isinstance(resolved, dict) else None
    if not isinstance(packages, list) or not isinstance(grants, list):
        raise ForkRuntimeError("PUBLISH_CONTRACT_INVALID", "resolved packages/grants 必须是数组")
    role_index = {str(role.get("role_id") or ""): role for role in manifest.get("runtime_roles") or []}
    names = set()
    all_formula_outputs = set()
    all_read_outputs = set()
    for package in packages:
        role_id = str(package.get("role_id") or package.get("name") or "")
        if not role_id or role_id in names:
            raise ForkRuntimeError("PACKAGE_CONTRACT_INVALID", "package role 缺失或重复")
        names.add(role_id)
        contract = package.get("contract") or {}
        formulas = contract.get("formulas")
        reads = contract.get("reads")
        begin_date = contract.get("begin_date")
        if isinstance(begin_date, bool):
            raise ForkRuntimeError("PACKAGE_BEGIN_DATE_INVALID", f"{role_id}.begin_date 必须是 YYYYMMDD 整数")
        try:
            begin_date = int(str(begin_date).strip())
        except (TypeError, ValueError) as exc:
            raise ForkRuntimeError("PACKAGE_BEGIN_DATE_INVALID", f"{role_id}.begin_date 必须是 YYYYMMDD 整数") from exc
        if begin_date < 20050104 or begin_date > 20991231 or len(str(begin_date)) != 8:
            raise ForkRuntimeError("PACKAGE_BEGIN_DATE_INVALID", f"{role_id}.begin_date 超出有效范围")
        if not isinstance(formulas, list) or not (1 <= len(formulas) <= MAX_PACKAGE_FORMULAS) or not all(isinstance(value, str) and value.strip() for value in formulas):
            raise ForkRuntimeError(
                "PACKAGE_CONTRACT_INVALID",
                f"{role_id}.formulas 必须是 1..{MAX_PACKAGE_FORMULAS} 条非空公式",
            )
        outputs = [formula_output(value) for value in formulas]
        if any(not value for value in outputs) or len(set(outputs)) != len(outputs):
            raise ForkRuntimeError("PACKAGE_OUTPUT_INVALID", f"{role_id} 公式左值缺失或重复")
        if not isinstance(reads, list) or not reads:
            raise ForkRuntimeError("PACKAGE_READS_INVALID", f"{role_id}.reads 必须是非空数组")
        read_outputs = [str(item.get("output") or "").strip() for item in reads if isinstance(item, dict)]
        if len(read_outputs) != len(reads) or any(not value for value in read_outputs) or len(set(read_outputs)) != len(read_outputs):
            raise ForkRuntimeError("PACKAGE_READS_INVALID", f"{role_id}.reads.output 缺失或重复")
        all_formula_outputs.update(outputs)
        all_read_outputs.update(read_outputs)
        unknown_reads = sorted(set(read_outputs) - set(outputs))
        required = set(_unique_strings(package.get("required_outputs")))
        missing_formula = sorted(required - set(outputs))
        missing_reads = sorted(required - set(read_outputs))
        if unknown_reads or missing_formula or missing_reads:
            raise ForkRuntimeError(
                "REQUIRED_OUTPUTS_MISMATCH",
                f"{role_id} required outputs、公式左值和 reads 不一致",
                unknown_reads=unknown_reads,
                missing_formula=missing_formula,
                missing_reads=missing_reads,
            )
        for output, formula in zip(outputs, formulas):
            _validate_percentile_semantics(output, formula, role_id)
        if package.get("contract_fingerprint") != contract_fingerprint(contract):
            raise ForkRuntimeError("PACKAGE_CONTRACT_FINGERPRINT_MISMATCH", f"{role_id} package fingerprint 不一致")
    global_required = set(_unique_strings(manifest.get("required_outputs")))
    global_missing_formula = sorted(global_required - all_formula_outputs)
    global_missing_reads = sorted(global_required - all_read_outputs)
    if global_missing_formula or global_missing_reads:
        raise ForkRuntimeError(
            "REQUIRED_OUTPUTS_MISMATCH",
            "manifest required outputs、公式左值和 reads 不一致",
            missing_formula=global_missing_formula,
            missing_reads=global_missing_reads,
        )
    for grant in grants:
        role_id = str(grant.get("role_id") or grant.get("name") or "")
        contract = grant.get("contract") or {}
        kind = contract.get("kind")
        payload = contract.get("payload")
        if kind not in ("fast_query", "stock_profile", "composition_select") or not isinstance(payload, dict) or not payload:
            raise ForkRuntimeError("GRANT_CONTRACT_INVALID", f"{role_id} Grant kind/payload 无效")
        role = role_index.get(role_id) or {}
        source_contract = role.get("source_contract") or {}
        source_payload = source_contract.get("payload") or {}
        allowed = set(source_contract.get("allowed_asset_scope_fields") or [])
        changed = {key for key in set(source_payload) | set(payload) if source_payload.get(key) != payload.get(key)}
        unauthorized = sorted(changed - allowed)
        if unauthorized and not str(grant.get("contract_change_reason") or "").strip():
            raise ForkRuntimeError(
                "GRANT_CONTRACT_MISMATCH",
                f"{role_id} 修改了来源 Grant 的非资产范围合同",
                unauthorized_fields=unauthorized,
            )
        if grant.get("contract_fingerprint") != contract_fingerprint(contract):
            raise ForkRuntimeError("GRANT_CONTRACT_FINGERPRINT_MISMATCH", f"{role_id} Grant fingerprint 不一致")
    return {"package_count": len(packages), "grant_count": len(grants)}
