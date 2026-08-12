#!/usr/bin/env python3
r"""
Progress-page HTML generator for quant-buddy-view first-link workflows.

The generated page is an inert iframe-friendly snapshot. It must not poll,
refresh itself, navigate, or talk to the parent page. The hosting product is
responsible for refreshing the iframe URL while the agent updates this page's
HTML through static_page.update.
"""

import html
import json
from datetime import datetime


STEP_STATUSES = {"pending", "running", "waiting", "done", "failed"}
PAGE_STATUSES = {"running", "waiting_input", "done", "failed"}

DEFAULT_STEPS = [
    {"id": "init", "title": "初始化活页链接", "status": "done"},
    {"id": "plan", "title": "确认活页方案", "status": "pending"},
    {"id": "template", "title": "选择活页样式", "status": "pending"},
    {"id": "formula_validation", "title": "验证实时数据", "status": "pending"},
    {"id": "package_register", "title": "准备实时数据", "status": "pending"},
    {"id": "html_build", "title": "生成活页内容", "status": "pending"},
    {"id": "verify", "title": "检查活页效果", "status": "pending"},
    {"id": "final_publish", "title": "完成活页生成", "status": "pending"},
]

PUBLIC_TEXT_REPLACEMENTS = [
    ("页面 HTML 已生成", "活页内容已生成"),
    ("正在做本地桌面与移动端浏览器验收", "正在检查不同屏幕上的展示效果"),
    ("页面 HTML", "活页内容"),
    ("最终 HTML", "活页内容"),
    ("HTML", "内容"),
    ("实时取数公式", "实时数据"),
    ("验证贵州茅台实时公式", "验证贵州茅台实时数据"),
    ("实时公式", "实时数据"),
    ("公式验证", "实时数据验证"),
    ("官方精选模板", "官方精选活页"),
    ("个股估值体检模板", "个股估值体检活页"),
    ("模板", "活页"),
    ("页面", "活页"),
    ("本地桌面与移动端浏览器验收", "检查不同屏幕上的展示效果"),
    ("桌面与移动端浏览器验收", "检查不同屏幕上的展示效果"),
    ("本地浏览器验收", "检查展示效果"),
    ("浏览器验收", "检查展示效果"),
    ("注册当前用户自己的公式包", "准备实时数据"),
    ("注册公式包", "准备实时数据"),
    ("公式包", "实时数据"),
    ("page_id", "链接"),
    ("URL", "链接"),
    ("iframe", "嵌入页"),
    ("外层系统", "页面容器"),
    ("外层网站", "页面容器"),
    ("覆盖", "更新"),
]


def _as_text(value, default=""):
    if value is None:
        return default
    return str(value)


def _friendly_text(value, default=""):
    text = _as_text(value, default)
    for old, new in PUBLIC_TEXT_REPLACEMENTS:
        text = text.replace(old, new)
    return text


def _safe_status(value, allowed, default):
    value = _as_text(value, default).strip().lower()
    return value if value in allowed else default


def _format_updated_at(value=None):
    raw = _as_text(value, "").strip()
    if not raw:
        return datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone()
        return parsed.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        pass
    if "T" in raw:
        raw = raw.replace("T", " ")
    if len(raw) >= 16:
        return raw[:16]
    return raw


def _step_id(step, index):
    raw = step.get("id") if isinstance(step, dict) else None
    raw = _as_text(raw, "").strip()
    return raw or "step_%02d" % (index + 1)


def _step_title(step, fallback):
    if isinstance(step, dict):
        return _friendly_text(step.get("title") or step.get("name") or fallback, fallback)
    return _friendly_text(step, fallback)


def _apply_linear_progression(steps, current_id, page_status):
    if not steps:
        return steps
    current_index = next((i for i, step in enumerate(steps) if step["id"] == current_id), None)
    if current_index is None:
        current_index = 0

    failed_index = next((i for i, step in enumerate(steps) if step["status"] == "failed"), None)
    if page_status == "failed":
        fail_at = failed_index if failed_index is not None else current_index
        for index, step in enumerate(steps):
            if index < fail_at:
                step["status"] = "done"
            elif index == fail_at:
                step["status"] = "failed"
            else:
                step["status"] = "pending"
        return steps

    if page_status == "done":
        for step in steps:
            if step["status"] != "failed":
                step["status"] = "done"
        return steps

    if page_status == "waiting_input":
        for index, step in enumerate(steps):
            if index < current_index:
                step["status"] = "done"
            elif index == current_index:
                step["status"] = "waiting"
            else:
                step["status"] = "pending"
        return steps

    for index, step in enumerate(steps):
        if index < current_index:
            step["status"] = "done"
        elif index == current_index:
            step["status"] = "running"
        else:
            step["status"] = "pending"
    return steps


def normalize_steps(steps=None, current_step=None, page_status="running"):
    source = steps if isinstance(steps, list) and steps else DEFAULT_STEPS
    normalized = []
    current_id = _as_text(current_step, "").strip()
    found_current = False

    for index, step in enumerate(source):
        if isinstance(step, dict):
            source_step = step
        else:
            source_step = {"title": step}
        sid = _step_id(source_step, index)
        status = _safe_status(source_step.get("status"), STEP_STATUSES, "pending")
        if current_id and sid == current_id:
            found_current = True
        normalized.append({
            "id": sid,
            "title": _step_title(source_step, sid),
            "status": status,
            "message": _friendly_text(source_step.get("message"), "") if isinstance(source_step, dict) else "",
        })

    if current_id and not found_current:
        normalized.append({
            "id": current_id,
            "title": _friendly_text(current_id),
            "status": "pending",
            "message": "",
        })

    return _apply_linear_progression(normalized, current_id or normalized[0]["id"], page_status)


def build_state(params):
    params = params or {}
    page_status = _safe_status(params.get("page_status"), PAGE_STATUSES, "running")
    current_step = _as_text(params.get("current_step") or "plan", "plan").strip()
    updated_at = _format_updated_at(params.get("updated_at"))
    steps = normalize_steps(params.get("steps"), current_step=current_step, page_status=page_status)
    current = next((step for step in steps if step["id"] == current_step), None)
    if not current:
        current = next((step for step in steps if step["status"] == "running"), None)
    if not current and steps:
        current = steps[-1] if page_status in ("done", "failed") else steps[0]

    return {
        "title": _friendly_text(params.get("title") or "活页生成中", "活页生成中"),
        "message": _friendly_text(params.get("message") or "正在生成可分享活页，请稍后查看。", ""),
        "page_status": page_status,
        "current_step": current["id"] if current else current_step,
        "current_step_title": current["title"] if current else current_step,
        "updated_at": updated_at,
        "steps": steps,
        "required_input": (
            params.get("required_input")
            if page_status == "waiting_input" and isinstance(params.get("required_input"), dict)
            else None
        ),
    }


def render_progress_html(params=None):
    state = build_state(params or {})
    title = html.escape(state["title"])
    message = html.escape(state["message"])
    current_title = html.escape(state["current_step_title"])
    updated_at = html.escape(state["updated_at"])
    page_status = html.escape(state["page_status"])
    state_json = _script_json(state)
    required_input = state.get("required_input") if isinstance(state.get("required_input"), dict) else None
    required_input_panel = ""
    if state["page_status"] == "waiting_input" and required_input:
        option_items = []
        for option in required_input.get("options") or []:
            if not isinstance(option, dict):
                continue
            label = html.escape(_as_text(option.get("label") or option.get("value"), "").strip())
            if label:
                option_items.append('<span class="required-input-option">%s</span>' % label)
        required_input_panel = (
            '<section class="required-input-panel" aria-label="等待用户确认">'
            '<strong>等待用户确认</strong>'
            '<p>{prompt}</p>{options}'
            '<small>请回到对话中确认；收到回复后，这个链接会从当前阶段继续更新。</small>'
            '</section>'
        ).format(
            prompt=html.escape(_as_text(required_input.get("prompt"), "")),
            options=(
                '<div class="required-input-options">%s</div>' % "".join(option_items)
                if option_items else ""
            ),
        )

    step_items = []
    for index, step in enumerate(state["steps"], start=1):
        sid = html.escape(step["id"])
        step_title = html.escape(step["title"])
        status = html.escape(step["status"])
        step_message = html.escape(step.get("message") or "")
        marker = _status_marker(step["status"], index)
        step_items.append(
            '<li class="qb-progress-step step-{status}" data-step-id="{sid}" data-step-status="{status}">'
            '<span class="step-node">{marker}</span>'
            '<span class="step-body"><span class="step-title">{title}</span>'
            '<span class="step-status">{status_text}</span>{message}</span>'
            "</li>".format(
                status=status,
                sid=sid,
                marker=marker,
                title=step_title,
                status_text=_status_label(step["status"]),
                message=('<span class="step-message">%s</span>' % step_message) if step_message else "",
            )
        )

    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f9f9ff;
      --panel: #ffffff;
      --panel-low: #f0f3ff;
      --panel-soft: #fff7ed;
      --ink: #111c2d;
      --primary: #172033;
      --muted: #45474c;
      --dim: #76777d;
      --line: #d9e0ea;
      --accent: #8f4e00;
      --accent-soft: #fe9c3c;
      --accent-wash: rgba(254, 156, 60, 0.09);
      --done: #198754;
      --failed: #c0352b;
      --pending: #8a9099;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; min-height: 100%; background: var(--bg); color: var(--ink); font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; }}
    body {{ overflow-x: hidden; }}
    .qb-progress-page {{ width: min(820px, calc(100% - 24px)); margin: 0 auto; padding: 28px 0 36px; }}
    .page-kicker {{ margin: 0 0 8px; color: var(--muted); font-size: 13px; line-height: 1.4; font-weight: 650; display: flex; align-items: center; gap: 7px; }}
    .page-kicker::before {{ content: ""; width: 7px; height: 7px; border-radius: 999px; background: var(--accent-soft); display: inline-block; }}
    h1 {{ margin: 0; color: var(--primary); font-size: clamp(24px, 4.8vw, 34px); line-height: 1.18; letter-spacing: 0; font-weight: 760; }}
    .summary {{ margin: 14px 0 0; color: var(--muted); max-width: 660px; font-size: 15px; line-height: 1.7; }}
    .current {{ margin: 22px 0 0; padding: 16px 18px; border-left: 4px solid var(--accent-soft); border-radius: 0 8px 8px 0; background: var(--panel-low); box-shadow: 0 8px 24px rgba(23, 32, 51, 0.05); }}
    .current-head {{ display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 6px; }}
    .current strong {{ color: var(--accent); font-size: 12px; line-height: 1.4; letter-spacing: .05em; text-transform: uppercase; }}
    .current .state-pill {{ color: var(--accent); font-size: 13px; font-weight: 700; white-space: nowrap; }}
    .current-title {{ display: block; color: var(--primary); font-size: 19px; line-height: 1.4; font-weight: 720; }}
    .required-input-panel {{ margin: 14px 0 0; padding: 16px 18px; border: 1px solid rgba(143, 78, 0, .28); border-radius: 8px; background: var(--panel-soft); }}
    .required-input-panel strong {{ color: var(--accent); font-size: 14px; }}
    .required-input-panel p {{ margin: 6px 0 0; color: var(--primary); font-size: 16px; line-height: 1.55; font-weight: 700; }}
    .required-input-panel small {{ display: block; margin-top: 10px; color: var(--muted); line-height: 1.55; }}
    .required-input-options {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }}
    .required-input-option {{ display: inline-flex; align-items: center; min-height: 30px; padding: 5px 12px; border: 1px solid rgba(143, 78, 0, .28); border-radius: 999px; background: #fff; color: var(--accent); font-size: 13px; font-weight: 700; }}
    .progress-shell {{ margin-top: 22px; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: clamp(18px, 4vw, 28px); box-shadow: 0 16px 40px rgba(23, 32, 51, 0.08); position: relative; overflow: hidden; }}
    .timeline {{ list-style: none; margin: 0; padding: 0; }}
    .qb-progress-step {{ min-height: 58px; display: grid; grid-template-columns: 42px 1fr; gap: 14px; align-items: start; position: relative; padding: 0 0 18px; }}
    .qb-progress-step:not(:last-child)::before {{ content: ""; position: absolute; left: 20px; top: 42px; bottom: 0; width: 2px; background: var(--line); }}
    .step-node {{ width: 42px; height: 42px; border-radius: 999px; display: inline-grid; place-items: center; color: #fff; background: var(--pending); border: 4px solid var(--panel); font-size: 14px; font-weight: 800; position: relative; z-index: 1; }}
    .step-body {{ min-width: 0; display: block; padding: 4px 0 0; }}
    .step-title {{ display: block; color: var(--primary); font-size: 16px; line-height: 1.45; font-weight: 700; }}
    .step-status {{ display: inline-block; margin-top: 4px; color: var(--muted); font-size: 13px; line-height: 1.4; font-weight: 600; }}
    .step-message {{ display: block; margin-top: 4px; color: var(--muted); font-size: 13px; line-height: 1.55; }}
    .step-pending {{ opacity: .56; }}
    .step-running .step-body {{ background: var(--accent-wash); border: 1px solid rgba(143, 78, 0, .2); border-radius: 8px; padding: 10px 12px; }}
    .step-running .step-node {{ background: var(--accent); box-shadow: 0 0 0 8px rgba(254, 156, 60, .16); }}
    .step-running .step-status {{ color: var(--accent); }}
    .step-waiting .step-body {{ background: var(--panel-soft); border: 1px solid rgba(143, 78, 0, .28); border-radius: 8px; padding: 10px 12px; }}
    .step-waiting .step-node {{ background: var(--accent-soft); color: var(--primary); box-shadow: 0 0 0 8px rgba(254, 156, 60, .13); }}
    .step-waiting .step-status {{ color: var(--accent); }}
    .step-done .step-node {{ background: var(--done); }}
    .step-failed .step-node {{ background: var(--failed); box-shadow: 0 0 0 8px rgba(192, 53, 43, .12); }}
    .step-failed .step-body {{ background: #fff6f5; border: 1px solid #f2b8b5; border-radius: 8px; padding: 10px 12px; }}
    .progress-footer {{ margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--line); display: flex; justify-content: space-between; gap: 14px; flex-wrap: wrap; color: var(--muted); font-size: 12px; line-height: 1.6; }}
    .snapshot-note {{ color: var(--dim); }}
    body.qb-progress-document #refresh {{ display: none !important; }}
    @media (max-width: 560px) {{
      .qb-progress-page {{ width: min(100% - 24px, 820px); padding: 20px 0 28px; }}
      .current-head {{ align-items: flex-start; flex-direction: column; gap: 4px; }}
      .progress-shell {{ padding: 16px; }}
      .qb-progress-step {{ grid-template-columns: 38px 1fr; gap: 12px; }}
      .step-node {{ width: 38px; height: 38px; }}
      .qb-progress-step:not(:last-child)::before {{ left: 18px; top: 38px; }}
    }}
  </style>
</head>
<body class="qb-progress-document">
  <main class="qb-progress-page" data-qb-progress-page data-page-status="{page_status}">
    <header>
      <p class="page-kicker">Quant Buddy 活页生成进度</p>
      <h1>{title}</h1>
      <p class="summary">{message}</p>
      <div class="current">
        <div class="current-head">
          <strong>当前阶段</strong>
          <span class="state-pill">{page_status_label}</span>
        </div>
        <span class="current-title">{current_title}</span>
      </div>
      {required_input_panel}
    </header>
    <section class="progress-shell" aria-label="活页生成步骤">
      <ol class="timeline">
        {steps}
      </ol>
      <div class="progress-footer">
        <span>更新时间：{updated_at}</span>
        <span class="snapshot-note">活页生成期间会持续更新，完成后将显示正式活页。</span>
      </div>
    </section>
    <script type="application/json" id="qb-progress-state">{state_json}</script>
  </main>
</body>
</html>""".format(
        title=title,
        message=message,
        current_title=current_title,
        required_input_panel=required_input_panel,
        page_status_label=_page_status_label(state["page_status"]),
        updated_at=updated_at,
        page_status=page_status,
        steps="\n        ".join(step_items),
        state_json=state_json,
    )


def _status_label(status):
    return {
        "pending": "待开始",
        "running": "进行中",
        "waiting": "等待确认",
        "done": "已完成",
        "failed": "失败",
    }.get(status, status)


def _page_status_label(status):
    return {
        "running": "处理中",
        "waiting_input": "等待用户确认",
        "done": "已完成",
        "failed": "处理失败",
    }.get(status, status)


def _status_marker(status, index):
    if status == "done":
        return "✓"
    if status == "running":
        return "↻"
    if status == "waiting":
        return "?"
    if status == "failed":
        return "!"
    return str(index)


def _script_json(value):
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
