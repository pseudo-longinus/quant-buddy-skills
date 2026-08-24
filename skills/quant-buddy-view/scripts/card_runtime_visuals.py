#!/usr/bin/env python3
"""Generic, contract-driven Card Runtime visual renderers.

This module intentionally contains no published page identifiers or page-specific
asset/output constants. A complete rebuild must provide every visible label and
output binding through ``visual_contract``.
"""

import html as _html


def _e(value):
    return _html.escape(str(value or ""), quote=True)


def _invalid(message):
    raise ValueError("CARD_VISUAL_INVALID: %s" % message)


def _required_text(value, path):
    text = str(value or "").strip()
    if not text:
        _invalid("%s 不能为空" % path)
    return text


def _required_dict(value, path):
    if not isinstance(value, dict):
        _invalid("%s 必须是 object" % path)
    return value


def _required_list(value, path, minimum, maximum):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        _invalid("%s 需要 %d-%d 项" % (path, minimum, maximum))
    return value


def _bounded_int(value, path, minimum, maximum):
    try:
        number = int(value)
    except (TypeError, ValueError):
        _invalid("%s 必须是整数" % path)
    if not minimum <= number <= maximum:
        _invalid("%s 必须在 %d-%d 之间" % (path, minimum, maximum))
    return number


def _metric(value, path):
    value = _required_dict(value, path)
    return {
        "label": _required_text(value.get("label"), "%s.label" % path),
        "output": _required_text(value.get("output"), "%s.output" % path),
        "format": _required_text(value.get("format") or "number1", "%s.format" % path),
        "note": str(value.get("note") or "").strip(),
    }


def _unique_outputs(items):
    result = []
    for output in items:
        if output not in result:
            result.append(output)
    return result


def _card(page_id, contract, core, visual_kind):
    title = _required_text(contract.get("title"), "visual_contract.title")
    description = _required_text(contract.get("description"), "visual_contract.description")
    theme = _required_text(contract.get("theme") or "orange", "visual_contract.theme")
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


def _render_numeric_focus(page_id, contract):
    metrics = [_metric(item, "visual_contract.metrics[%d]" % index) for index, item in enumerate(
        _required_list(contract.get("metrics"), "visual_contract.metrics", 1, 3)
    )]
    primary = metrics[0]
    secondary = "\n".join(
        """        <div><span>{label}</span><b data-qb-value data-output="{output}" data-format="{format}">待更新</b></div>""".format(
            label=_e(metric["label"]), output=_e(metric["output"]), format=_e(metric["format"])
        )
        for metric in metrics[1:]
    )
    core = """    <div class="qb-numeric-focus{solo_class}" data-qb-card-numeric-focus data-qb-card-visual>
      <div class="qb-numeric-hero">
        <span>{primary_label}</span>
        <b data-qb-value data-output="{primary_output}" data-format="{primary_format}">待更新</b>
      </div>
      <div class="qb-numeric-context">
{secondary}
      </div>
    </div>""".format(
        solo_class=" is-solo" if len(metrics) == 1 else "",
        primary_label=_e(primary["label"]),
        primary_output=_e(primary["output"]),
        primary_format=_e(primary["format"]),
        secondary=secondary,
    )
    return _unique_outputs(item["output"] for item in metrics), _card(page_id, contract, core, "numeric-focus")


def _render_industry_ranking(page_id, contract):
    output = _required_text(contract.get("output"), "visual_contract.output")
    fmt = _required_text(contract.get("format") or "signed-pct", "visual_contract.format")
    top_count = _bounded_int(contract.get("top_count"), "visual_contract.top_count", 2, 4)
    bottom_count = _bounded_int(contract.get("bottom_count"), "visual_contract.bottom_count", 2, 4)
    labels = _required_dict(contract.get("labels"), "visual_contract.labels")
    strong = _required_text(labels.get("strong"), "visual_contract.labels.strong")
    weak = _required_text(labels.get("weak"), "visual_contract.labels.weak")
    top_badge = _required_text(labels.get("top_badge"), "visual_contract.labels.top_badge").replace("{count}", str(top_count))
    bottom_badge = _required_text(labels.get("bottom_badge"), "visual_contract.labels.bottom_badge").replace("{count}", str(bottom_count))
    axis_top = _required_text(labels.get("axis_top"), "visual_contract.labels.axis_top")
    axis_center = _required_text(labels.get("axis_center"), "visual_contract.labels.axis_center")
    axis_bottom = _required_text(labels.get("axis_bottom"), "visual_contract.labels.axis_bottom")
    loading = _required_text(labels.get("loading"), "visual_contract.labels.loading")
    core = """    <div class="qb-industry-ranking" data-qb-card-visual data-qb-ranking-output="{output}">
      <div class="qb-ranking-side is-strong" data-qb-ranking-list="top" data-output="{output}" data-format="{fmt}" data-limit="{top_count}">
        <div class="qb-ranking-side__head"><span>{strong}</span><b>{top_badge}</b></div>
        <div class="qb-ranking-rows"><div class="qb-ranking-placeholder">{loading}</div></div>
      </div>
      <div class="qb-ranking-spine" aria-hidden="true">
        <span>{axis_top}</span><i></i><b>{axis_center}</b><i></i><span>{axis_bottom}</span>
      </div>
      <div class="qb-ranking-side is-weak" data-qb-ranking-list="bottom" data-output="{output}" data-format="{fmt}" data-limit="{bottom_count}">
        <div class="qb-ranking-side__head"><span>{weak}</span><b>{bottom_badge}</b></div>
        <div class="qb-ranking-rows"><div class="qb-ranking-placeholder">{loading}</div></div>
      </div>
    </div>""".format(**{key: _e(value) for key, value in {
        "output": output, "fmt": fmt, "top_count": top_count, "bottom_count": bottom_count,
        "strong": strong, "weak": weak, "top_badge": top_badge, "bottom_badge": bottom_badge,
        "axis_top": axis_top, "axis_center": axis_center, "axis_bottom": axis_bottom, "loading": loading,
    }.items()})
    return [output], _card(page_id, contract, core, "industry-ranking")


def _render_event_flow(page_id, contract):
    stages = _required_list(contract.get("stages"), "visual_contract.stages", 2, 6)
    normalized_stages = []
    for index, stage in enumerate(stages):
        stage = _required_dict(stage, "visual_contract.stages[%d]" % index)
        normalized_stages.append({
            "label": _required_text(stage.get("label"), "visual_contract.stages[%d].label" % index),
            "detail": _required_text(stage.get("detail"), "visual_contract.stages[%d].detail" % index),
        })
    metrics = [_metric(item, "visual_contract.metrics[%d]" % index) for index, item in enumerate(
        _required_list(contract.get("metrics"), "visual_contract.metrics", 1, 3)
    )]
    aria_label = _required_text(contract.get("aria_label"), "visual_contract.aria_label")
    stage_html = "\n".join(
        "        <div class=\"qb-event-flow-stage\"><b>{label}</b><span>{detail}</span></div>".format(
            label=_e(item["label"]), detail=_e(item["detail"])
        ) for item in normalized_stages
    )
    metric_html = "\n".join(
        "        <div><b data-qb-value data-output=\"{output}\" data-format=\"{format}\">待更新</b><span>{label}</span></div>".format(
            output=_e(item["output"]), format=_e(item["format"]), label=_e(item["label"])
        ) for item in metrics
    )
    core = """    <div class="qb-event-flow-flow" data-qb-card-visual>
      <div class="qb-event-flow-track" data-qb-stage-count="{stage_count}" aria-label="{aria_label}">
{stages}
      </div>
      <div class="qb-event-flow-metrics">
{metrics}
      </div>
    </div>""".format(stage_count=len(normalized_stages), aria_label=_e(aria_label), stages=stage_html, metrics=metric_html)
    return _unique_outputs(item["output"] for item in metrics), _card(page_id, contract, core, "event-flow")


def _render_basis_structure(page_id, contract):
    spot = _metric(contract.get("spot"), "visual_contract.spot")
    nodes_raw = _required_list(contract.get("contracts"), "visual_contract.contracts", 1, 2)
    nodes = []
    for index, node in enumerate(nodes_raw):
        node = _required_dict(node, "visual_contract.contracts[%d]" % index)
        nodes.append({
            "label": _required_text(node.get("label"), "visual_contract.contracts[%d].label" % index),
            "output": _required_text(node.get("output"), "visual_contract.contracts[%d].output" % index),
        })
    labels = _required_dict(contract.get("labels"), "visual_contract.labels")
    hero = _required_text(labels.get("hero"), "visual_contract.labels.hero")
    hero_note = _required_text(labels.get("hero_note"), "visual_contract.labels.hero_note")
    discount = _required_text(labels.get("discount"), "visual_contract.labels.discount")
    anchor = _required_text(labels.get("anchor"), "visual_contract.labels.anchor")
    premium = _required_text(labels.get("premium"), "visual_contract.labels.premium")
    axis_label = _required_text(labels.get("axis_label"), "visual_contract.labels.axis_label")
    marker_html = "\n".join(
        """        <div class="qb-basis-marker {klass}" data-qb-spread-marker data-a="{output}" data-b="{spot}">
          <b>{label}</b><em></em>
        </div>""".format(
            klass="is-front" if index == 0 else "is-next",
            output=_e(node["output"]), spot=_e(spot["output"]), label=_e(node["label"]),
        ) for index, node in enumerate(nodes)
    )
    primary = nodes[0]
    core = """    <div class="qb-basis-structure" data-qb-card-visual>
      <div class="qb-basis-hero">
        <span>{hero}</span>
        <b data-qb-spread data-a="{primary_output}" data-b="{spot_output}">待更新</b>
        <small>{hero_note}</small>
      </div>
      <div class="qb-basis-axis" aria-label="{axis_label}">
        <div class="qb-basis-scale"><span>{discount}</span><b>{anchor}</b><span>{premium}</span></div>
        <i class="qb-basis-zero"></i>
{markers}
      </div>
      <div class="qb-basis-anchor"><span>{spot_label}</span><b data-qb-value data-output="{spot_output}" data-format="{spot_format}">待更新</b></div>
    </div>""".format(
        hero=_e(hero), primary_output=_e(primary["output"]), spot_output=_e(spot["output"]),
        hero_note=_e(hero_note), axis_label=_e(axis_label), discount=_e(discount), anchor=_e(anchor),
        premium=_e(premium), markers=marker_html, spot_label=_e(spot["label"]), spot_format=_e(spot["format"]),
    )
    return _unique_outputs([spot["output"]] + [node["output"] for node in nodes]), _card(page_id, contract, core, "basis-structure")


def _render_event_pulse(page_id, contract):
    primary = _metric(contract.get("primary"), "visual_contract.primary")
    comparisons = [_metric(item, "visual_contract.comparisons[%d]" % index) for index, item in enumerate(
        _required_list(contract.get("comparisons"), "visual_contract.comparisons", 1, 2)
    )]
    transmission = _required_text(contract.get("transmission"), "visual_contract.transmission")
    primary_note = _required_text(primary.get("note"), "visual_contract.primary.note")
    lanes = "\n".join(
        """        <div class="qb-pulse-lane {klass}">
          <div><span>{label}</span><b data-qb-value data-output="{output}" data-format="{format}">待更新</b></div>
          <i><em data-qb-bar data-output="{output}"></em></i>
        </div>""".format(
            klass="is-alpha" if index == 0 else "is-market", label=_e(item["label"]),
            output=_e(item["output"]), format=_e(item["format"]),
        ) for index, item in enumerate(comparisons)
    )
    core = """    <div class="qb-event-pulse" data-qb-card-visual>
      <div class="qb-event-pulse__hero">
        <span>{primary_label}</span>
        <b data-qb-value data-output="{primary_output}" data-format="{primary_format}">待更新</b>
        <small>{primary_note}</small>
      </div>
      <div class="qb-event-pulse__lanes">
{lanes}
        <small class="qb-pulse-note">{transmission}</small>
      </div>
    </div>""".format(
        primary_label=_e(primary["label"]), primary_output=_e(primary["output"]),
        primary_format=_e(primary["format"]), primary_note=_e(primary_note), lanes=lanes,
        transmission=_e(transmission),
    )
    return _unique_outputs([primary["output"]] + [item["output"] for item in comparisons]), _card(page_id, contract, core, "event-pulse")


def _render_rotation_wheel(page_id, contract):
    nodes = [_metric(item, "visual_contract.nodes[%d]" % index) for index, item in enumerate(
        _required_list(contract.get("nodes"), "visual_contract.nodes", 2, 4)
    )]
    for index, node in enumerate(nodes):
        node["note"] = _required_text(node.get("note"), "visual_contract.nodes[%d].note" % index)
    caption = _required_text(contract.get("caption"), "visual_contract.caption")
    track = "".join("<i></i>" for _ in nodes)
    node_html = "\n".join(
        """      <div class="qb-cycle-node qb-cycle-node--{position}">
        <span>{label}</span>
        <b data-qb-value data-output="{output}" data-format="{format}">待更新</b>
        <small>{note}</small>
      </div>""".format(
            position="node-%d" % (index + 1), label=_e(node["label"]),
            output=_e(node["output"]), format=_e(node["format"]), note=_e(node["note"]),
        ) for index, node in enumerate(nodes)
    )
    core = """    <div class="qb-cycle-map" data-qb-card-visual data-qb-node-count="{count}">
      <div class="qb-cycle-track" aria-hidden="true">{track}</div>
{nodes}
      <div class="qb-cycle-caption">{caption}</div>
    </div>""".format(count=len(nodes), track=track, nodes=node_html, caption=_e(caption))
    return _unique_outputs(item["output"] for item in nodes), _card(page_id, contract, core, "rotation-wheel")


def _render_value_quality_map(page_id, contract):
    steps_raw = _required_list(contract.get("steps"), "visual_contract.steps", 2, 4)
    steps = []
    for index, step in enumerate(steps_raw):
        step = _required_dict(step, "visual_contract.steps[%d]" % index)
        steps.append({
            "label": _required_text(step.get("label"), "visual_contract.steps[%d].label" % index),
            "detail": _required_text(step.get("detail"), "visual_contract.steps[%d].detail" % index),
        })
    rankings_raw = _required_list(contract.get("rankings"), "visual_contract.rankings", 2, 2)
    rankings = []
    for index, ranking in enumerate(rankings_raw):
        ranking = _required_dict(ranking, "visual_contract.rankings[%d]" % index)
        rankings.append({
            "label": _required_text(ranking.get("label"), "visual_contract.rankings[%d].label" % index),
            "badge": _required_text(ranking.get("badge"), "visual_contract.rankings[%d].badge" % index),
            "output": _required_text(ranking.get("output"), "visual_contract.rankings[%d].output" % index),
            "format": _required_text(ranking.get("format") or "number1", "visual_contract.rankings[%d].format" % index),
            "limit": _bounded_int(ranking.get("limit"), "visual_contract.rankings[%d].limit" % index, 1, 4),
            "loading": _required_text(ranking.get("loading"), "visual_contract.rankings[%d].loading" % index),
        })
    evidence = _required_dict(contract.get("evidence"), "visual_contract.evidence")
    evidence_metric = _metric(evidence, "visual_contract.evidence")
    evidence_limit = _bounded_int(evidence.get("limit"), "visual_contract.evidence.limit", 1, 2)
    evidence_badge = _required_text(evidence.get("badge"), "visual_contract.evidence.badge")
    evidence_note = _required_text(evidence.get("note"), "visual_contract.evidence.note")
    evidence_loading = _required_text(evidence.get("loading"), "visual_contract.evidence.loading")
    aria_label = _required_text(contract.get("aria_label"), "visual_contract.aria_label")
    footnote = _required_text(contract.get("footnote"), "visual_contract.footnote")
    step_html = []
    for index, step in enumerate(steps):
        if index:
            step_html.append('        <i aria-hidden="true">→</i>')
        step_html.append(
            "        <div class=\"qb-value-quality-step is-step-{index}\"><b>{number:02d}</b><strong>{label}</strong><span>{detail}</span></div>".format(
                index=index + 1, number=index + 1, label=_e(step["label"]), detail=_e(step["detail"])
            )
        )
    ranking_html = "\n".join(
        """        <section class="qb-value-quality-lane {klass}" data-qb-top-list data-output="{output}" data-format="{format}" data-limit="{limit}">
          <header><span>{label}</span><b>{badge}</b></header>
          <div class="qb-top-list-body"><div><span>{loading}</span><b>—</b></div></div>
        </section>""".format(
            klass="is-core" if index == 0 else "is-extended", output=_e(item["output"]),
            format=_e(item["format"]), limit=item["limit"], label=_e(item["label"]),
            badge=_e(item["badge"]), loading=_e(item["loading"]),
        ) for index, item in enumerate(rankings)
    )
    core = """    <div class="qb-value-quality-map" data-qb-card-visual>
      <div class="qb-value-quality-steps" data-qb-step-count="{step_count}" aria-label="{aria_label}">
{steps}
      </div>
      <div class="qb-value-quality-grid">
{rankings}
        <section class="qb-value-quality-check" data-qb-top-list data-output="{evidence_output}" data-format="{evidence_format}" data-limit="{evidence_limit}">
          <header><span>{evidence_label}</span><b>{evidence_badge}</b></header>
          <div class="qb-top-list-body"><div><span>{evidence_loading}</span><b>—</b></div></div>
          <small>{evidence_note}</small>
        </section>
      </div>
      <div class="qb-value-quality-foot"><span>{footnote}</span><time data-qb-bind="date">待更新</time></div>
    </div>""".format(
        step_count=len(steps), aria_label=_e(aria_label), steps="\n".join(step_html), rankings=ranking_html,
        evidence_output=_e(evidence_metric["output"]), evidence_format=_e(evidence_metric["format"]),
        evidence_limit=evidence_limit, evidence_label=_e(evidence_metric["label"]), evidence_badge=_e(evidence_badge),
        evidence_loading=_e(evidence_loading), evidence_note=_e(evidence_note), footnote=_e(footnote),
    )
    outputs = [item["output"] for item in rankings] + [evidence_metric["output"]]
    return _unique_outputs(outputs), _card(page_id, contract, core, "value-quality-map")


def _render_recovery_evidence(page_id, contract):
    stages_raw = _required_list(contract.get("stages"), "visual_contract.stages", 2, 4)
    stages = []
    for index, stage in enumerate(stages_raw):
        stage = _required_dict(stage, "visual_contract.stages[%d]" % index)
        stages.append({
            "label": _required_text(stage.get("label"), "visual_contract.stages[%d].label" % index),
            "detail": _required_text(stage.get("detail"), "visual_contract.stages[%d].detail" % index),
        })
    guard = _required_dict(contract.get("guard"), "visual_contract.guard")
    guard_eyebrow = _required_text(guard.get("eyebrow"), "visual_contract.guard.eyebrow")
    guard_badge = _required_text(guard.get("badge"), "visual_contract.guard.badge")
    guard_title = _required_text(guard.get("title"), "visual_contract.guard.title")
    guard_description = _required_text(guard.get("description"), "visual_contract.guard.description")
    tags = [_required_text(item, "visual_contract.guard.tags[%d]" % index) for index, item in enumerate(
        _required_list(guard.get("tags"), "visual_contract.guard.tags", 1, 4)
    )]
    checks_raw = _required_list(guard.get("checks"), "visual_contract.guard.checks", 1, 4)
    checks = []
    for index, check in enumerate(checks_raw):
        check = _required_dict(check, "visual_contract.guard.checks[%d]" % index)
        checks.append({
            "label": _required_text(check.get("label"), "visual_contract.guard.checks[%d].label" % index),
            "detail": _required_text(check.get("detail"), "visual_contract.guard.checks[%d].detail" % index),
        })
    panel = _required_dict(contract.get("metrics_panel"), "visual_contract.metrics_panel")
    panel_eyebrow = _required_text(panel.get("eyebrow"), "visual_contract.metrics_panel.eyebrow")
    panel_badge = _required_text(panel.get("badge"), "visual_contract.metrics_panel.badge")
    panel_note = _required_text(panel.get("note"), "visual_contract.metrics_panel.note")
    metrics = [_metric(item, "visual_contract.metrics_panel.metrics[%d]" % index) for index, item in enumerate(
        _required_list(panel.get("metrics"), "visual_contract.metrics_panel.metrics", 1, 3)
    )]
    aria_label = _required_text(contract.get("aria_label"), "visual_contract.aria_label")
    footnote = _required_text(contract.get("footnote"), "visual_contract.footnote")
    stage_html = []
    for index, stage in enumerate(stages):
        if index:
            stage_html.append('        <i aria-hidden="true">→</i>')
        stage_html.append(
            "        <div class=\"qb-recovery-node is-stage-{index}\"><b>{number:02d}</b><strong>{label}</strong><span>{detail}</span></div>".format(
                index=index + 1, number=index + 1, label=_e(stage["label"]), detail=_e(stage["detail"])
            )
        )
    tag_html = "".join("<em>%s</em>" % _e(tag) for tag in tags)
    check_html = "\n".join(
        "            <div><span>{label}</span><b>{detail}</b></div>".format(label=_e(item["label"]), detail=_e(item["detail"]))
        for item in checks
    )
    metric_html = "\n".join(
        "            <div><small>{label}</small><strong data-qb-value data-output=\"{output}\" data-format=\"{format}\">待更新</strong></div>".format(
            label=_e(item["label"]), output=_e(item["output"]), format=_e(item["format"])
        ) for item in metrics
    )
    core = """    <div class="qb-recovery-evidence" data-qb-card-visual>
      <div class="qb-recovery-rail" data-qb-step-count="{step_count}" aria-label="{aria_label}">
{stages}
      </div>
      <div class="qb-recovery-body">
        <section class="qb-recovery-guard">
          <header><span>{guard_eyebrow}</span><b>{guard_badge}</b></header>
          <strong>{guard_title}</strong>
          <p>{guard_description}</p>
          <div class="qb-recovery-tags">{tags}</div>
          <div class="qb-recovery-checklist">
{checks}
          </div>
        </section>
        <section class="qb-recovery-valuation">
          <header><span>{panel_eyebrow}</span><b>{panel_badge}</b></header>
          <div class="qb-recovery-valuation-grid">
{metrics}
          </div>
          <small class="qb-recovery-valuation-note">{panel_note}</small>
        </section>
      </div>
      <div class="qb-recovery-foot"><span>{footnote}</span><time data-qb-bind="date">待更新</time></div>
    </div>""".format(
        step_count=len(stages), aria_label=_e(aria_label), stages="\n".join(stage_html), guard_eyebrow=_e(guard_eyebrow),
        guard_badge=_e(guard_badge), guard_title=_e(guard_title), guard_description=_e(guard_description),
        tags=tag_html, checks=check_html, panel_eyebrow=_e(panel_eyebrow), panel_badge=_e(panel_badge),
        metrics=metric_html, panel_note=_e(panel_note), footnote=_e(footnote),
    )
    return _unique_outputs(item["output"] for item in metrics), _card(page_id, contract, core, "recovery-evidence")


_RENDERERS = {
    "numeric-focus": _render_numeric_focus,
    "industry-ranking": _render_industry_ranking,
    "event-flow": _render_event_flow,
    "basis-structure": _render_basis_structure,
    "event-pulse": _render_event_pulse,
    "rotation-wheel": _render_rotation_wheel,
    "value-quality-map": _render_value_quality_map,
    "recovery-evidence": _render_recovery_evidence,
}


def render_visual(page_id, visual_contract, available_outputs):
    if not isinstance(visual_contract, dict) or not str(visual_contract.get("kind") or "").strip():
        raise ValueError(
            "CARD_VISUAL_REQUIRED: 页面 %s 没有显式视觉合同；完整重建禁止按 page_id 或前三个 outputs 自动选择视觉"
            % (page_id or "<unknown>")
        )
    visual_kind = str(visual_contract.get("kind") or "").strip()
    renderer = _RENDERERS.get(visual_kind)
    if renderer is None:
        raise ValueError(
            "CARD_VISUAL_UNSUPPORTED: 页面 %s 不支持 visual_contract.kind=%s"
            % (page_id or "<unknown>", visual_kind)
        )
    required, card = renderer(page_id, visual_contract)
    available = set(str(item) for item in (available_outputs or []))
    missing = [output for output in required if output not in available]
    if missing:
        _invalid("visual_contract 引用了公式包不存在的 output: %s" % ", ".join(missing))
    return required, card, visual_kind
