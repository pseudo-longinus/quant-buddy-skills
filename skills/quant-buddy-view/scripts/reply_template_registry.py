#!/usr/bin/env python3
"""Shared loader and validator for Agent reply template render policies."""

import copy
import json
import os
import re
from functools import lru_cache

import common as C


REGISTRY_PATH = os.path.join(C.SKILL_ROOT, "reply-templates", "index.json")
POLICY_VERSION = "reply_render_policy_v1"
DATA_POLICY_VERSION = "reply_data_policy_v1"
_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_FENCED_MARKDOWN_RE = re.compile(r"```markdown\s*(.*?)```", re.IGNORECASE | re.DOTALL)


def _template_path(entry):
    return os.path.join(C.SKILL_ROOT, "reply-templates", str(entry.get("file") or ""))


def _reply_data_policy(entry, template_id):
    relative = str(entry.get("reply_data_policy_file") or "").strip()
    if not relative:
        return None
    path = os.path.abspath(os.path.join(C.SKILL_ROOT, relative))
    root = os.path.abspath(C.SKILL_ROOT) + os.sep
    if not path.startswith(root) or not os.path.isfile(path):
        raise ValueError(f"{template_id}.reply_data_policy_file 不存在或越界")
    with open(path, "r", encoding="utf-8-sig") as handle:
        policy = json.load(handle)
    if not isinstance(policy, dict) or policy.get("version") != DATA_POLICY_VERSION:
        raise ValueError(f"{template_id}.reply_data_policy.version 必须是 {DATA_POLICY_VERSION}")
    if policy.get("template_ref") != template_id:
        raise ValueError(f"{template_id}.reply_data_policy.template_ref 不一致")
    policy["policy_file"] = path
    return policy


def _headings_from_file(path):
    with open(path, "r", encoding="utf-8-sig") as handle:
        text = handle.read()
    fenced = _FENCED_MARKDOWN_RE.search(text)
    skeleton = fenced.group(1) if fenced else text
    return [heading.strip() for heading in _HEADING_RE.findall(skeleton)]


def _string_list(value, field, template_id):
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{template_id}.{field} 必须是字符串数组")
    normalized = [item.strip() for item in value]
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{template_id}.{field} 不能包含重复章节")
    return normalized


def _normalize_policy(policy, template_id, headings):
    if not isinstance(policy, dict):
        raise ValueError(f"{template_id}.reply_render_policy 必须是对象")
    if policy.get("version") != POLICY_VERSION:
        raise ValueError(f"{template_id}.reply_render_policy.version 必须是 {POLICY_VERSION}")
    required = _string_list(policy.get("required_sections"), "required_sections", template_id)
    optional = _string_list(policy.get("optional_sections"), "optional_sections", template_id)
    overlap = sorted(set(required) & set(optional))
    if overlap:
        raise ValueError(f"{template_id} required/optional 章节重复: {', '.join(overlap)}")
    declared = set(required) | set(optional)
    unknown = sorted(declared - set(headings))
    if unknown:
        raise ValueError(f"{template_id} policy 包含模板中不存在的章节: {', '.join(unknown)}")
    groups = policy.get("at_least_one_groups")
    if not isinstance(groups, list):
        raise ValueError(f"{template_id}.at_least_one_groups 必须是数组")
    normalized_groups = []
    for index, group in enumerate(groups):
        values = _string_list(group, f"at_least_one_groups[{index}]", template_id)
        if not values:
            raise ValueError(f"{template_id}.at_least_one_groups[{index}] 不能为空")
        missing = sorted(set(values) - declared)
        if missing:
            raise ValueError(f"{template_id}.at_least_one_groups[{index}] 含未声明章节: {', '.join(missing)}")
        normalized_groups.append(values)
    if policy.get("placeholder_policy") != "partial_only":
        raise ValueError(f"{template_id}.placeholder_policy 目前只支持 partial_only")
    return {
        "version": POLICY_VERSION,
        "required_sections": required,
        "optional_sections": optional,
        "at_least_one_groups": normalized_groups,
        "omit_all_missing_columns": policy.get("omit_all_missing_columns") is True,
        "omit_all_missing_rows": policy.get("omit_all_missing_rows") is True,
        "placeholder_policy": "partial_only",
    }


@lru_cache(maxsize=1)
def _load_registry_cached():
    with open(REGISTRY_PATH, "r", encoding="utf-8-sig") as handle:
        registry = json.load(handle)
    entries = registry.get("templates")
    if not isinstance(entries, list):
        raise ValueError("reply template registry 缺少 templates 数组")
    by_id = {}
    for raw in entries:
        if not isinstance(raw, dict):
            raise ValueError("reply template registry 条目必须是对象")
        template_id = str(raw.get("id") or "").strip()
        if not template_id or template_id in by_id:
            raise ValueError(f"reply template id 缺失或重复: {template_id}")
        path = _template_path(raw)
        if not os.path.isfile(path):
            raise ValueError(f"reply template 文件不存在: {path}")
        entry = dict(raw)
        entry["template_headings"] = _headings_from_file(path)
        entry["reply_render_policy"] = _normalize_policy(
            raw.get("reply_render_policy"),
            template_id,
            entry["template_headings"],
        )
        entry["reply_data_policy"] = _reply_data_policy(raw, template_id)
        by_id[template_id] = entry
    return {"registry": registry, "by_id": by_id}


def load_registry():
    return copy.deepcopy(_load_registry_cached()["registry"])


def get_template_entry(template_ref):
    entry = _load_registry_cached()["by_id"].get(str(template_ref or ""))
    return copy.deepcopy(entry) if entry else None


def get_reply_render_policy(template_ref):
    entry = get_template_entry(template_ref)
    return entry.get("reply_render_policy") if entry else None


def get_template_headings(template_ref):
    entry = get_template_entry(template_ref)
    return entry.get("template_headings") if entry else []


def get_reply_data_policy(template_ref):
    entry = get_template_entry(template_ref)
    return entry.get("reply_data_policy") if entry else None
