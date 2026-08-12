#!/usr/bin/env python3
"""Retrofit an already-generated page to the shared QuantBuddy shell.

Input is JSON via @file, RS_PARAMS, command JSON, or stdin:

{
  "html_file": "output/pages/old.html",
  "out_file": "output/pages/old-retrofit.html",
  "page_id": "page_xxx",
  "url": "https://pages.quantbuddy.cn/pages/.../page_xxx.html",
  "update": false,
  "theme": {
    "chrome_bg": "#101827",
    "accent": "#d8a54b",
    "line": "rgba(216,165,75,.35)"
  }
}

Use html_file for local files. Use page_id/url to download an already-published
page first. Set update=true to overwrite the same page_id after retrofit.
"""

import os
import re
import sys
import urllib.parse
import urllib.request

import common as C
import compile_bespoke_page as CB
import static_page as SP


DEFAULT_THEME = {
    "chrome_bg": "#101827",
    "accent": "#d8a54b",
    "line": "rgba(216,165,75,.35)",
}
MAX_PAGE_BYTES = 2 * 1024 * 1024


def _read(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read()


def _write(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _resolve(path):
    if os.path.isabs(path):
        return path
    return os.path.join(C.SKILL_ROOT, path)


def _css_value(value, fallback):
    value = str(value or fallback).strip()
    if re.fullmatch(r"#[0-9a-fA-F]{3,8}", value):
        return value
    if re.fullmatch(r"rgba?\([0-9.,% ]+\)", value):
        return value
    return fallback


def _theme_style(params):
    theme = params.get("theme") if isinstance(params.get("theme"), dict) else {}
    chrome_bg = _css_value(theme.get("chrome_bg") or theme.get("bg"), DEFAULT_THEME["chrome_bg"])
    header_bg = _css_value(theme.get("header_bg") or chrome_bg, chrome_bg)
    footer_bg = _css_value(theme.get("footer_bg") or chrome_bg, chrome_bg)
    accent = _css_value(theme.get("accent"), DEFAULT_THEME["accent"])
    line = _css_value(theme.get("line"), DEFAULT_THEME["line"])
    return f"""<style id="qb-shell-theme">
:root {{
  --qb-shell-chrome-bg: {chrome_bg};
  --qb-shell-header-bg: {header_bg};
  --qb-shell-footer-bg: {footer_bg};
  --qb-shell-accent: {accent};
  --qb-shell-accent-strong: {accent};
  --qb-shell-line: {line};
}}
</style>"""


def _replace_count(pattern, repl, html, flags=re.S):
    html2, count = re.subn(pattern, repl, html, count=1, flags=flags)
    return html2, count


def _sub_count(pattern, repl, html, flags=re.S, count=0):
    html2, replaced = re.subn(pattern, repl, html, count=count, flags=flags)
    return html2, replaced


def _inject_before(pattern, insertion, html):
    if insertion in html:
        return html, 0
    html2, count = re.subn(pattern, lambda _m: insertion + "\n" + _m.group(0), html, count=1)
    return html2, count


def _inject_after_body(insertion, html):
    if insertion in html:
        return html, 0
    html2, count = re.subn(
        r"<body\b[^>]*>",
        lambda m: m.group(0) + "\n" + insertion,
        html,
        count=1,
        flags=re.I,
    )
    return html2, count


def _hero_spacing_style():
    return """<style id="qb-retrofit-preserve-hero">
.share-card.qb-retrofit-qr-placeholder{visibility:hidden;min-height:171px;pointer-events:none}
</style>"""


def _page_id_from_url(url):
    parsed = urllib.parse.urlparse(str(url or ""))
    m = re.search(r"(page_[0-9a-zA-Z_]+)\.html?$", parsed.path)
    return m.group(1) if m else None


def _fetch_public_url(url):
    req = urllib.request.Request(str(url), method="GET")
    with C._NO_PROXY_OPENER.open(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


RETROFIT_JS = r"""
function qbRetrofitText(v) {
  return String(v == null ? '' : v);
}
function qbRetrofitOutput(panel) {
  const outputs = (BOOT && BOOT.outputs) || {};
  return outputs[panel.output] || null;
}
function qbRetrofitTable(out) {
  if (!out || out.error || !out.data) return {columns: [], rows: []};
  try {
    if (typeof normalize === 'function') return normalize(out.data);
  } catch (e) {}
  const data = out.data;
  if (Array.isArray(data.columns) && Array.isArray(data.rows)) return data;
  if (data.last_value) return {columns: ['date', 'value'], rows: [[data.last_value.date, data.last_value.value]]};
  if (data.range_data && Array.isArray(data.range_data.dates)) {
    return {columns: ['date', data.range_data.series_name || 'value'], rows: data.range_data.dates.map((d, i) => [d, (data.range_data.values || [])[i]])};
  }
  return {columns: [], rows: []};
}
function qbRetrofitFmt(v) {
  try {
    if (typeof fmt === 'function') return fmt(v);
  } catch (e) {}
  if (v == null || v === '') return '—';
  if (typeof v === 'number' && isFinite(v)) return Math.abs(v) >= 10000 ? v.toLocaleString(undefined, {maximumFractionDigits: 2}) : v.toLocaleString(undefined, {maximumFractionDigits: 4});
  return String(v);
}
function qbRetrofitLastValue(panel) {
  const out = qbRetrofitOutput(panel);
  const tab = qbRetrofitTable(out);
  if (!tab.rows.length) return '—';
  let value = null;
  if (panel.value_field && typeof colIdx === 'function' && typeof lastRealNumber === 'function') {
    const ci = colIdx(tab, panel.value_field);
    value = lastRealNumber(tab, ci);
  }
  if (value == null) {
    for (let c = tab.columns.length - 1; c >= 0; c--) {
      for (let r = tab.rows.length - 1; r >= 0; r--) {
        const v = tab.rows[r][c];
        if (typeof v === 'number' && isFinite(v)) { value = v; break; }
      }
      if (value != null) break;
    }
  }
  return value == null ? '—' : qbRetrofitFmt(value) + (panel.unit ? ' ' + panel.unit : '');
}
function qbRetrofitPanelItems(panel) {
  const tab = qbRetrofitTable(qbRetrofitOutput(panel));
  return tab.rows.slice(-6).reverse().map(row => ({
    label: qbRetrofitText(row[0] == null ? (panel.title || panel.output || '指标') : row[0]),
    value: qbRetrofitFmt(row.length > 1 ? row[row.length - 1] : row[0])
  }));
}
function qbRetrofitSummary() {
  const textPanel = ((BOOT && BOOT.panels) || []).find(p => (p.type || '').toLowerCase() === 'text');
  return (textPanel && (textPanel.text || textPanel.content || textPanel.description)) || 'QuantBuddy 实时数据页面，打开页面查看完整内容。';
}
function qbRetrofitPosterData() {
  const panels = (BOOT && BOOT.panels) || [];
  let metrics = panels
    .filter(p => (p.type || '').toLowerCase() === 'number')
    .slice(0, 8)
    .map(p => ({label: p.title || p.output || '指标', value: qbRetrofitLastValue(p), sub: p.description || p.output || ''}));
  if (!metrics.length) {
    metrics = panels.slice(0, 6).map(p => ({label: p.title || p.output || '指标', value: qbRetrofitLastValue(p), sub: p.output || ''}));
  }
  const sections = panels
    .filter(p => !['number', 'text'].includes((p.type || '').toLowerCase()))
    .slice(0, 3)
    .map(p => ({title: p.title || p.output || '数据区', type: 'list', summary: p.description || '', items: qbRetrofitPanelItems(p), height: 176}));
  return {
    headline: document.title || 'QuantBuddy 页面',
    summary: qbRetrofitSummary(),
    metrics,
    sections,
    asof: (BOOT && BOOT.generatedAt) || ''
  };
}
async function qbRetrofitRefresh() {
  if (BOOT && BOOT.mode === 'live' && BOOT.endpoint && BOOT.packageId && BOOT.signature && typeof fetchLive === 'function') {
    return fetchLive();
  }
  if (typeof renderAll === 'function') renderAll((BOOT && BOOT.outputs) || {});
}
function qbRetrofitInitShell() {
  if (!window.QBShareShell) return;
  QBShareShell.init({
    templateName: document.title || '标准实时看板',
    title: () => document.title || 'QuantBuddy 页面',
    subtitle: () => qbRetrofitSummary(),
    asof: () => (BOOT && BOOT.generatedAt) || '',
    onRefresh: qbRetrofitRefresh,
    getPosterData: qbRetrofitPosterData
  });
}
"""


def _install_shell_placeholders(html, params):
    changes = {}
    preserve_hero = not params.get("remove_legacy_hero")

    if preserve_hero:
        changes["old_header"] = 0
    else:
        html, changes["old_header"] = _replace_count(
            r"<header\b[^>]*class=[\"'][^\"']*\bshare-shell\b[^\"']*[\"'][^>]*>.*?</header>",
            "",
            html,
        )
    share_card_repl = ""
    if preserve_hero and not params.get("collapse_qr_space"):
        share_card_repl = '<aside class="share-card qb-retrofit-qr-placeholder" aria-hidden="true"></aside>'
    html, changes["old_share_card"] = _replace_count(
        r"\s*<aside\b[^>]*class=[\"'][^\"']*\bshare-card\b[^\"']*[\"'][^>]*>.*?</aside>",
        share_card_repl,
        html,
    )
    html, changes["old_share_qr_node"] = _sub_count(
        r"\s*<[^>]+id=[\"']shareQrCanvas[\"'][^>]*>.*?</[^>]+>",
        "",
        html,
        flags=re.S | re.I,
        count=1,
    )
    html, changes["old_footer"] = _replace_count(
        r"<footer\b[^>]*class=[\"'][^\"']*\bsite-footer\b[^\"']*[\"'][^>]*>.*?</footer>",
        "",
        html,
    )
    html, changes["qrcode_cdn"] = _sub_count(
        r"\s*<script\b[^>]*src=[\"'][^\"']*(?:qrcode|QRCode)[^\"']*[\"'][^>]*>\s*</script>",
        "",
        html,
        flags=re.I,
    )

    html, changes["setup_share_shell"] = _replace_count(
        r"\nfunction setupShareShell\(\) \{.*?\n\}\n\n(?=document\.addEventListener\('DOMContentLoaded')",
        "\n",
        html,
    )
    html, changes["setup_share_shell_calls"] = _sub_count(
        r"\s*setupShareShell\(\);\s*",
        "\n",
        html,
        flags=re.I,
    )

    html, changes["head_css"] = _inject_before("</head>", "<!-- QB_SHARED_SHELL_CSS -->\n" + _theme_style(params), html)
    if share_card_repl:
        html, changes["hero_spacing_css"] = _inject_before("</head>", _hero_spacing_style(), html)
    else:
        changes["hero_spacing_css"] = 0
    if "<!-- QB_SHARED_SHELL_HEADER -->" not in html:
        html, changes["header_inserted"] = _inject_after_body("<!-- QB_SHARED_SHELL_HEADER -->", html)
    else:
        changes["header_inserted"] = 0
    if "<!-- QB_SHARED_SHELL_FOOTER -->" not in html:
        html, changes["footer_inserted"] = _inject_before("</body>", "<!-- QB_SHARED_SHELL_FOOTER -->", html)
    else:
        changes["footer_inserted"] = 0
    html, changes["modal"] = _inject_before("</body>", "<!-- QB_SHARED_SHELL_MODAL -->", html)
    html, changes["qr_mini"] = _inject_before("</body>", "<!-- QB_SHARED_QR_MINI -->", html)
    html, changes["shared_js"] = _inject_before("</body>", "<!-- QB_SHARED_SHELL_JS -->", html)

    dom_re = re.compile(
        r"document\.addEventListener\('DOMContentLoaded',\s*\(\)\s*=>\s*\{\s*"
        r"(?:setupShareShell\(\);\s*)?"
        r"if \(BOOT\.mode === 'live'\) fetchLive\(\);\s*"
        r"else renderAll\(BOOT\.outputs\);\s*"
        r"\}\);",
        flags=re.S,
    )
    new_dom = RETROFIT_JS + """
document.addEventListener('DOMContentLoaded', () => {
  qbRetrofitInitShell();
  if (BOOT.mode === 'live') fetchLive();
  else renderAll(BOOT.outputs);
});
"""
    html, changes["dom_ready"] = dom_re.subn(new_dom, html, count=1)
    return html, changes


def _source_html(params):
    if params.get("html_file"):
        return _read(_resolve(params["html_file"])), {"source": "html_file"}
    if params.get("html"):
        return str(params["html"]), {"source": "html"}
    if params.get("url") and not params.get("download_via_api"):
        url = params["url"]
        return _fetch_public_url(url), {"source": "url", "page_id": _page_id_from_url(url), "url": url}
    if params.get("page_id") or params.get("url"):
        dl = SP.cmd_download({"page_id": params.get("page_id"), "url": params.get("url")})
        if not (isinstance(dl, dict) and dl.get("code") == 0 and dl.get("html")):
            raise ValueError("download failed: " + str(dl))
        return dl["html"], {"source": "download", "page_id": dl.get("page_id"), "url": dl.get("url")}
    raise ValueError("missing html_file/html/page_id/url")


def _check(html, params=None):
    params = params or {}
    problems = []
    legacy_tokens = ["手机扫码查看", "shareQrCanvas", "setupShareShell", "<footer class=\"site-footer\""]
    if params.get("remove_legacy_hero"):
        legacy_tokens.append("<header class=\"share-shell\"")
    for token in legacy_tokens:
        if token in html:
            problems.append(f"legacy residue: {token}")
    if "QB_SHARED_" in html or "__QB_LOGO_SRC__" in html:
        problems.append("shared shell placeholder residue")
    if re.search(r"<script\s+src=[\"'][^\"']*(?:qrcode|QRCode)[^\"']*[\"']", html, flags=re.I):
        problems.append("legacy qrcode script residue")
    size = len(html.encode("utf-8"))
    if size > MAX_PAGE_BYTES:
        problems.append(f"page exceeds 2MB: {size} bytes")
    return problems, size


def cmd_retrofit(params):
    html, meta = _source_html(params)
    working, changes = _install_shell_placeholders(html, params)
    compiled = CB._compile(working, {"inline_qr_mini": True, "inline_data_kernel": False})
    problems, size = _check(compiled, params)
    if problems and not params.get("allow_warnings"):
        return {"code": 1, "message": "retrofit check failed", "problems": problems, "changes": changes, **meta}

    out_file = params.get("out_file")
    if out_file:
        out_path = _resolve(out_file)
    elif meta.get("page_id"):
        out_path = os.path.join(C.SKILL_ROOT, "output", "pages", meta["page_id"] + "-retrofit.html")
    else:
        out_path = os.path.join(C.SKILL_ROOT, "output", "pages", "retrofit-share-shell.html")
    _write(out_path, compiled)

    result = {
        "code": 0,
        "out_file": out_path,
        "size": size,
        "warnings": problems,
        "changes": changes,
        **meta,
    }

    page_id = params.get("page_id") or meta.get("page_id")
    if params.get("update"):
        if not page_id:
            return {**result, "code": 1, "message": "update=true requires page_id"}
        update_params = {"page_id": page_id, "html": compiled}
        for k in ("title", "description", "ttl_days"):
            if params.get(k) is not None:
                update_params[k] = params[k]
        update = SP.cmd_update(update_params)
        result["update"] = update
        if not (isinstance(update, dict) and update.get("code") == 0):
            result["code"] = 1
            result["message"] = "static_page update failed"
    return result


def main():
    params = C.read_params(sys.argv[1:], env_var="RS_PARAMS")
    try:
        result = cmd_retrofit(params)
    except Exception as e:
        result = {"code": 1, "message": str(e)}
    C.emit(result, out_name="retrofit_share_shell_out.txt")
    sys.exit(0 if result.get("code") == 0 else 1)


if __name__ == "__main__":
    main()
