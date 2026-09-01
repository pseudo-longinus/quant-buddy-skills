#!/usr/bin/env python3
"""校验终态 contract 对应的最终 Markdown 草稿，防止漏章节、漏链接或泄露敏感信息。"""

import hashlib
import json
import os
import re
import sys

import common as C
import reply_template_registry as RTR


_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_FENCED_MARKDOWN_RE = re.compile(r"```markdown\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_UNRESOLVED_FIELD_RE = re.compile(r"\{[^{}\r\n]+\}")
_TABLE_SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$")
_MISSING_VALUES = {"", "--", "—", "本轮未返回", "不适用", "n/a", "na"}
_SENSITIVE_PATTERNS = [
    ("windows_local_path", re.compile(r"(?i)(?:^|[\s(])(?:[a-z]:\\|file:///)")),
    ("unix_local_path", re.compile(r"(?:^|[\s(])/(?:Users|home|tmp|var/tmp)/")),
    ("api_key", re.compile(r"(?i)\bapi[_ -]?key\b\s*[:=]")),
    ("authorization", re.compile(r"(?i)\bauthorization\b\s*[:=]")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{8,}")),
    ("signature", re.compile(r"(?i)\bsignature(?:_hash)?\b\s*[:=]")),
]


def _read_json_or_object(params, key, file_key):
    value = params.get(key)
    if isinstance(value, dict):
        return value
    path = params.get(file_key)
    if not path:
        return None
    with open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _read_text(params, key, file_key):
    value = params.get(key)
    if isinstance(value, str):
        return value
    path = params.get(file_key)
    if not path:
        return ""
    with open(path, "r", encoding="utf-8-sig") as handle:
        return handle.read()


def _required_headings(template_ref):
    policy = RTR.get_reply_render_policy(template_ref)
    if isinstance(policy, dict):
        return list(policy.get("required_sections") or [])
    return RTR.get_template_headings(template_ref)


def _is_missing_value(value):
    normalized = re.sub(r"[。；;，,]+$", "", str(value or "").strip()).lower()
    return normalized in _MISSING_VALUES


def _section_bodies(draft):
    matches = list(_HEADING_RE.finditer(draft or ""))
    sections = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(draft)
        sections.append({
            "heading": match.group(1).strip(),
            "body": draft[match.end():end].strip(),
            "position": match.start(),
        })
    return sections


def _split_table_row(line):
    text = str(line or "").strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    return [cell.strip() for cell in text.split("|")]


def _markdown_tables(draft):
    lines = str(draft or "").splitlines()
    tables = []
    index = 0
    while index + 1 < len(lines):
        header = _split_table_row(lines[index]) if "|" in lines[index] else []
        separator = _split_table_row(lines[index + 1]) if "|" in lines[index + 1] else []
        if (
            len(header) >= 2
            and len(separator) == len(header)
            and all(_TABLE_SEPARATOR_CELL_RE.match(cell) for cell in separator)
        ):
            rows = []
            cursor = index + 2
            while cursor < len(lines) and "|" in lines[cursor]:
                row = _split_table_row(lines[cursor])
                if len(row) != len(header):
                    break
                rows.append(row)
                cursor += 1
            tables.append({"headers": header, "rows": rows, "line": index + 1})
            index = cursor
            continue
        index += 1
    return tables


def _placeholder_only(body):
    text = re.sub(r"[`*_>#\-+\[\]()]", " ", str(body or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return _is_missing_value(text)


def _render_policy_errors(template_ref, policy, draft, sections):
    errors = []
    canonical = RTR.get_reply_render_policy(template_ref)
    if not isinstance(policy, dict) or policy.get("version") != RTR.POLICY_VERSION or not canonical:
        return None, [{"code": "REPLY_RENDER_POLICY_INVALID", "message": "终态 contract 的回复裁剪策略无效或模板未注册"}]
    policy = canonical
    required = policy["required_sections"]
    optional = policy["optional_sections"]
    present = [item["heading"] for item in sections]
    present_set = set(present)

    for heading in required:
        if heading not in present_set:
            errors.append({"code": "REQUIRED_SECTION_MISSING", "message": f"缺少必填章节：## {heading}"})
    for group in policy["at_least_one_groups"]:
        if not present_set.intersection(group):
            errors.append({
                "code": "AT_LEAST_ONE_SECTION_REQUIRED",
                "message": "以下章节至少展示一个：" + " / ".join(group),
                "sections": group,
            })

    template_order = {heading: index for index, heading in enumerate(RTR.get_template_headings(template_ref))}
    displayed_template_sections = [heading for heading in present if heading in template_order]
    if displayed_template_sections != sorted(displayed_template_sections, key=template_order.get):
        errors.append({"code": "SECTION_ORDER_INVALID", "message": "已展示章节未保持回复模板中的原始顺序"})

    for item in sections:
        if item["heading"] in optional and _placeholder_only(item["body"]):
            errors.append({
                "code": "EMPTY_OPTIONAL_SECTION",
                "message": f"可选章节只有空值占位，应删除：## {item['heading']}",
                "section": item["heading"],
            })

    for table in _markdown_tables(draft):
        rows = table["rows"]
        if not rows:
            continue
        if policy["omit_all_missing_columns"]:
            for column_index in range(1, len(table["headers"])):
                if all(_is_missing_value(row[column_index]) for row in rows):
                    errors.append({
                        "code": "EMPTY_TABLE_COLUMN",
                        "message": f"表格整列为空，应删除：{table['headers'][column_index]}",
                        "column": table["headers"][column_index],
                        "line": table["line"],
                    })
        if policy["omit_all_missing_rows"]:
            for row in rows:
                if all(_is_missing_value(cell) for cell in row[1:]):
                    errors.append({
                        "code": "EMPTY_TABLE_ROW",
                        "message": f"表格整行无有效指标，应删除：{row[0]}",
                        "row": row[0],
                        "line": table["line"],
                    })

    return policy, errors


def _read_hashed_evidence(contract):
    evidence_file = str(contract.get("reply_data_evidence_file") or "").strip()
    expected_sha256 = str(contract.get("reply_data_evidence_sha256") or "").strip().lower()
    if not evidence_file or not expected_sha256:
        return None, {
            "code": "REPLY_DATA_EVIDENCE_REQUIRED",
            "message": "严格数据回复模板缺少 reply_data_evidence_file / SHA256",
        }
    try:
        with open(evidence_file, "rb") as handle:
            payload = handle.read()
    except OSError as exc:
        return None, {"code": "REPLY_DATA_EVIDENCE_UNREADABLE", "message": str(exc)}
    actual_sha256 = hashlib.sha256(payload).hexdigest()
    if actual_sha256 != expected_sha256:
        return None, {
            "code": "REPLY_DATA_EVIDENCE_HASH_MISMATCH",
            "message": "回复证据文件哈希不匹配",
            "expected_sha256": expected_sha256,
            "actual_sha256": actual_sha256,
        }
    try:
        evidence = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, {"code": "REPLY_DATA_EVIDENCE_INVALID", "message": str(exc)}
    if not isinstance(evidence, dict) or evidence.get("version") != "reply_data_evidence_v1":
        return None, {"code": "REPLY_DATA_EVIDENCE_INVALID", "message": "回复证据版本无效"}
    if evidence.get("template_ref") != contract.get("template_ref"):
        return None, {"code": "REPLY_DATA_EVIDENCE_TEMPLATE_MISMATCH", "message": "回复证据与模板不匹配"}
    return evidence, None


def _section_line_candidates(body, label):
    label = str(label or "").strip().lower()
    if not label:
        return []
    return [line for line in str(body or "").splitlines() if label in line.lower()]


def _render_token_in_line(token, line):
    token = str(token or "").strip()
    if not token:
        return False
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", token):
        normalized = token.rstrip("0").rstrip(".") if "." in token else token
        number = re.escape(normalized)
        if "." in normalized:
            pattern = rf"(?<![\d.]){number}0*(?![\d.A-Za-z])"
        else:
            pattern = rf"(?<![\d.]){number}(?:\.0+)?(?![\d.A-Za-z])"
        return re.search(pattern, line) is not None
    return token in line


def _data_coverage_errors(contract, sections):
    if not RTR.get_reply_data_policy(contract.get("template_ref")):
        return None, []
    evidence, evidence_error = _read_hashed_evidence(contract)
    if evidence_error:
        return None, [evidence_error]
    errors = []
    section_map = {item["heading"]: item["body"] for item in sections}
    fields_by_section = {}
    for field in evidence.get("fields") or []:
        if isinstance(field, dict):
            fields_by_section.setdefault(field.get("section"), []).append(field)
    for heading, metadata in (evidence.get("sections") or {}).items():
        body = section_map.get(heading)
        if body is None:
            continue
        section_fields = fields_by_section.get(heading) or []
        if not section_fields and not str(heading).endswith("综合观察"):
            expected = str((metadata or {}).get("no_data_text") or "").strip()
            if expected and expected not in body:
                errors.append({
                    "code": "NO_DATA_SECTION_TEXT_REQUIRED",
                    "message": f"无数据章节必须使用标准说明：## {heading}",
                    "section": heading,
                    "expected_text": expected,
                })
    for field in evidence.get("fields") or []:
        if not isinstance(field, dict):
            continue
        section = str(field.get("section") or "")
        label = str(field.get("row_label") or "")
        candidates = _section_line_candidates(section_map.get(section, ""), label)
        if not candidates:
            errors.append({
                "code": "AVAILABLE_DATA_OMITTED",
                "message": f"有可用数据但未输出指标：{label}",
                "field_id": field.get("field_id"),
                "section": section,
            })
            continue
        tokens = [str(token) for token in field.get("render_tokens") or [] if str(token)]
        if any(any(_render_token_in_line(token, line) for token in tokens) for line in candidates):
            continue
        if any(re.search(r"(?:^|[|\s])(?:--|—)(?:$|[|\s])", line) for line in candidates):
            errors.append({
                "code": "AVAILABLE_VALUE_REPLACED_WITH_PLACEHOLDER",
                "message": f"指标已有值，不能用 -- 代替：{label}",
                "field_id": field.get("field_id"),
                "section": section,
            })
        else:
            errors.append({
                "code": "AVAILABLE_DATA_OMITTED",
                "message": f"指标行未包含可用值：{label}",
                "field_id": field.get("field_id"),
                "section": section,
            })
    return evidence, errors


def _delivery_constraint_errors(contract, draft):
    policy = contract.get("delivery_policy")
    if not isinstance(policy, dict) or "max_markdown_tables" not in policy:
        return [], None
    max_tables = policy.get("max_markdown_tables")
    if isinstance(max_tables, bool) or not isinstance(max_tables, int) or max_tables < 0:
        return [{
            "code": "DELIVERY_POLICY_INVALID",
            "message": "delivery_policy.max_markdown_tables 必须是非负整数",
        }], None
    table_count = len(_markdown_tables(draft))
    if table_count <= max_tables:
        return [], table_count
    return [{
        "code": "MARKDOWN_TABLE_LIMIT_EXCEEDED",
        "message": f"当前渠道最多允许 {max_tables} 张 Markdown 表格，实际为 {table_count} 张",
        "channel": policy.get("channel"),
        "max_tables": max_tables,
        "actual_tables": table_count,
    }], table_count


def validate_reply(contract_payload, draft):
    contract_payload = contract_payload if isinstance(contract_payload, dict) else {}
    contract = contract_payload.get("agent_reply_contract") if isinstance(contract_payload.get("agent_reply_contract"), dict) else contract_payload
    errors = []
    if contract.get("terminal") is not True:
        errors.append({"code": "TERMINAL_CONTRACT_REQUIRED", "message": "缺少 terminal=true 的终态 contract"})
    public_url = str(contract.get("public_url") or "").strip()
    if not public_url:
        errors.append({"code": "PUBLIC_URL_REQUIRED", "message": "终态 contract 缺少 public_url"})
    elif public_url not in draft:
        errors.append({"code": "PUBLIC_URL_MISSING", "message": "最终回复未包含终态 public_url"})

    if contract.get("require_page_id_in_reply") is True:
        page_id = str(contract.get("page_id") or "").strip()
        if not page_id:
            errors.append({"code": "PAGE_ID_REQUIRED", "message": "终态 contract 要求回传 page_id，但 contract 缺少 page_id"})
        elif page_id not in draft.replace(public_url, ""):
            errors.append({"code": "PAGE_ID_MISSING", "message": "最终回复未在公开链接之外单独包含终态 page_id"})

    sections = _section_bodies(draft)
    actual = [item["heading"] for item in sections]
    render_policy = contract.get("reply_render_policy")
    required = []
    optional = []
    if render_policy is not None:
        render_policy, policy_errors = _render_policy_errors(
            contract.get("template_ref"), render_policy, draft, sections
        )
        errors.extend(policy_errors)
        if render_policy:
            required = render_policy["required_sections"]
            optional = render_policy["optional_sections"]
    else:
        required = _required_headings(contract.get("template_ref")) if contract.get("required") else []
        cursor = -1
        for heading in required:
            try:
                index = actual.index(heading, cursor + 1)
            except ValueError:
                errors.append({"code": "REQUIRED_SECTION_MISSING", "message": f"缺少或顺序错误的章节：## {heading}"})
                continue
            cursor = index

    evidence, evidence_errors = _data_coverage_errors(contract, sections)
    errors.extend(evidence_errors)
    delivery_errors, markdown_table_count = _delivery_constraint_errors(contract, draft)
    errors.extend(delivery_errors)

    unresolved = _UNRESOLVED_FIELD_RE.findall(draft)
    if unresolved:
        errors.append({
            "code": "UNRESOLVED_FIELDS",
            "message": "最终回复仍有模板字段未替换；结构性不存在的字段应删除，偶发缺值才可写 --",
            "fields": unresolved[:20],
        })
    for name, pattern in _SENSITIVE_PATTERNS:
        if pattern.search(draft):
            errors.append({"code": "SENSITIVE_CONTENT", "message": f"最终回复包含禁止内容：{name}"})

    result = {
        "code": 0 if not errors else 1,
        "valid": not errors,
        "template_ref": contract.get("template_ref") or None,
        "required_sections": required,
        "errors": errors,
    }
    if render_policy is not None:
        result.update({
            "reply_render_policy": render_policy,
            "optional_sections": optional,
            "present_sections": actual,
            "omitted_optional_sections": [heading for heading in optional if heading not in set(actual)],
        })
    if evidence is not None:
        result["reply_data_evidence_version"] = evidence.get("version")
        result["validated_field_count"] = len(evidence.get("fields") or [])
    if markdown_table_count is not None:
        result["markdown_table_count"] = markdown_table_count
        result["max_markdown_tables"] = contract.get("delivery_policy", {}).get("max_markdown_tables")
    if result["valid"]:
        result["validated_markdown"] = draft
        result["validated_markdown_sha256"] = hashlib.sha256(draft.encode("utf-8")).hexdigest()
    return result


def _read_hashed_contract(params):
    contract_file = str(params.get("contract_file") or "").strip()
    expected_sha256 = str(params.get("contract_sha256") or "").strip().lower()
    if not contract_file or not expected_sha256:
        return None, {
            "code": "CONTRACT_ARTIFACT_REQUIRED",
            "message": "必须使用发布器返回的 contract_file 和 contract_sha256",
        }
    with open(contract_file, "rb") as handle:
        payload = handle.read()
    actual_sha256 = hashlib.sha256(payload).hexdigest()
    if actual_sha256 != expected_sha256:
        return None, {
            "code": "CONTRACT_HASH_MISMATCH",
            "message": "contract 文件已变化，拒绝验证手工重建或篡改的 contract",
            "expected_sha256": expected_sha256,
            "actual_sha256": actual_sha256,
        }
    return json.loads(payload.decode("utf-8")), None



def main():
    params = C.read_params(sys.argv[1:], env_var="REPLY_PARAMS")
    try:
        contract, contract_error = _read_hashed_contract(params)
        draft = _read_text(params, "draft", "draft_file")
        if contract_error:
            result = {"code": 1, "valid": False, "errors": [contract_error]}
        elif not contract or not draft:
            result = {"code": 1, "valid": False, "errors": [{"code": "INPUT_REQUIRED", "message": "需要 contract/contract_file 和 draft/draft_file"}]}
        else:
            result = validate_reply(contract, draft)
            if result.get("valid") and params.get("cleanup_task_id"):
                result["cleaned_temp_files"] = C.cleanup_task_temp_files(params.get("cleanup_task_id"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {"code": 1, "valid": False, "errors": [{"code": "INPUT_ERROR", "message": str(exc)}]}
    C.emit(result, out_name="reply_validation_out.txt")
    sys.exit(0 if result.get("code") == 0 else 1)


if __name__ == "__main__":
    main()
