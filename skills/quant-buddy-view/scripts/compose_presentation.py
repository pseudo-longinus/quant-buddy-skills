"""Safe model-authored presentation layer for controlled Compose pages.

The presentation file owns narrative and layout only.  Data panels are mounted
into whitelist-safe containers and remain rendered by the standard QBV engine,
so custom prose/layout cannot bypass runtime, snapshot, or publication gates.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from html import escape as html_escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import compose_inputs as CI
import execution_plan as EP

VERSION = 1
DESIGN = "compose-bespoke-v1"
MAX_PRESENTATION_BYTES = 1024 * 1024
ALLOWED_TAGS = {
    "main", "section", "article", "div", "header", "h1", "h2", "h3", "p", "span",
    "strong", "em", "ul", "ol", "li", "figure", "figcaption", "details", "summary",
    "table", "thead", "tbody", "tr", "th", "td", "style",
}
VOID_TAGS = set()
ALLOWED_ATTRS = {"class", "id", "open", "style"}
ALLOWED_DATA_ATTRS = {
    "data-qb-panel", "data-qb-summary", "data-qb-metric", "data-qb-page-design",
    "data-qb-page-title",
}
ALLOWED_CSS_PROPERTIES = {
    "align-items", "background", "background-color", "border", "border-color",
    "border-radius", "border-width", "border-style", "bottom", "box-shadow", "color",
    "display", "flex", "flex-direction", "flex-wrap", "font-family", "font-size",
    "font-weight", "gap", "grid", "grid-area", "grid-auto-flow", "grid-column",
    "grid-row", "grid-template", "grid-template-areas", "grid-template-columns",
    "grid-template-rows", "height", "justify-content", "left", "letter-spacing",
    "line-height", "margin", "margin-bottom", "margin-left", "margin-right", "margin-top",
    "max-height", "max-width", "min-height", "min-width", "opacity", "overflow",
    "overflow-x", "overflow-y", "padding", "padding-bottom", "padding-left",
    "padding-right", "padding-top", "position", "right", "text-align", "top",
    "vertical-align", "white-space", "width", "z-index",
}
FORBIDDEN_HTML_PATTERN = re.compile(
    r"(?i)(api[_-]?key|authorization|access[_-]?token|secret|signature|grant_id|package_id|\bdg_[a-z0-9_-]+\b|\bpkg_[a-z0-9_-]+\b)"
)
ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,79}$")


class PresentationError(EP.PlanError):
    pass


def _error(code: str, message: str, **details: Any) -> PresentationError:
    return PresentationError(code, message, **details)


def _safe_css(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("@import", "url(", "expression", "<", ">", "\\", "!important", "position:fixed")):
        raise _error("PRESENTATION_CSS_FORBIDDEN", "Presentation CSS 禁止外部引用、fixed 定位或高风险声明")
    if "position" in lowered and re.search(r"position\s*:\s*fixed", text, re.I):
        raise _error("PRESENTATION_CSS_FORBIDDEN", "Presentation CSS 禁止 position:fixed")
    output_blocks = []
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text):
        selectors = [item.strip() for item in selector.split(",") if item.strip()]
        selector_pattern = r"[.#]?[A-Za-z_][A-Za-z0-9_.:-]*(?:\s+[.#]?[A-Za-z_][A-Za-z0-9_.:-]*)*"
        if not selectors or any(not re.fullmatch(selector_pattern, item) for item in selectors):
            raise _error("PRESENTATION_CSS_SELECTOR_INVALID", "Presentation CSS 选择器必须使用简单 class/id/tag/伪类选择器")
        declarations = []
        for declaration in body.split(";"):
            key, sep, value = declaration.partition(":")
            key, value = key.strip().lower(), value.strip()
            if not sep or not key or not value:
                continue
            if key not in ALLOWED_CSS_PROPERTIES:
                raise _error("PRESENTATION_CSS_PROPERTY_FORBIDDEN", f"Presentation CSS 不支持属性 {key}")
            if key == "position" and value.lower() not in ("static", "relative", "sticky", "absolute"):
                raise _error("PRESENTATION_CSS_FORBIDDEN", "Presentation CSS 禁止 fixed 定位")
            declarations.append(f"{key}:{value}")
        if declarations:
            output_blocks.append(",".join(selectors) + "{" + ";".join(declarations) + "}")
    return "\n".join(output_blocks)


def _safe_style_attribute(value: str) -> str:
    declarations = []
    for declaration in value.split(";"):
        key, sep, raw = declaration.partition(":")
        key, raw = key.strip().lower(), raw.strip()
        if not sep or not key or not raw:
            continue
        if key not in ALLOWED_CSS_PROPERTIES or key == "position":
            raise _error("PRESENTATION_CSS_PROPERTY_FORBIDDEN", f"Presentation style 属性不支持 {key}")
        if any(token in raw.lower() for token in ("url(", "@", "expression", "!important", "<", ">", "\\")):
            raise _error("PRESENTATION_CSS_FORBIDDEN", "Presentation style 属性包含高风险值")
        declarations.append(f"{key}:{raw}")
    return ";".join(declarations)


class _SafePresentationParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.main_depth = 0
        self.main_parts: list[str] = []
        self.style_parts: list[str] = []
        self.current_style = False
        self.counts: dict[str, int] = {}
        self.mounts: list[dict[str, Any]] = []
        self.all_mounts: list[str] = []
        self.ids: list[str] = []
        self.details_depth = 0
        self.node_index = 0
        self.mount_h1_count = 0
        self.summary_count = 0
        self.mount_summary_count = 0
        self.metric_count = 0
        self.mount_metric_count = 0
        self.main_design: str | None = None

    def _attr(self, attrs: list[tuple[str, str | None]], tag: str) -> str:
        allowed = ALLOWED_ATTRS | ALLOWED_DATA_ATTRS
        pieces = []
        for raw_key, raw_value in attrs:
            key = str(raw_key or "").strip()
            value = str(raw_value or "")
            if key.startswith("on") or key.lower() in {"href", "src", "srcset", "action", "formaction", "xlink:href"}:
                raise _error("PRESENTATION_ATTRIBUTE_FORBIDDEN", f"Presentation 禁止属性 {key}")
            if key == "style":
                value = _safe_style_attribute(value)
            if key not in allowed and not (key.startswith("data-qb-") and key in ALLOWED_DATA_ATTRS):
                raise _error("PRESENTATION_ATTRIBUTE_FORBIDDEN", f"标签 <{tag}> 不支持属性 {key}")
            if FORBIDDEN_HTML_PATTERN.search(value):
                raise _error("PRESENTATION_CREDENTIAL_FORBIDDEN", "Presentation HTML 不能包含凭据或运行时标识")
            pieces.append(f'{key}="{html_escape(value, quote=True)}"')
            if key == "id":
                self.ids.append(value)
            if key == "data-qb-panel":
                self.node_index += 1
                self.all_mounts.append(value)
                self.mounts.append({"id": value, "index": self.node_index, "collapsed": self.details_depth > 0})
            if key == "data-qb-summary":
                self.summary_count += 1
                if any(raw_key == "data-qb-panel" for raw_key, _ in attrs): self.mount_summary_count += 1
            if key == "data-qb-metric":
                self.metric_count += 1
                if any(raw_key == "data-qb-panel" for raw_key, _ in attrs): self.mount_metric_count += 1
        return (" " + " ".join(pieces)) if pieces else ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in ALLOWED_TAGS:
            raise _error("PRESENTATION_TAG_FORBIDDEN", f"Presentation 不允许标签 <{tag}>")
        self.counts[tag] = self.counts.get(tag, 0) + 1
        attr_text = self._attr(attrs, tag)
        if tag == "h1" and not any(key == "data-qb-page-title" for key, _ in attrs):
            attr_text += ' data-qb-page-title=""'
        if tag == "style":
            if self.main_depth:
                raise _error("PRESENTATION_STYLE_LOCATION_INVALID", "style 必须位于 main 顶层")
            self.current_style = True
            self.stack.append(tag)
            return
        if tag == "h1" and any(key == "data-qb-panel" for key, _ in attrs):
            self.mount_h1_count += 1
        if tag == "main":
            if self.main_depth:
                raise _error("PRESENTATION_MAIN_INVALID", "Presentation 不允许嵌套 main")
            self.main_depth = 1
            designs = [str(v or "") for k, v in attrs if k == "data-qb-page-design"]
            self.main_design = designs[0] if designs else ""
            if self.main_design != DESIGN:
                raise _error("PRESENTATION_DESIGN_INVALID", f"main 必须声明 data-qb-page-design=\"{DESIGN}\"")
            # The outer research-v1 main already exists in the generated page.
            self.main_parts.append('<div class="qb-compose-presentation">')
            self.stack.append(tag)
            return
        if self.main_depth:
            self.main_parts.append(f"<{tag}{attr_text}>")
        self.stack.append(tag)
        if tag == "details":
            self.details_depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # The v1 grammar intentionally contains no void elements.
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag not in self.stack:
            raise _error("PRESENTATION_HTML_INVALID", f"Presentation 标签未正确闭合: <{tag}>")
        while self.stack:
            current = self.stack.pop()
            if current == "details":
                self.details_depth = max(0, self.details_depth - 1)
            if current == "main":
                self.main_parts.append("</div>")
            elif self.main_depth and current != "style":
                self.main_parts.append(f"</{current}>")
            if current == "main":
                self.main_depth = 0
            if current == tag:
                break
        if tag == "style":
            self.current_style = False

    def handle_data(self, data: str) -> None:
        if FORBIDDEN_HTML_PATTERN.search(data):
            raise _error("PRESENTATION_CREDENTIAL_FORBIDDEN", "Presentation HTML 不能包含凭据或运行时标识")
        if self.current_style:
            self.style_parts.append(data)
        elif self.main_depth:
            self.main_parts.append(html_escape(data, quote=False))


def validate_panel_ids(panels: list[dict[str, Any]], *, require_mounts: bool = False) -> list[str]:
    ids: list[str] = []
    for index, panel in enumerate(panels):
        value = str(panel.get("id") or "").strip()
        if require_mounts and not value:
            raise _error("PRESENTATION_PANEL_ID_REQUIRED", f"panels[{index}] 在 Presentation Mode 必须提供 id")
        if value:
            if not ID_PATTERN.fullmatch(value):
                raise _error("PRESENTATION_PANEL_ID_INVALID", f"panels[{index}].id 只能使用字母开头的字母数字_.-")
            if value in ids:
                raise _error("PRESENTATION_PANEL_ID_DUPLICATE", f"panels[{index}].id 重复: {value}")
            ids.append(value)
    return ids


def load(task: str, presentation: Any, panels: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(presentation, dict):
        raise _error("PRESENTATION_INVALID", "presentation 必须是对象")
    if presentation.get("version") != VERSION:
        raise _error("PRESENTATION_VERSION_INVALID", "presentation.version 当前只支持 1")
    if presentation.get("mode") != "bespoke":
        raise _error("PRESENTATION_MODE_INVALID", "presentation.mode 当前只支持 bespoke")
    if presentation.get("design") not in (None, DESIGN):
        raise _error("PRESENTATION_DESIGN_INVALID", f"presentation.design 只支持 {DESIGN}")
    raw_file = presentation.get("html_file")
    if not isinstance(raw_file, str) or not raw_file.strip():
        raise _error("PRESENTATION_FILE_REQUIRED", "presentation.html_file 必填")
    root = CI.editable_root(task).resolve()
    path = Path(raw_file).expanduser().resolve()
    if not path.is_relative_to(root):
        raise _error("PRESENTATION_PATH_INVALID", "presentation 文件必须位于当前任务输出目录")
    if not path.is_file():
        raise _error("PRESENTATION_FILE_INVALID", "presentation 文件不存在")
    raw = path.read_text(encoding="utf-8")
    encoded = raw.encode("utf-8")
    if len(encoded) > MAX_PRESENTATION_BYTES:
        raise _error("PRESENTATION_TOO_LARGE", "presentation HTML 超过 1MB")
    if FORBIDDEN_HTML_PATTERN.search(raw):
        raise _error("PRESENTATION_CREDENTIAL_FORBIDDEN", "Presentation HTML 不能包含凭据或运行时标识")

    parser = _SafePresentationParser()
    try:
        parser.feed(raw)
        parser.close()
    except PresentationError:
        raise
    except Exception as exc:
        raise _error("PRESENTATION_HTML_INVALID", f"Presentation HTML 解析失败: {exc}") from exc
    if parser.stack:
        raise _error("PRESENTATION_HTML_INVALID", "Presentation HTML 存在未闭合标签")
    if parser.counts.get("main", 0) != 1:
        raise _error("PRESENTATION_MAIN_REQUIRED", "Presentation 必须且只能包含一个 main")
    if parser.counts.get("h1", 0) != 1 or parser.mount_h1_count:
        raise _error("PRESENTATION_TITLE_REQUIRED", "Presentation 必须包含一个不作为数据面板挂载点的 h1 作为页面主标题")
    if parser.summary_count <= parser.mount_summary_count:
        raise _error("PRESENTATION_SUMMARY_REQUIRED", "Presentation 需要位于数据面板挂载点外的 data-qb-summary 首屏结论节点")
    if parser.metric_count <= parser.mount_metric_count:
        raise _error("PRESENTATION_METRIC_REQUIRED", "Presentation 需要位于数据面板挂载点外的 data-qb-metric 核心指标节点")

    ids = validate_panel_ids(panels, require_mounts=True)
    mounts = parser.all_mounts
    if len(mounts) != len(set(mounts)):
        raise _error("PRESENTATION_MOUNT_DUPLICATE", "data-qb-panel 挂载点重复")
    missing = [panel_id for panel_id in ids if panel_id not in mounts]
    unknown = [mount for mount in mounts if mount not in ids]
    if missing or unknown:
        raise _error(
            "PRESENTATION_PANEL_MOUNT_MISMATCH", "每个 panel 必须有唯一 data-qb-panel 挂载点",
            missing_panels=missing, unknown_mounts=unknown,
        )
    if parser.ids and len(parser.ids) != len(set(parser.ids)):
        raise _error("PRESENTATION_ID_DUPLICATE", "Presentation id 重复")

    body = "".join(parser.main_parts)
    css = _safe_css("".join(parser.style_parts))
    return {
        "version": VERSION,
        "mode": "bespoke",
        "design": DESIGN,
        "file": str(path),
        "file_sha256": hashlib.sha256(encoded).hexdigest(),
        "body_html": body,
        "css": css,
        "mounts": copy.deepcopy(parser.mounts),
        "summary_present": parser.summary_count > parser.mount_summary_count,
        "metric_present": parser.metric_count > parser.mount_metric_count,
    }


def ensure_mount(task: str, presentation: Any, panel_id: str, title: str) -> dict[str, Any]:
    """Append a safe mount before the authored main closes (recovery only).

    The inserted node is inert and contains no executable content; the standard
    renderer still owns all data display inside it.
    """
    if not isinstance(presentation, dict):
        raise _error("PRESENTATION_INVALID", "presentation 必须是对象")
    raw_file = presentation.get("html_file")
    root = CI.editable_root(task).resolve()
    path = Path(str(raw_file or "")).expanduser().resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise _error("PRESENTATION_PATH_INVALID", "presentation 文件必须位于当前任务输出目录")
    if not ID_PATTERN.fullmatch(panel_id):
        raise _error("PRESENTATION_PANEL_ID_INVALID", "恢复挂载点id非法")
    raw = path.read_text(encoding="utf-8")
    marker = f'data-qb-panel="{panel_id}"'
    parser = _SafePresentationParser()
    parser.feed(raw)
    parser.close()
    if panel_id not in parser.all_mounts:
        close = raw.rfind("</main>")
        if close < 0:
            raise _error("PRESENTATION_MAIN_REQUIRED", "presentation 缺少 main")
        safe_title = html_escape(title or panel_id, quote=True)
        block = (f'<section class="qb-recovered-panel"><h3>{safe_title}</h3>'
                 f'<div {marker}></div></section>')
        raw = raw[:close] + block + raw[close:]
        path.write_text(raw, encoding="utf-8")
    return {**presentation, "html_file": str(path)}
