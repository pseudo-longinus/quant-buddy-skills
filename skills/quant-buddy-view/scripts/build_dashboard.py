#!/usr/bin/env python3
r"""
看板生成器 —— 把「公式任务包 + 看板 spec」编译成一份自包含 HTML，可直接上传托管。

工具说明文档：tools/build_dashboard.md

输入一个 spec（描述标题 + 若干面板，每个面板把某个公式包产出渲染成 折线/柱/表格/数值），
输出一份 live 实时取数 HTML（样式内联，图表库引公网 CDN ECharts）。

  实时取数：HTML 内嵌 package_id + signature，打开时即时调用 queryFormulaPackage
            拉取最新数据并渲染，底层数据更新即自动重算，页面打开就是最新。
            构建期会先取一次数做质量体检（数据健康 + 单标的文案一致性），但不内联进 HTML，
            页面仍走浏览器实时取数。spec 不需要写 mode 字段。
  前提：① queryFormulaPackage 端点须对页面域名放开 CORS（当前 https 端点已满足）；
        ② signature 会随页面公开（公式包 query 本就以 signature 作能力令牌、设计上允许嵌入页面）。

参数（优先级：BD_PARAMS 环境变量 > @file > 命令行 JSON > stdin）：
    {
      "title":      "看板标题（必填，用于 <title> 与页头）",
      "subtitle":   "可选副标题",
      "description": "可选页面说明（≤1000 字，仅用于 static_page 列表/详情展示；显式传才透传给 upload/update，不传则不动）",
      "package_id": "公式包 id（缺省从最近一次本地凭证推断）",
      "signature":  "必需（缺省从本地凭证补全），写入页面供实时取数",
      "panels": [
        {
          "title":  "面板标题",
          "output": "对应公式包 reads 的产出名（= query 返回 outputs 的 key）；数据授权面板改填 grant_id",
          "grant_id": "数据授权面板：dg_... （与 output 互斥，构建期自动补 signature、运行时走 queryDataGrant），可与公式包面板同页混用",
          "type":   "line | bar | table | number | text | raw（默认 table）",
          "x":      "line/bar 横轴字段名（数据为对象数组时）",
          "y":      ["line/bar 纵轴字段名，可多条"],
          "value_field": "number 取值字段（缺省取首个数值）",
          "unit":   "number 单位（可选）",
          "description": "面板说明（可选）",
          "span":   "full | wide | auto（可选，默认按类型决定）",
          "text":   "text 面板正文（可选）"
        }
      ],
      "out_file":   "可选，输出 HTML 路径（默认 output/pages/<slug>.html）",
      "upload":     "可选 true，则生成后顺带调用 static_page 上传，返回公开 url",
      "update_page_id": "可选 page_xxx，则替换该已发布页面的内容（URL/page_id 不变），优先于新上传",
      "brand":      "可选对象：name/cn_name/tagline/homepage/page_type/footer_note",
      "official_url": "可选，默认 https://www.quantbuddy.cn"
    }

用法示例：
    python scripts/build_dashboard.py @spec.json
    BD_PARAMS='{"title":"...","panels":[...],"upload":true}' python scripts/build_dashboard.py

输出：打印 {code, out_file, ...(upload 时含 url)}，并写一份到临时目录 bd_out.txt。

局部产出模式（emit=panel_block）：不生成整页 HTML，只生成 marker 包住的运行时 <script> 片段，
供 bespoke（手写）页面把某几个图表交给标准声明式引擎画——panel 里加 target_selector 指向 bespoke
布局里已经摆好的容器，图表直接渲染进那个容器，不包卡片外壳。生成的片段仍带
QBV_RENDER_JS_START/END marker，chart_edit.py 之后能对这些嵌入的图表做定点编辑。用法：
    python scripts/build_dashboard.py '{"emit":"panel_block","panels":[...]}'
详见 cmd_panel_block 函数文档与 guides/bespoke-page.md。
"""

import datetime
import hashlib
from html import escape as html_escape
import json
import math
import os
import pathlib
import re
import sys
import uuid
from urllib.parse import quote

import common as C
import formula_package as FP
import data_grant as DG
import fast_query_csv as FQCSV
import live_card as LC
import data_kernel_retrofit as DKR

PAGES_DIR = os.path.join(C.SKILL_ROOT, "output", "pages")
ASSETS_DIR = os.path.join(C.SKILL_ROOT, "assets")
SHARED_SHELL_DIR = os.path.join(C.SKILL_ROOT, "assets", "share-shell")

_ECHARTS_CDN = "https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"
_DEFAULT_OFFICIAL_URL = "https://www.quantbuddy.cn"
_DEFAULT_LOGO_PATH = os.path.join(ASSETS_DIR, "logo.svg")
_MAX_INLINE_LOGO_BYTES = 1_300_000


def _slug(title):
    s = re.sub(r"[^0-9A-Za-z一-鿿]+", "-", (title or "dashboard")).strip("-")
    return (s or "dashboard")[:40] + "-" + uuid.uuid4().hex[:8]


def _resolve_credential(params):
    """解析 package_id + signature：params 优先，其次本地凭证。返回 (pkg, sig, err)。"""
    pkg = params.get("package_id")
    sig = params.get("signature")
    if pkg and sig:
        return pkg, sig, None
    if pkg and not sig:
        cred = FP.load_credential(pkg)
        if cred:
            return pkg, cred.get("signature"), None
        return pkg, None, None  # signature 缺失，live 模式后续会报错
    # 未给 package_id：尝试取最近一次落盘的凭证
    cred_dir = os.path.join(C.SKILL_ROOT, "output", "formula_packages")
    if os.path.isdir(cred_dir):
        files = [os.path.join(cred_dir, f) for f in os.listdir(cred_dir) if f.endswith(".json")]
        if files:
            latest = max(files, key=os.path.getmtime)
            try:
                with open(latest, "r", encoding="utf-8") as f:
                    cred = json.load(f)
                return cred.get("package_id"), cred.get("signature"), None
            except Exception:
                pass
    return None, None, {"code": 1, "message": "未能确定 package_id：请在 spec 里指定，或先 register 落一份本地凭证"}


def _resolve_grant_panels(panels):
    """扫描 panels 找 grant_id 引用（与公式包 output 面板并存）：signature 缺省用本地凭证补全，
    并把 panel.output 归一成 grant_id、打 _source 标记，使下游校验/渲染管线无需区分来源。
    返回 (grants:[{grant_id,signature}] 去重, err|None)。"""
    seen = {}
    grants = []
    for p in panels:
        if not isinstance(p, dict):
            continue
        gid = p.get("grant_id")
        if not gid:
            continue
        p["_source"] = "grant"
        if not p.get("output"):
            p["output"] = gid
        if gid in seen:
            continue
        sig = p.get("signature")
        if not sig:
            cred = DG.load_credential(gid)
            sig = cred.get("signature") if cred else None
        if not sig:
            return None, {"code": 1, "message": f"grant_id={gid} 缺 signature（可在 panel 里指定，或先 register/query 落一份本地凭证 output/data_grants/{gid}.json）"}
        seen[gid] = sig
        grants.append({"grant_id": gid, "signature": sig})
    return grants, None


def _as_bool(value, default=True):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "no", "off", "否", "关闭")
    return bool(value)


def _share_config(spec):
    brand = spec.get("brand") if isinstance(spec.get("brand"), dict) else {}
    official_url = (
        spec.get("official_url")
        or brand.get("official_url")
        or brand.get("homepage")
        or _DEFAULT_OFFICIAL_URL
    )
    return {
        "brand_name": brand.get("name") or spec.get("brand_name") or "QuantBuddy",
        "brand_cn": brand.get("cn_name") or spec.get("brand_cn") or "观照量化",
        "tagline": brand.get("tagline") or spec.get("brand_tagline") or "Agent 调用 Skill 计算 · HTML 可调",
        "page_type": spec.get("page_type") or brand.get("page_type") or "量化看板",
        "official_url": official_url,
        "official_label": spec.get("official_label") or brand.get("official_label") or "问一问",
        "show_qr": _as_bool(spec.get("show_qr", brand.get("show_qr")), True),
        "share_url": spec.get("share_url") or brand.get("share_url") or "",
        "share_title": spec.get("share_title") or brand.get("share_title") or "分享海报",
        "footer_note": spec.get("footer_note") or brand.get("footer_note") or "页面仅作市场观察与数据展示，不构成投资建议。",
    }


def _brand_logo_html():
    if not os.path.exists(_DEFAULT_LOGO_PATH):
        return "QB"
    try:
        if os.path.getsize(_DEFAULT_LOGO_PATH) > _MAX_INLINE_LOGO_BYTES:
            return "QB"
        with open(_DEFAULT_LOGO_PATH, "r", encoding="utf-8") as f:
            svg = f.read()
    except Exception:
        return "QB"

    if re.search(r"<\s*(script|foreignObject)\b|on\w+\s*=|(?:xlink:)?href\s*=|<\s*(image|use)\b", svg, re.I):
        return "QB"

    svg = re.sub(r"^\s*<\?xml[^>]*>\s*", "", svg, flags=re.I)
    svg = re.sub(r"<!doctype[^>]*>\s*", "", svg, flags=re.I)
    svg = re.sub(r"<!--.*?-->", "", svg, flags=re.S)
    svg = svg.strip()
    if not svg.lower().startswith("<svg"):
        return "QB"

    svg_open = re.search(r"<svg\b[^>]*>", svg, re.I)
    if svg_open and not re.search(r"\bviewBox\s*=", svg_open.group(0), re.I):
        width_match = re.search(r'\bwidth\s*=\s*["\']([0-9.]+)', svg_open.group(0), re.I)
        height_match = re.search(r'\bheight\s*=\s*["\']([0-9.]+)', svg_open.group(0), re.I)
        if width_match and height_match:
            view_box = f' viewBox="0 0 {width_match.group(1)} {height_match.group(1)}"'
            svg = svg[:svg_open.end() - 1] + view_box + svg[svg_open.end() - 1:]

    return re.sub(
        r"<svg\b",
        '<svg class="brand-logo-svg" aria-hidden="true" focusable="false"',
        svg,
        count=1,
        flags=re.I,
    )


def _read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _logo_data_uri():
    if not os.path.exists(_DEFAULT_LOGO_PATH):
        return ""
    raw = _read_text(_DEFAULT_LOGO_PATH).strip()
    return "data:image/svg+xml;charset=utf-8," + quote(raw, safe="")


def _shared_shell_section(name):
    shell = _read_text(os.path.join(SHARED_SHELL_DIR, "shell.html"))
    m = re.search(
        rf"<!-- QB_SHELL_{name}_START -->(.*?)<!-- QB_SHELL_{name}_END -->",
        shell,
        flags=re.S,
    )
    if not m:
        raise ValueError(f"shell.html 缺少 {name} section")
    return m.group(1).strip().replace("__QB_LOGO_SRC__", _logo_data_uri())


def _shared_shell_css():
    return _read_text(os.path.join(SHARED_SHELL_DIR, "shell.css"))


def _shared_shell_js():
    return "\n".join([
        _read_text(os.path.join(ASSETS_DIR, "qr-mini.js")).strip(),
        _read_text(os.path.join(SHARED_SHELL_DIR, "poster.js")).strip(),
        _read_text(os.path.join(SHARED_SHELL_DIR, "shell.js")).strip(),
    ])


# QBV_RENDER_JS_START/END 标记着运行时渲染引擎（取数 + 面板渲染），供 chart_edit.py 在编辑已发布页面时
# 做「只换这一块 <script>、页面其余内容字节不变」的定点 retrofit——写法与 assets/data-kernel.js 的
# QB_DATA_KERNEL_START/END 标记一致。BOOT 用 __BOOT__ 占位，由 _render_html / chart_edit.py 各自替换。
RENDER_JS_START_MARKER = "/* QBV_RENDER_JS_START:v1 */"
RENDER_JS_END_MARKER = "/* QBV_RENDER_JS_END:v1 */"

_RENDER_JS_TEMPLATE = r"""/* QBV_RENDER_JS_START:v1 */
(function () {
'use strict';
const BOOT = __BOOT__;
let LAST_OUTPUTS = {};

function apiUrl(endpoint, path) {
  endpoint = String(endpoint || '').replace(/\/+$/, '');
  path = '/' + String(path || '').replace(/^\/+/, '');
  if (endpoint.endsWith('/skill') && path.startsWith('/skill/')) {
    path = path.slice('/skill'.length);
  }
  return endpoint + path;
}

function fmtDate(v) {
  // 整数 / 8 位数字串 YYYYMMDD → YYYY-MM-DD；其它原样返回
  if (typeof v === 'number' && Number.isInteger(v) && v >= 10000101 && v <= 99991231) v = String(v);
  if (typeof v === 'string' && /^\d{8}$/.test(v)) return v.slice(0, 4) + '-' + v.slice(4, 6) + '-' + v.slice(6, 8);
  return v;
}

function normalize(data) {
  // 归一为 {columns:[...], rows:[[...]]}，兼容公式包各 read_mode 的 data 形态
  if (data == null) return {columns: [], rows: []};
  if (Array.isArray(data)) {
    if (data.length === 0) return {columns: [], rows: []};
    if (typeof data[0] === 'object' && data[0] !== null && !Array.isArray(data[0])) {
      const cols = []; data.forEach(o => Object.keys(o).forEach(k => { if (!cols.includes(k)) cols.push(k); }));
      return {columns: cols, rows: data.map(o => cols.map(c => o[c]))};
    }
    if (Array.isArray(data[0])) {
      const n = Math.max.apply(null, data.map(r => r.length));
      return {columns: Array.from({length: n}, (_, i) => 'c' + i), rows: data};
    }
    return {columns: ['value'], rows: data.map(v => [v])};
  }
  if (typeof data === 'object') {
    // 解包公式包按 read_mode 命名的外层 key：range_data / last_value / last_day_stats / last_valid_per_asset
    for (const wk of ['range_data', 'last_value', 'last_day_stats', 'last_column_full', 'last_valid_per_asset']) {
      if (data[wk] && typeof data[wk] === 'object') return normalize(data[wk]);
    }
    if (Array.isArray(data.columns) && Array.isArray(data.rows)) return {columns: data.columns, rows: data.rows};
    // 截面榜单：top_values / items / records / last_column_full.values 是对象数组
    for (const ak of ['top_values', 'items', 'records']) {
      if (Array.isArray(data[ak])) return normalize(data[ak]);
    }
    if (Array.isArray(data.values) && data.values.every(v => v && typeof v === 'object' && !Array.isArray(v))) {
      return normalize(data.values);
    }
    // 序列：x 轴候选 + y 轴候选成对出现（range_data 的 dates/values 即走这里）
    const xk = ['dates', 'date', 'x', 'index', 'labels', 'categories'].find(k => Array.isArray(data[k]));
    const yk = ['values', 'y', 'series', 'data'].find(k => Array.isArray(data[k]));
    if (xk && yk) {
      const xs = data[xk], ys = data[yk];
      const yName = data.series_name || yk;
      // 裁掉尾部 null（range_data 最新若干日常未回填），整数日期归一为 YYYY-MM-DD
      const isNull = v => v == null || (typeof v === 'number' && !isFinite(v));
      let end = xs.length;
      while (end > 0 && isNull(ys[end - 1])) end--;
      const rows = [];
      for (let i = 0; i < end; i++) rows.push([fmtDate(xs[i]), ys[i]]);
      return {columns: [xk, yName], rows: rows};
    }
    if (Array.isArray(data.data)) return normalize(data.data);
    // 普通对象（如 last_value 的 {date,value}）→ key/value 两列
    const keys = Object.keys(data);
    return {columns: ['key', 'value'], rows: keys.map(k => [k, data[k]])};
  }
  return {columns: ['value'], rows: [[data]]};
}

// 数据授权三类 kind 的 data 归一为「对象数组」，再交给 normalize 出规整表。
// 必须与 Python 侧 _normalize_grant_data 同款口径。无法识别时原样返回。
function normalizeGrantData(kind, data) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return data;
  var k = (kind || '').toLowerCase();
  if (k === 'fast_query') {
    var results = data.results || [];
    var hasSeries = results.some(function (r) {
      return (r.fields || []).some(function (f) { return Array.isArray(f.series); });
    });
    if (hasSeries) {
      var multiSeries = results.length > 1, seriesRows = [];
      results.forEach(function (r) {
        var name = r.asset_name || r.ticker || r.asset_intent;
        var byDate = new Map(), dateOrder = [];
        (r.fields || []).forEach(function (f) {
          if (!Array.isArray(f.series)) return;
          f.series.forEach(function (p) {
            var date = fmtDate(p.date);
            if (!byDate.has(date)) {
              var base = multiSeries ? {'标的': name, '日期': date} : {'日期': date};
              byDate.set(date, base); dateOrder.push(date);
            }
            byDate.get(date)[f.intent] = p.value;
          });
        });
        dateOrder.forEach(function (date) { seriesRows.push(byDate.get(date)); });
      });
      if (seriesRows.length) return seriesRows;
    }
    var multi = results.length > 1, rows = [];
    results.forEach(function (r) {
      var name = r.asset_name || r.ticker || r.asset_intent;
      (r.fields || []).forEach(function (f) {
        var row = multi ? {'标的': name} : {};
        row['指标'] = f.intent; row['值'] = f.value; row['单位'] = f.unit; row['日期'] = f.date;
        rows.push(row);
      });
    });
    return rows.length ? rows : data;
  }
  if (k === 'composition_select') {
    var rs = data.results || [];
    var out = rs.map(function (r) {
      return {'排名': r.rank, '名称': r.name, '代码': r.code, '行业': r.industry, '得分': r.score};
    });
    return out.length ? out : data;
  }
  if (k === 'stock_profile') {
    var dims = data.dimensions || {}, drows = [];
    Object.keys(dims).forEach(function (dname) {
      var inds = (dims[dname] && dims[dname].indicators) || {};
      Object.keys(inds).forEach(function (ik) {
        var iv = inds[ik] || {};
        drows.push({'维度': dname, '指标': iv.name || ik, '最新值': iv.latest_value, '单位': iv.unit});
      });
    });
    return drows.length ? drows : data;
  }
  return data;
}

function colIdx(tab, name) {
  const i = tab.columns.indexOf(name);
  return i >= 0 ? i : null;
}

function renderTable(el, tab, panel) {
  const cols = (panel.columns && panel.columns.length) ? panel.columns : tab.columns;
  const idx = cols.map(c => colIdx(tab, c));
  let h = '<table><thead><tr>' + cols.map(c => '<th>' + c + '</th>').join('') + '</tr></thead><tbody>';
  tab.rows.forEach(r => {
    h += '<tr>' + idx.map(i => '<td>' + fmt(i == null ? '' : r[i]) + '</td>').join('') + '</tr>';
  });
  h += '</tbody></table>';
  el.innerHTML = h;
}

function fmt(v) {
  if (v == null) return '';
  if (typeof v === 'number') return (Math.abs(v) >= 1e4 || (v % 1 !== 0)) ? v.toLocaleString(undefined, {maximumFractionDigits: 4}) : v;
  return String(v);
}

function esc(v) {
  return String(v == null ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function clsForNumber(v) {
  if (typeof v !== 'number' || !isFinite(v)) return '';
  if (v > 0) return ' up';
  if (v < 0) return ' down';
  return ' flat';
}

function lastRealNumber(tab, ci) {
  // 自底向上扫某列，返回末个有效数值（跳过 null/NaN/尾部空洞）
  if (ci == null) return null;
  for (let r = tab.rows.length - 1; r >= 0; r--) {
    const v = tab.rows[r][ci];
    if (typeof v === 'number' && isFinite(v)) return v;
  }
  return null;
}
function renderNumber(el, tab, panel) {
  let val = null;
  const f = panel.value_field;
  if (f && colIdx(tab, f) != null) {
    val = lastRealNumber(tab, colIdx(tab, f));
  } else {
    // 默认取「最后一个数值列」的末个有效值：对 range_data 的 [日期, 序列] 形态即取序列值，
    // 不再用 .find(第一个数字) 误命中日期列。末列若全空则向前回退到其它数值列。
    for (let c = tab.columns.length - 1; c >= 0; c--) {
      val = lastRealNumber(tab, c);
      if (val != null) break;
    }
  }
  const desc = panel.description ? '<div class="desc">' + esc(panel.description) + '</div>' : '';
  el.innerHTML = '<div class="big' + clsForNumber(val) + '">' + fmt(val) + (panel.unit ? '<span class="unit">' + esc(panel.unit) + '</span>' : '') + '</div>' + desc;
}

function renderText(el, panel) {
  const text = panel.text || panel.content || panel.description || '';
  el.innerHTML = '<div class="text-panel">' + esc(text).replace(/\n/g, '<br>') + '</div>';
}

function openImageLightbox(src, alt, caption, trigger) {
  const dialog = document.createElement('dialog');
  dialog.className = 'image-lightbox';
  dialog.setAttribute('aria-label', '图片大图预览');
  dialog.innerHTML = '<div class="image-lightbox__shell">' +
    '<button type="button" class="image-lightbox__close" aria-label="关闭大图">×</button>' +
    '<figure class="image-lightbox__figure"><img src="' + esc(src) + '" alt="' + esc(alt) + '" decoding="async">' +
    (caption ? '<figcaption>' + esc(caption) + '</figcaption>' : '') + '</figure></div>';
  const close = () => { if (dialog.open) dialog.close(); };
  dialog.querySelector('.image-lightbox__close').addEventListener('click', close);
  dialog.addEventListener('click', event => { if (event.target === dialog) close(); });
  dialog.addEventListener('close', () => {
    document.body.classList.remove('image-lightbox-open');
    dialog.remove();
    if (trigger && document.contains(trigger)) trigger.focus();
  }, {once: true});
  document.body.appendChild(dialog);
  document.body.classList.add('image-lightbox-open');
  dialog.showModal();
  dialog.querySelector('.image-lightbox__close').focus();
}

function renderImage(el, panel) {
  const url = panel.image_url || '';
  const fit = ['cover', 'contain', 'fill', 'none', 'scale-down'].includes(panel.fit) ? panel.fit : 'contain';
  const width = Number(panel.width || 0);
  const height = Number(panel.height || 0);
  const eager = panel.loading === 'lazy' ? 'lazy' : 'eager';
  const alt = panel.alt || panel.title || '';
  const zoomable = panel.zoomable !== false;
  const attrs = (width > 0 ? ' width="' + width + '"' : '') + (height > 0 ? ' height="' + height + '"' : '');
  const image = '<img src="' + esc(url) + '" alt="' + esc(alt) + '" loading="' + eager + '" decoding="async"' + attrs + ' style="object-fit:' + fit + '">';
  const visual = zoomable
    ? '<button type="button" class="image-zoom-trigger" aria-label="查看大图：' + esc(alt) + '">' + image + '<span class="image-zoom-hint" aria-hidden="true">查看大图</span></button>'
    : image;
  el.innerHTML = '<figure class="image-panel">' + visual +
    (panel.caption ? '<figcaption>' + esc(panel.caption) + '</figcaption>' : '') + '</figure>';
  const trigger = el.querySelector('.image-zoom-trigger');
  if (trigger) trigger.addEventListener('click', () => openImageLightbox(url, alt, panel.caption || '', trigger));
}

function renderChart(el, tab, panel) {
  const chart = echarts.init(el);
  const xName = panel.x || tab.columns[0];
  const xi = colIdx(tab, xName);
  const xData = tab.rows.map(r => xi == null ? '' : r[xi]);
  let yCols = panel.y && panel.y.length ? panel.y : tab.columns.filter(c => c !== xName);
  // 只保留数值列
  yCols = yCols.filter(c => {
    const i = colIdx(tab, c);
    return i != null && tab.rows.some(r => typeof r[i] === 'number');
  });
  // 双轴：panel.right_series 声明哪些列（= 多 output 面板里的 output 名）归右轴，其余归左轴；
  // 未声明 right_series 或 dual_axis!==true 时行为与单轴完全一致（向后兼容默认关闭）。
  const rightSet = new Set(Array.isArray(panel.right_series) ? panel.right_series : []);
  const dualAxis = panel.dual_axis === true && rightSet.size > 0;
  // 迷你走势图：panel.sparkline===true 时去掉坐标轴/图例/网格留白，只保留曲线本身。
  const spark = panel.sparkline === true;
  const series = yCols.map(c => {
    const i = colIdx(tab, c);
    const onRight = dualAxis && rightSet.has(c);
    return {name: c, type: panel.type === 'bar' ? 'bar' : 'line', smooth: panel.type !== 'bar',
            showSymbol: false, connectNulls: true, data: tab.rows.map(r => r[i]),
            yAxisIndex: onRight ? 1 : 0,
            lineStyle: spark ? {width: 2} : undefined};
  });
  const yAxisBase = {type: 'value', scale: true, axisLabel: {color: '#697586'}, splitLine: {lineStyle: {color: '#e8edf4'}}};
  const yAxis = dualAxis
    ? [yAxisBase, Object.assign({}, yAxisBase, {splitLine: {show: false}})]
    : yAxisBase;
  chart.setOption({
    tooltip: {trigger: 'axis', show: !spark},
    legend: {data: yCols, top: 0, type: 'scroll', show: !spark},
    color: ['#2454a6', '#7a8ca8', '#c03d3d', '#16845b', '#b2762d'],
    grid: spark ? {left: 2, right: 2, top: 2, bottom: 2} : {left: 56, right: dualAxis ? 56 : 24, top: 34, bottom: 42},
    xAxis: {type: 'category', data: xData, boundaryGap: panel.type === 'bar', show: !spark,
            axisLine: {lineStyle: {color: '#bfccda'}}, axisTick: {show:false}, axisLabel: {color: '#697586'}},
    yAxis: spark ? Object.assign({}, yAxisBase, {show: false, splitLine: {show: false}}) : yAxis,
    series: series,
  });
  window.addEventListener('resize', () => chart.resize());
}

// 雷达图：tab 第一列是维度名、第二列（或唯一列）是 0..max 的得分。panel.max 缺省 1（比例型分数）。
function renderRadarChart(el, tab, panel) {
  const chart = echarts.init(el);
  const nameIdx = 0;
  const valueIdx = tab.columns.length > 1 ? 1 : 0;
  const maxVal = typeof panel.max === 'number' ? panel.max : 1;
  const indicator = tab.rows.map(r => ({name: String(r[nameIdx] == null ? '' : r[nameIdx]), max: maxVal}));
  const values = tab.rows.map(r => (typeof r[valueIdx] === 'number' ? r[valueIdx] : 0));
  chart.setOption({
    tooltip: {},
    color: ['#2454a6'],
    radar: {
      indicator: indicator, radius: '65%',
      axisName: {color: '#697586', fontSize: 11},
      splitLine: {lineStyle: {color: '#e8edf4'}},
      splitArea: {show: false},
      axisLine: {lineStyle: {color: '#dde5ef'}},
    },
    series: [{type: 'radar', data: [{value: values, areaStyle: {opacity: 0.15}}]}],
  });
  window.addEventListener('resize', () => chart.resize());
}

// 骨架先行：先把所有面板卡片铺出来，正文随产出到达再逐个填。
// PANEL_REG 存每个面板的 body/span/是否已填/它依赖的 output 名单；OUTPUT_INDEX 把产出名映射到引用它的面板
// （一个产出可被多个面板复用，一个面板也可以同时依赖多个产出——叠加对比线就是这么接进来的）。
let PANEL_REG = [];
let OUTPUT_INDEX = {};

// 面板依赖的 output 名单：新的 panel.outputs（复数，叠加对比线）优先，兼容旧的 panel.output（单数）。
function panelOutputNames(panel) {
  if (Array.isArray(panel.outputs) && panel.outputs.length) return panel.outputs;
  if (panel.output) return [panel.output];
  return [];
}

// 把一个面板依赖的若干 output 合并成一张表：单 output 时行为与老版本完全一致（直接 normalize）；
// 多 output 时各自 normalize 成 [x,y] 两列，再按 x（日期）外连接拼成宽表，喂给 renderChart 出多条线。
function mergeOutputTables(names, received) {
  if (names.length <= 1) {
    const out = names.length ? received[names[0]] : null;
    if (!out || out.error) return {tab: null, out: out || {error: '无产出'}};
    return {tab: normalize(out.data), out: null};
  }
  const perOutput = names.map(name => {
    const out = received[name];
    if (!out || out.error) return null;
    const tab = normalize(out.data);
    if (!tab.rows.length) return null;
    const yi = tab.columns.length > 1 ? 1 : 0;
    return {name: name, rows: tab.rows.map(r => [r[0], r[yi]])};
  });
  if (perOutput.every(s => !s)) return {tab: null, out: {error: '无产出'}};
  const byX = new Map();
  const order = [];
  perOutput.forEach(s => {
    if (!s) return;
    s.rows.forEach(([x, y]) => {
      if (!byX.has(x)) { byX.set(x, {}); order.push(x); }
      byX.get(x)[s.name] = y;
    });
  });
  const columns = ['x'].concat(names);
  const rows = order.map(x => {
    const cell = byX.get(x);
    return columns.map(c => c === 'x' ? x : (c in cell ? cell[c] : null));
  });
  return {tab: {columns: columns, rows: rows}, out: null};
}

function createCard(panel) {
  const type = panel.type || 'table';
  // target_selector：bespoke 页面自己排好版的容器（如 <div id="priceChart">），直接渲染进去，
  // 不包卡片外壳（标题/边框/间距），页面布局与样式完全由 bespoke 页面自己掌控。
  // 命中不到时退化为标准网格卡片，不让整页因为一个选择器写错而白屏。
  if (panel.target_selector) {
    const target = document.querySelector(panel.target_selector);
    if (target) {
      // 普通 bespoke 容器允许声明式 renderer 接管，但先处置同一 ECharts
      // 注册表中的旧实例，避免只清 DOM 留下悬挂实例。stock 原生价格图在
      // Python 侧 owner contract 中直接拒绝，不会进入这里。
      const existing = window.echarts && typeof window.echarts.getInstanceByDom === 'function'
        ? window.echarts.getInstanceByDom(target)
        : null;
      if (existing && typeof existing.dispose === 'function') existing.dispose();
      target.replaceChildren();
      target.classList.add('qb-embedded-body', 'body', type);
      return {body: target, span: 'embedded'};
    }
    console.warn('[QBV] target_selector 未命中: ' + panel.target_selector + '，回退到标准网格卡片');
  }
  const card = document.createElement('section');
  const defaultSpan = (type === 'line' || type === 'bar' || type === 'radar') ? 'full' : 'auto';
  const span = ['full', 'wide', 'auto'].includes(panel.span) ? panel.span : defaultSpan;
  card.className = 'card card-' + type + ' span-' + span;
  card.innerHTML = '<div class="card-head"><h3>' + esc(panel.title || panel.output || '') + '</h3>' +
    (panel.description && type !== 'number' && type !== 'text' ? '<p>' + esc(panel.description) + '</p>' : '') +
    '</div>';
  const body = document.createElement('div');
  body.className = 'body ' + type;
  card.appendChild(body);
  const grid = document.getElementById('grid');
  if (grid) grid.appendChild(card);
  return {body: body, span: span};
}

// 展示层裁剪：panel.x_range.start_date（chart_edit.py set_window 在"目标窗口已在已取数范围内"时写入）
// 只影响这张图从第几天开始画，不影响实际取数范围——不用重新验证/注册公式包就能收窄可视窗口。
function applyXRange(tab, panel) {
  const startDate = panel.x_range && panel.x_range.start_date;
  if (!startDate || !tab || !tab.rows || !tab.rows.length) return tab;
  return {columns: tab.columns, rows: tab.rows.filter(r => r[0] == null || String(r[0]) >= startDate)};
}

function renderPanelBody(body, panel, span, merged) {
  const type = panel.type || 'table';
  const out = merged.out;
  if (!merged.tab) { body.innerHTML = '<p class="empty">无产出：' + (panel.output || (panel.outputs || []).join('、') || '') + '</p>'; return; }
  if (out && out.error) { body.innerHTML = '<p class="empty err">取数失败：' + out.error + '</p>'; return; }
  const tab = (type === 'line' || type === 'bar') ? applyXRange(merged.tab, panel) : merged.tab;
  try {
    if (type === 'raw') body.innerHTML = '<pre>' + JSON.stringify((merged.rawData !== undefined ? merged.rawData : tab), null, 2) + '</pre>';
    else if (type === 'number') renderNumber(body, tab, panel);
    else if (type === 'table') renderTable(body, tab, panel);
    else if (type === 'radar') { body.style.height = (panel.height || (span === 'full' ? 360 : 300)) + 'px'; renderRadarChart(body, tab, panel); }
    else { body.style.height = (panel.height || (span === 'full' ? 360 : 300)) + 'px'; renderChart(body, tab, panel); }
  } catch (e) {
    body.innerHTML = '<p class="empty">渲染失败: ' + e + '</p>';
  }
}

function buildSkeletons() {
  // 嵌入模式（面板全部走 target_selector）可能压根没有 #grid；null 时跳过清空，不整页报错。
  const grid = document.getElementById('grid');
  if (grid) grid.innerHTML = '';
  PANEL_REG = [];
  OUTPUT_INDEX = {};
  BOOT.panels.forEach(panel => {
    const type = panel.type || 'table';
    const made = createCard(panel);
    const names = panelOutputNames(panel);
    const reg = {panel: panel, body: made.body, span: made.span, filled: false, names: names, received: {}};
    PANEL_REG.push(reg);
    if (type === 'text') { renderText(made.body, panel); reg.filled = true; return; }
    if (type === 'image') { renderImage(made.body, panel); reg.filled = true; return; }
    made.body.innerHTML = '<p class="empty">加载中…</p>';
    names.forEach(name => { (OUTPUT_INDEX[name] = OUTPUT_INDEX[name] || []).push(reg); });
  });
}

// 某产出到达后记进对应面板的 received；面板依赖的 output 全部到齐才渲染（单 output 面板天然一到即齐，
// 不改变既有的「先到先显」行为；只有引用多个 output 的叠加对比面板才会等）。
function applyOutput(name, out) {
  (OUTPUT_INDEX[name] || []).forEach(reg => {
    reg.received[name] = out;
    if (!reg.names.every(n => Object.prototype.hasOwnProperty.call(reg.received, n))) return;
    const merged = mergeOutputTables(reg.names, reg.received);
    if (reg.names.length === 1 && (reg.panel.type || 'table') === 'raw') merged.rawData = out.data;
    renderPanelBody(reg.body, reg.panel, reg.span, merged);
    reg.filled = true;
  });
}

function syncLiveCard(outputs) {
  try {
    const payload = outputs || LAST_OUTPUTS || {};
    window.dispatchEvent(new CustomEvent('qb:outputs', {detail: {outputs: payload}}));
  } catch (e) {}
}

// 一次性渲染（封面模式 / 流式兜底）：先铺骨架，再把已知产出全部填上
function renderAll(outputs) {
  LAST_OUTPUTS = outputs || {};
  buildSkeletons();
  Object.keys(LAST_OUTPUTS).forEach(name => applyOutput(name, LAST_OUTPUTS[name]));
  syncLiveCard(LAST_OUTPUTS);
}

function parseSSEBlock(block) {
  // 解析单个 SSE 事件块（event/data 行）→ {output, out} 或 null（与服务端 query 的 result 事件对齐）
  let event = null;
  const dataLines = [];
  block.split('\n').forEach(line => {
    line = line.replace(/\r$/, '');
    if (line.startsWith(':')) return;
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).replace(/^ /, ''));
  });
  if (event !== 'result' || !dataLines.length) return null;
  try {
    const p = JSON.parse(dataLines.join('\n'));
    return {output: p.output, out: {read_mode: p.read_mode, data_id: p.data_id, data: p.data, error: p.error}};
  } catch (e) { return null; }
}

function parseSSE(text) {
  // 整段 SSE 文本 → outputs（流式兜底 / 封面模式用）。事件以空行分隔，先归一 CRLF 再按 \n\n 切块。
  const outputs = {};
  text.replace(/\r\n/g, '\n').split('\n\n').forEach(block => {
    const r = parseSSEBlock(block);
    if (r) outputs[r.output] = r.out;
  });
  return outputs;
}

// 只标错公式包来源、且尚未拿到产出的面板（type=grant 的面板走自己的 fetchGrantsLive，互不牵连；
// 已经渲染成功的面板不因为「同页另一个包」失败而被覆盖——每个包只影响它自己名下、还没到齐的面板）。
function markPackagePanelsError(msg) {
  PANEL_REG.forEach(reg => {
    if (reg.filled) return;
    if (reg.panel._source === 'grant') return;
    if ((reg.panel.type || 'table') === 'text') return;
    renderPanelBody(reg.body, reg.panel, reg.span, {tab: null, out: {error: msg}});
  });
}

// BOOT.packages（多包，叠加编辑用）优先；缺省时从旧版单包字段 packageId/signature 合成一个元素，
// 保证「只 retrofit 了运行时 JS、还没来得及 patch BOOT」的过渡态页面也能正常取数。
function resolvePackages() {
  if (Array.isArray(BOOT.packages) && BOOT.packages.length) return BOOT.packages;
  if (BOOT.packageId) return [{package_id: BOOT.packageId, signature: BOOT.signature}];
  return [];
}

// 单个公式包取数：SSE 流，边收边渲染（钉死 output → panel，重算会走 stale/recomputed）
async function _fetchOnePackageLive(pkg) {
  let resp;
  try {
    resp = await fetch(apiUrl(BOOT.endpoint, '/skill/queryFormulaPackage'), {
      method: 'POST',
      headers: Object.assign(
        {'Content-Type': 'application/json', 'Accept': 'text/event-stream'},
        BOOT.skillVersion ? {'x-skill-version': BOOT.skillVersion, 'x-skill-name': BOOT.skillName || 'quant-buddy-view'} : {}
      ),
      body: JSON.stringify({package_id: pkg.package_id, signature: pkg.signature}),
    });
  } catch (e) {
    markPackagePanelsError('取数失败（可能是跨域/网络）：' + e);
    throw new Error('公式包取数失败（网络或跨域）');
  }
  if (!resp.ok) { markPackagePanelsError('取数失败：HTTP ' + resp.status); throw new Error('公式包取数失败：HTTP ' + resp.status); }

  // 老环境不支持可读流：回退到一次性取整段再渲染
  if (!resp.body || typeof resp.body.getReader !== 'function') {
    const outputs = parseSSE(await resp.text());
    Object.keys(outputs).forEach(name => {
      LAST_OUTPUTS[name] = outputs[name];
      applyOutput(name, outputs[name]);
    });
    syncLiveCard(LAST_OUTPUTS);
    return;
  }

  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  const handle = block => {
    const r = parseSSEBlock(block);
    if (!r) return;
    LAST_OUTPUTS[r.output] = r.out;
    applyOutput(r.output, r.out);   // 边收边渲染：先到先显
    syncLiveCard(LAST_OUTPUTS);
  };
  try {
    for (;;) {
      const {value, done} = await reader.read();
      if (done) break;
      // 删掉所有 \r，使 \n\n 切块对 LF / CRLF 两种分隔都成立
      buf += dec.decode(value, {stream: true}).replace(/\r/g, '');
      const blocks = buf.split('\n\n');
      buf = blocks.pop();           // 末段可能是半条事件，留到下个 chunk 续上
      blocks.forEach(handle);
    }
    if (buf.trim()) handle(buf);     // 收尾残留块
  } catch (e) {
    throw new Error('公式包流式取数中断');
  }
}

// 多公式包并发取数：每个包各自流式、互不阻塞——叠加一条线只需多注册一个小包，不牵连已有包的数据。
async function fetchPackageLive() {
  const packages = resolvePackages();
  if (!packages.length) return;
  QB.runtime.begin('sse');
  try {
    await Promise.all(packages.map(pkg => _fetchOnePackageLive(pkg)));
  } catch (e) {
    QB.runtime.fail(e);
    throw e;
  } finally {
    QB.runtime.end();
  }
}

// 数据授权取数：普通 JSON（非 SSE，不重算），各 grant 并发独立请求、互不阻塞
async function fetchGrantsLive() {
  const grants = BOOT.grants || [];
  await Promise.all(grants.map(async (g) => {
    let out;
    try {
      const grantOut = await QB.queryGrant({endpoint: BOOT.endpoint, grant_id: g.grant_id, signature: g.signature});
      const item = grantOut[g.grant_id];
      out = {data: normalizeGrantData(item.kind, item.data), error: item.error || null};
    } catch (e) {
      out = {data: null, error: '取数失败（可能是跨域/网络）：' + e};
    }
    LAST_OUTPUTS[g.grant_id] = out;
    applyOutput(g.grant_id, out);
    syncLiveCard(LAST_OUTPUTS);
  }));
}

async function fetchLive() {
  buildSkeletons();          // 先把面板骨架铺出来，产出到一个就渲染一个
  LAST_OUTPUTS = {};
  const tasks = [];
  if (resolvePackages().length) tasks.push(fetchPackageLive());
  if (BOOT.grants && BOOT.grants.length) tasks.push(fetchGrantsLive());
  if (tasks.length) await Promise.all(tasks.map(task => task.catch(() => null)));
  // 收尾：始终没等到产出的非 text 面板，标注无产出
  PANEL_REG.forEach(reg => {
    if (!reg.filled && (reg.panel.type || 'table') !== 'text') {
      reg.body.innerHTML = '<p class="empty">无产出：' + (reg.panel.output || (reg.panel.outputs || []).join('、') || '') + '</p>';
    }
  });
  return LAST_OUTPUTS;
}

function panelDisplayValue(panel) {
  const out = LAST_OUTPUTS[panel.output];
  if (!out || out.error) return '—';
  const tab = normalize(out.data);
  if (!tab.rows.length) return '—';
  let value = null;
  if (panel.value_field && colIdx(tab, panel.value_field) != null) {
    value = lastRealNumber(tab, colIdx(tab, panel.value_field));
  } else {
    for (let c = tab.columns.length - 1; c >= 0; c--) {
      value = lastRealNumber(tab, c);
      if (value != null) break;
    }
  }
  return value == null ? '—' : fmt(value) + (panel.unit ? ' ' + panel.unit : '');
}

function panelListItems(panel) {
  const out = LAST_OUTPUTS[panel.output];
  if (!out || out.error) return [];
  const tab = normalize(out.data);
  if (!tab.rows.length) return [];
  return tab.rows.slice(-6).reverse().map(row => {
    const label = row[0] == null ? (panel.output || panel.title || '—') : row[0];
    const value = row.length > 1 ? row[row.length - 1] : row[0];
    return {label: String(label), value: fmt(value)};
  });
}

function getDashboardPosterData() {
  const share = BOOT.share || {};
  const numberPanels = BOOT.panels.filter(p => (p.type || '').toLowerCase() === 'number');
  let metrics = numberPanels.slice(0, 8).map(p => ({
    label: p.title || p.output || '指标',
    value: panelDisplayValue(p),
    sub: p.description || p.output || ''
  }));
  if (!metrics.length) {
    metrics = BOOT.panels.slice(0, 6).map(p => ({
      label: p.title || p.output || '指标',
      value: panelDisplayValue(p),
      sub: p.output || ''
    }));
  }
  const sections = BOOT.panels
    .filter(p => (p.type || '').toLowerCase() !== 'number' && (p.type || '').toLowerCase() !== 'text')
    .slice(0, 3)
    .map(p => ({
      title: p.title || p.output || '数据区',
      type: 'list',
      summary: p.description || '',
      items: panelListItems(p),
      height: 176
    }));
  return {
    headline: share.title || document.title,
    summary: share.subtitle || 'QuantBuddy 实时取数看板，打开页面即拉取最新公式包输出。',
    metrics,
    sections,
    asof: BOOT.generatedAt || ''
  };
}

document.addEventListener('DOMContentLoaded', () => {
  // 封面模式：构建期把已校验产出注入 window.__QB_COVER__，直接离线渲染整页内容（去头尾），
  // 供 Edge 无头截图当封面。正常上传页面无此全局，分支 inert。
  if (window.__QB_COVER__) {
    document.body.classList.add('qb-cover');
    try { renderAll((window.__QB_COVER__ && window.__QB_COVER__.outputs) || {}); } catch (e) {}
    return;
  }
  if (window.QBShareShell) {
    QBShareShell.init({
      templateName: (BOOT.share && BOOT.share.pageType) || '标准实时看板',
      title: () => (BOOT.share && BOOT.share.title) || document.title,
      subtitle: () => (BOOT.share && BOOT.share.subtitle) || '',
      asof: () => BOOT.generatedAt || '',
      onRefresh: fetchLive,
      getPosterData: getDashboardPosterData
    });
  }
  fetchLive();
});
})();
/* QBV_RENDER_JS_END:v1 */
"""

# 局部嵌入模式（bespoke 页面内嵌图表用）：复用同一份渲染引擎正文，只换启动方式——不接管整页
# （不调 QBShareShell.init、不处理 __QB_COVER__ 封面分支），改成暴露 window.QBV.refresh 并立即取数。
# 用正则从标准模板里换掉 DOMContentLoaded 引导块，而不是维护第二份 JS 正文，避免两份渲染逻辑长期漂移。
_BOOTSTRAP_BLOCK_RE = re.compile(
    r"document\.addEventListener\('DOMContentLoaded', \(\) => \{.*?\n\}\);\n\}\)\(\);\n"
    + re.escape(RENDER_JS_END_MARKER),
    re.S,
)

_EMBEDDED_BOOTSTRAP = (
    "(function () {\n"
    "  window.QBV = window.QBV || {};\n"
    "  window.QBV.refresh = fetchLive;\n"
    "  fetchLive();\n"
    "})();\n"
    "})();\n"  # 闭合模板最外层的渲染引擎 IIFE（_RENDER_JS_TEMPLATE 开头新增的那一层）
) + RENDER_JS_END_MARKER


def _render_js_for_boot(boot):
    """把 BOOT 编译成运行时 <script> 正文。boot.embedded 为真时换成嵌入式启动，供 bespoke 页面内嵌图表用；
    否则走标准整页启动，行为与此前完全一致。_render_html（整页生成）与 chart_edit.py（定点编辑回写）
    共用这份判断，保证「这个页面当初是不是嵌入模式生成的」在编辑时不会被错误地换回整页启动逻辑。"""
    boot_json = json.dumps(boot, ensure_ascii=False)
    full = _RENDER_JS_TEMPLATE.replace("__BOOT__", boot_json)
    if not boot.get("embedded"):
        return full
    embedded, n = _BOOTSTRAP_BLOCK_RE.subn(_EMBEDDED_BOOTSTRAP, full, count=1)
    if n != 1:
        raise ValueError("无法定位 DOMContentLoaded 引导代码块，embedded 模式生成失败（渲染引擎模板可能已变化）")
    return embedded


def _render_html(spec, *, title, subtitle, panels, endpoint, package_id, signature, generated_at, grants=None):
    """组装 HTML。骨架自包含（样式/内核内联），数据走运行时实时取数：页面内联 endpoint+凭证 + 取数 JS。
    grants：panel 里引用 grant_id 的数据授权列表 [{grant_id,signature}]，与公式包 panel 同页并存。"""
    share = _share_config(spec)
    page_mode = "live" if package_id or grants else "static"

    # packages：多公式包列表，运行时并发取数、互不阻塞。生成时只有一个包，但形状从一开始就是数组，
    # 后续 chart_edit.py 增/删/改某条线时只需往这个数组追加/摘除元素，不用改造整页。
    # formulas/reads（若 spec 显式给出）随包一起落进页面——不是敏感信息（signature 本就设计成随页面
    # 公开），留在页面里是给未来编辑用的"溯源清单"：不用再翻会话记录或猜测原始公式。
    packages = []
    if package_id:
        pkg_entry = {"role": "primary", "package_id": package_id, "signature": signature}
        if isinstance(spec.get("formulas"), list):
            pkg_entry["formulas"] = spec["formulas"]
        if isinstance(spec.get("reads"), list):
            pkg_entry["reads"] = spec["reads"]
        packages.append(pkg_entry)

    boot = {
        "mode": page_mode,
        "panels": panels,
        "grants": grants or [],
        "generatedAt": generated_at,
        "share": {
            "enabled": share["show_qr"],
            "url": share["share_url"],
            "officialUrl": share["official_url"],
            "title": title or "看板",
            "subtitle": subtitle or "",
            "pageType": share["page_type"],
            "footerNote": share["footer_note"],
        },
        "endpoint": endpoint,
        # packageId/signature（单数）保留只为兼容任何仍读取旧字段的代码；运行时以 packages（数组）为准。
        "packageId": package_id,
        "signature": signature,
        "packages": packages,
        # 构建时的 quant-buddy-view 版本/名，随实时取数上报给服务端 audit
        "skillVersion": C.SKILL_VERSION,
        "skillName": C.SKILL_NAME,
    }

    title_esc = html_escape(title or "看板")
    subtitle_esc = html_escape(subtitle or "")
    brand_name_esc = html_escape(share["brand_name"])
    brand_cn_esc = html_escape(share["brand_cn"])
    tagline_esc = html_escape(share["tagline"])
    page_type_esc = html_escape(share["page_type"])
    official_url_attr = html_escape(share["official_url"], quote=True)
    official_host_esc = html_escape(re.sub(r"^https?://", "", share["official_url"]).rstrip("/"))
    official_label_esc = html_escape(share["official_label"])
    share_title_esc = html_escape(share["share_title"])
    footer_note_esc = html_escape(share["footer_note"])
    brand_logo_html = _brand_logo_html()
    shared_header = _shared_shell_section("HEADER")
    shared_footer = _shared_shell_section("FOOTER")
    shared_modal = _shared_shell_section("MODAL")
    shared_css = _shared_shell_css()
    shared_runtime_js = _shared_shell_js()
    data_kernel_js = _read_text(os.path.join(ASSETS_DIR, "data-kernel.js")).replace(
        "__QBV_SKILL_VERSION__", C.SKILL_VERSION or ""
    )
    live_card_config = LC.dashboard_config(spec, panels)
    live_card_css = _read_text(os.path.join(ASSETS_DIR, "live-card.css")) if live_card_config else ""
    card_runtime_bundle = LC.card_runtime_bundle(
        live_card_config,
        endpoint=endpoint,
        package_id=package_id,
        signature=signature,
        style=live_card_css,
        fallback_title=title or "",
        fallback_description=subtitle or "",
    ) if live_card_config else None
    card_runtime_artifacts = card_runtime_bundle["artifacts"] if card_runtime_bundle else ""
    card_runtime_js = card_runtime_bundle["runtime"] if card_runtime_bundle else ""

    # 渲染脚本：把任意 data 形态归一为 {columns, rows}，再按 panel.type 出图/表
    render_js = _render_js_for_boot(boot)

    mode_note = "数据：打开时实时取最新" if page_mode == "live" else "内容：静态展示"
    mode_label = "Live HTML" if page_mode == "live" else "Static HTML"
    mode_label_esc = html_escape(mode_label)
    poster_target_attr = " data-qb-poster-target" if any(
        isinstance(panel, dict) and (panel.get("type") or "").lower() == "image"
        for panel in panels
    ) else ""
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title_esc}</title>
<style>
  :root {{
    color-scheme: light;
    --qb-ink: #101827;
    --qb-text: #1f2937;
    --qb-muted: #697586;
    --qb-canvas: #f3f6fa;
    --qb-surface: #ffffff;
    --qb-surface-soft: #f8fafc;
    --qb-border: #dde5ef;
    --qb-border-strong: #bfccda;
    --qb-accent: #d8a54b;
    --qb-up: #c2412d;
    --qb-down: #16845b;
    --qb-line: #2454a6;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", Roboto, Helvetica, Arial, sans-serif;
         background: var(--qb-canvas); color: var(--qb-text); }}
  a {{ color: inherit; }}
  a:focus-visible {{ outline: 2px solid #d8a54b; outline-offset: 3px; }}
  .shell-inner {{ max-width: 1180px; margin: 0 auto; padding: 0 20px; }}
  .eyebrow {{ margin: 0 0 8px; color: #a8b1c2; font-size: 12px; letter-spacing: .08em; text-transform: uppercase; }}
  h1 {{ margin: 0; font-size: 32px; line-height: 1.12; letter-spacing: 0; }}
  .subtitle {{ margin: 12px 0 0; color: #dbe2ee; max-width: 860px; font-size: 14px; }}
  .meta-row {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:16px; }}
  .meta-pill {{ display:inline-flex; align-items:center; min-height:26px; padding:0 9px; border-radius:8px;
               background:rgba(255,255,255,.08); color:#cbd5e1; font-size:12px; }}
  .meta-pill-strong {{ background:rgba(216,165,75,.16); color:#f8e4b7; border:1px solid rgba(216,165,75,.34); }}
  main {{ max-width: 1180px; margin: 0 auto; padding: 18px 20px 26px; }}
  #grid {{ display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 12px; align-items: stretch; }}
  .card {{ position:relative; background: var(--qb-surface); border: 1px solid var(--qb-border); border-radius: 8px; padding: 14px 16px;
          box-shadow: 0 10px 26px rgba(16,24,39,.045); min-width: 0; }}
  .card h3 {{ margin: 0; font-size: 13px; color:#2b3445; font-weight:700; }}
  .card-head {{ display:flex; flex-direction:column; gap:3px; margin-bottom: 10px; }}
  .card-head p {{ margin:0; color:var(--qb-muted); font-size:12px; }}
  .card .body {{ overflow: auto; }}
  .span-full {{ grid-column: span 12; }}
  .span-wide {{ grid-column: span 8; }}
  .span-auto {{ grid-column: span 4; }}
  .card-text {{ display:grid; grid-template-columns: 132px minmax(0,1fr); gap:16px; align-items:start;
               padding:15px 18px; border-color:#d7e0eb; background:linear-gradient(90deg, rgba(216,165,75,.10), rgba(255,255,255,.96) 34%, #fff); }}
  .card-text::before {{ content:""; position:absolute; inset:12px auto 12px 0; width:4px; border-radius:0 4px 4px 0; background:var(--qb-accent); }}
  .card-text .card-head {{ margin:0; padding-top:1px; }}
  .card-text h3 {{ color:#172033; font-size:14px; }}
  .card-text .body {{ overflow:visible; }}
  .card-number {{ min-height: 112px; display:flex; flex-direction:column; justify-content:flex-start; gap:12px; padding:13px 15px 12px; background:linear-gradient(180deg,#fff,#fbfdff); }}
  .card-number .card-head {{ margin-bottom:0; min-height:18px; }}
  .card-number .body {{ overflow:visible; min-height:58px; display:flex; flex-direction:column; justify-content:flex-start; }}
  .card-number::before {{ content:""; position:absolute; left:14px; right:14px; top:0; height:3px; border-radius:0 0 3px 3px; background:#c7d2df; }}
  .card-number:has(.big.up)::before {{ background:var(--qb-up); }}
  .card-number:has(.big.down)::before {{ background:var(--qb-down); }}
  .card-line {{ padding:16px 18px 18px; border-color:#cfd9e6; box-shadow:0 14px 34px rgba(16,24,39,.06); }}
  .card-line .card-head {{ padding-bottom:8px; border-bottom:1px solid #edf1f6; }}
  .card-line h3 {{ font-size:15px; color:#172033; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th, td {{ border-bottom: 1px solid #eef0f2; padding: 6px 8px; text-align: right; white-space: nowrap; }}
  th:first-child, td:first-child {{ text-align: left; }}
  thead th {{ position: sticky; top: 0; background: #fafbfc; }}
  .big {{ font-size: 30px; line-height:1.1; font-weight: 760; padding: 3px 0 2px; letter-spacing:0; color:#111827; font-variant-numeric: tabular-nums; }}
  .big.up {{ color:var(--qb-up); }} .big.down {{ color:var(--qb-down); }} .big.flat {{ color:#667085; }}
  .big .unit {{ font-size: 16px; font-weight: 400; margin-left: 6px; opacity: .7; }}
  .desc {{ color:var(--qb-muted); font-size:12px; line-height:1.35; margin-top:2px; }}
  .text-panel {{ color:#334155; font-size:13px; line-height:1.7; max-height:7em; overflow:auto; padding-right:4px; }}
  .image-panel {{ margin:0; display:grid; gap:8px; }}
  .image-panel img {{ display:block; width:100%; max-height:520px; border-radius:10px; background:#f1f5f9; }}
  .image-panel figcaption {{ color:#64748b; font-size:12px; line-height:1.6; }}
  .image-zoom-trigger {{ position:relative; display:block; width:100%; padding:0; overflow:hidden; border:0; border-radius:10px; background:transparent; cursor:zoom-in; }}
  .image-zoom-trigger:focus-visible {{ outline:3px solid var(--qb-accent); outline-offset:3px; }}
  .image-zoom-hint {{ position:absolute; right:10px; bottom:10px; padding:5px 9px; border:1px solid rgba(255,255,255,.35); border-radius:999px; background:rgba(16,24,39,.78); color:#fff; font-size:12px; line-height:1.2; opacity:0; transform:translateY(4px); transition:opacity .16s ease, transform .16s ease; pointer-events:none; }}
  .image-zoom-trigger:hover .image-zoom-hint, .image-zoom-trigger:focus-visible .image-zoom-hint {{ opacity:1; transform:none; }}
  body.image-lightbox-open {{ overflow:hidden; }}
  .image-lightbox {{ width:min(96vw, 1600px); max-width:none; max-height:94vh; padding:0; overflow:hidden; border:1px solid rgba(255,255,255,.18); border-radius:14px; background:#0b1220; color:#fff; box-shadow:0 28px 90px rgba(0,0,0,.48); }}
  .image-lightbox::backdrop {{ background:rgba(3,8,18,.82); backdrop-filter:blur(5px); }}
  .image-lightbox__shell {{ position:relative; display:grid; max-height:94vh; padding:42px 18px 16px; }}
  .image-lightbox__close {{ position:absolute; z-index:1; top:8px; right:10px; width:34px; height:34px; padding:0; border:1px solid rgba(255,255,255,.24); border-radius:50%; background:rgba(255,255,255,.10); color:#fff; font:400 26px/30px Arial,sans-serif; cursor:pointer; }}
  .image-lightbox__close:hover {{ background:rgba(255,255,255,.18); }}
  .image-lightbox__close:focus-visible {{ outline:3px solid #f2c86f; outline-offset:2px; }}
  .image-lightbox__figure {{ display:grid; gap:10px; min-height:0; margin:0; }}
  .image-lightbox__figure img {{ display:block; width:auto; max-width:100%; height:auto; max-height:calc(94vh - 92px); margin:auto; border-radius:8px; object-fit:contain; }}
  .image-lightbox__figure figcaption {{ overflow:hidden; color:#d4dbe7; font-size:12px; line-height:1.5; text-align:center; text-overflow:ellipsis; white-space:nowrap; }}
  .empty {{ color: #8a9099; padding: 12px 0; }}
  .empty.err {{ color: #d33; }}
  pre {{ margin: 0; font-size: 12px; white-space: pre-wrap; word-break: break-all; }}
  .site-footer {{ max-width: 1180px; margin: 0 auto; padding: 0 20px 24px; color: #697586; font-size: 12px; }}
  .footer-inner {{ border-top:1px solid #e2e7ef; padding-top:16px; display:flex; justify-content:space-between; gap:16px; align-items:flex-start; }}
  .footer-brand {{ color:#344054; font-weight:700; margin-bottom:4px; }}
  .footer-note {{ max-width:760px; line-height:1.7; }}
  .footer-link {{ color:#2454a6; text-decoration:none; white-space:nowrap; }}
  .footer-link:hover {{ text-decoration:underline; }}
  @media (max-width: 860px) {{
    .span-full, .span-wide, .span-auto {{ grid-column: span 12; }}
    .card-number.span-auto {{ grid-column: span 6; }}
    h1 {{ font-size:26px; }}
    main {{ padding:14px 12px 22px; }}
    #grid {{ gap:10px; }}
    .card-text {{ grid-template-columns:1fr; gap:8px; padding:13px 14px 14px; }}
    .card-text .card-head {{ margin-bottom:0; }}
    .text-panel {{ max-height:9em; }}
    .card-number {{ min-height:104px; gap:10px; padding:12px 12px 11px; }}
    .card-number .body {{ min-height:52px; }}
    .card-number::before {{ left:12px; right:12px; }}
    .big {{ font-size:24px; }}
    .big .unit {{ font-size:13px; margin-left:4px; }}
    .card-line {{ padding:14px 12px 16px; }}
    .image-lightbox {{ width:96vw; max-height:92vh; border-radius:10px; }}
    .image-lightbox__shell {{ max-height:92vh; padding:40px 10px 10px; }}
    .image-lightbox__figure img {{ max-height:calc(92vh - 82px); }}
    .footer-inner {{ flex-direction:column; }}
  }}
  @media (hover:none) {{
    .image-zoom-hint {{ opacity:1; transform:none; }}
  }}
  @media (prefers-reduced-motion: reduce) {{
    .image-zoom-hint {{ transition:none; }}
  }}
  @media (max-width: 360px) {{
    .card-number.span-auto {{ grid-column: span 12; }}
  }}
  @media (prefers-color-scheme: dark) {{
    body {{ background:#0d1117; color:#c9d1d9; }}
    .card {{ background:#161b22; border-color:#30363d; box-shadow:none; }}
    .card h3 {{ color:#dbe2ee; }}
    .card-head p, .desc {{ color:#8b949e; }}
    .big {{ color:#f0f6fc; }}
    .text-panel {{ color:#c9d1d9; }}
    th, td {{ border-color:#21262d; }} thead th {{ background:#1b2129; }}
    .site-footer {{ color:#8b949e; }}
    .footer-inner {{ border-color:#30363d; }}
    .footer-brand {{ color:#dbe2ee; }}
    .footer-link {{ color:#8fb4ff; }}
  }}
  .std-hero {{ margin:0 0 14px; padding:16px 18px; background:#ffffff; border:1px solid var(--qb-border); border-radius:8px; }}
  .std-hero .eyebrow {{ margin:0 0 7px; color:#8a6a26; font-size:12px; letter-spacing:.06em; text-transform:uppercase; }}
  .std-hero h1 {{ color:#172033; }}
  .std-hero .subtitle {{ color:#475467; }}
  .std-hero .meta-pill {{ background:#eef3f8; color:#4b5b70; }}
  .std-hero .meta-pill-strong {{ background:rgba(216,165,75,.16); color:#87611d; border:1px solid rgba(216,165,75,.34); }}
{shared_css}
</style>
</head>
<body>
{shared_header}
<main{poster_target_attr}>
  {card_runtime_artifacts}
  <section class="std-hero">
    <div class="eyebrow">{mode_note}</div>
    <h1>{title_esc}</h1>
    {f"<p class='subtitle'>{subtitle_esc}</p>" if subtitle_esc else ""}
    <div class="meta-row">
      <span class="meta-pill">{page_type_esc}</span>
      <span class="meta-pill meta-pill-strong">Agent + Skill 生成</span>
      <span class="meta-pill">{mode_label_esc}</span>
    </div>
  </section>
  <div id="grid"></div>
</main>
{shared_footer}
{shared_modal}
<script src="{_ECHARTS_CDN}"></script>
<script>
{shared_runtime_js}
{data_kernel_js}
{render_js}
</script>
{card_runtime_js}
</body>
</html>
"""
    return html


def _host_already_has_kernel(host_html):
    """判断宿主 bespoke 页面是否已经有一份取数内核（marker 版或历史手写等价版）。
    复用 data_kernel_retrofit.py 现成的 marker 常量和指纹判断，不重新发明一套检测逻辑。"""
    if DKR.START in host_html and DKR.END in host_html:
        return True
    return any(
        DKR._is_legacy_kernel(m.group(2))
        for m in DKR.SCRIPT_RE.finditer(host_html)
    )


def _host_has_echarts(host_html):
    """Conservatively detect an ECharts script already owned by the host page."""
    return bool(re.search(
        r"<script\b[^>]*\bsrc\s*=\s*['\"][^'\"]*echarts(?:\.min)?\.js(?:[?#][^'\"]*)?['\"][^>]*>",
        host_html or "",
        re.I,
    ))


def _stock_instance_version(host_html):
    """Return the stock instance version declared by the host, if any."""
    match = re.search(
        r"<script\b[^>]*\bdata-qbv-stock-instance(?:\s*=\s*['\"][^'\"]*['\"])?[^>]*>(.*?)</script\s*>",
        host_html or "",
        re.I | re.S,
    )
    if not match:
        return None
    try:
        payload = json.loads(match.group(1).lstrip('\ufeff').strip() or "{}")
    except (TypeError, ValueError):
        return None
    return str(payload.get("version") or "").strip() or None


def _stock_price_owner_conflict(host_html, panels):
    if _stock_instance_version(host_html) != "stock_analysis_instance_v1":
        return False
    return any(
        isinstance(panel, dict) and str(panel.get("target_selector") or "").strip() == "#priceChart"
        for panel in panels
    )


def cmd_panel_block(params):
    """局部产出模式（emit=panel_block）：只生成 marker 包住的运行时 <script>，不生成整页 HTML
    （不含 <head>/样式/页头页尾/#grid）。供 bespoke 页面把某几个图表交给标准声明式引擎画：
    在 bespoke 布局里摆好容器（如 <div id="priceChart">），panel 里传 target_selector 指向它，
    这段脚本运行时会直接把图渲染进那个容器，不包卡片外壳，bespoke 页面其余布局/样式不受影响。

    生成的页面因此仍然带 QBV_RENDER_JS_START/END marker + BOOT.packages/panels[]，chart_edit.py
    可以照常对其做定点编辑——bespoke 页面里嵌入的这几个图表和整页声明式看板走的是同一套编辑机制。

    参数（与 cmd_build 的 spec 同源，但不需要 title/out_file/upload 这些整页专属字段）：
        {
          "panels": [ ... 同 build_dashboard 的 panel 结构，新增 target_selector（必填，
                       bespoke 页面里已存在的容器选择器）、right_series/dual_axis（双轴，可选）],
          "package_id": "可选，缺省从本地凭证推断",
          "signature":  "可选，缺省从本地凭证补全",
          "formulas":   "可选，随包落进页面供以后编辑溯源",
          "reads":      "可选，同上",
          "include_echarts_cdn": "可选 bool，默认 true；bespoke 页面自己已引入 ECharts 时可传 false 跳过",
          "host_html_file": "可选，目标 bespoke 页面当前 HTML 的本地文件路径；给了这个参数会自动探测宿主"
                            "页面是否已经有取数内核（marker 版或历史手写等价版），有则跳过重复内联"
                            "data-kernel.js（否则两份内核在同一页面里会因为顶层变量重复声明而崩溃）",
          "include_data_kernel": "可选 bool，显式指定要不要内联 data-kernel.js；不传时若给了 "
                                 "host_html_file 走自动探测，否则默认 true（与旧行为一致）"
        }

    返回 {code, script_html, package_id, panels}；script_html 是可以直接粘贴进 bespoke 页面
    <body> 里（放在对应容器之后）的完整 <script> 片段字符串，不落盘、不上传——bespoke 页面的
    发布仍走 compile_bespoke_page.py / static_page.py 常规流程。
    """
    panels = params.get("panels")
    if not isinstance(panels, list) or not panels:
        return {"code": 1, "message": "panels 必须是非空数组"}
    missing_target = [i for i, p in enumerate(panels) if isinstance(p, dict) and not p.get("target_selector")]
    if missing_target:
        return {"code": 1, "message": f"panels{missing_target} 缺少 target_selector（局部产出模式下每个面板都必须指定要渲染进哪个已存在的容器）"}
    image_panel_error = _validate_image_panels(panels)
    if image_panel_error:
        return image_panel_error

    host_html_file = params.get("host_html_file")
    host_html = None
    if host_html_file:
        try:
            host_html = _read_text(_resolve_local_path(host_html_file))
        except OSError as exc:
            return {"code": 1, "message": f"host_html_file 读取失败: {exc}"}
        if _stock_price_owner_conflict(host_html, panels):
            return {
                "code": 1,
                "error": "STOCK_CHART_OWNER_CONFLICT",
                "message": (
                    "stock_analysis_instance_v1 的 #priceChart 由原生 stock runtime 持有，"
                    "禁止再注入 panel_block 形成第二个 renderer；请使用 scripts/stock_comparison.py "
                    "把基准序列并入原生加载与渲染生命周期。"
                ),
                "target_selector": "#priceChart",
                "host_html_file": os.path.abspath(_resolve_local_path(host_html_file)),
            }

    grants, grant_err = _resolve_grant_panels(panels)
    if grant_err:
        return grant_err

    needs_formula = any(
        isinstance(p, dict) and p.get("output") and p.get("_source") != "grant"
        for p in panels
    )
    pkg = sig = None
    if needs_formula or params.get("package_id"):
        pkg, sig, err = _resolve_credential(params)
        if err:
            return err
        if not pkg or not sig:
            return {"code": 1, "message": "需要 package_id + signature 才能在页面内实时取数（signature 可由本地凭证补全）"}
    if not pkg and not grants:
        return {"code": 1, "message": "panels 未引用任何 output（公式包）或 grant_id（数据授权），无法确定取数来源"}

    endpoint = C.endpoint_of(C.load_config())

    packages = []
    if pkg:
        pkg_entry = {"role": "primary", "package_id": pkg, "signature": sig}
        if isinstance(params.get("formulas"), list):
            pkg_entry["formulas"] = params["formulas"]
        if isinstance(params.get("reads"), list):
            pkg_entry["reads"] = params["reads"]
        packages.append(pkg_entry)

    boot = {
        "mode": "live",
        "embedded": True,     # 关键标记：_render_js_for_boot 据此换成嵌入式启动，不接管整页
        "panels": panels,
        "grants": grants or [],
        "endpoint": endpoint,
        "packageId": pkg,
        "signature": sig,
        "packages": packages,
        "skillVersion": C.SKILL_VERSION,
        "skillName": C.SKILL_NAME,
    }

    render_js = _render_js_for_boot(boot)

    include_kernel = params.get("include_data_kernel")
    kernel_skip_reason = None
    if include_kernel is None and host_html is not None:
        if _host_already_has_kernel(host_html):
            include_kernel = False
            kernel_skip_reason = "检测到宿主页面已有取数内核，跳过重复内联（避免同页两份内核顶层变量重复声明报错）"
    if include_kernel is None:
        include_kernel = True  # 缺省行为不变，向后兼容

    data_kernel_js = ""
    if include_kernel:
        data_kernel_js = _read_text(os.path.join(ASSETS_DIR, "data-kernel.js")).replace(
            "__QBV_SKILL_VERSION__", C.SKILL_VERSION or ""
        )

    include_cdn_value = params.get("include_echarts_cdn")
    include_cdn = _as_bool(include_cdn_value, True)
    cdn_skip_reason = None
    if include_cdn_value is None and host_html is not None and _host_has_echarts(host_html):
        include_cdn = False
        cdn_skip_reason = "检测到宿主页面已加载 ECharts，跳过重复 CDN"
    cdn_tag = f'<script src="{_ECHARTS_CDN}"></script>\n' if include_cdn else ""
    kernel_block = (data_kernel_js + "\n") if data_kernel_js else ""
    script_html = (
        cdn_tag
        + "<script>\n"
        + kernel_block
        + render_js + "\n"
        + "</script>"
    )

    message = ("已生成局部产出的运行时 <script> 片段，把它粘贴进 bespoke 页面 <body>（对应 target_selector 容器之后）；"
               "该片段带 QBV_RENDER_JS_START/END marker，之后可用 chart_edit.py 对这些面板做定点编辑。")
    if kernel_skip_reason:
        message += " " + kernel_skip_reason
    if cdn_skip_reason:
        message += " " + cdn_skip_reason

    return {
        "code": 0,
        "package_id": pkg,
        "grants": [g["grant_id"] for g in grants],
        "panels": len(panels),
        "script_html": script_html,
        "size": len(script_html.encode("utf-8")),
        "included_data_kernel": include_kernel,
        "included_echarts_cdn": include_cdn,
        "message": message,
    }


def _normalize_grant_data(kind, data):
    """把数据授权三类 kind 的 data 归一成「对象数组」，供渲染 normalize 与体检统一消费。
    必须与前端 normalizeGrantData 同款口径。无法识别时原样返回 data（走通用兜底）。"""
    if not isinstance(data, dict):
        return data
    k = (kind or "").lower()
    if k == "fast_query":
        results = data.get("results") or []
        has_series = any(
            isinstance(field.get("series"), list)
            for result in results
            for field in (result.get("fields") or [])
        )
        if has_series:
            series_rows = []
            multi_series = len(results) > 1
            for result in results:
                name = result.get("asset_name") or result.get("ticker") or result.get("asset_intent")
                by_date = {}
                date_order = []
                for field in result.get("fields") or []:
                    if not isinstance(field.get("series"), list):
                        continue
                    for point in field["series"]:
                        date = point.get("date")
                        if date not in by_date:
                            by_date[date] = {"标的": name, "日期": date} if multi_series else {"日期": date}
                            date_order.append(date)
                        by_date[date][field.get("intent")] = point.get("value")
                series_rows.extend(by_date[date] for date in date_order)
            if series_rows:
                return series_rows
        rows = []
        multi = len(results) > 1
        for r in results:
            name = r.get("asset_name") or r.get("ticker") or r.get("asset_intent")
            for f in (r.get("fields") or []):
                row = {"标的": name} if multi else {}
                row.update({"指标": f.get("intent"), "值": f.get("value"),
                            "单位": f.get("unit"), "日期": f.get("date")})
                rows.append(row)
        return rows or data
    if k == "composition_select":
        results = data.get("results") or []
        rows = [{"排名": r.get("rank"), "名称": r.get("name"), "代码": r.get("code"),
                 "行业": r.get("industry"), "得分": r.get("score")} for r in results]
        return rows or data
    if k == "stock_profile":
        dims = data.get("dimensions") or {}
        rows = []
        for dname, dobj in dims.items():
            inds = ((dobj or {}).get("indicators")) or {}
            for ik, iv in inds.items():
                iv = iv or {}
                rows.append({"维度": dname, "指标": iv.get("name") or ik,
                             "最新值": iv.get("latest_value"), "单位": iv.get("unit")})
        return rows or data
    return data


def _inspect_output_data(data):
    """对单个产出的 data 做结构体检：健康返回 None，否则返回疑因字符串。
    与前端 normalize 的解包口径一致，专门识别「取数没崩、但实质为空/无有效数值」的假成功。"""
    if data is None:
        return "data 为空（null）"
    if isinstance(data, dict):
        status = str(data.get("status") or "").lower()
        if status in ("failed", "fail", "error"):
            err = data.get("error") or data.get("message") or data.get("reason") or "未提供错误详情"
            return f"data.status={status}：{err}"
        if data.get("success") is False:
            err = data.get("error") or data.get("message") or data.get("reason") or "未提供错误详情"
            return f"data.success=false：{err}"
        # 解包按 read_mode 命名的外层 key（与前端 normalize 对齐）
        for wk in ("range_data", "last_value", "last_day_stats", "last_column_full", "last_valid_per_asset"):
            inner = data.get(wk)
            if isinstance(inner, (dict, list)):
                return _inspect_output_data(inner)
        values = data.get("values")
        if isinstance(values, list) and (not values or all(isinstance(v, dict) for v in values)):
            if not values:
                return "截面 values 为空（目标日期之前无可用数据）"
            if not any(_is_number(row.get("value")) for row in values):
                return "截面 values 不含有效数值"
            return None
        if "dates" in data or "values" in data:   # 序列（range_data）
            dates = data.get("dates")
            if not dates or not values:
                return "range_data 的 dates/values 为空（疑似区间无数据/日期类型不符）"
            flat = []
            for v in values:
                flat.extend(v) if isinstance(v, list) else flat.append(v)
            if not any(isinstance(x, (int, float)) and not isinstance(x, bool) for x in flat):
                return "range_data values 不含有效数值（疑似全 null：日期类型/区间无数据/更新频率不匹配）"
            return None
        if "value" in data:                        # 单值（last_value）
            v = data.get("value")
            return None if isinstance(v, (int, float)) and not isinstance(v, bool) else "last_value.value 非有效数值"
        if data.get("top_values") or data.get("items") or data.get("records"):
            return None
        return None if data else "data 为空对象"
    if isinstance(data, list):
        return None if len(data) > 0 else "data 为空数组"
    if isinstance(data, str):
        return f"data 是字符串而非结构化数据：{data[:80]}"
    return None


def _inspect_outputs(panels, outputs):
    """逐 panel 体检其引用的产出，返回问题列表（空=全部健康）。"""
    problems = []
    for p in panels:
        if (p.get("type") or "").lower() in ("text", "image"):
            continue
        name = p.get("output")
        out = outputs.get(name)
        if out is None:
            problems.append({"output": name, "reason": "取数结果缺该产出"})
            continue
        if out.get("error"):
            problems.append({"output": name, "reason": str(out.get("error"))})
            continue
        why = _inspect_output_data(out.get("data"))
        if why:
            problems.append({"output": name, "reason": why})
    return problems


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _last_numeric(data):
    """Return (value, date) using the same last-effective-value idea as number cards."""
    if data is None:
        return None, None
    if isinstance(data, dict):
        for wk in ("range_data", "last_value", "last_day_stats", "last_column_full", "last_valid_per_asset"):
            inner = data.get(wk)
            if isinstance(inner, (dict, list)):
                return _last_numeric(inner)
        if "dates" in data or "values" in data:
            dates, values = data.get("dates") or [], data.get("values") or []
            if isinstance(values, list):
                if values and all(_is_number(x) or x is None for x in values):
                    for i in range(len(values) - 1, -1, -1):
                        if _is_number(values[i]):
                            d = dates[i] if i < len(dates) else None
                            return float(values[i]), d
                if values and isinstance(values[0], list):
                    # Most range_data payloads are series-oriented: values[0][i].
                    for series in values:
                        if not isinstance(series, list):
                            continue
                        for i in range(len(series) - 1, -1, -1):
                            if _is_number(series[i]):
                                d = dates[i] if i < len(dates) else None
                                return float(series[i]), d
                if values and all(isinstance(row, dict) for row in values):
                    for row in reversed(values):
                        if _is_number(row.get("value")):
                            return float(row["value"]), row.get("date") or data.get("date")
            return None, None
        if "value" in data and _is_number(data.get("value")):
            return float(data.get("value")), data.get("date")
        # Fallback for last_day_stats-like dicts: pick the last numeric field.
        for key in reversed(list(data.keys())):
            if _is_number(data.get(key)):
                return float(data.get(key)), data.get("date") or data.get("trade_date")
    if isinstance(data, list):
        for item in reversed(data):
            val, date = _last_numeric(item)
            if val is not None:
                return val, date
    return None, None


def _single_stock_facts(outputs):
    facts = {}
    for name in ("px", "chg", "ret20", "ret60", "pe", "pb", "amt_yi"):
        out = outputs.get(name) or {}
        val, date = _last_numeric(out.get("data"))
        if val is not None:
            facts[name] = {"value": val, "date": date}
    return facts


_NUM_RE = re.compile(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?")


def _numbers_near_keywords(text, keywords, radius=36):
    hits = []
    if not text:
        return hits
    for m in _NUM_RE.finditer(text):
        start, end = m.span()
        prev_ch = text[start - 1] if start > 0 else ""
        next_ch = text[end] if end < len(text) else ""
        raw = m.group(0)
        # Ignore ISO/date fragments such as 2026-06-16 or 2026年.
        if raw.startswith("-") and prev_ch.isdigit():
            continue
        if prev_ch in ("-", "/", ".") or next_ch in ("-", "/", ".", "年", "月", "日"):
            continue
        if len(raw) == 4 and raw.startswith("20"):
            continue
        window = text[max(0, start - radius): min(len(text), end + radius)]
        if any(k in window for k in keywords):
            try:
                hits.append(float(raw.replace(",", "")))
            except ValueError:
                pass
    return hits


def _close_enough(actual, claimed, *, abs_tol, rel_tol=0.0):
    return abs(actual - claimed) <= max(abs_tol, abs(actual) * rel_tol)


def _validate_single_stock_copy_consistency(params, panels, outputs):
    """Validate key prose numbers against the build-time verification outputs for single-stock pages."""
    if not _is_single_stock_candidate(params):
        return None, None
    if _as_bool(params.get("allow_inconsistent_copy"), False):
        return None, _single_stock_facts(outputs)

    facts = _single_stock_facts(outputs)
    text_parts = [str(params.get("subtitle") or "")]
    for p in panels:
        if isinstance(p, dict) and (p.get("type") or "").lower() == "text":
            text_parts.append(str(p.get("text") or p.get("content") or p.get("description") or ""))
    text = "\n".join(text_parts)

    metric_rules = [
        ("px", "最新收盘价", ("收盘", "收盘价", "最新价"), 0.05, 0.001),
        ("chg", "日涨跌幅", ("涨跌幅", "单日", "当日", "日涨"), 0.08, 0.0),
        ("ret20", "20日表现", ("20日", "20 日"), 0.12, 0.0),
        ("ret60", "60日表现", ("60日", "60 日"), 0.12, 0.0),
        ("pe", "PE(TTM)", ("PE", "市盈率"), 0.08, 0.001),
        ("pb", "PB", ("PB", "市净率"), 0.08, 0.001),
        ("amt_yi", "成交额(亿元)", ("成交额",), 0.2, 0.01),
    ]

    mismatches = []
    for output, label, keywords, abs_tol, rel_tol in metric_rules:
        fact = facts.get(output)
        if not fact:
            continue
        actual = fact["value"]
        claims = _numbers_near_keywords(text, keywords)
        if not claims:
            continue
        if any(_close_enough(actual, n, abs_tol=abs_tol, rel_tol=rel_tol) for n in claims):
            continue
        mismatches.append({
            "output": output,
            "label": label,
            "expected": round(actual, 4),
            "claimed_near_keywords": [round(n, 4) for n in claims[:6]],
        })

    if not mismatches:
        return None, facts
    return {
        "code": 1,
        "message": "单标的画像页文案与实时取数结果不一致，拒绝生成/上传",
        "mismatches": mismatches,
        "facts": {k: {"value": round(v["value"], 4), "date": v.get("date")} for k, v in facts.items()},
        "hint": "请用 build_dashboard 实时取数结果（最终 outputs）里的数值重写 subtitle 和阅读摘要，不要使用旧查询结果或手工估算值。",
    }, facts


def _is_single_stock_candidate(params):
    """Detect specs that claim to be the standard single-stock factsheet."""
    brand = params.get("brand") if isinstance(params.get("brand"), dict) else {}
    template = str(params.get("template") or params.get("page_template") or "").strip().lower()
    if template in ("single-stock", "single_stock", "stock-factsheet"):
        return True
    if str(params.get("template_contract") or "").strip().lower() in ("custom", "none", "off"):
        return False
    text = " ".join(
        str(v or "")
        for v in (
            params.get("title"),
            params.get("page_type"),
            brand.get("page_type"),
        )
    )
    return any(
        k in text
        for k in (
            "个股画像",
            "单股画像",
            "单标的画像",
            "股票画像",
            "单只股票",
            "单股",
        )
    )


def _validate_template_contract(params, panels):
    """Hard guardrails for reusable templates so agents do not silently emit stale layouts."""
    if not _is_single_stock_candidate(params):
        return None
    if _as_bool(params.get("allow_custom_single_stock"), False):
        return None

    outputs = {
        str(p.get("output"))
        for p in panels
        if isinstance(p, dict) and p.get("output")
    }
    required = {"px", "chg", "ret20", "ret60", "pe", "pb", "amt_yi"}
    missing = sorted(required - outputs)
    has_text = any((p.get("type") or "").lower() == "text" for p in panels if isinstance(p, dict))
    has_px_number = any(
        p.get("output") == "px" and (p.get("type") or "").lower() == "number"
        for p in panels
        if isinstance(p, dict)
    )
    has_px_line = any(
        p.get("output") == "px" and (p.get("type") or "").lower() == "line"
        for p in panels
        if isinstance(p, dict)
    )

    issues = []
    if missing:
        issues.append("缺少默认 outputs: " + ", ".join(missing))
    if not has_text:
        issues.append("缺少阅读摘要 text panel")
    if not has_px_number:
        issues.append("缺少最新收盘价 number panel（output=px）")
    if not has_px_line:
        issues.append("缺少近一年收盘价 line panel（output=px）")
    if not issues:
        return None

    return {
        "code": 1,
        "message": "单标的画像页未满足模板契约，拒绝生成旧版 1 条线 + 少量数字卡页面",
        "template": "online templates / single-stock contract",
        "issues": issues,
        "hint": "请先通过 static_page.py templates/template 复用在线个股画像模板；若自行构建 spec，保留 template=single-stock，并补齐阅读摘要、px/chg/ret20/ret60/pe/pb/amt_yi、subtitle 与日期口径。",
    }


def _validate_image_panels(panels):
    for index, panel in enumerate(panels):
        if not isinstance(panel, dict) or (panel.get("type") or "").lower() != "image":
            continue
        image_url = str(panel.get("image_url") or "").strip()
        if not re.fullmatch(r"https://pages\.quantbuddy\.cn/pages/assets/[^/]+/asset_[0-9a-f]{24}\.webp", image_url):
            return {
                "code": 1,
                "error": "IMAGE_URL_REQUIRED",
                "message": f"panels[{index}] image 只接受已上传的 pages.quantbuddy.cn 托管 WebP image_url",
            }
        if not str(panel.get("alt") or "").strip():
            return {"code": 1, "error": "IMAGE_ALT_REQUIRED", "message": f"panels[{index}] image.alt 必填"}
        if "zoomable" in panel and not isinstance(panel.get("zoomable"), bool):
            return {"code": 1, "error": "IMAGE_ZOOMABLE_INVALID", "message": f"panels[{index}] image.zoomable 必须是布尔值"}
    return None


def _manifest_path_for(out_file):
    root, _ext = os.path.splitext(out_file)
    return root + ".manifest.json"


def _write_manifest(out_file, manifest):
    path = _manifest_path_for(out_file)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return path


def _resolve_local_path(path):
    if not path:
        return None
    return path if os.path.isabs(path) else os.path.join(C.SKILL_ROOT, path)



def cmd_build(params):
    task_id = str((params or {}).get("task_id") or C.current_trace_context().get("task_id") or "").strip()
    if task_id:
        import static_page as SP
        routing, _, routing_error = SP._read_routing_credential(task_id)
        if routing_error:
            return routing_error
        existing_page_error = SP._existing_page_mutation_error(
            {**(params or {}), "task_id": task_id}, action="build_dashboard"
        )
        if existing_page_error:
            return existing_page_error
        decision = (routing or {}).get("routing_decision") if isinstance((routing or {}).get("routing_decision"), dict) else {}
        if decision.get("mode") == "fork":
            borrow_mode = str(decision.get("borrow_mode") or "")
            emit = str((params or {}).get("emit") or "").strip().lower()
            if borrow_mode != "compose" or emit != "panel_block":
                return {
                    "code": 1,
                    "error": "FORK_BUILD_MODE_FORBIDDEN",
                    "message": (
                        "fork/inherit* 不能用 build_dashboard 重建整页；fork/compose 也只允许 "
                        "emit=panel_block 生成局部模块，并且必须先完成 fork_compose 借鉴绑定。"
                    ),
                    "task_id": task_id,
                    "borrow_mode": borrow_mode,
                    "allowed_action": "fork_compose_then_build_dashboard_panel_block",
                }
            compose, compose_error = SP._compose_binding_publish_state(routing, str((routing or {}).get("page_id") or ""))
            if compose_error:
                return compose_error
            if not compose:
                return {
                    "code": 1, "error": "COMPOSE_BINDING_REQUIRED",
                    "message": "emit=panel_block 前必须先运行 research_templates → fork_compose。",
                }
        binding, _, binding_error = SP._read_fork_task_binding(task_id)
        if binding_error:
            return binding_error
        if isinstance(binding, dict) and binding.get("status") == "prepared":
            return {
                "code": 1,
                "error": "FORK_TASK_BOUND",
                "message": "当前 task 已进入 fork 分支，禁止 build_dashboard；请继续编辑 working_html_file 并调用 fork_validate",
                "task_id": task_id,
                "source_template_id": binding.get("source_template_id") or "",
                "working_html_file": binding.get("working_html_file") or "",
                "fork_manifest_file": binding.get("fork_manifest_file") or "",
                "next_command": "static_page.py fork_validate",
            }
    title = params.get("title")
    if not title:
        return {"code": 1, "message": "spec 缺少 title"}
    panels = params.get("panels")
    if not isinstance(panels, list) or not panels:
        return {"code": 1, "message": "spec.panels 必须是非空数组"}
    image_panel_error = _validate_image_panels(panels)
    if image_panel_error:
        return image_panel_error
    template_err = _validate_template_contract(params, panels)
    if template_err:
        return template_err
    # 页面实时取数；spec 不需要 mode 字段，旧 spec 里残留的 mode 兼容忽略。
    legacy_mode = (params.get("mode") or "").lower()

    # panel 支持两种取数来源、可同页并存：output→公式包（钉死+可重算）；grant_id→数据授权（钉死+不重算）。
    grants, grant_err = _resolve_grant_panels(panels)
    if grant_err:
        return grant_err

    needs_formula = any(
        isinstance(p, dict) and p.get("output") and p.get("_source") != "grant"
        for p in panels
    )

    pkg = sig = None
    if needs_formula or params.get("package_id"):
        pkg, sig, err = _resolve_credential(params)
        if err:
            return err
        if not pkg or not sig:
            return {"code": 1, "message": "需要 package_id + signature 才能在页面内实时取数（signature 可由本地凭证补全）"}

    static_only = all(
        isinstance(p, dict) and (p.get("type") or "").lower() in ("text", "image")
        for p in panels
    )
    if not pkg and not grants and not static_only:
        return {"code": 1, "message": "spec.panels 未引用任何 output（公式包）或 grant_id（数据授权），无法确定取数来源"}

    endpoint = C.endpoint_of(C.load_config())  # query 无需 api_key，仅取 endpoint

    # 构建期取一次数：只用于质量体检 + 单标的文案一致性校验，不内联进 HTML（页面仍走运行时实时取数）。
    verify_outputs = {}
    if pkg:
        res = FP.query_package(endpoint, pkg, sig)
        if res.get("code") != 0:
            return {"code": 1, "message": "构建期取数失败，无法校验看板（公式 / 读取模式 / 凭证 / 端点 任一异常）",
                    "failures": res.get("failures"), "query_result": res}
        verify_outputs.update(res.get("outputs") or {})
    for g in grants:
        try:
            gr = FQCSV.hydrate_query_result(
                lambda g=g: DG.query_grant(endpoint, g["grant_id"], g["signature"]),
                timeout=20,
                max_workers=4,
            )
        except FQCSV.CsvHydrationError as exc:
            return {"code": 1,
                    "message": f"构建期 CSV 取数失败（数据授权 grant_id={g['grant_id']}）：{exc}",
                    "grant_id": g["grant_id"]}
        if gr.get("code") != 0:
            return {"code": 1, "message": f"构建期取数失败（数据授权 grant_id={g['grant_id']}），拒绝生成看板",
                    "grant_id": g["grant_id"], "query_result": gr}
        verify_outputs[g["grant_id"]] = {"data": _normalize_grant_data(gr.get("kind"), gr.get("data")), "error": None}
    # P0-1 数据体检：取数即便 code:0，也逐 panel 校验产出结构，杜绝「假成功看板」
    problems = _inspect_outputs(panels, verify_outputs)
    if problems:
        return {"code": 1,
                "message": "取数体检未通过，拒绝生成可能假成功的看板（请检查公式 / 读取模式 / 日期区间）",
                "failed_outputs": problems}
    copy_err, single_stock_facts = _validate_single_stock_copy_consistency(params, panels, verify_outputs)
    if copy_err:
        return copy_err

    generated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    live_card_enabled = params.get("live_card") is not None and params.get("live_card") is not False
    html = _render_html(params, title=title, subtitle=params.get("subtitle"),
                        panels=panels, endpoint=endpoint, package_id=pkg, signature=sig,
                        generated_at=generated_at, grants=grants)

    out_file = params.get("out_file")
    if out_file:
        if not os.path.isabs(out_file):
            out_file = os.path.join(C.SKILL_ROOT, out_file)
    else:
        os.makedirs(PAGES_DIR, exist_ok=True)
        out_file = os.path.join(PAGES_DIR, _slug(title) + ".html")
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(html)

    manifest = {
        "schema_version": 1,
        "page_id": None,
        "url": None,
        "html_file": out_file,
        "html_sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
        "endpoint": endpoint,
        "formula_packages": ({
            "DEFAULT": {
                "package_id": pkg,
                "outputs": [
                    p.get("output") for p in panels
                    if isinstance(p, dict) and p.get("output") and p.get("_source") != "grant"
                ],
            }
        } if pkg else {}),
        "data_grants": [
            {
                "grant_id": g["grant_id"],
                "outputs": [
                    p.get("output") for p in panels
                    if isinstance(p, dict) and p.get("grant_id") == g["grant_id"]
                ],
            }
            for g in grants
        ],
        "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "verification": {
            "build_time_query": "ok",
            "output_health": "ok",
            "publish_runtime_check": "not_run",
        },
        "card_runtime": {
            "enabled": live_card_enabled,
        },
    }
    manifest_path = _write_manifest(out_file, manifest)

    page_mode = "live" if pkg or grants else "static"
    result = {
        "code": 0,
        "out_file": out_file,
        "mode": page_mode,
        "package_id": pkg,
        "grants": [g["grant_id"] for g in grants],
        "panels": len(panels),
        "size": len(html.encode("utf-8")),
        "manifest": manifest_path,
        "message": "已生成实时取数看板 HTML" if page_mode == "live" else "已生成静态看板 HTML",
    }
    if legacy_mode and legacy_mode != page_mode:
        result["note"] = f"spec 里的 mode 字段已忽略，页面按实际数据源生成 {page_mode} 模式。"
    if single_stock_facts:
        result["facts"] = {
            k: {"value": round(v["value"], 4), "date": v.get("date")}
            for k, v in single_stock_facts.items()
        }

    update_page_id = params.get("update_page_id")
    if params.get("upload") or update_page_id:
        import static_page as SP
        # 页面说明（列表/详情展示用）：仅显式传 spec.description 时透传；不传则不动（update 保留原值）
        page_desc = params.get("description")
        reply_params, reply_resolution, reply_error = SP._resolve_publish_agent_reply_template(
            {
                **params,
                "title": title,
                "description": page_desc,
                "primary_outputs": [
                    p.get("output") or p.get("title")
                    for p in panels
                    if isinstance(p, dict) and (p.get("output") or p.get("title"))
                ],
            },
            html=html,
        )
        if reply_error:
            return reply_error
        reply_metadata = {
            "page_context": reply_params.get("page_context"),
            "agent_reply_template": reply_params.get("agent_reply_template"),
        }
        result["agent_reply_template_resolution"] = reply_resolution
        if update_page_id:
            # 替换已发布页面：URL / page_id 不变，已分享链接照常可用
            up = SP.cmd_update({
                "page_id": update_page_id,
                "html_file": out_file,
                "title": title,
                "description": page_desc,
                "ttl_days": params.get("ttl_days"),
                "verify_packages": params.get("verify_packages"),
                "verify_card_runtime": params.get("verify_card_runtime"),
                **reply_metadata,
            })
            result["update"] = up
            verb = "替换"
        else:
            up = SP.cmd_upload({
                "html_file": out_file,
                "title": title,
                "description": page_desc,
                "ttl_days": params.get("ttl_days"),
                "verify_packages": params.get("verify_packages"),
                "verify_card_runtime": params.get("verify_card_runtime"),
                **reply_metadata,
            })
            result["upload"] = up
            verb = "上传"
        if up.get("code") == 0 and up.get("url"):
            result["url"] = up["url"]
            manifest["page_id"] = up.get("page_id")
            manifest["url"] = up.get("url")
            if up.get("card_runtime_verification"):
                manifest["verification"]["card_runtime"] = "ok"
            manifest["verification"]["publish_runtime_check"] = (
                (up.get("_package_runtime_check") or {}).get("status")
                or "not_verifiable_by_publish_key"
            )
            manifest_path = _write_manifest(out_file, manifest)
            result["manifest"] = manifest_path
        elif up.get("code") != 0:
            result["message"] += f"（HTML 已生成，但{verb}失败，见 {'update' if update_page_id else 'upload'} 字段）"
            manifest["verification"]["publish_runtime_check"] = "upload_failed"
            manifest_path = _write_manifest(out_file, manifest)
            result["manifest"] = manifest_path

    return result


def main():
    params = C.read_params(sys.argv[1:], env_var="BD_PARAMS")
    emit = str((params or {}).get("emit") or "").strip().lower()
    try:
        if emit == "panel_block":
            result = cmd_panel_block(params)
        else:
            result = cmd_build(params)
    except (FileNotFoundError, ValueError) as e:
        result = {"code": 1, "message": str(e)}
    C.emit(result, out_name="bd_out.txt")
    sys.exit(0 if (isinstance(result, dict) and result.get("code") == 0) else 1)


if __name__ == "__main__":
    main()
