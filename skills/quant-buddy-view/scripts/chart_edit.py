#!/usr/bin/env python3
r"""
已发布页面的图表增删改查（chart edit） —— 只改一个面板/一条线，不牵连页面上其它已有内容。

工具说明文档：tools/chart_edit.md
背景/设计动机：workflows/edit-existing-chart.md

为什么需要这个脚本：build_dashboard.py 生成的页面是"一份 HTML = 若干面板 + 若干公式包"，过去任何一次
编辑（哪怕只是给一张折线图叠加一条新线）都被当成整页重建：把页面上*所有*公式（包括跟这次改动毫不相关
的）重新丢进 runMultiFormulaBatchStream + register，再整份 HTML 覆盖上传。本脚本把"增/删/改窗口/查"
做成四个定点操作：

  · add_series    只注册一个只含"新公式"的最小公式包，往目标面板追加这一条线；页面上其它面板/公式包
                   原样保留，不重新校验/计算。
  · remove_series  纯粹是把某个 output 从面板配置里摘掉（面板只剩这一条线时连面板一起删），不调用任何
                   formula_package 接口——旧公式包留着任其 TTL 到期，不主动 revoke（可能被其它面板复用）。
  · set_window     目标窗口落在"已经取过的范围"内 → 只改前端展示裁剪，不碰后端；只有目标窗口超出已注册
                   范围，才重新注册——而且只重新注册这一个 output 的公式，不牵连页面上其它系列。
  · query_data     页面本身不内嵌真实数据（只有 package_id+signature），要看真实数值必须显式取数——
                   这条路径是把 formula_package.py query 包一层，凭页面记录的凭证直接查。
  · inspect        只读：解析页面当前有哪些面板、每个面板依赖哪些 output、每个 output 由哪个公式包
                   （含公式文本/读取窗口——"编辑溯源清单"）提供，取代过去临时 grep/sed 页面源码猜结构。

对 HTML 的改动统一走"定点替换 render_js 这一块 <script>"（marker 见 build_dashboard.
RENDER_JS_START_MARKER/END_MARKER），页面壳/样式/无关面板保持字节级不变；顺带把这一块 JS 换成当前版本，
即便页面是旧版 build_dashboard 生成也会被升级到支持多公式包/多产出叠加面板的运行时。若页面连这个 marker
都没有（本次改动之前生成、从未被 chart_edit.py 碰过的老页面），一律返回 legacy，交给
workflows/dashboard-end-to-end.md 的整页重建流程兜底，不强行升级。

渲染器升级到当前版本的同时，取数内核（QB_DATA_KERNEL marker 或历史手写等价版）与 BOOT.skillVersion
也会原子同步到当前版本（见 _patch_page），避免"新渲染器 + 旧内核"混装导致 QB.runtime 等新接口调用
在旧内核上报错、取数被静默跳过却仍回报"叠加成功"。内核升级失败（页面结构异常）会直接拒绝写回。

子命令：
    inspect        {page_id}
    add_series     {page_id, panel, formula|formulas, output_name, read_mode?, mode_params?, begin_date?, ttl_days?}
    remove_series  {page_id, panel, output_name?}   # 不传 output_name = 整个面板一起删
    set_window     {page_id, panel, output_name, start_date|lookback_days, ttl_days?}
    query_data     {page_id, output_name, result_mode?, package_id?}

参数传递（规避 PowerShell GBK 截断中文）：优先级 CE_PARAMS 环境变量 > @file > 命令行 JSON > stdin。

用法示例：
    python scripts/chart_edit.py inspect '{"page_id":"page_xxx"}'
    python scripts/chart_edit.py add_series @add_hs300.json
    python scripts/chart_edit.py remove_series '{"page_id":"page_xxx","panel":"机器人产业链观察指数","output_name":"沪深300指数"}'
    python scripts/chart_edit.py set_window '{"page_id":"page_xxx","panel":0,"output_name":"机器人链观察指数","start_date":"2022-01-01"}'
    python scripts/chart_edit.py query_data '{"page_id":"page_xxx","output_name":"机器人链观察指数","result_mode":"full"}'

panel 选择器（panel 参数）：0-based 整数下标 / 面板 title 精确匹配 / 该面板当前引用的某个 output 名。

输出：结果打印到 stdout（UTF-8），并写入临时目录下 ce_out.txt。
"""

import datetime as _dt
import json
import re
import sys

import build_dashboard as BD
import common as C
import data_kernel_retrofit as DKR
import formula_package as FP
import session_complete as SC
import static_page as SP

# 结尾的 \n? 必须跟 BD._RENDER_JS_TEMPLATE 的收尾方式对齐（模板本身以 END marker + 一个换行结束），
# 否则每 patch 一次都会在 </script> 前多攒一个空行。
_RENDER_BLOCK_RE = re.compile(
    re.escape(BD.RENDER_JS_START_MARKER) + r".*?" + re.escape(BD.RENDER_JS_END_MARKER) + r"\n?", re.S
)
_BOOT_MARK_RE = re.compile(r"const\s+BOOT\s*=\s*")
_DATE8_RE = re.compile(r"^\d{8}$")
_DATE_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class _ChartEditError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


# ────────────────────────────────────────────────
# HTML <-> BOOT 定点解析/回写
# ────────────────────────────────────────────────

def _extract_boot(html):
    """从页面 HTML 里定点抠出 BOOT 对象。返回 (boot_dict, (start,end), error_code|None)。
    error_code=NO_RENDER_JS_MARKER 表示这是本次改动之前生成的老页面（没有可定点替换的运行时区块）。
    BOOT 边界靠 json.JSONDecoder().raw_decode 定位（解析到哪就停），不要求 `const BOOT = {...};`
    后面紧跟 `let LAST_OUTPUTS`——这样 marker 区块内部多出的空白/注释/其它代码不会让解析直接失败。"""
    m = _RENDER_BLOCK_RE.search(html or "")
    if not m:
        return None, None, "NO_RENDER_JS_MARKER"
    block = m.group(0)
    bm = _BOOT_MARK_RE.search(block)
    if not bm:
        return None, None, "BOOT_NOT_FOUND"
    try:
        boot, _end = json.JSONDecoder().raw_decode(block, bm.end())
    except (ValueError, TypeError) as exc:
        return None, None, f"BOOT_PARSE_ERROR: {exc}"
    return boot, m.span(), None


def _patch_page(html, mutate_fn):
    """解析 BOOT → mutate_fn(boot) 返回改好的 boot → 用当前 render_js 模板 + 新 BOOT 整体换掉那一块
    <script>（顺带把运行时 JS 升级到当前版本），页面其余内容原样保留。mutate_fn 可以抛 _ChartEditError。
    换回时用 BD._render_js_for_boot（而不是直接套标准模板）——它会看 boot.embedded 是否为真来选
    嵌入式还是整页启动方式，保证 bespoke 页面里用 emit=panel_block 嵌入的图表被编辑后不会被错误地
    换成会接管整页、二次初始化 QBShareShell 的启动逻辑。

    渲染器既然换成了当前版本，BOOT.skillVersion/skillName 与取数内核必须原子跟着同步，否则会出现
    "新渲染器调用的 QB.runtime 等接口在旧内核上不存在"这类静默取数失败（旧内核/新渲染器混装）。
    是否同步内核只看这个页面自己的 HTML 里有没有内联内核（BD._host_already_has_kernel，与
    cmd_panel_block 判断"宿主是否已有内核"复用同一份指纹逻辑），不看 boot.embedded：
    embedded 只表示这块面板用嵌入式启动而不接管整页，不代表内核就一定托管在别的宿主文件里——
    实测 embedded:true 的页面照样会把内核和渲染器一起内联在同一份 HTML 里，这种页面同样需要
    (且必须) 被同步升级。只有当页面 HTML 里确实找不到任何内联内核时才跳过（真正的外部宿主场景，
    内核不归这里管）。内核升级不了（页面结构异常，命中数量不为一）就直接拒绝写回，不能让页面带着
    不兼容的组合被静默发布成功。"""
    boot, span, err = _extract_boot(html)
    if err:
        return None, err
    new_boot = mutate_fn(boot)
    new_boot["skillVersion"] = C.SKILL_VERSION
    new_boot["skillName"] = C.SKILL_NAME
    new_block = BD._render_js_for_boot(new_boot)
    start, end = span
    patched = html[:start] + new_block + html[end:]
    if not BD._host_already_has_kernel(patched):
        return patched, None
    try:
        patched, _matched_by = DKR.retrofit_html(patched)
    except DKR.RetrofitError as exc:
        return None, f"KERNEL_RETROFIT_FAILED: {exc}"
    return patched, None


def _normalize_boot_packages(boot):
    """BOOT.packages（数组）优先；缺省时从旧版单包字段 packageId/signature 合成一个元素——
    与 render_js 里的 resolvePackages() 同一套兜底逻辑，保证两边判断一致。"""
    packages = boot.get("packages")
    if isinstance(packages, list) and packages:
        return [dict(p) for p in packages if isinstance(p, dict)]
    if boot.get("packageId"):
        return [{"role": "primary", "package_id": boot.get("packageId"), "signature": boot.get("signature")}]
    return []


def _panel_output_names(panel):
    if isinstance(panel.get("outputs"), list) and panel["outputs"]:
        return list(panel["outputs"])
    if panel.get("output"):
        return [panel["output"]]
    return []


def _find_panel_index(panels, selector):
    if isinstance(selector, bool):
        return None
    if isinstance(selector, int):
        return selector if 0 <= selector < len(panels) else None
    if isinstance(selector, str):
        s = selector.strip()
        if s.isdigit():
            idx = int(s)
            return idx if 0 <= idx < len(panels) else None
        for i, p in enumerate(panels):
            if isinstance(p, dict) and str(p.get("title") or "").strip() == s:
                return i
        for i, p in enumerate(panels):
            if isinstance(p, dict) and s in _panel_output_names(p):
                return i
    return None


def _find_package_for_output(packages, output_name):
    matches = [
        p for p in packages
        if any(isinstance(r, dict) and r.get("output") == output_name for r in (p.get("reads") or []))
    ]
    if matches:
        return matches[0]
    if len(packages) == 1:
        return packages[0]
    return None


def _parse_date(value):
    """接受 YYYYMMDD（int/str）或 YYYY-MM-DD，返回 datetime.date；解析失败返回 None。"""
    if value is None:
        return None
    s = str(value).strip()
    if _DATE8_RE.fullmatch(s):
        return _dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    if _DATE_ISO_RE.fullmatch(s):
        y, m, d = s.split("-")
        return _dt.date(int(y), int(m), int(d))
    return None


def _fmt_date(d):
    return d.strftime("%Y-%m-%d")


def _download_page(params):
    return SP.cmd_download({"page_id": params.get("page_id"), "task_id": params.get("task_id")})


def _update_page(params, html):
    out = SP.cmd_update({"page_id": params.get("page_id"), "html": html, "task_id": params.get("task_id")})
    # 增量编辑不产出 reply_validation_command，走不到 validate_agent_reply.py 里的终态埋点，
    # 所以在这里补一次上报。best-effort，失败不影响编辑结果。
    if isinstance(out, dict) and out.get("code") == 0:
        SC.report(
            params.get("task_id") or C.current_trace_context().get("task_id"),
            public_url=out.get("url") or out.get("public_url") or "",
            user_query=C.current_trace_context().get("user_query") or "",
            operation="chart_edit",
        )
    return out


# ────────────────────────────────────────────────
# 子命令
# ────────────────────────────────────────────────

def cmd_inspect(params):
    page_id = params.get("page_id")
    if not page_id:
        return {"code": 1, "message": "inspect 需要 page_id"}
    dl = _download_page(params)
    if dl.get("code") != 0:
        return dl  # 透传 FORBIDDEN / PAGE_NOT_FOUND 等

    boot, _span, err = _extract_boot(dl.get("html") or "")
    if err:
        return {
            "code": 0,
            "page_id": page_id,
            "legacy": True,
            "reason": err,
            "message": "该页面没有 QBV_RENDER_JS_START/END marker，不支持定点增量编辑。"
                       "若这是 bespoke（手写 canvas/SVG）页面：折线/柱状/双轴/雷达图这类图表可以用 "
                       "build_dashboard.py（emit=panel_block）重新生成成局部嵌入的声明式图表块、"
                       "替换掉原来手写的那部分（见 guides/bespoke-page.md），换成这种写法之后该图表"
                       "就能用 chart_edit.py 定点编辑；仪表盘/水位条这类非图表指标组件不受影响，继续手写。"
                       "如果不打算升级模板，或改动本质要求整页重算/换版式，才落回 "
                       "workflows/dashboard-end-to-end.md 的整页重建流程。",
        }

    packages = _normalize_boot_packages(boot)
    panels_out = []
    for i, p in enumerate(boot.get("panels") or []):
        if not isinstance(p, dict):
            continue
        panels_out.append({
            "index": i,
            "title": p.get("title"),
            "type": p.get("type") or "table",
            "output": p.get("output"),
            "outputs": p.get("outputs"),
            "x_range": p.get("x_range"),
        })
    packages_out = [
        {
            "role": p.get("role"),
            "package_id": p.get("package_id"),
            "formulas": p.get("formulas"),
            "reads": p.get("reads"),
            "begin_date": p.get("begin_date"),
            "formulas_known": bool(p.get("formulas") and p.get("reads")),
        }
        for p in packages
    ]
    return {
        "code": 0,
        "page_id": page_id,
        "legacy": False,
        "panels": panels_out,
        "packages": packages_out,
        "grants": boot.get("grants") or [],
    }


def cmd_add_series(params):
    page_id = params.get("page_id")
    panel_sel = params.get("panel")
    output_name = params.get("output_name")
    formulas = params.get("formulas")
    if not formulas and params.get("formula"):
        formulas = [params["formula"]]
    if not page_id or panel_sel is None or not output_name or not formulas:
        return {"code": 1, "message": "add_series 需要 page_id, panel, output_name, formula(s)"}
    axis = params.get("axis")
    if axis not in (None, "left", "right"):
        return {"code": 1, "message": "add_series 的 axis 只接受 left/right（缺省 left，不建双轴）"}

    dl = _download_page(params)
    if dl.get("code") != 0:
        return dl
    html = dl.get("html") or ""
    boot, _span, err = _extract_boot(html)
    if err:
        return {"code": 1, "error": "LEGACY_PAGE", "reason": err,
                "message": "该页面不支持定点增量编辑，请走整页重建流程（dashboard-end-to-end.md）"}
    if _find_panel_index(boot.get("panels") or [], panel_sel) is None:
        return {"code": 1, "error": "PANEL_NOT_FOUND", "message": f"未找到面板: {panel_sel}"}

    read_mode = params.get("read_mode") or "range_data"
    reads = [{"output": output_name, "read_mode": read_mode, "mode_params": params.get("mode_params") or {}}]
    register_body = {"formulas": formulas, "reads": reads}
    for k in ("intents", "begin_date", "ttl_days"):
        if params.get(k) is not None:
            register_body[k] = params[k]
    reg = FP.cmd_register(register_body)
    if reg.get("code") != 0:
        return {"code": 1, "message": "新增系列的公式包注册失败（只含这条新线的公式，与页面上其它系列无关）",
                "register_result": reg}

    new_pkg_entry = {
        "role": output_name, "package_id": reg["package_id"], "signature": reg["signature"],
        "formulas": formulas, "reads": reads,
    }
    if params.get("begin_date") is not None:
        new_pkg_entry["begin_date"] = params["begin_date"]

    def mutate(boot):
        packages = _normalize_boot_packages(boot)
        packages.append(new_pkg_entry)
        boot["packages"] = packages
        idx = _find_panel_index(boot.get("panels") or [], panel_sel)
        if idx is None:
            raise _ChartEditError("PANEL_NOT_FOUND", f"未找到面板: {panel_sel}")
        panel = boot["panels"][idx]
        names = _panel_output_names(panel)
        if output_name not in names:
            names.append(output_name)
        panel["outputs"] = names
        panel.pop("output", None)
        if axis == "right":
            right_series = list(panel.get("right_series") or [])
            if output_name not in right_series:
                right_series.append(output_name)
            panel["right_series"] = right_series
            panel["dual_axis"] = True
        return boot

    try:
        new_html, perr = _patch_page(html, mutate)
    except _ChartEditError as exc:
        return {"code": 1, "error": exc.code, "message": exc.message, "package_id": reg["package_id"]}
    if perr:
        return {"code": 1, "error": perr, "message": "页面 patch 失败（BOOT 解析或内核/渲染器版本同步失败），未写回", "package_id": reg["package_id"]}

    up = _update_page(params, new_html)
    if up.get("code") != 0:
        return {"code": 1, "message": "页面更新失败（公式包已注册成功，仅页面写回失败）",
                "update_result": up, "package_id": reg["package_id"]}
    axis_note = "，已归入右轴（双轴）" if axis == "right" else ""
    return {
        "code": 0, "page_id": page_id, "package_id": reg["package_id"], "output_name": output_name,
        "url": up.get("url"),
        "message": f"已叠加新系列 {output_name}{axis_note}：只注册了这条新线的公式，页面上其它已有系列未重新验证/计算",
    }


def cmd_remove_series(params):
    page_id = params.get("page_id")
    panel_sel = params.get("panel")
    output_name = params.get("output_name")
    if not page_id or panel_sel is None:
        return {"code": 1, "message": "remove_series 需要 page_id, panel（output_name 可选：不传则整个面板一起删）"}

    dl = _download_page(params)
    if dl.get("code") != 0:
        return dl
    html = dl.get("html") or ""

    removed_whole_panel = {"value": False}

    def mutate(boot):
        panels = boot.get("panels") or []
        idx = _find_panel_index(panels, panel_sel)
        if idx is None:
            raise _ChartEditError("PANEL_NOT_FOUND", f"未找到面板: {panel_sel}")
        panel = panels[idx]
        if not output_name:
            panels.pop(idx)
            removed_whole_panel["value"] = True
            boot["panels"] = panels
            return boot
        names = _panel_output_names(panel)
        if output_name not in names:
            raise _ChartEditError("OUTPUT_NOT_ON_PANEL", f"面板未引用 output={output_name}")
        names.remove(output_name)
        if not names:
            panels.pop(idx)
            removed_whole_panel["value"] = True
        elif len(names) == 1:
            panel["output"] = names[0]
            panel.pop("outputs", None)
        else:
            panel["outputs"] = names
        boot["panels"] = panels
        return boot

    try:
        new_html, perr = _patch_page(html, mutate)
    except _ChartEditError as exc:
        return {"code": 1, "error": exc.code, "message": exc.message}
    if perr:
        if perr == "NO_RENDER_JS_MARKER":
            return {"code": 1, "error": "LEGACY_PAGE", "reason": perr,
                    "message": "该页面不支持定点增量编辑，请走整页重建流程（dashboard-end-to-end.md）"}
        return {"code": 1, "error": perr, "message": "页面 patch 失败（BOOT 解析或内核/渲染器版本同步失败），未写回"}

    up = _update_page(params, new_html)
    if up.get("code") != 0:
        return {"code": 1, "message": "页面更新失败", "update_result": up}
    return {
        "code": 0, "page_id": page_id, "output_name": output_name,
        "removed_whole_panel": removed_whole_panel["value"], "url": up.get("url"),
        "message": "已从页面摘除该系列/面板；对应公式包未撤销（保留给可能仍引用它的其它面板，到期自然失效）",
    }


def cmd_set_window(params):
    page_id = params.get("page_id")
    panel_sel = params.get("panel")
    output_name = params.get("output_name")
    if not page_id or panel_sel is None or not output_name:
        return {"code": 1, "message": "set_window 需要 page_id, panel, output_name"}

    requested_start = _parse_date(params.get("start_date"))
    if requested_start is None and params.get("lookback_days") is not None:
        try:
            requested_start = _dt.date.today() - _dt.timedelta(days=int(params["lookback_days"]))
        except (TypeError, ValueError):
            requested_start = None
    if requested_start is None:
        return {"code": 1, "message": "set_window 需要 start_date（YYYYMMDD 或 YYYY-MM-DD）或 lookback_days 之一"}

    dl = _download_page(params)
    if dl.get("code") != 0:
        return dl
    html = dl.get("html") or ""
    boot, _span, err = _extract_boot(html)
    if err:
        return {"code": 1, "error": "LEGACY_PAGE", "reason": err,
                "message": "该页面不支持定点增量编辑，请走整页重建流程（dashboard-end-to-end.md）"}
    if _find_panel_index(boot.get("panels") or [], panel_sel) is None:
        return {"code": 1, "error": "PANEL_NOT_FOUND", "message": f"未找到面板: {panel_sel}"}

    packages = _normalize_boot_packages(boot)
    pkg = _find_package_for_output(packages, output_name)
    if not pkg:
        return {"code": 1, "message": f"未找到 output={output_name} 所属的公式包，无法判断当前窗口"}

    current_start = _parse_date(pkg.get("begin_date"))
    read_entry = next((dict(r) for r in (pkg.get("reads") or []) if r.get("output") == output_name), None)
    if current_start is None and read_entry:
        lb = (read_entry.get("mode_params") or {}).get("lookback_days")
        if isinstance(lb, (int, float)):
            current_start = _dt.date.today() - _dt.timedelta(days=int(lb))

    if current_start is not None and requested_start >= current_start:
        # 目标窗口落在已注册范围内：纯前端裁剪展示，不碰后端、不重新验证/注册公式包
        def mutate(boot):
            idx = _find_panel_index(boot.get("panels") or [], panel_sel)
            if idx is None:
                raise _ChartEditError("PANEL_NOT_FOUND", f"未找到面板: {panel_sel}")
            boot["panels"][idx]["x_range"] = {"start_date": _fmt_date(requested_start)}
            return boot

        try:
            new_html, perr = _patch_page(html, mutate)
        except _ChartEditError as exc:
            return {"code": 1, "error": exc.code, "message": exc.message}
        if perr:
            return {"code": 1, "error": perr, "message": "页面 patch 失败（BOOT 解析或内核/渲染器版本同步失败），未写回"}
        up = _update_page(params, new_html)
        if up.get("code") != 0:
            return {"code": 1, "message": "页面更新失败", "update_result": up}
        return {
            "code": 0, "page_id": page_id, "mode": "display_only",
            "start_date": _fmt_date(requested_start), "url": up.get("url"),
            "message": "目标窗口落在已取数范围内，只调整了图表展示裁剪，未重新验证/注册公式包",
        }

    # 目标窗口超出已注册范围：只重新注册这一个 output 的公式，页面上其它系列/公式包不受影响
    if not pkg.get("formulas") or not read_entry:
        return {
            "code": 1, "error": "FORMULAS_UNKNOWN",
            "message": (
                f"output={output_name} 所属公式包未在页面里留存公式文本（老页面/老包），"
                "无法安全扩窗自动重注册；请显式传 formulas 参数重新指定该 output 的公式，或改走整页重建流程"
            ),
        }
    mode_params = dict(read_entry.get("mode_params") or {})
    mode_params["lookback_days"] = (_dt.date.today() - requested_start).days
    read_entry["mode_params"] = mode_params
    begin_date_int = int(_fmt_date(requested_start).replace("-", ""))

    register_body = {"formulas": pkg["formulas"], "reads": [read_entry], "begin_date": begin_date_int}
    if params.get("ttl_days") is not None:
        register_body["ttl_days"] = params["ttl_days"]
    reg = FP.cmd_register(register_body)
    if reg.get("code") != 0:
        return {"code": 1, "message": "扩窗重新注册失败", "register_result": reg}

    new_pkg_entry = {
        "role": pkg.get("role") or output_name, "package_id": reg["package_id"], "signature": reg["signature"],
        "formulas": pkg["formulas"], "reads": [read_entry], "begin_date": begin_date_int,
    }

    def mutate(boot):
        packages = [p for p in _normalize_boot_packages(boot) if p.get("package_id") != pkg.get("package_id")]
        packages.append(new_pkg_entry)
        boot["packages"] = packages
        idx = _find_panel_index(boot.get("panels") or [], panel_sel)
        if idx is None:
            raise _ChartEditError("PANEL_NOT_FOUND", f"未找到面板: {panel_sel}")
        boot["panels"][idx].pop("x_range", None)
        return boot

    try:
        new_html, perr = _patch_page(html, mutate)
    except _ChartEditError as exc:
        return {"code": 1, "error": exc.code, "message": exc.message, "package_id": reg["package_id"]}
    if perr:
        return {"code": 1, "error": perr, "message": "页面 patch 失败（BOOT 解析或内核/渲染器版本同步失败），未写回", "package_id": reg["package_id"]}

    up = _update_page(params, new_html)
    if up.get("code") != 0:
        return {"code": 1, "message": "页面更新失败（公式包已注册成功，仅页面写回失败）",
                "update_result": up, "package_id": reg["package_id"]}
    return {
        "code": 0, "page_id": page_id, "mode": "reregistered", "package_id": reg["package_id"],
        "start_date": _fmt_date(requested_start), "url": up.get("url"),
        "message": f"目标窗口超出已注册范围，只重新注册了 output={output_name} 这一个产出，页面上其它系列未受影响",
    }


def cmd_query_data(params):
    page_id = params.get("page_id")
    output_name = params.get("output_name")
    if not page_id or not output_name:
        return {"code": 1, "message": "query_data 需要 page_id, output_name"}

    package_id = params.get("package_id")
    signature = params.get("signature")
    if not (package_id and signature):
        dl = _download_page(params)
        if dl.get("code") != 0:
            return dl
        boot, _span, err = _extract_boot(dl.get("html") or "")
        if err:
            return {"code": 1, "error": err, "message": "无法从页面解析取数凭证"}
        packages = _normalize_boot_packages(boot)
        pkg = _find_package_for_output(packages, output_name)
        if package_id:
            pkg = next((p for p in packages if p.get("package_id") == package_id), pkg)
        if not pkg:
            return {"code": 1, "message": f"页面未找到 output={output_name} 所属的公式包；"
                                          "如页面同时有多个包且无法从 reads 判断归属，请显式传 package_id"}
        package_id, signature = pkg.get("package_id"), pkg.get("signature")

    return FP.cmd_query({
        "package_id": package_id,
        "signature": signature,
        "outputs": [output_name],
        "result_mode": params.get("result_mode") or "summary",
    })


_COMMANDS = {
    "inspect": cmd_inspect,
    "add_series": cmd_add_series,
    "remove_series": cmd_remove_series,
    "set_window": cmd_set_window,
    "query_data": cmd_query_data,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in _COMMANDS:
        C.emit({"code": 1, "message": f"用法: chart_edit.py <{'|'.join(_COMMANDS)}> [params]",
                "doc": (__doc__ or "").strip()[:600]}, out_name="ce_out.txt")
        sys.exit(1)
    cmd = sys.argv[1]
    params = C.read_params(sys.argv[2:], env_var="CE_PARAMS")

    try:
        result = _COMMANDS[cmd](params)
    except (FileNotFoundError, ValueError) as e:
        result = {"code": 1, "message": str(e)}
    C.emit(result, out_name="ce_out.txt")
    sys.exit(0 if (isinstance(result, dict) and result.get("code") == 0) else 1)


if __name__ == "__main__":
    main()
