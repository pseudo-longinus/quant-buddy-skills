#!/usr/bin/env python3
"""Render new_asset_page evidence as a reply draft for Agent-authored synthesis."""

import hashlib
import json
from collections import OrderedDict
from pathlib import Path


TEMPLATE_REF = "single_stock_deep_dive_v1"
SECTIONS = [
    "一、行情与估值",
    "二、财务分析",
    "三、资金 / 交易特征",
    "四、计算维度",
    "五、波动率与风险",
    "六、综合观察",
]
STANDARD_NO_DATA_TEXT = "本轮未返回可核验的该章节数据"
OPTIONAL_DATA_SECTIONS = {"四、计算维度"}
MAX_MARKDOWN_TABLES = 5
MAX_LIST_BULLET_CHARS = 160
AGENT_SUMMARY_MARKER = "{{QBV_AGENT_PURPOSE_ALIGNED_SUMMARY}}"
_SECTION_NUMERALS = ("一", "二", "三", "四", "五", "六", "七", "八", "九", "十")


class ReplyRenderError(ValueError):
    """Raised when hash-bound evidence cannot produce a safe complete reply."""


def _read_evidence(path, expected_sha256):
    evidence_path = Path(str(path or ""))
    expected = str(expected_sha256 or "").strip().lower()
    if not evidence_path.is_file() or not expected:
        raise ReplyRenderError("缺少可读取的 reply evidence 或 SHA256")
    payload = evidence_path.read_bytes()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise ReplyRenderError("reply evidence SHA256 不匹配")
    try:
        evidence = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReplyRenderError(f"reply evidence 不是有效 UTF-8 JSON：{exc}") from exc
    if not isinstance(evidence, dict) or evidence.get("template_ref") != TEMPLATE_REF:
        raise ReplyRenderError("reply evidence 模板类型不支持单股回复草稿")
    fields = evidence.get("fields")
    if not isinstance(fields, list) or not fields:
        raise ReplyRenderError("reply evidence 没有可渲染字段")
    return evidence


def _escape_cell(value):
    return str(value or "").replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def _render_value(field):
    tokens = [str(item).strip() for item in field.get("render_tokens") or [] if str(item).strip()]
    if not tokens:
        raise ReplyRenderError(f"字段 {field.get('field_id') or field.get('row_label')} 缺少 render_tokens")
    value = tokens[0]
    unit = str(field.get("unit") or "").strip()
    field_id = str(field.get("field_id") or "").lower()
    column = str(field.get("column_label") or "")
    is_percentile = "分位" in column or ".pctrank" in field_id
    if is_percentile and unit != "%":
        unit = ""
    if unit and not value.endswith(unit):
        value += unit
    return value


def _display_date(value):
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    if "T" in text:
        return text.split("T", 1)[0]
    return text


def _group_section_fields(fields):
    grouped = OrderedDict()
    for field in fields:
        if not isinstance(field, dict):
            continue
        label = str(field.get("row_label") or field.get("field_id") or "").strip()
        if not label:
            raise ReplyRenderError("reply evidence 包含没有 row_label/field_id 的字段")
        grouped.setdefault(label, []).append(field)
    return grouped


def _display_section_heading(section, ordinal):
    title = str(section or "").split("、", 1)[-1]
    if ordinal < 1 or ordinal > len(_SECTION_NUMERALS):
        raise ReplyRenderError("可见章节数量超出编号范围")
    return f"{_SECTION_NUMERALS[ordinal - 1]}、{title}"


def _render_section_table(fields):
    rows = ["| 指标 | 可核验数据 | 数据日期 |", "|---|---|---|"]
    for label, row_fields in _group_section_fields(fields).items():
        values = []
        dates = []
        for field in row_fields:
            column = str(field.get("column_label") or "值").strip()
            values.append(f"{_escape_cell(column)}：{_escape_cell(_render_value(field))}")
            date_value = _display_date(field.get("date"))
            if date_value and date_value not in dates:
                dates.append(date_value)
        rows.append(f"| {_escape_cell(label)} | {'；'.join(values)} | {_escape_cell('、'.join(dates) or '—')} |")
    return "\n".join(rows)


def _render_section_list(fields):
    rows = []
    for label, row_fields in _group_section_fields(fields).items():
        values = []
        for field in row_fields:
            column = str(field.get("column_label") or "值").strip()
            values.append(f"{column}：{_render_value(field)}")
        prefix = f"- **{label}**："
        current = []
        for value in values:
            candidate = "；".join(current + [value])
            if current and len(prefix + candidate) > MAX_LIST_BULLET_CHARS:
                rows.append(prefix + "；".join(current))
                current = [value]
            else:
                current.append(value)
        if current:
            rows.append(prefix + "；".join(current))
    return "\n\n".join(rows)


def _latest_evidence_date(fields, evidence):
    dates = [_display_date(field.get("date")) for field in fields if isinstance(field, dict)]
    dates = [item for item in dates if item]
    if dates:
        return max(dates)
    created_at = _display_date(evidence.get("created_at"))
    if not created_at:
        raise ReplyRenderError("reply evidence 缺少可核验的数据日期和创建时间")
    return created_at


def _asset_identity(asset, evidence):
    asset = asset if isinstance(asset, dict) else {}
    name = str(asset.get("name") or "").strip()
    code = str(asset.get("code") or asset.get("ticker") or "").strip()
    if name:
        return name, code
    for source in (evidence.get("source_evidence") or {}).values():
        source_asset = source.get("asset") if isinstance(source, dict) else None
        if not isinstance(source_asset, dict):
            continue
        name = str(source_asset.get("name") or source_asset.get("asset_name") or "").strip()
        code = str(source_asset.get("code") or source_asset.get("ticker") or "").strip()
        if name:
            return name, code
    raise ReplyRenderError("无法从页面结果或 evidence 确认标的名称")


def render(*, evidence_file, evidence_sha256, asset, public_url):
    """Return a complete data draft whose summary marker must be authored by the Agent."""
    evidence = _read_evidence(evidence_file, evidence_sha256)
    public_url = str(public_url or "").strip()
    if not public_url.startswith(("https://pages.quantbuddy.cn/", "https://www.quantbuddy.cn/playground/")):
        raise ReplyRenderError("终态公开 URL 缺失或域名不受支持")

    fields = [item for item in evidence.get("fields") or [] if isinstance(item, dict)]
    name, code = _asset_identity(asset, evidence)
    as_of = _latest_evidence_date(fields, evidence)
    identity = f"{name}（{code}）" if code else name
    by_section = {section: [] for section in SECTIONS}
    for field in fields:
        section = str(field.get("section") or "").strip()
        if section not in by_section:
            raise ReplyRenderError(f"字段 {field.get('field_id')} 指向未知章节：{section}")
        by_section[section].append(field)

    lines = [
        f"**{identity}全面分析**", "",
        f"时间：截至 {as_of} | 数据来源：QB / 活页实时数据", "",
        "---",
    ]
    visible_data_sections = [
        section for section in SECTIONS[:-1]
        if by_section[section] or section not in OPTIONAL_DATA_SECTIONS
    ]
    table_count = 0
    for ordinal, section in enumerate(visible_data_sections, start=1):
        section_fields = by_section[section]
        lines.extend(["", f"## {_display_section_heading(section, ordinal)}", ""])
        if section_fields:
            if section in SECTIONS[:5] and table_count < MAX_MARKDOWN_TABLES:
                lines.append(_render_section_table(section_fields))
                table_count += 1
            else:
                lines.append(_render_section_list(section_fields))
        else:
            lines.append(STANDARD_NO_DATA_TEXT)
        lines.extend(["", "---"])

    summary_heading = _display_section_heading(SECTIONS[-1], len(visible_data_sections) + 1)
    lines.extend(["", f"## {summary_heading}", "", AGENT_SUMMARY_MARKER])
    # Keep the delivery block as the literal end of the reply.  The browser
    # streams this Markdown incrementally, so emitting the public URL above
    # the evidence sections makes the link appear before the analysis ends.
    lines.extend([
        "", f"> 数据截至 {as_of}；不构成投资建议。",
        "", "---", "",
        f"可分享实时活页：[{public_url}]({public_url})",
        "若效果不满意，页面可进一步升级",
    ])
    return "\n".join(lines) + "\n"
