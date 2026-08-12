#!/usr/bin/env python3
"""Build standalone card-runtime artifacts for already published QBV pages."""

import html as _html
import json
import os
import re
import urllib.error
import urllib.request

import common as C
from card_runtime_contract import (
    CARD_RUNTIME_KIND,
    CARD_RUNTIME_VERSION,
    artifact_hash,
    validate_manifest,
    validate_runtime_source,
)
START = "<!-- QB_CARD_RUNTIME_ARTIFACTS_START -->"
END = "<!-- QB_CARD_RUNTIME_ARTIFACTS_END -->"


def first_tagged_block(html, tag, marker):
    match = re.search(r"<%s\b(?=[^>]*\b%s\b)[^>]*>([\s\S]*?)</%s>" % (tag, marker, tag), html or "", re.I)
    return (match.group(1).strip() if match else "")


def parse_manifest(html):
    text = first_tagged_block(html, "script", "data-qb-card-manifest")
    if text:
        data = json.loads(text)
        existing = _manifest_packages(data)
        legacy = _parse_legacy_packages(html)
        if legacy:
            seen = {
                (pkg.get("endpoint"), pkg.get("package_id"), pkg.get("signature"))
                for pkg in existing
            }
            merged = []
            for pkg in (data.get("packages") or []):
                if isinstance(pkg, dict):
                    merged.append(pkg)
            for pkg in legacy:
                key = (pkg.get("endpoint"), pkg.get("package_id"), pkg.get("signature"))
                if key in seen:
                    continue
                seen.add(key)
                merged.append(pkg)
            data["packages"] = merged
        packages = _manifest_packages(data)
        if not packages:
            raise ValueError("card manifest 缺少 package_id/signature/endpoint")
        return data

    packages = _parse_legacy_packages(html)
    if not packages:
        raise ValueError("未找到 script[data-qb-card-manifest] 或旧页公式包配置")
    first = packages[0]
    return {
        "version": CARD_RUNTIME_VERSION,
        "kind": CARD_RUNTIME_KIND,
        "endpoint": first["endpoint"],
        "package_id": first["package_id"],
        "signature": first["signature"],
        "packages": packages,
    }


def _key_pattern(key):
    if key == "package_id":
        return r"(?:package_id|packageId)"
    return re.escape(key)


def _extract_js_string(block, key):
    match = re.search(r"(?:['\"])?%s(?:['\"])?\s*:\s*(['\"])(.*?)\1" % _key_pattern(key), block or "", re.S)
    return match.group(2).strip() if match else ""


def _resolve_js_var(html, name):
    """Resolve `const NAME = "..."` / `NAME = "..."` string declarations."""
    if not name:
        return ""
    m = re.search(r"(?:const|let|var)\s+%s\s*=\s*(['\"])(.*?)\1" % re.escape(name), html or "", re.S)
    if not m:
        m = re.search(r"\b%s\s*=\s*(['\"])(.*?)\1" % re.escape(name), html or "", re.S)
    return m.group(2).strip() if m else ""


def _normalize_endpoint(endpoint):
    endpoint = (endpoint or "").strip().rstrip("/")
    if not endpoint:
        return ""
    if endpoint.endswith("/skill/queryFormulaPackage"):
        return endpoint[: -len("/queryFormulaPackage")]
    if endpoint.endswith("/queryFormulaPackage"):
        return endpoint[: -len("/queryFormulaPackage")].rstrip("/") + "/skill"
    return endpoint


def _endpoint_from_block(html, block):
    """Endpoint value in a package block: quoted string, or a JS variable
    reference like `endpoint: ENDPOINT` resolved against its declaration."""
    literal = _extract_js_string(block, "endpoint")
    if literal:
        return _normalize_endpoint(literal)
    ident = re.search(r"\bendpoint\s*:\s*([A-Za-z_$][\w$]*)", block or "")
    if ident:
        return _normalize_endpoint(_resolve_js_var(html, ident.group(1)))
    return ""


def _parse_legacy_packages(html):
    packages = []
    seen = set()
    package_key = r"(?:package_id|packageId)"
    pattern = re.compile(r"([A-Za-z_$][\w$-]*)\s*:\s*\{([^{}]*?\b%s\b[^{}]*?\bsignature\b[^{}]*?)\}" % package_key, re.S)
    for match in pattern.finditer(html or ""):
        role, block = match.group(1), match.group(2)
        endpoint = _endpoint_from_block(html, block)
        package_id = _extract_js_string(block, "package_id")
        signature = _extract_js_string(block, "signature")
        key = (endpoint, package_id, signature)
        if not endpoint or not package_id or not signature or key in seen:
            continue
        seen.add(key)
        packages.append({
            "role": role,
            "endpoint": endpoint,
            "package_id": package_id,
            "signature": signature,
        })
    if packages:
        return packages

    for match in re.finditer(r"\{([^{}]*?\b%s\b[^{}]*?\bsignature\b[^{}]*?)\}" % package_key, html or "", re.S):
        block = match.group(1)
        endpoint = _endpoint_from_block(html, block)
        package_id = _extract_js_string(block, "package_id")
        signature = _extract_js_string(block, "signature")
        key = (endpoint, package_id, signature)
        if not endpoint or not package_id or not signature or key in seen:
            continue
        seen.add(key)
        packages.append({
            "role": "package_%d" % (len(packages) + 1),
            "endpoint": endpoint,
            "package_id": package_id,
            "signature": signature,
        })
    if packages:
        return packages

    endpoint = _normalize_endpoint(_resolve_js_var(html, "ENDPOINT") or _extract_js_string(html, "endpoint"))
    package_pattern = re.compile(r"(?:['\"])?%s(?:['\"])?\s*:\s*(['\"])(.*?)\1" % package_key, re.S)
    for match in package_pattern.finditer(html or ""):
        package_id = match.group(2).strip()
        window = html[match.end(): min(len(html), match.end() + 1600)]
        signature = _extract_js_string(window, "signature")
        local_endpoint = _endpoint_from_block(html, window) or endpoint
        key = (local_endpoint, package_id, signature)
        if not local_endpoint or not package_id or not signature or key in seen:
            continue
        seen.add(key)
        packages.append({
            "role": "package_%d" % (len(packages) + 1),
            "endpoint": local_endpoint,
            "package_id": package_id,
            "signature": signature,
        })
    return packages


def _manifest_packages(manifest):
    packages = []
    for index, item in enumerate(manifest.get("packages") or [], start=1):
        if not isinstance(item, dict):
            continue
        endpoint = _normalize_endpoint(item.get("endpoint") or manifest.get("endpoint"))
        package_id = item.get("package_id") or item.get("packageId")
        signature = item.get("signature")
        if endpoint and package_id and signature:
            packages.append({
                "role": item.get("role") or "package_%d" % index,
                "endpoint": endpoint,
                "package_id": package_id,
                "signature": signature,
                "outputs": list(item.get("outputs") or []),
            })
    if packages:
        return packages
    package_id = manifest.get("package_id") or manifest.get("packageId")
    endpoint = _normalize_endpoint(manifest.get("endpoint"))
    if endpoint and package_id and manifest.get("signature"):
        return [{
            "role": "default",
            "endpoint": endpoint,
            "package_id": package_id,
            "signature": manifest["signature"],
            "outputs": list(manifest.get("required_outputs") or []),
        }]
    return []


def _api_url(endpoint, path):
    return C.api_url(_normalize_endpoint(endpoint), path)


def _post_json_stream(url, body, timeout=90):
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=C.headers(accept="text/event-stream"),  # 带上 x-skill-version / x-skill-name
        method="POST",
    )
    try:
        with C._NO_PROXY_OPENER.open(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise ValueError("queryFormulaPackage HTTP %s: %s" % (exc.code, raw[:300]))


def _parse_sse(text):
    outputs = {}
    done = None
    for block in re.split(r"\n\s*\n", (text or "").replace("\r", "")):
        event = ""
        data_lines = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(re.sub(r"^ ", "", line[5:]))
        if not data_lines:
            continue
        try:
            payload = json.loads("\n".join(data_lines))
        except Exception:
            continue
        if event == "result" and payload.get("output"):
            outputs[payload["output"]] = payload
        elif event == "done":
            done = payload
    return outputs, done


def query_all_outputs(manifest):
    all_outputs = {}
    resolved = []
    for pkg in _manifest_packages(manifest):
        raw = _post_json_stream(
            _api_url(pkg["endpoint"], "/skill/queryFormulaPackage"),
            {"package_id": pkg["package_id"], "signature": pkg["signature"]},
        )
        outputs, done = _parse_sse(raw)
        if not outputs:
            raise ValueError(
                "公式包 %s 未返回任何 outputs；done=%s"
                % (pkg["package_id"], json.dumps(done or {}, ensure_ascii=False))
            )
        keys = _sort_keys(outputs.keys())
        resolved.append({
            "role": pkg.get("role") or "package_%d" % (len(resolved) + 1),
            "endpoint": pkg["endpoint"],
            "package_id": pkg["package_id"],
            "signature": pkg["signature"],
            "outputs": keys,
        })
        for key, value in outputs.items():
            all_outputs.setdefault(key, value)
    if not all_outputs:
        raise ValueError("公式包未返回任何 outputs")
    manifest["_packages_resolved"] = resolved
    return all_outputs


def _e(text):
    return _html.escape(str(text or ""), quote=True)


def _title_from_html(html):
    match = re.search(r"<title[^>]*>([\s\S]*?)</title>", html or "", re.I)
    if not match:
        return ""
    return re.sub(r"\s+", " ", _html.unescape(match.group(1))).strip()


def _sort_keys(keys):
    return sorted(set(keys), key=lambda k: (k.lower(), k))


def _card(page_id, title, description, core, theme="orange", visual_kind=""):
    return """<section class="qb-card-artifact" data-qb-live-card data-theme="{theme}" data-qb-card-visual-kind="{visual_kind}">
  <div class="qb-card-meta">
    <span data-qb-live-card-brand></span>
    <time data-qb-live-card-date data-qb-bind="date" datetime="">待更新</time>
  </div>
  <h1 data-qb-live-card-title>{title}</h1>
  <p data-qb-live-card-description>{description}</p>
  <section class="qb-card-core" data-qb-live-card-core data-card-page="{page_id}">
{core}
  </section>
</section>""".format(
        theme=_e(theme),
        visual_kind=_e(visual_kind),
        page_id=_e(page_id),
        title=_e(title),
        description=_e(description),
        core=core,
    )


def _metric(label, output, fmt="number", klass=""):
    return """    <div class="qb-mini-metric {klass}">
      <span>{label}</span>
      <b data-qb-value data-output="{output}" data-format="{fmt}">0</b>
    </div>""".format(label=_e(label), output=_e(output), fmt=_e(fmt), klass=_e(klass))


PAGE_VISUAL_DEFAULTS = {
    "page_13e5b862a47135363442bf54": {"kind": "event-flow"},
    "page_1256a77743fab9aa39838ce9": {"kind": "basis-structure"},
    "page_a130c11588ffb3e5e50787f1": {"kind": "event-pulse"},
    "page_6325ee8277a2455c76f3a480": {"kind": "rotation-wheel"},
}


def _numeric_focus_card(page_id, title, contract):
    metrics = contract.get("metrics")
    if not isinstance(metrics, list) or not 1 <= len(metrics) <= 3:
        raise ValueError("CARD_VISUAL_INVALID: numeric-focus 需要 1-3 个显式 metrics")
    normalized = []
    for index, metric in enumerate(metrics):
        if not isinstance(metric, dict):
            raise ValueError("CARD_VISUAL_INVALID: metrics[%d] 必须是 object" % index)
        label = str(metric.get("label") or "").strip()
        output = str(metric.get("output") or "").strip()
        if not label or not output:
            raise ValueError("CARD_VISUAL_INVALID: metrics[%d] 缺少 label/output" % index)
        normalized.append({
            "label": label,
            "output": output,
            "format": str(metric.get("format") or "number1").strip(),
        })
    required = []
    for metric in normalized:
        if metric["output"] not in required:
            required.append(metric["output"])
    primary = normalized[0]
    secondary = "\n".join(
        """        <div><span>{label}</span><b data-qb-value data-output="{output}" data-format="{format}">待更新</b></div>""".format(
            label=_e(metric["label"]),
            output=_e(metric["output"]),
            format=_e(metric["format"]),
        )
        for metric in normalized[1:]
    )
    solo_class = " is-solo" if len(normalized) == 1 else ""
    core = """    <div class="qb-numeric-focus{solo_class}" data-qb-card-numeric-focus>
      <div class="qb-numeric-hero">
        <span>{primary_label}</span>
        <b data-qb-value data-output="{primary_output}" data-format="{primary_format}">待更新</b>
      </div>
      <div class="qb-numeric-context">
{secondary}
      </div>
    </div>""".format(
        primary_label=_e(primary["label"]),
        primary_output=_e(primary["output"]),
        primary_format=_e(primary["format"]),
        secondary=secondary,
        solo_class=solo_class,
    )
    return required, _card(
        page_id,
        contract.get("title") or title or "实时指标",
        contract.get("description") or "主指标实时刷新，解释项只服务于核心判断。",
        core,
        contract.get("theme") or "orange",
        "numeric-focus",
    ), "numeric-focus"


def _build_page_card(page_id, title, keys, visual_contract=None):
    contract = visual_contract or PAGE_VISUAL_DEFAULTS.get(page_id)
    if not isinstance(contract, dict) or not str(contract.get("kind") or "").strip():
        raise ValueError(
            "CARD_VISUAL_REQUIRED: 页面 %s 没有显式视觉合同；禁止自动选择前三个 outputs 生成三指标卡"
            % (page_id or "<unknown>")
        )
    visual_kind = str(contract.get("kind") or "").strip()

    if visual_kind == "numeric-focus":
        return _numeric_focus_card(page_id, title, contract)

    if visual_kind == "event-flow" and page_id == "page_13e5b862a47135363442bf54":
        required = ["VIX_px", "KWEB_ret", "GREATSTAR_ret"]
        core = """    <div class="qb-taco-flow" data-qb-card-visual>
      <div class="qb-taco-track" aria-label="TACO五步逻辑链">
        <div class="qb-taco-stage"><b>威胁</b><span>Tariff</span></div>
        <div class="qb-taco-stage"><b>抛售</b><span>Selloff</span></div>
        <div class="qb-taco-stage"><b>施压</b><span>Pressure</span></div>
        <div class="qb-taco-stage"><b>退路</b><span>Off-ramp</span></div>
        <div class="qb-taco-stage"><b>反弹</b><span>Rebound</span></div>
      </div>
      <div class="qb-taco-metrics">
        <div><b data-qb-value data-output="VIX_px" data-format="number1">待更新</b><span>VIX</span></div>
        <div><b data-qb-value data-output="KWEB_ret" data-format="signed-pct">待更新</b><span>KWEB日涨跌</span></div>
        <div><b data-qb-value data-output="GREATSTAR_ret" data-format="signed-pct">待更新</b><span>A股敏感资产</span></div>
      </div>
    </div>"""
        return required, _card(
            page_id,
            contract.get("title") or "关税冲击是否正在走TACO剧本？",
            contract.get("description") or "对照美股波动率与两地敏感资产，判断冲击、缓和还是分化。",
            core,
            contract.get("theme") or "orange",
            "event-flow",
        ), "event-flow"

    if visual_kind == "basis-structure" and page_id == "page_1256a77743fab9aa39838ce9":
        required = ["IC_C0_fut_px", "IC_C1_fut_px", "IC_spot_px"]
        core = """    <div class="qb-basis-structure" data-qb-card-visual>
      <div class="qb-basis-hero">
        <span>主连基差</span>
        <b data-qb-spread data-a="IC_C0_fut_px" data-b="IC_spot_px">待更新</b>
        <small>负值为贴水 · 正值为升水</small>
      </div>
      <div class="qb-basis-axis" aria-label="主连与次主连相对现货的位置">
        <div class="qb-basis-scale"><span>贴水</span><b>现货锚</b><span>升水</span></div>
        <i class="qb-basis-zero"></i>
        <div class="qb-basis-marker is-front" data-qb-spread-marker data-a="IC_C0_fut_px" data-b="IC_spot_px">
          <b>主连</b><em></em>
        </div>
        <div class="qb-basis-marker is-next" data-qb-spread-marker data-a="IC_C1_fut_px" data-b="IC_spot_px">
          <b>次主连</b><em></em>
        </div>
      </div>
      <div class="qb-basis-anchor"><span>现货锚</span><b data-qb-value data-output="IC_spot_px" data-format="number1">待更新</b></div>
    </div>"""
        return required, _card(
            page_id,
            contract.get("title") or "股指期货基差监控",
            contract.get("description") or "主连、次主连和现货同口径刷新，重点看贴水收敛。",
            core,
            contract.get("theme") or "blue",
            "basis-structure",
        ), "basis-structure"

    if visual_kind == "event-pulse" and page_id == "page_a130c11588ffb3e5e50787f1":
        required = ["bu_ret", "nh_bu_ret", "nh_energy_ret"]
        core = """    <div class="qb-event-pulse" data-qb-card-visual>
      <div class="qb-event-pulse__hero">
        <span>AI 硬件</span>
        <b data-qb-value data-output="bu_ret" data-format="signed-pct">待更新</b>
        <small>板块涨幅</small>
      </div>
      <div class="qb-event-pulse__lanes">
        <div class="qb-pulse-lane is-alpha">
          <div><span>相对沪深300</span><b data-qb-value data-output="nh_bu_ret" data-format="signed-pct">待更新</b></div>
          <i><em data-qb-bar data-output="nh_bu_ret"></em></i>
        </div>
        <div class="qb-pulse-lane is-market">
          <div><span>沪深300</span><b data-qb-value data-output="nh_energy_ret" data-format="signed-pct">待更新</b></div>
          <i><em data-qb-bar data-output="nh_energy_ret"></em></i>
        </div>
        <small class="qb-pulse-note">事件冲击 → 板块承接 → 超额扩散</small>
      </div>
    </div>"""
        return required, _card(
            page_id,
            "WAIC 后，AI 硬件是否扩散？",
            "对照沪深300，实时观察板块涨幅与超额收益。",
            core,
            contract.get("theme") or "red",
            "event-pulse",
        ), "event-pulse"

    if visual_kind == "rotation-wheel" and page_id == "page_6325ee8277a2455c76f3a480":
        required = ["HW_RET", "KC_RET", "HG_RET"]
        core = """    <div class="qb-cycle-map" data-qb-card-visual>
      <div class="qb-cycle-track" aria-hidden="true"><i></i><i></i><i></i></div>
      <div class="qb-cycle-node qb-cycle-node--hw">
        <span>寒武纪</span>
        <b data-qb-value data-output="HW_RET" data-format="number1">待更新</b>
        <small>龙头</small>
      </div>
      <div class="qb-cycle-node qb-cycle-node--kc">
        <span>科创50</span>
        <b data-qb-value data-output="KC_RET" data-format="number1">待更新</b>
        <small>周期中枢</small>
      </div>
      <div class="qb-cycle-node qb-cycle-node--hg">
        <span>海光信息</span>
        <b data-qb-value data-output="HG_RET" data-format="number1">待更新</b>
        <small>龙头</small>
      </div>
      <div class="qb-cycle-caption">250 日表现 · 指数与龙头分层对照</div>
    </div>"""
        return required, _card(
            page_id,
            "科创50与龙头：周期坐标",
            "以科创50为中枢，对照寒武纪与海光信息的长期表现。",
            core,
            contract.get("theme") or "blue",
            "rotation-wheel",
        ), "rotation-wheel"

    raise ValueError(
        "CARD_VISUAL_UNSUPPORTED: 页面 %s 不支持 visual_contract.kind=%s"
        % (page_id or "<unknown>", visual_kind)
    )


STYLE = r"""
.qb-card-artifact,.qb-card-artifact *{box-sizing:border-box}
.qb-card-artifact[data-qb-live-card]{
  --accent:#ef7a1a;--ink:#201713;--muted:#725f4c;--line:#ead8c6;--soft:#fff7ec;
  width:100%;height:100%;aspect-ratio:4/3;container-type:inline-size;display:grid;grid-template-rows:auto auto auto minmax(0,1fr);
  gap:clamp(4px,1.4%,9px);padding:clamp(12px,4.6%,24px);background:linear-gradient(135deg,#fffdf8 0%,#fff5e8 100%);
  color:var(--ink);font-family:"Inter","PingFang SC","Microsoft YaHei",system-ui,sans-serif;overflow:hidden;border-top:5px solid var(--accent)
}
.qb-card-artifact[data-theme=red]{--accent:#d71920}
.qb-card-artifact[data-theme=green]{--accent:#16825a;--line:#cfe5d9;--soft:#f1fbf5}
.qb-card-artifact[data-theme=blue]{--accent:#1f5fbf;--line:#d4e2f5;--soft:#f3f8ff}
.qb-card-meta{display:flex;align-items:center;justify-content:space-between;min-height:16px;font-size:clamp(10px,2.1cqw,13px);font-weight:800;color:var(--muted)}
.qb-card-meta [data-qb-live-card-brand]{min-width:1px}
.qb-card-artifact h1{margin:0;font-size:clamp(17px,5.1cqw,30px);line-height:1.06;font-weight:950;letter-spacing:0}
.qb-card-artifact p{margin:0;color:var(--muted);font-size:clamp(10px,2.5cqw,15px);font-weight:650;line-height:1.28}
.qb-card-core{min-height:0;display:grid;gap:clamp(5px,1.4cqw,9px);align-content:stretch}
.qb-hero-split{min-height:0;display:grid;grid-template-columns:minmax(70px,.72fr) 1fr;gap:10px;align-items:center}
.qb-signal-mark{display:grid;place-items:center;min-height:64px;border-radius:8px;background:linear-gradient(135deg,var(--accent),#ffb45f);color:#fff;font-size:clamp(25px,7cqw,46px);line-height:1;font-weight:950}
.qb-hero-split strong{display:block;font-size:clamp(26px,7.4cqw,48px);line-height:1;font-weight:950;color:var(--accent)}
.qb-hero-split span{display:block;margin-top:5px;color:var(--muted);font-size:clamp(10px,2.3cqw,13px);font-weight:800}
.qb-tier-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
.qb-tier-grid>div,.qb-mini-metric{min-width:0;border:1px solid var(--line);border-radius:7px;background:rgba(255,255,255,.72);padding:8px}
.qb-tier-grid span,.qb-mini-metric span{display:block;color:var(--muted);font-size:clamp(10px,2.1cqw,12px);font-weight:800}
.qb-tier-grid b,.qb-mini-metric b{display:block;margin-top:4px;font-size:clamp(17px,4.3cqw,25px);line-height:1;font-weight:950}
.qb-tier-grid i{display:block;margin-top:3px;color:var(--accent);font-size:clamp(10px,2.1cqw,12px);font-style:normal;font-weight:850}
.qb-ladder-card{min-height:0;display:grid;grid-template-rows:auto minmax(0,1fr);gap:clamp(7px,2cqw,11px);align-items:stretch}
.qb-ladder-thesis{min-width:0;display:grid;grid-template-columns:auto auto minmax(0,1fr);gap:clamp(6px,1.8cqw,10px);align-items:center;border:1px solid rgba(215,25,32,.22);border-radius:8px;background:linear-gradient(90deg,#fff7ef,#ffe6da);padding:clamp(6px,1.6cqw,10px)}
.qb-ladder-thesis small{min-width:0;border-radius:999px;background:var(--accent);color:white;padding:clamp(4px,1cqw,6px) clamp(7px,2cqw,12px);font-size:clamp(9px,2.2cqw,12px);font-weight:950;white-space:nowrap}
.qb-ladder-thesis b{font-size:clamp(22px,6.6cqw,38px);line-height:1;font-weight:950;color:var(--accent)}
.qb-ladder-thesis span{min-width:0;color:var(--muted);font-size:clamp(9px,2.1cqw,12px);font-weight:850;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.qb-ladder-track{min-height:0;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:clamp(5px,1.5cqw,8px);align-items:end;position:relative}
.qb-ladder-track:before{content:"";position:absolute;left:9%;right:9%;bottom:20%;height:46%;border-left:2px solid rgba(215,25,32,.15);border-top:2px solid rgba(215,25,32,.15);transform:skewX(-18deg);pointer-events:none}
.qb-ladder-step{position:relative;min-width:0;display:grid;align-content:end;border:1px solid var(--line);border-radius:8px;background:rgba(255,255,255,.84);padding:clamp(6px,1.7cqw,10px);box-shadow:0 8px 18px rgba(120,66,24,.08)}
.qb-ladder-step.is-first{height:62%}
.qb-ladder-step.is-second{height:80%}
.qb-ladder-step.is-third{height:100%}
.qb-ladder-step span{min-width:0;color:var(--muted);font-size:clamp(9px,2.05cqw,12px);font-weight:850;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.qb-ladder-step b{display:block;margin-top:5px;font-size:clamp(15px,4cqw,23px);line-height:1;font-weight:950;color:var(--ink)}
.qb-ladder-step i{display:block;margin-top:4px;color:var(--accent);font-size:clamp(9px,2cqw,12px);font-style:normal;font-weight:900}
.qb-event-card{min-height:0;display:grid;grid-template-columns:minmax(78px,.72fr) minmax(0,1.28fr);grid-template-rows:minmax(0,1fr) auto;gap:clamp(6px,1.7cqw,10px);align-items:stretch}
.qb-event-window{grid-row:1/3;min-width:0;display:grid;align-content:center;justify-items:center;text-align:center;border:1px solid rgba(215,25,32,.24);border-radius:8px;background:linear-gradient(180deg,#fff6ed,#ffe3d4);padding:clamp(7px,2cqw,12px)}
.qb-event-window span,.qb-event-window i{color:var(--muted);font-size:clamp(9px,2.1cqw,12px);font-style:normal;font-weight:850}
.qb-event-window b{font-size:clamp(28px,8.5cqw,52px);line-height:.98;font-weight:950;color:var(--accent)}
.qb-st-lanes{min-height:0;display:grid;gap:clamp(5px,1.5cqw,8px)}
.qb-st-lane{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:5px 8px;align-items:center;border-bottom:1px solid rgba(234,216,198,.82);padding-bottom:clamp(5px,1.3cqw,8px)}
.qb-st-lane span{min-width:0;color:var(--ink);font-size:clamp(10px,2.25cqw,13px);font-weight:900;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.qb-st-lane b{font-size:clamp(11px,2.7cqw,15px);font-weight:950;color:var(--accent);text-align:right}
.qb-st-lane i{grid-column:1/3;display:block;height:clamp(8px,2.1cqw,12px);border-radius:999px;background:#f1e5d8;overflow:hidden}
.qb-st-lane em{display:block;width:8%;height:100%;border-radius:999px;background:linear-gradient(90deg,var(--accent),#ff8c3a)}
.qb-st-lane.is-hot i{background:#f7d8d3}
.qb-event-chips{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:clamp(4px,1.3cqw,7px)}
.qb-event-chips div{min-width:0;border:1px solid var(--line);border-radius:8px;background:rgba(255,255,255,.78);padding:clamp(5px,1.5cqw,8px)}
.qb-event-chips span{display:block;color:var(--muted);font-size:clamp(8px,1.95cqw,11px);font-weight:850;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.qb-event-chips b{display:block;margin-top:4px;color:var(--ink);font-size:clamp(13px,3.4cqw,20px);line-height:1;font-weight:950}
.qb-risk-map{min-height:0;display:grid;grid-template-columns:minmax(0,.95fr) minmax(0,1.05fr);gap:clamp(7px,2cqw,12px);align-items:stretch}
.qb-risk-field{position:relative;min-width:0;min-height:0;display:grid;place-items:center;overflow:hidden;border:1px solid var(--line);border-radius:8px;background:linear-gradient(135deg,#fffaf3,#ffe7d0)}
.qb-risk-field>i{position:absolute;display:block;border:1px solid rgba(239,122,26,.24);border-radius:50%;aspect-ratio:1}
.qb-risk-field>i:nth-child(1){width:86%}
.qb-risk-field>i:nth-child(2){width:62%}
.qb-risk-field>i:nth-child(3){width:38%;background:rgba(255,255,255,.42)}
.qb-risk-field:before,.qb-risk-field:after{content:"";position:absolute;background:rgba(239,122,26,.16)}
.qb-risk-field:before{width:1px;height:84%}
.qb-risk-field:after{height:1px;width:84%}
.qb-risk-radius{position:relative;z-index:1;display:grid;justify-items:center;text-align:center}
.qb-risk-radius span{color:var(--muted);font-size:clamp(9px,2.1cqw,12px);font-weight:850}
.qb-risk-radius b{margin-top:4px;color:var(--accent);font-size:clamp(23px,7cqw,40px);line-height:1;font-weight:950}
.qb-risk-field small{position:absolute;left:8px;bottom:7px;color:var(--muted);font-size:clamp(8px,1.9cqw,11px);font-weight:850}
.qb-risk-summary{min-height:0;display:grid;gap:clamp(5px,1.5cqw,8px)}
.qb-risk-summary div{min-width:0;display:grid;align-content:center;border:1px solid var(--line);border-radius:8px;background:rgba(255,255,255,.78);padding:clamp(6px,1.7cqw,10px)}
.qb-risk-summary span{color:var(--muted);font-size:clamp(9px,2.05cqw,12px);font-weight:850;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.qb-risk-summary b{min-width:0;margin-top:4px;color:var(--ink);font-size:clamp(12px,3.15cqw,19px);line-height:1.05;font-weight:950;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.qb-risk-summary div:nth-child(2) b{color:var(--accent)}
.qb-card-bar-row{display:grid;grid-template-columns:76px 54px 1fr;gap:8px;align-items:center;padding:7px 0;border-bottom:1px solid rgba(234,216,198,.8)}
.qb-card-bar-row span{font-size:clamp(10px,2.25cqw,13px);font-weight:850;color:var(--ink)}
.qb-card-bar-row b{font-size:clamp(11px,2.4cqw,14px);font-weight:950;color:var(--accent);text-align:right}
.qb-card-bar-row i{display:block;height:10px;border-radius:999px;background:#f1e5d8;overflow:hidden}
.qb-card-bar-row em{display:block;height:100%;width:8%;border-radius:999px;background:var(--accent)}
.qb-card-tags{display:flex;gap:6px;align-items:end;flex-wrap:wrap}
.qb-card-tags span{border:1px solid var(--line);border-radius:999px;background:#fffaf2;padding:4px 8px;font-size:clamp(9px,2cqw,11px);font-weight:850}
.qb-spark{width:100%;height:72px;border:1px solid var(--line);border-radius:8px;background:rgba(255,255,255,.66);overflow:hidden}
.qb-spark path{fill:none;stroke:var(--accent);stroke-width:4;stroke-linecap:round;stroke-linejoin:round}
.qb-card-visual-stack{min-height:0;display:grid;grid-template-rows:minmax(46px,1fr) auto;gap:clamp(5px,1.5cqw,8px)}
.qb-multi-spark{height:clamp(50px,20cqw,100px);background:linear-gradient(180deg,rgba(255,255,255,.9),var(--soft))}
.qb-multi-spark path:nth-child(2){stroke:#25364f;opacity:.78}
.qb-multi-spark path:nth-child(3){stroke:#8b6f50;opacity:.68}
.qb-race-list{min-height:0;display:grid;gap:clamp(4px,1.5cqw,7px)}
.qb-race-list.compact{gap:clamp(4px,1.3cqw,6px)}
.qb-race-row{display:grid;grid-template-columns:minmax(62px,.9fr) minmax(46px,.48fr) 1.3fr;gap:clamp(5px,1.7cqw,8px);align-items:center;min-height:clamp(22px,6.5cqw,34px);border:1px solid var(--line);border-radius:7px;background:rgba(255,255,255,.74);padding:4px 7px}
.qb-race-row span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted);font-size:clamp(9px,2.35cqw,12px);font-weight:850}
.qb-race-row b{font-size:clamp(12px,3.55cqw,19px);font-weight:950;line-height:1;color:var(--ink);text-align:right}
.qb-race-row i{display:block;height:clamp(5px,1.8cqw,8px);border-radius:999px;background:#efe3d6;overflow:hidden}
.qb-race-row em{display:block;height:100%;width:10%;border-radius:999px;background:var(--accent)}
.qb-regime-meter,.qb-waterline{border:1px solid var(--line);border-radius:8px;background:rgba(255,255,255,.75);padding:8px 10px}
.qb-regime-meter>div{display:flex;align-items:center;justify-content:space-between;color:var(--muted);font-size:clamp(10px,2.2cqw,12px);font-weight:850}
.qb-regime-meter b,.qb-waterline b{font-size:clamp(16px,4.2cqw,24px);color:var(--accent)}
.qb-regime-meter i,.qb-waterline i{display:block;height:10px;border-radius:999px;background:#eee3d5;overflow:hidden;margin-top:6px}
.qb-regime-meter em,.qb-waterline em{display:block;height:100%;width:50%;border-radius:999px;background:linear-gradient(90deg,#6f8fb3,var(--accent))}
.qb-window-strip{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px}
.qb-window-strip>div{min-width:0;border:1px solid var(--line);border-radius:8px;background:rgba(255,255,255,.78);padding:8px}
.qb-window-strip span{display:block;color:var(--muted);font-size:clamp(9px,2.2cqw,11px);font-weight:850}
.qb-window-strip b{display:block;margin-top:5px;font-size:clamp(15px,4.2cqw,23px);line-height:1;font-weight:950;color:var(--ink)}
.qb-top-list{min-height:0;border:1px solid var(--line);border-radius:9px;background:rgba(255,255,255,.76);padding:9px;display:grid;gap:7px}
.qb-top-list>strong{font-size:clamp(11px,2.5cqw,14px);line-height:1.1}
.qb-top-list-body{display:grid;gap:5px}
.qb-top-list-body>div{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;border-top:1px solid rgba(0,0,0,.06);padding-top:5px}
.qb-top-list-body span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted);font-size:clamp(10px,2.3cqw,12px);font-weight:820}
.qb-top-list-body b{font-size:clamp(12px,3.1cqw,16px);font-weight:950;color:var(--accent)}
.qb-card-dashboard,.qb-alert-board,.qb-basis-board,.qb-limit-structure,.qb-valuation-waterline{min-height:0;display:grid;gap:8px}
.qb-card-dashboard{grid-template-columns:.8fr 1.2fr;align-items:stretch}
.qb-score-orbit,.qb-alert-score,.qb-basis-main{display:grid;place-items:center;text-align:center;border:1px solid var(--line);border-radius:12px;background:radial-gradient(circle at 50% 40%,rgba(255,255,255,.98),var(--soft));padding:10px}
.qb-score-orbit b,.qb-alert-score b,.qb-basis-main b{font-size:clamp(28px,8cqw,46px);line-height:1;font-weight:950;color:var(--accent)}
.qb-score-orbit span,.qb-alert-score span,.qb-basis-main span{color:var(--muted);font-size:clamp(10px,2.3cqw,12px);font-weight:850}
.qb-alert-board,.qb-basis-board{grid-template-columns:.9fr 1.2fr;align-items:stretch}
.qb-limit-structure{grid-template-columns:.7fr 1.3fr;align-items:stretch}
.qb-numeric-focus{min-height:0;display:grid;grid-template-columns:minmax(104px,.9fr) minmax(0,1.1fr);gap:clamp(7px,2cqw,12px);align-items:stretch}
.qb-numeric-hero{min-height:0;display:grid;place-content:center;justify-items:center;text-align:center;border:1px solid rgba(239,122,26,.24);border-radius:16px;background:radial-gradient(circle at 50% 38%,#fff,var(--soft));padding:clamp(7px,2cqw,12px)}
.qb-numeric-hero span{color:var(--muted);font-size:clamp(9px,2.2cqw,12px);font-weight:900}
.qb-numeric-hero b{margin-top:5px;color:var(--accent);font-size:clamp(31px,9.4cqw,56px);line-height:.92;font-weight:950;letter-spacing:-.04em}
.qb-numeric-context{min-width:0;display:grid;grid-template-rows:repeat(2,minmax(0,1fr));gap:clamp(6px,1.6cqw,9px)}
.qb-numeric-focus.is-solo{grid-template-columns:1fr}.qb-numeric-focus.is-solo .qb-numeric-context{display:none}
.qb-numeric-context>div{min-width:0;display:grid;align-content:center;border:1px solid var(--line);border-radius:10px;background:rgba(255,255,255,.78);padding:clamp(7px,2cqw,12px)}
.qb-numeric-context span{color:var(--muted);font-size:clamp(9px,2.1cqw,12px);font-weight:850;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.qb-numeric-context b{margin-top:5px;color:var(--ink);font-size:clamp(18px,5.2cqw,30px);line-height:1;font-weight:950}
.qb-basis-structure{min-height:0;display:grid;grid-template-columns:minmax(100px,.72fr) minmax(0,1.28fr);grid-template-rows:minmax(0,1fr) auto;gap:clamp(7px,2cqw,12px);align-items:stretch}
.qb-basis-hero{grid-row:1/3;min-height:0;display:grid;place-content:center;justify-items:center;text-align:center;border:1px solid #cadcf3;border-radius:15px;background:radial-gradient(circle at 50% 38%,#fff,#eef6ff);padding:clamp(8px,2.1cqw,13px)}
.qb-basis-hero span{color:var(--muted);font-size:clamp(9px,2.2cqw,12px);font-weight:900}
.qb-basis-hero b{margin-top:4px;color:var(--accent);font-size:clamp(28px,8.4cqw,50px);line-height:.95;font-weight:950;letter-spacing:-.04em}
.qb-basis-hero small{margin-top:6px;color:#6e83a0;font-size:clamp(8px,1.85cqw,10px);font-weight:800}
.qb-basis-axis{position:relative;min-height:84px;border:1px solid #d4e2f5;border-radius:12px;background:linear-gradient(90deg,#f0f6ff 0 49.8%,#fff4ed 50.2% 100%);overflow:hidden}
.qb-basis-axis:before{content:"";position:absolute;left:8%;right:8%;top:54%;height:2px;background:linear-gradient(90deg,#6f8fb3,#9caabd 49.5%,#d46a3b 50.5%,#ef7a1a)}
.qb-basis-scale{position:absolute;left:8%;right:8%;top:8px;display:flex;justify-content:space-between;align-items:center;color:#71839a;font-size:clamp(8px,1.9cqw,10px);font-weight:850}
.qb-basis-scale b{color:#425a78;font-size:inherit}.qb-basis-zero{position:absolute;left:50%;top:28%;bottom:16%;width:2px;background:rgba(48,80,120,.25);transform:translateX(-50%)}
.qb-basis-marker{position:absolute;left:50%;top:44%;display:grid;justify-items:center;gap:3px;transform:translate(-50%,-50%);transition:left .35s ease}
.qb-basis-marker.is-next{top:70%}.qb-basis-marker b{border-radius:999px;background:#fff;border:1px solid #9fb8d8;color:#31557e;padding:3px 7px;font-size:clamp(8px,1.9cqw,10px);line-height:1;font-weight:900;white-space:nowrap;box-shadow:0 4px 10px rgba(31,95,191,.1)}
.qb-basis-marker em{width:9px;height:9px;border:2px solid #fff;border-radius:50%;background:#1f5fbf;box-shadow:0 0 0 3px rgba(31,95,191,.15)}
.qb-basis-marker.is-positive b{border-color:#e5a081;color:#a94a20}.qb-basis-marker.is-positive em{background:#ef7a1a;box-shadow:0 0 0 3px rgba(239,122,26,.16)}
.qb-basis-anchor{display:flex;align-items:baseline;justify-content:space-between;gap:8px;border-top:1px dashed #c7d6e8;padding:clamp(5px,1.4cqw,8px) 3px 0;color:var(--muted);font-size:clamp(9px,2.1cqw,12px);font-weight:850}
.qb-basis-anchor b{color:var(--ink);font-size:clamp(15px,4.2cqw,24px);line-height:1;font-weight:950}
.qb-taco-flow{min-height:0;display:grid;grid-template-rows:minmax(0,1fr) auto;gap:clamp(6px,1.7cqw,10px)}
.qb-taco-track{min-height:0;display:grid;grid-template-columns:repeat(5,minmax(0,1fr));align-items:center;gap:clamp(3px,1.1cqw,8px)}
.qb-taco-stage{position:relative;min-width:0;height:76%;display:grid;place-items:center;align-content:center;gap:4px;border:1px solid var(--line);border-radius:clamp(8px,2cqw,14px);background:rgba(255,255,255,.86);text-align:center;color:var(--muted);font-size:clamp(8px,1.9cqw,11px);font-weight:850;box-shadow:0 7px 18px rgba(120,66,24,.06)}
.qb-taco-stage:after{content:"→";position:absolute;right:calc(clamp(3px,1.1cqw,8px) * -1 - .58em);color:#a39a91;font-weight:900}
.qb-taco-stage:last-child:after{display:none}
.qb-taco-stage b{color:var(--ink);font-size:clamp(12px,2.8cqw,18px);line-height:1;font-weight:950;white-space:nowrap}
.qb-taco-stage:nth-child(1),.qb-taco-stage:nth-child(2){background:linear-gradient(180deg,#fff,#fff1e6)}
.qb-taco-stage:nth-child(3){border-color:rgba(215,25,32,.25);background:linear-gradient(180deg,#fff,#ffe7e3)}
.qb-taco-stage:nth-child(4),.qb-taco-stage:nth-child(5){border-color:#cfe5d9;background:linear-gradient(180deg,#fff,#effaf4)}
.qb-taco-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:clamp(4px,1.2cqw,8px)}
.qb-taco-metrics>div{min-width:0;border:1px solid var(--line);border-radius:clamp(7px,1.6cqw,12px);background:rgba(255,255,255,.78);padding:clamp(5px,1.2cqw,10px)}
.qb-taco-metrics b{display:block;color:var(--ink);font-size:clamp(13px,3.1cqw,22px);line-height:1;font-weight:950;font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.qb-taco-metrics span{display:block;margin-top:3px;color:var(--muted);font-size:clamp(8px,1.9cqw,11px);font-weight:850;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.qb-event-pulse{min-height:0;display:grid;grid-template-columns:minmax(112px,.8fr) minmax(0,1.2fr);gap:clamp(9px,2.6cqw,16px);align-items:stretch}
.qb-event-pulse__hero{position:relative;isolation:isolate;display:grid;place-content:center;justify-items:center;text-align:center;min-height:0;border:1px solid rgba(215,25,32,.22);border-radius:50%;background:radial-gradient(circle,#fff 0 34%,#ffe9e1 35% 50%,#fff7f2 51% 64%,transparent 65%);overflow:hidden}
.qb-event-pulse__hero:before,.qb-event-pulse__hero:after{content:"";position:absolute;z-index:-1;border:1px solid rgba(215,25,32,.18);border-radius:50%;animation:qb-pulse 3.2s ease-out infinite}
.qb-event-pulse__hero:before{inset:18%}.qb-event-pulse__hero:after{inset:7%;animation-delay:1.1s}
.qb-event-pulse__hero span{font-size:clamp(10px,2.45cqw,14px);font-weight:900;color:var(--muted)}
.qb-event-pulse__hero b{margin-top:3px;font-size:clamp(26px,8.5cqw,50px);line-height:.95;font-weight:950;color:var(--accent);letter-spacing:-.04em}
.qb-event-pulse__hero small{margin-top:5px;font-size:clamp(8px,1.9cqw,11px);font-weight:800;color:var(--muted)}
.qb-event-pulse__lanes{min-width:0;display:grid;align-content:center;gap:clamp(8px,2.2cqw,13px)}
.qb-pulse-lane{min-width:0}.qb-pulse-lane>div{display:flex;align-items:baseline;justify-content:space-between;gap:8px}
.qb-pulse-lane span{min-width:0;font-size:clamp(9px,2.2cqw,12px);font-weight:850;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.qb-pulse-lane b{font-size:clamp(15px,4cqw,23px);font-weight:950;color:var(--ink)}
.qb-pulse-lane i{display:block;height:clamp(8px,2.2cqw,12px);margin-top:5px;border-radius:999px;background:#f1e5dd;overflow:hidden}
.qb-pulse-lane em{display:block;height:100%;min-width:8%;border-radius:999px;background:linear-gradient(90deg,#f5a166,var(--accent));box-shadow:0 0 12px rgba(215,25,32,.22)}
.qb-pulse-lane.is-market em{background:#8da0b6;box-shadow:none}.qb-pulse-lane.is-market b{color:#596b80}
.qb-pulse-note{padding-top:3px;border-top:1px dashed rgba(215,25,32,.24);font-size:clamp(8px,1.95cqw,11px);font-weight:800;color:var(--accent);letter-spacing:.02em}
@keyframes qb-pulse{0%{transform:scale(.82);opacity:.7}70%,100%{transform:scale(1.12);opacity:0}}
@media (prefers-reduced-motion:reduce){.qb-event-pulse__hero:before,.qb-event-pulse__hero:after{animation:none}}
.qb-cycle-map{position:relative;min-height:0;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));grid-template-rows:minmax(0,1fr) auto;gap:clamp(7px,1.8cqw,11px);align-items:center;padding:clamp(5px,1.2cqw,8px) 0 0}
.qb-cycle-map:before{content:"";position:absolute;inset:0 0 24px;background-image:linear-gradient(rgba(31,95,191,.06) 1px,transparent 1px),linear-gradient(90deg,rgba(31,95,191,.06) 1px,transparent 1px);background-size:18px 18px;border-radius:10px;mask-image:linear-gradient(to bottom,transparent,black 28%,black)}
.qb-cycle-track{position:absolute;z-index:0;left:10%;right:10%;top:47%;height:2px;background:linear-gradient(90deg,#7aa5df,#1f5fbf,#7aa5df)}
.qb-cycle-track i{position:absolute;top:50%;width:8px;height:8px;border:2px solid #fff;border-radius:50%;background:#1f5fbf;transform:translate(-50%,-50%);box-shadow:0 0 0 3px rgba(31,95,191,.14)}
.qb-cycle-track i:nth-child(1){left:0}.qb-cycle-track i:nth-child(2){left:50%}.qb-cycle-track i:nth-child(3){left:100%}
.qb-cycle-node{position:relative;z-index:1;min-width:0;display:grid;justify-items:center;text-align:center;padding:clamp(8px,2cqw,12px) clamp(4px,1.2cqw,8px);border:1px solid #cbdcf3;border-radius:12px;background:rgba(255,255,255,.9);box-shadow:0 9px 24px rgba(31,95,191,.08)}
.qb-cycle-node--kc{transform:translateY(-9px);border:2px solid #1f5fbf;background:linear-gradient(160deg,#fff,#eaf3ff)}
.qb-cycle-node span{font-size:clamp(9px,2.3cqw,13px);font-weight:900;color:var(--muted);white-space:nowrap}
.qb-cycle-node b{margin-top:4px;font-size:clamp(22px,6.7cqw,39px);line-height:.95;font-weight:950;color:#173b72;letter-spacing:-.04em}
.qb-cycle-node--kc b{color:#1f5fbf}.qb-cycle-node small{margin-top:5px;font-size:clamp(8px,1.85cqw,10px);font-weight:800;color:#6b83a4}
.qb-cycle-caption{position:relative;z-index:1;grid-column:1/4;text-align:center;font-size:clamp(8px,2cqw,11px);font-weight:800;color:#5e7596;letter-spacing:.025em}
@container (max-width: 340px){
  .qb-card-artifact[data-qb-live-card]{gap:3px;padding:8px;border-top-width:4px}
  .qb-card-meta{min-height:12px;font-size:9px}
  .qb-card-artifact h1{font-size:15px;line-height:1.02}
  .qb-card-artifact p{font-size:9px;line-height:1.1;display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden}
  .qb-card-core{gap:4px}
  .qb-tier-grid{gap:4px}
  .qb-tier-grid>div,.qb-mini-metric{padding:5px;border-radius:6px}
  .qb-tier-grid span,.qb-mini-metric span{font-size:8px}
  .qb-tier-grid b,.qb-mini-metric b{margin-top:2px;font-size:14px}
  .qb-tier-grid i{margin-top:2px;font-size:8px}
  .qb-hero-split{gap:6px;grid-template-columns:minmax(54px,.64fr) 1fr}
  .qb-signal-mark{min-height:48px;font-size:25px}
  .qb-taco-flow{gap:4px}
  .qb-taco-stage{gap:2px;border-radius:6px}
  .qb-taco-stage b{font-size:10px}
  .qb-taco-stage span{font-size:7px}
  .qb-taco-metrics>div{padding:4px}
  .qb-taco-metrics b{font-size:12px}
  .qb-taco-metrics span{font-size:7px}
  .qb-numeric-focus{grid-template-columns:minmax(80px,.82fr) minmax(0,1.18fr);gap:5px}
  .qb-numeric-hero,.qb-numeric-context>div{padding:5px;border-radius:7px}
  .qb-basis-structure{grid-template-columns:minmax(78px,.7fr) minmax(0,1.3fr);gap:5px}
  .qb-basis-hero{padding:5px;border-radius:8px}.qb-basis-axis{min-height:62px;border-radius:7px}
  .qb-basis-marker b{padding:2px 5px}.qb-basis-marker em{width:7px;height:7px}
  .qb-event-pulse{grid-template-columns:minmax(82px,.72fr) minmax(0,1.28fr);gap:7px}
  .qb-pulse-note{display:none}
  .qb-cycle-node{padding:6px 3px;border-radius:8px}
  .qb-cycle-node--kc{transform:translateY(-5px)}
}
"""


RUNTIME = r"""<script id="qb-card-runtime-v1" data-qb-card-runtime>
(function(){
  var INDUSTRY_NAMES = {
    sw_agri:"农林牧渔",sw_chem:"基础化工",sw_steel:"钢铁",sw_nonferrous:"有色金属",sw_electronics:"电子",sw_homeapp:"家用电器",sw_food:"食品饮料",sw_textile:"纺织服饰",sw_light:"轻工制造",sw_pharma:"医药生物",sw_utility:"公用事业",sw_transport:"交通运输",sw_realestate:"房地产",sw_retail:"商贸零售",sw_service:"社会服务",sw_conglomerate:"综合",
    sw_buildmat:"建筑材料",sw_build:"建筑装饰",sw_power:"电力设备",sw_defense:"国防军工",sw_computer:"计算机",sw_media:"传媒",sw_telecom:"通信",sw_bank:"银行",sw_broker:"非银金融",sw_auto:"汽车",sw_machine:"机械设备",sw_coal:"煤炭",sw_oil:"石油石化",sw_env:"环保",sw_beauty:"美容护理"
  };
  function isObj(v){ return v && typeof v === "object" && !Array.isArray(v); }
  function unwrap(v){
    if (v && v.data != null && (v.read_mode || v.data_id || v.error == null)) v = v.data;
    if (isObj(v)) {
      var keys = ["last_value", "last_day_stats", "last_valid_per_asset"];
      for (var i=0;i<keys.length;i++) if (v[keys[i]] != null) return unwrap(v[keys[i]]);
    }
    return v;
  }
  function range(output){
    var data = unwrap(output);
    if (isObj(data) && data.range_data) data = data.range_data;
    if (isObj(data) && Array.isArray(data.values)) return { values:data.values, dates:data.dates || [] };
    if (Array.isArray(data)) return { values:data, dates:[] };
    return { values:[], dates:[] };
  }
  function topValues(output){
    var data = unwrap(output);
    if (isObj(data) && data.top_values) data = data.top_values;
    if (isObj(data) && data.last_valid_per_asset) data = data.last_valid_per_asset;
    if (isObj(data) && Array.isArray(data.values)) data = data.values;
    var rows = [];
    if (Array.isArray(data)) {
      data.forEach(function(item, idx){
        if (isObj(item)) {
          var asset = item.asset || item.asset_code || item.symbol || item.code || "";
          var name = item.asset_name || item.name || item.asset || item.symbol || item.code || item.industry || item.label || ("#" + (idx + 1));
          var value = item.value != null ? item.value : numericFromObject(item);
          if (value != null && isFinite(Number(value))) rows.push({ asset:String(asset), name:String(name), value:Number(value) });
        } else if (item != null && isFinite(Number(item))) {
          rows.push({ name:"#" + (idx + 1), value:Number(item) });
        }
      });
    } else if (isObj(data)) {
      Object.keys(data).forEach(function(key){
        if (/date|range|total|valid|returned|asset|coverage|nan|shape|signature|id/i.test(key)) return;
        var item = data[key], value = isObj(item) ? numericFromObject(item) : item;
        if (value != null && isFinite(Number(value))) rows.push({ name:String(key), value:Number(value) });
      });
    }
    rows.sort(function(a,b){ return b.value - a.value; });
    return rows;
  }
  function assetRows(output){
    var data = output && output.data != null ? output.data : output;
    if (isObj(data) && data.last_valid_per_asset) data = data.last_valid_per_asset;
    if (isObj(data) && Array.isArray(data.values)) data = data.values;
    if (!Array.isArray(data)) {
      data = unwrap(output);
      if (isObj(data) && Array.isArray(data.values)) data = data.values;
    }
    var rows = [];
    if (!Array.isArray(data)) return rows;
    data.forEach(function(item, idx){
      if (!isObj(item)) return;
      var asset = item.asset || item.asset_code || item.symbol || item.code;
      var value = item.value != null ? item.value : numericFromObject(item);
      if (!asset || value == null || !isFinite(Number(value))) return;
      rows.push({
        asset:String(asset),
        name:String(item.asset_name || item.name || asset || ("#" + (idx + 1))),
        value:Number(value)
      });
    });
    return rows;
  }
  function avg(vals){
    vals = vals.filter(function(v){ return v != null && isFinite(Number(v)); }).map(Number);
    if (!vals.length) return null;
    return vals.reduce(function(a,b){ return a + b; }, 0) / vals.length;
  }
  function industryTopValues(outputs, metricKey, maskKeys){
    var metricByAsset = {};
    assetRows(outputs[metricKey]).forEach(function(row){ metricByAsset[row.asset] = row; });
    var rows = [];
    maskKeys.forEach(function(maskKey){
      var vals = [];
      assetRows(outputs[maskKey]).forEach(function(maskRow){
        if (!(Number(maskRow.value) > 0)) return;
        var metric = metricByAsset[maskRow.asset];
        if (metric && metric.value != null && isFinite(Number(metric.value))) vals.push(Number(metric.value));
      });
      var value = avg(vals);
      if (value != null) rows.push({ key:maskKey, name:INDUSTRY_NAMES[maskKey] || maskKey, value:value, count:vals.length });
    });
    rows.sort(function(a,b){ return b.value - a.value; });
    return rows;
  }
  function numericFromObject(obj){
    if (!isObj(obj)) return null;
    var preferred = ["value","score","ret","return","pct","pe","pb","roe","amount","price","close"];
    for (var i=0;i<preferred.length;i++) {
      var key = preferred[i];
      if (obj[key] != null && obj[key] !== "" && isFinite(Number(obj[key]))) return Number(obj[key]);
    }
    var vals = [];
    Object.keys(obj).forEach(function(key){
      if (/date|time|code|asset|symbol|name|industry/i.test(key)) return;
      var v = obj[key];
      if (v != null && v !== "" && isFinite(Number(v))) vals.push(Number(v));
    });
    if (!vals.length) return null;
    return vals.reduce(function(a,b){ return a + b; }, 0) / vals.length;
  }
  function lastValue(output){
    var data = unwrap(output);
    if (isObj(data) && data.value != null) return data.value;
    if (isObj(data) && Array.isArray(data.top_values)) {
      var topVals = data.top_values.map(function(item){ return item && item.value; }).filter(function(v){ return v != null && v !== "" && isFinite(Number(v)); }).map(Number);
      if (topVals.length) return topVals.reduce(function(a,b){ return a + b; }, 0) / topVals.length;
    }
    var ranged = range(output).values;
    for (var k=ranged.length-1;k>=0;k--) if (ranged[k] != null && ranged[k] !== "" && isFinite(Number(ranged[k]))) return Number(ranged[k]);
    if (Array.isArray(data)) {
      for (var j=data.length-1;j>=0;j--) {
        if (isObj(data[j])) {
          var objVal = numericFromObject(data[j]);
          if (objVal != null) return objVal;
        } else if (data[j] != null && data[j] !== "" && isFinite(Number(data[j]))) {
          return Number(data[j]);
        }
      }
    }
    if (isObj(data)) {
      var direct = numericFromObject(data);
      if (direct != null) return direct;
      var children = [];
      Object.keys(data).forEach(function(key){ if (isObj(data[key]) || Array.isArray(data[key])) children.push(lastValue({ data:data[key] })); });
      children = children.filter(function(v){ return v != null && isFinite(Number(v)); }).map(Number);
      if (children.length) return children.reduce(function(a,b){ return a + b; }, 0) / children.length;
    }
    if (data != null && data !== "" && isFinite(Number(data))) return Number(data);
    return null;
  }
  function firstValue(output){
    var r = range(output).values;
    for (var i=0;i<r.length;i++) if (r[i] != null && r[i] !== "" && isFinite(Number(r[i]))) return Number(r[i]);
    return lastValue(output);
  }
  function outputDate(output){
    var data = output && output.data != null ? output.data : output;
    var best = "";
    var bestNum = -1;
    function consider(date){
      var digits = dateDigits(date);
      var n = digits ? Number(digits) : -1;
      if (n > bestNum) {
        bestNum = n;
        best = digits;
      }
    }
    function walk(value, depth){
      if (depth > 8 || value == null) return;
      if (Array.isArray(value)) {
        value.forEach(function(item){ walk(item, depth + 1); });
        return;
      }
      if (!isObj(value)) return;
      consider(value.date || value.trade_date || value.data_date || value.as_of_date);
      Object.keys(value).forEach(function(key){
        if (/^(dates?|begin_date|end_date|start_date)$/i.test(key)) return;
        var child = value[key];
        if (isObj(child) || Array.isArray(child)) walk(child, depth + 1);
      });
    }
    var r = range(output);
    for (var i=0;i<r.dates.length;i++) if (r.values[i] != null && r.dates[i]) consider(r.dates[i]);
    walk(data, 0);
    return best;
  }
  function dateDigits(date){
    var digits = String(date || "").replace(/\D/g, "");
    return digits.length >= 8 ? digits.slice(0, 8) : "";
  }
  function formatDate(date){
    var digits = dateDigits(date);
    return digits ? digits.slice(0,4) + "-" + digits.slice(4,6) + "-" + digits.slice(6,8) : "";
  }
  function cardDate(outputs){
    var keys = Object.keys(outputs || {});
    var best = "";
    var bestNum = -1;
    for (var i=0;i<keys.length;i++) {
      var d = outputDate(outputs[keys[i]]);
      var digits = dateDigits(d);
      var n = digits ? Number(digits) : -1;
      if (n > bestNum) {
        bestNum = n;
        best = digits;
      }
    }
    return formatDate(best);
  }
  function ret(outputs, key){
    var out = outputs && outputs[key];
    var a = firstValue(out), b = lastValue(out);
    if (a == null || b == null || !isFinite(a) || !isFinite(b) || a === 0) return null;
    return (b / a - 1) * 100;
  }
  function pctSmart(v){
    if (v == null || !isFinite(Number(v))) return null;
    v = Number(v);
    return Math.abs(v) <= 1 ? v * 100 : v;
  }
  function fmt(v, format){
    if (v == null || v === "" || !isFinite(Number(v))) return "0";
    v = Number(v);
    if (format === "int") return String(Math.round(v));
    if (format === "pct") return (v * 100).toFixed(1) + "%";
    if (format === "pct-smart") return pctSmart(v).toFixed(1) + "%";
    if (format === "signed-pct") return (v >= 0 ? "+" : "") + pctSmart(v).toFixed(1) + "%";
    if (format === "return") return (v >= 0 ? "+" : "") + v.toFixed(1) + "%";
    if (format === "regime") return v >= 0.5 ? "进攻" : "防守";
    if (format === "number1") return v.toFixed(1);
    return Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2);
  }
  function groupReturn(outputs, list){
    var vals = list.map(function(k){ return ret(outputs, k); }).filter(function(v){ return v != null && isFinite(v); });
    if (!vals.length) return null;
    return vals.reduce(function(a,b){ return a+b; }, 0) / vals.length;
  }
  function dispersion(outputs, list){
    var vals = list.map(function(k){ return ret(outputs, k); }).filter(function(v){ return v != null && isFinite(v); });
    if (!vals.length) return null;
    var avg = vals.reduce(function(a,b){ return a+b; }, 0) / vals.length;
    var variance = vals.reduce(function(a,b){ return a + Math.pow(b - avg, 2); }, 0) / vals.length;
    return Math.sqrt(variance);
  }
  function setBar(el, value){
    var width = Math.max(6, Math.min(100, Math.abs(value == null ? 0 : Number(value)) * 4));
    el.style.width = width.toFixed(0) + "%";
  }
  function positionSpreadMarkers(root, outputs){
    var markers = Array.prototype.slice.call(root.querySelectorAll("[data-qb-spread-marker]"));
    if (!markers.length) return;
    var values = markers.map(function(el){
      return spread(outputs, el.getAttribute("data-a"), el.getAttribute("data-b"));
    });
    var finite = values.filter(function(value){ return value != null && isFinite(Number(value)); }).map(function(value){ return Math.abs(Number(value)); });
    var maxAbs = Math.max.apply(null, finite.concat([1]));
    markers.forEach(function(el, index){
      var value = values[index];
      var numeric = value == null || !isFinite(Number(value)) ? 0 : Number(value);
      var left = 50 + Math.max(-1, Math.min(1, numeric / maxAbs)) * 38;
      el.style.left = left.toFixed(1) + "%";
      el.classList.toggle("is-positive", numeric > 0);
      el.setAttribute("aria-label", (el.textContent || "合约").trim() + " " + fmt(numeric, "number1"));
    });
  }
  function percentForBar(value, format){
    if (value == null || !isFinite(Number(value))) return 0;
    if (format === "pct") return Number(value) * 100;
    if (format === "pct-smart" || format === "signed-pct") return pctSmart(value);
    return Number(value);
  }
  function setMeter(el, value, format){
    var width = Math.max(0, Math.min(100, percentForBar(value, format)));
    el.style.width = width.toFixed(0) + "%";
  }
  function drawSpark(el, outputs){
    var r = range(outputs[el.getAttribute("data-output")]);
    var vals = r.values.filter(function(v){ return v != null && isFinite(Number(v)); }).map(Number);
    if (vals.length < 2) return;
    vals = vals.slice(Math.max(0, vals.length - 80));
    var min = Math.min.apply(null, vals), max = Math.max.apply(null, vals);
    var span = max - min || 1;
    var points = vals.map(function(v, i){
      var x = 10 + i * (280 / Math.max(1, vals.length - 1));
      var y = 70 - ((v - min) / span) * 58;
      return [x.toFixed(1), y.toFixed(1)];
    });
    el.innerHTML = '<path d="M' + points.map(function(p){ return p[0] + ' ' + p[1]; }).join(' L') + '"/>';
  }
  function drawMultiSpark(el, outputs){
    var list = (el.getAttribute("data-outputs") || "").split(/\s+/).filter(Boolean);
    var series = list.map(function(key){
      var vals = range(outputs[key]).values.filter(function(v){ return v != null && isFinite(Number(v)); }).map(Number);
      if (vals.length < 2) return null;
      vals = vals.slice(Math.max(0, vals.length - 80));
      var first = vals[0] || 1;
      return vals.map(function(v){ return first ? (v / first - 1) * 100 : v; });
    }).filter(Boolean);
    if (!series.length) return;
    var all = [];
    series.forEach(function(vals){ all = all.concat(vals); });
    var min = Math.min.apply(null, all), max = Math.max.apply(null, all), span = max - min || 1;
    el.innerHTML = series.map(function(vals){
      var points = vals.map(function(v, i){
        var x = 10 + i * (280 / Math.max(1, vals.length - 1));
        var y = 82 - ((v - min) / span) * 68;
        return [x.toFixed(1), y.toFixed(1)];
      });
      return '<path d="M' + points.map(function(p){ return p[0] + ' ' + p[1]; }).join(' L') + '"/>';
    }).join("");
  }
  function spread(outputs, a, b){
    var av = lastValue(outputs[a]), bv = lastValue(outputs[b]);
    if (av == null || bv == null || !isFinite(Number(av)) || !isFinite(Number(bv))) return null;
    return Number(av) - Number(bv);
  }
  function relativeReturn(outputs, key, base){
    var value = ret(outputs, key);
    if (!base) return value;
    var baseValue = ret(outputs, base);
    if (value == null || baseValue == null) return value;
    return value - baseValue;
  }
  function renderTopList(el, outputs){
    var key = el.getAttribute("data-output");
    var format = el.getAttribute("data-format") || "";
    var limit = Math.max(1, Math.min(6, Number(el.getAttribute("data-limit") || 4)));
    var rows = topValues(outputs[key]).slice(0, limit);
    var body = el.querySelector(".qb-top-list-body");
    if (!body || !rows.length) return;
    body.innerHTML = rows.map(function(row){
      return "<div><span>" + String(row.name).replace(/[<>&]/g, "") + "</span><b>" + fmt(row.value, format) + "</b></div>";
    }).join("");
  }
  function renderTopValue(el, outputs){
    var key = el.getAttribute("data-output");
    var format = el.getAttribute("data-format") || "";
    var rows = topValues(outputs[key]);
    if (!rows.length) return;
    el.textContent = fmt(rows[0].value, format);
  }
  function renderIndustryTopList(el, outputs){
    var key = el.getAttribute("data-output");
    var masks = (el.getAttribute("data-masks") || "").split(/\s+/).filter(Boolean);
    var format = el.getAttribute("data-format") || "";
    var limit = Math.max(1, Math.min(6, Number(el.getAttribute("data-limit") || 4)));
    var rows = industryTopValues(outputs, key, masks).slice(0, limit);
    var body = el.querySelector(".qb-top-list-body");
    if (!body || !rows.length) return;
    body.innerHTML = rows.map(function(row){
      return "<div><span>" + String(row.name).replace(/[<>&]/g, "") + "</span><b>" + fmt(row.value, format) + "</b></div>";
    }).join("");
  }
  function renderIndustryTopValue(el, outputs){
    var key = el.getAttribute("data-output");
    var masks = (el.getAttribute("data-masks") || "").split(/\s+/).filter(Boolean);
    var format = el.getAttribute("data-format") || "";
    var rows = industryTopValues(outputs, key, masks);
    if (!rows.length) return;
    el.textContent = fmt(rows[0].value, format);
  }
  function hydrate(root, outputs){
    if (!root) return;
    outputs = outputs || {};
    var d = cardDate(outputs);
    if (d) Array.prototype.forEach.call(root.querySelectorAll('[data-qb-bind="date"]'), function(el){ el.textContent = d; el.setAttribute("datetime", d); });
    Array.prototype.forEach.call(root.querySelectorAll("[data-qb-value]"), function(el){
      var key = el.getAttribute("data-output");
      var format = el.getAttribute("data-format") || "";
      var value = format === "return" ? ret(outputs, key) : lastValue(outputs[key]);
      el.textContent = fmt(value, format);
    });
    Array.prototype.forEach.call(root.querySelectorAll("[data-qb-bar]"), function(el){
      var key = el.getAttribute("data-output");
      var format = el.getAttribute("data-format") || "";
      var value = percentForBar(lastValue(outputs[key]), format);
      setBar(el, value);
    });
    Array.prototype.forEach.call(root.querySelectorAll("[data-qb-group]"), function(row){
      var list = (row.getAttribute("data-qb-group") || "").split(/\s+/).filter(Boolean);
      var value = groupReturn(outputs, list);
      var score = row.querySelector("[data-qb-group-score]");
      var bar = row.querySelector("[data-qb-group-bar]");
      if (score) score.textContent = fmt(value, "return");
      if (bar) setBar(bar, value);
    });
    Array.prototype.forEach.call(root.querySelectorAll("[data-qb-sparkline]"), function(el){ drawSpark(el, outputs); });
    Array.prototype.forEach.call(root.querySelectorAll("[data-qb-multi-spark]"), function(el){ drawMultiSpark(el, outputs); });
    Array.prototype.forEach.call(root.querySelectorAll("[data-qb-top-list]"), function(el){ renderTopList(el, outputs); });
    Array.prototype.forEach.call(root.querySelectorAll("[data-qb-top-value]"), function(el){ renderTopValue(el, outputs); });
    Array.prototype.forEach.call(root.querySelectorAll("[data-qb-industry-top-list]"), function(el){ renderIndustryTopList(el, outputs); });
    Array.prototype.forEach.call(root.querySelectorAll("[data-qb-industry-top-value]"), function(el){ renderIndustryTopValue(el, outputs); });
    Array.prototype.forEach.call(root.querySelectorAll("[data-qb-meter-bar]"), function(el){
      var key = el.getAttribute("data-output");
      var format = el.getAttribute("data-format") || "";
      setMeter(el, lastValue(outputs[key]), format);
    });
    Array.prototype.forEach.call(root.querySelectorAll("[data-qb-spread]"), function(el){
      el.textContent = fmt(spread(outputs, el.getAttribute("data-a"), el.getAttribute("data-b")), "number1");
    });
    Array.prototype.forEach.call(root.querySelectorAll("[data-qb-spread-bar]"), function(el){
      setBar(el, spread(outputs, el.getAttribute("data-a"), el.getAttribute("data-b")));
    });
    positionSpreadMarkers(root, outputs);
    Array.prototype.forEach.call(root.querySelectorAll("[data-qb-relative-return]"), function(el){
      el.textContent = fmt(relativeReturn(outputs, el.getAttribute("data-output"), el.getAttribute("data-base")), "return");
    });
    Array.prototype.forEach.call(root.querySelectorAll("[data-qb-relative-return-bar]"), function(el){
      setBar(el, relativeReturn(outputs, el.getAttribute("data-output"), el.getAttribute("data-base")));
    });
    Array.prototype.forEach.call(root.querySelectorAll("[data-qb-dispersion]"), function(el){
      var list = (el.getAttribute("data-outputs") || "").split(/\s+/).filter(Boolean);
      el.textContent = fmt(dispersion(outputs, list), "return");
    });
    Array.prototype.forEach.call(root.querySelectorAll("[data-qb-dispersion-bar]"), function(el){
      var list = (el.getAttribute("data-outputs") || "").split(/\s+/).filter(Boolean);
      setBar(el, dispersion(outputs, list));
    });
    Array.prototype.forEach.call(root.querySelectorAll("[data-qb-return]"), function(el){
      el.textContent = fmt(ret(outputs, el.getAttribute("data-output")), "return");
    });
    Array.prototype.forEach.call(root.querySelectorAll("[data-qb-return-bar]"), function(el){
      setBar(el, ret(outputs, el.getAttribute("data-output")));
    });
    Array.prototype.forEach.call(root.querySelectorAll("[data-qb-best]"), function(el){
      var list = (el.getAttribute("data-outputs") || "").split(/\s+/).filter(Boolean);
      var best = list.map(function(k){ return { k:k, v:ret(outputs,k) }; }).filter(function(x){ return x.v != null; }).sort(function(a,b){ return b.v-a.v; })[0];
      el.textContent = best ? best.k.replace(/_px$/,'') + ' ' + fmt(best.v, 'return') : '0%';
    });
    var card = root.querySelector("[data-qb-live-card]");
    if (card) card.setAttribute("data-qb-card-ready", "true");
  }
  window.QBCardRuntimeV1 = {
    hydrate: function(root, outputs){ hydrate(root, outputs); },
    mount: function(root, options){
      var template = document.querySelector("template[data-qb-card-template]");
      if (!root || !template) return null;
      root.replaceChildren(template.content.cloneNode(true));
      hydrate(root, options && options.outputs || {});
      return { hydrate:function(outputs){ hydrate(root, outputs); }, dispose:function(){ root.replaceChildren(); } };
    },
    dispose: function(root){ if (root) root.replaceChildren(); }
  };
})();
</script>"""


def build_artifacts(page_id, title, manifest, output_keys, visual_contract=None):
    required, card, visual_kind = _build_page_card(
        page_id,
        title,
        _sort_keys(output_keys),
        visual_contract=visual_contract,
    )
    missing = [k for k in required if k not in output_keys]
    if missing:
        raise ValueError("生成器引用了不存在的 outputs: %s" % ", ".join(missing))
    packages = manifest.get("_packages_resolved") or _manifest_packages(manifest)
    if not packages:
        raise ValueError("card manifest 缺少可用公式包")
    first = packages[0]
    package_blocks = []
    required_set = set(required)
    for pkg in packages:
        outputs = [key for key in (pkg.get("outputs") or []) if key in required_set]
        if not outputs:
            continue
        package_blocks.append({
            "role": pkg.get("role") or "package_%d" % (len(package_blocks) + 1),
            "endpoint": pkg["endpoint"],
            "package_id": pkg["package_id"],
            "signature": pkg["signature"],
            "outputs": outputs,
        })
    if not package_blocks:
        raise ValueError("required_outputs 未匹配到任何公式包")
    manifest2 = {
        "version": CARD_RUNTIME_VERSION,
        "kind": CARD_RUNTIME_KIND,
        "package_id": first["package_id"],
        "signature": first["signature"],
        "endpoint": first["endpoint"],
        "packages": package_blocks,
        "required_outputs": required,
        "aspect_ratio": "4/3",
        "visual_kind": visual_kind,
    }
    validate_manifest(manifest2)
    manifest_text = json.dumps(manifest2, ensure_ascii=False, indent=2).replace("</", "<\\/")
    template = "<template data-qb-card-template>\n%s\n</template>" % card
    style = "<style data-qb-card-style>\n%s\n</style>" % STYLE.strip()
    manifest_block = "<script type=\"application/json\" data-qb-card-manifest>\n%s\n</script>" % manifest_text
    block = "\n".join([START, template, style, manifest_block, RUNTIME, END])
    runtime_text = first_tagged_block(RUNTIME, "script", "data-qb-card-runtime")
    validate_runtime_source(runtime_text)
    digest = artifact_hash(card, STYLE, manifest_text, runtime_text)
    return block, {
        "card_runtime_supported": True,
        "card_runtime_version": CARD_RUNTIME_VERSION,
        "card_runtime_kind": CARD_RUNTIME_KIND,
        "card_required_outputs": required,
        "card_visual_kind": visual_kind,
        "card_artifact_hash": digest,
    }


READY_COMPAT_BRIDGE = r"""
;(function(){
  var runtime = window.QBCardRuntimeV1;
  if (!runtime || runtime.__qbReadyCompatV110) return;
  function markReady(root){
    if (!root || !root.querySelector) return;
    var card = root.querySelector("[data-qb-live-card]");
    if (card) card.setAttribute("data-qb-card-ready", "true");
  }
  var originalHydrate = runtime.hydrate;
  if (typeof originalHydrate === "function") {
    runtime.hydrate = function(root, outputs){
      var result = originalHydrate.call(runtime, root, outputs);
      markReady(root);
      return result;
    };
  }
  var originalMount = runtime.mount;
  if (typeof originalMount === "function") {
    runtime.mount = function(root, options){
      var mounted = originalMount.call(runtime, root, options);
      markReady(root);
      if (mounted && typeof mounted.hydrate === "function") {
        var mountedHydrate = mounted.hydrate;
        mounted.hydrate = function(outputs){
          var result = mountedHydrate.call(mounted, outputs);
          markReady(root);
          return result;
        };
      }
      return mounted;
    };
  }
  runtime.__qbReadyCompatV110 = true;
})();
""".strip()


def upgrade_artifact_protocol(html):
    """Upgrade an existing artifact without changing its template or style."""
    text = html or ""
    artifact = {
        "template": first_tagged_block(text, "template", "data-qb-card-template"),
        "style": first_tagged_block(text, "style", "data-qb-card-style"),
        "manifest": first_tagged_block(text, "script", "data-qb-card-manifest"),
        "runtime": first_tagged_block(text, "script", "data-qb-card-runtime"),
    }
    missing = [name for name, value in artifact.items() if not value]
    if missing:
        raise ValueError("页面缺少完整 Card Runtime artifact: %s" % ", ".join(missing))

    manifest = json.loads(artifact["manifest"])
    manifest["version"] = CARD_RUNTIME_VERSION
    validate_manifest(manifest)
    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2).replace("</", "<\\/")
    manifest_pattern = re.compile(
        r"(<script\b(?=[^>]*\bdata-qb-card-manifest\b)[^>]*>)[\s\S]*?(</script>)",
        re.I,
    )
    next_html, manifest_count = manifest_pattern.subn(
        lambda match: match.group(1) + "\n" + manifest_text + "\n" + match.group(2),
        text,
        count=1,
    )
    if manifest_count != 1:
        raise ValueError("无法精确升级 card manifest")

    runtime_text = artifact["runtime"]
    if "data-qb-card-ready" not in runtime_text:
        runtime_text = runtime_text.rstrip() + "\n" + READY_COMPAT_BRIDGE
    validate_runtime_source(runtime_text)
    runtime_pattern = re.compile(
        r"(<script\b(?=[^>]*\bdata-qb-card-runtime\b)[^>]*>)[\s\S]*?(</script>)",
        re.I,
    )
    next_html, runtime_count = runtime_pattern.subn(
        lambda match: match.group(1) + "\n" + runtime_text + "\n" + match.group(2),
        next_html,
        count=1,
    )
    if runtime_count != 1:
        raise ValueError("无法精确升级 card runtime")

    digest = artifact_hash(artifact["template"], artifact["style"], manifest_text, runtime_text)
    return next_html, {
        "mode": "protocol_only",
        "card_runtime_supported": True,
        "card_runtime_version": CARD_RUNTIME_VERSION,
        "card_runtime_kind": manifest.get("kind") or CARD_RUNTIME_KIND,
        "card_required_outputs": list(manifest.get("required_outputs") or []),
        "card_artifact_hash": digest,
        "template_preserved": first_tagged_block(next_html, "template", "data-qb-card-template") == artifact["template"],
        "style_preserved": first_tagged_block(next_html, "style", "data-qb-card-style") == artifact["style"],
    }


def replace_artifact_block(html, block):
    pattern = re.compile(re.escape(START) + r"[\s\S]*?" + re.escape(END), re.I)
    if pattern.search(html or ""):
        return pattern.sub(lambda _m: block, html, count=1), "replace"

    # Early Card Runtime pages predate the marker-delimited artifact block.
    # Appending a new block leaves the legacy template/manifest first in DOM
    # order, so both the verifier and snapshot worker keep hydrating v1.0.x.
    # Remove every unmarked artifact tag before inserting the current block.
    legacy_patterns = [
        r"<template\b(?=[^>]*\bdata-qb-card-template\b)[^>]*>[\s\S]*?</template>",
        r"<style\b(?=[^>]*\bdata-qb-card-style\b)[^>]*>[\s\S]*?</style>",
        r"<script\b(?=[^>]*\bdata-qb-card-manifest\b)[^>]*>[\s\S]*?</script>",
        r"<script\b(?=[^>]*\bdata-qb-card-runtime\b)[^>]*>[\s\S]*?</script>",
    ]
    next_html = html or ""
    removed = 0
    for legacy_pattern in legacy_patterns:
        next_html, count = re.subn(legacy_pattern, "", next_html, flags=re.I)
        removed += count
    mode = "replace_legacy" if removed else "append"
    if "</body>" in next_html.lower():
        return re.sub(r"</body\s*>", lambda _m: block + "\n</body>", next_html, count=1, flags=re.I), mode
    return next_html + "\n" + block, mode


def retrofit_html(html, *, page_id="", title="", visual_contract=None):
    manifest = parse_manifest(html)
    outputs = query_all_outputs(manifest)
    output_keys = _sort_keys(outputs.keys())
    block, meta = build_artifacts(
        page_id,
        title or _title_from_html(html),
        manifest,
        output_keys,
        visual_contract=visual_contract,
    )
    next_html, mode = replace_artifact_block(html, block)
    return next_html, {
        "mode": mode,
        "output_count": len(output_keys),
        "output_keys": output_keys,
        **meta,
    }
