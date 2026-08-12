#!/usr/bin/env python3
"""Shared helpers for QuantBuddy card runtime artifacts (embedded-card-v1)."""

import datetime
from html import escape as html_escape
import json
import re

from card_runtime_contract import (
    CARD_RUNTIME_KIND,
    CARD_RUNTIME_VERSION,
    artifact_hash,
    validate_manifest,
    validate_runtime_source,
)


def _clean_text(value, fallback=""):
    text = "" if value is None else str(value).strip()
    return text or fallback


def _theme(value):
    value = _clean_text(value, "orange").lower()
    return value if value in ("red", "blue", "green", "orange") else "orange"


def _date(value=None):
    text = _clean_text(value)
    if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return text
    return datetime.date.today().isoformat()


def _metric_items(config):
    metrics = config.get("metrics") if isinstance(config.get("metrics"), list) else []
    out = []
    for i, item in enumerate(metrics[:3]):
        if isinstance(item, dict):
            out.append({
                "label": _clean_text(item.get("label"), f"指标{i + 1}"),
                "value": _clean_text(item.get("value"), "待更新"),
                "output": _clean_text(item.get("output")),
                "field": _clean_text(item.get("field") or item.get("value_field")),
                "unit": _clean_text(item.get("unit")),
            })
        else:
            out.append({"label": f"指标{i + 1}", "value": _clean_text(item, "待更新")})
    if not out:
        out = [
            {"label": "核心指标", "value": "待更新"},
            {"label": "变化", "value": "待更新"},
            {"label": "水位", "value": "待更新"},
        ]
    return out


def normalize_config(config=None, *, fallback_title="", fallback_description=""):
    if config is True:
        config = {}
    if not isinstance(config, dict):
        config = {}
    metrics = _metric_items(config)
    title = _clean_text(config.get("title"), fallback_title or "页面核心结论一眼看懂")
    description = _clean_text(config.get("description"), fallback_description or "核心指标实时更新，打开页面即按最新数据刷新。")
    primary = config.get("primary") if isinstance(config.get("primary"), dict) else {}
    tags = config.get("tags") if isinstance(config.get("tags"), list) else []
    tags = [_clean_text(t) for t in tags if _clean_text(t)][:3]
    if not tags:
        tags = ["实时取数", "重点摘要"]
    return {
        "title": title,
        "description": description,
        "theme": _theme(config.get("theme")),
        "date": _date(config.get("date")),
        "date_output": _clean_text(config.get("date_output")),
        "metrics": metrics,
        "primary": {
            "label": _clean_text(primary.get("label"), metrics[0]["label"]),
            "value": _clean_text(primary.get("value"), metrics[0]["value"]),
            "output": _clean_text(primary.get("output"), metrics[0].get("output", "")),
            "field": _clean_text(primary.get("field") or primary.get("value_field"), metrics[0].get("field", "")),
            "unit": _clean_text(primary.get("unit"), metrics[0].get("unit", "")),
        },
        "tags": tags,
    }


def card_html(config=None, *, fallback_title="", fallback_description=""):
    cfg = normalize_config(config, fallback_title=fallback_title, fallback_description=fallback_description)
    metrics = []
    for i, item in enumerate(cfg["metrics"]):
        metrics.append(
            '<div class="live-card-metric" data-qb-live-card-metric="{i}"'
            '{output}{field}{unit}><b>{value}</b><span>{label}</span></div>'.format(
                i=i,
                output=f' data-qb-live-card-output="{html_escape(item.get("output", ""), quote=True)}"' if item.get("output") else "",
                field=f' data-qb-live-card-field="{html_escape(item.get("field", ""), quote=True)}"' if item.get("field") else "",
                unit=f' data-qb-live-card-unit="{html_escape(item.get("unit", ""), quote=True)}"' if item.get("unit") else "",
                value=html_escape(item["value"]),
                label=html_escape(item["label"]),
            )
        )
    tags = "\n".join(f'          <span class="live-card-tag">{html_escape(tag)}</span>' for tag in cfg["tags"])
    primary = cfg["primary"]
    return """<section class="essence-section" id="essenceSection" aria-label="宽宝活卡" hidden>
      <article class="essence-card" id="essenceCard" data-qb-live-card data-theme="{theme}">
        <div class="live-card-meta">
          <span data-qb-live-card-brand></span>
          <time data-qb-live-card-date datetime="{date}">{date}</time>
        </div>
        <h1 data-qb-live-card-title>{title}</h1>
        <p data-qb-live-card-description>{description}</p>
        <section class="live-card-core-grid" data-qb-live-card-core>
          <div class="live-card-primary" data-qb-live-card-primary-output="{primary_output}" data-qb-live-card-primary-field="{primary_field}" data-qb-live-card-primary-unit="{primary_unit}">
            <div class="live-card-primary-value" data-qb-live-card-primary>{primary_value}</div>
            <div class="live-card-primary-label">{primary_label}</div>
          </div>
          <div class="live-card-panel">
            <div class="live-card-metric-grid">
              {metrics}
            </div>
          </div>
        </section>
        <div class="live-card-tags">
{tags}
        </div>
      </article>
    </section>""".format(
        theme=html_escape(cfg["theme"], quote=True),
        date=html_escape(cfg["date"], quote=True),
        title=html_escape(cfg["title"]),
        description=html_escape(cfg["description"]),
        primary_output=html_escape(primary.get("output", ""), quote=True),
        primary_field=html_escape(primary.get("field", ""), quote=True),
        primary_unit=html_escape(primary.get("unit", ""), quote=True),
        primary_value=html_escape(primary.get("value", "待更新")),
        primary_label=html_escape(primary.get("label", "核心指标")),
        metrics="\n              ".join(metrics),
        tags=tags,
    )


def required_outputs(config=None, *, fallback_title="", fallback_description=""):
    cfg = normalize_config(config, fallback_title=fallback_title, fallback_description=fallback_description)
    values = []
    for item in [cfg.get("primary"), *(cfg.get("metrics") or [])]:
        if isinstance(item, dict) and _clean_text(item.get("output")):
            values.append(_clean_text(item.get("output")))
    if _clean_text(cfg.get("date_output")):
        values.append(_clean_text(cfg.get("date_output")))
    out = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def card_runtime_artifacts(config=None, *, endpoint="", package_id="", signature="", style="", fallback_title="", fallback_description=""):
    cfg = normalize_config(config, fallback_title=fallback_title, fallback_description=fallback_description)
    card = card_html(cfg)
    card = re.sub(r'\s+id="essenceSection"', "", card, flags=re.I)
    card = re.sub(r"\s+hidden(?=[\s>])", "", card, flags=re.I)
    manifest = {
        "version": CARD_RUNTIME_VERSION,
        "kind": CARD_RUNTIME_KIND,
        "package_id": _clean_text(package_id),
        "signature": _clean_text(signature),
        "endpoint": _clean_text(endpoint),
        "required_outputs": required_outputs(cfg),
        "aspect_ratio": "4/3",
    }
    validate_manifest(manifest)
    manifest_json = json.dumps(manifest, ensure_ascii=False, indent=2).replace("</", "<\\/")
    return """
<template data-qb-card-template>
{card}
</template>
<style data-qb-card-style>
{style}
</style>
<script type="application/json" data-qb-card-manifest>
{manifest}
</script>""".format(card=card, style=style or "", manifest=manifest_json)


def card_runtime_script():
    runtime = r"""<script id="qb-card-runtime-v1" data-qb-card-runtime>
(function(){
  function text(value, fallback){
    var raw = value == null ? "" : String(value).trim();
    return raw || fallback || "";
  }
  function isObj(v){ return v && typeof v === "object" && !Array.isArray(v); }
  function unwrap(data){
    if (data && data.data != null && (data.read_mode || data.data_id || data.error == null)) data = data.data;
    if (isObj(data)) {
      var keys = ["last_value", "last_day_stats", "last_valid_per_asset", "range_data"];
      for (var i = 0; i < keys.length; i++) if (data[keys[i]] != null) return unwrap(data[keys[i]]);
    }
    return data;
  }
  function firstUseful(data, field){
    data = unwrap(data);
    if (Array.isArray(data)) {
      for (var i = data.length - 1; i >= 0; i--) {
        var item = data[i];
        if (Array.isArray(item)) {
          for (var j = item.length - 1; j >= 0; j--) if (item[j] != null && item[j] !== "") return item[j];
        } else if (isObj(item)) {
          if (field && item[field] != null) return item[field];
          var vals = Object.keys(item).map(function(k){ return item[k]; }).filter(function(v){ return v != null && v !== ""; });
          if (vals.length) return vals[vals.length - 1];
        } else if (item != null && item !== "") {
          return item;
        }
      }
    }
    if (isObj(data)) {
      if (field && data[field] != null) return data[field];
      if (Array.isArray(data.values)) {
        for (var k = data.values.length - 1; k >= 0; k--) if (data.values[k] != null) return data.values[k];
      }
      var keys = Object.keys(data).filter(function(k){ return data[k] != null && data[k] !== ""; });
      if (keys.length) return data[keys[keys.length - 1]];
    }
    return data;
  }
  function outputValue(outputs, output, field){
    if (!output || !outputs) return null;
    return firstUseful(outputs[output], field);
  }
  function fmt(v, unit){
    if (v == null || v === "") return "待更新";
    if (typeof v === "number" && isFinite(v)) {
      var abs = Math.abs(v);
      v = abs >= 100 ? v.toFixed(0) : abs >= 10 ? v.toFixed(1) : v.toFixed(2);
    }
    return String(v) + (unit ? " " + unit : "");
  }
  function hydrate(root, outputs){
    if (!root) return;
    outputs = outputs || {};
    var dateEl = root.querySelector("[data-qb-live-card-date]");
    if (dateEl) {
      var date = "";
      Object.keys(outputs).some(function(key){
        var data = unwrap(outputs[key]);
        date = firstUseful(data, "trade_date") || firstUseful(data, "date") || "";
        return !!date;
      });
      if (date) {
        dateEl.textContent = String(date).slice(0, 10);
        if (dateEl.tagName && dateEl.tagName.toLowerCase() === "time") dateEl.setAttribute("datetime", String(date).slice(0, 10));
      }
    }
    var primaryWrap = root.querySelector("[data-qb-live-card-primary-output]");
    var primary = root.querySelector("[data-qb-live-card-primary]");
    if (primary && primaryWrap) {
      var pv = outputValue(outputs, primaryWrap.getAttribute("data-qb-live-card-primary-output"), primaryWrap.getAttribute("data-qb-live-card-primary-field"));
      primary.textContent = fmt(pv, primaryWrap.getAttribute("data-qb-live-card-primary-unit") || "");
    }
    Array.prototype.forEach.call(root.querySelectorAll("[data-qb-live-card-metric]"), function(item){
      var valueEl = item.querySelector("b");
      if (!valueEl) return;
      var value = outputValue(outputs, item.getAttribute("data-qb-live-card-output"), item.getAttribute("data-qb-live-card-field"));
      valueEl.textContent = fmt(value, item.getAttribute("data-qb-live-card-unit") || "");
    });
    var card = root.querySelector("[data-qb-live-card]");
    if (card) card.setAttribute("data-qb-card-ready", "true");
  }
  window.QBCardRuntimeV1 = {
    mount: function(root, options){
      var template = document.querySelector("template[data-qb-card-template]");
      if (!root || !template) return null;
      root.replaceChildren(template.content.cloneNode(true));
      if (options && options.outputs) hydrate(root, options.outputs);
      return {
        hydrate: function(outputs){ hydrate(root, outputs); },
        dispose: function(){ root.replaceChildren(); }
      };
    },
    hydrate: function(root, outputs){ hydrate(root, outputs); },
    dispose: function(root){ if (root) root.replaceChildren(); }
  };
})();
</script>"""
    validate_runtime_source(runtime)
    return runtime


def _artifact_block(source, tag, marker):
    match = re.search(
        r"<%s\b(?=[^>]*\b%s\b)[^>]*>([\s\S]*?)</%s>" % (tag, marker, tag),
        source or "",
        re.I,
    )
    return match.group(1).strip() if match else ""


def card_runtime_bundle(config=None, *, endpoint="", package_id="", signature="", style="", fallback_title="", fallback_description=""):
    """Build the standard artifact and expose the same canonical metadata as retrofit."""
    artifacts = card_runtime_artifacts(
        config,
        endpoint=endpoint,
        package_id=package_id,
        signature=signature,
        style=style,
        fallback_title=fallback_title,
        fallback_description=fallback_description,
    )
    runtime = card_runtime_script()
    template_text = _artifact_block(artifacts, "template", "data-qb-card-template")
    style_text = _artifact_block(artifacts, "style", "data-qb-card-style")
    manifest_text = _artifact_block(artifacts, "script", "data-qb-card-manifest")
    runtime_text = _artifact_block(runtime, "script", "data-qb-card-runtime")
    if not all((template_text, style_text, manifest_text, runtime_text)):
        raise ValueError("标准生成器产出的 card runtime artifact 不完整")
    manifest = json.loads(manifest_text)
    return {
        "artifacts": artifacts,
        "runtime": runtime,
        "metadata": {
            "card_runtime_supported": True,
            "card_runtime_version": CARD_RUNTIME_VERSION,
            "card_runtime_kind": CARD_RUNTIME_KIND,
            "card_required_outputs": manifest["required_outputs"],
            "card_artifact_hash": artifact_hash(template_text, style_text, manifest_text, runtime_text),
        },
    }


def dashboard_config(spec, panels):
    raw = spec.get("live_card")
    if not raw:
        return None
    if raw is True:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    metrics = raw.get("metrics") if isinstance(raw.get("metrics"), list) else []
    if not metrics:
        ordered = [p for p in panels if isinstance(p, dict) and (p.get("type") or "").lower() == "number"]
        ordered += [p for p in panels if isinstance(p, dict) and p not in ordered]
        for panel in ordered[:3]:
            metrics.append({
                "label": panel.get("title") or panel.get("output") or "指标",
                "output": panel.get("output") or "",
                "field": panel.get("value_field") or "",
                "unit": panel.get("unit") or "",
                "value": "待更新",
            })
    cfg = dict(raw)
    cfg.setdefault("title", spec.get("live_card_title") or spec.get("title"))
    cfg.setdefault("description", spec.get("live_card_description") or spec.get("subtitle") or spec.get("description"))
    cfg.setdefault("metrics", metrics)
    cfg.setdefault("tags", ["实时取数", "重点摘要"])
    return normalize_config(cfg, fallback_title=spec.get("title", ""), fallback_description=spec.get("subtitle", ""))
