// Read-only, advisory checks. This module must never decide publication success.
export function dataLabelMetrics() {
  try {
    const visible = node => {
      const r = node.getBoundingClientRect(), s = getComputedStyle(node);
      return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
    };
    const selector = '[data-qb-label-module], .card > .body, .qb-embedded-body, [data-qb-live-mode="live"], figure:has([data-qb-data-label])';
    const nodes = [...new Set(document.querySelectorAll(selector))];
    const modules = nodes.map((node, index) => {
      const expected = node.getAttribute('data-qb-label-module') || 'unknown';
      const card = node.closest('section.card, article.card');
      const scope = card || node;
      let heading = card?.querySelector(':scope > .card-head > h2, :scope > .card-head > h3');
      if (!heading && card?.classList.contains('card-unheaded')) heading = card.closest('.qb-compose-module')?.querySelector(':scope > h2');
      const labelRoot = heading || scope;
      const badges = [...labelRoot.querySelectorAll('[data-qb-data-label]')];
      const shown = badges.filter(visible);
      const originalHeading = heading?.cloneNode(true);
      originalHeading?.querySelectorAll('[data-qb-data-label]').forEach(b => b.remove());
      const title = originalHeading?.textContent || '';
      const semanticLive = /\bLIVE\b|实时(?:数据|取数|更新)/i.test(title);
      const semanticSnapshot = /\bSNAPSHOT\b|研究快照|数据快照|静态(?:数据|快照|内容)/i.test(title);
      const legacy = node.getAttribute('data-qb-live-mode') === 'live' &&
        /LIVE/.test(getComputedStyle(node, '::after').content || '') && visible(node);
      const labels = [...new Set(shown.map(b => b.getAttribute('data-qb-data-label'))
        .concat(legacy || (heading && visible(heading) && semanticLive) ? ['live'] : [])
        .concat(heading && visible(heading) && semanticSnapshot ? ['snapshot'] : []))];
      const warnings = [];
      if (visible(node) && !labels.length) warnings.push('LABEL_MISSING');
      if (badges.length && shown.length !== badges.length) warnings.push('LABEL_NOT_VISIBLE');
      if (shown.some((b, i) => shown.slice(i + 1).some(other =>
        other.getAttribute('data-qb-data-label') === b.getAttribute('data-qb-data-label')))) warnings.push('LABEL_DUPLICATE');
      if (expected !== 'unknown' && labels.some(mode => mode !== expected)) warnings.push('LABEL_CONFLICT');
      if (node.getAttribute('data-qb-label-placement') === 'label_error') warnings.push('LABEL_RENDER_UNAVAILABLE');
      for (const badge of shown) {
        const r = badge.getBoundingClientRect();
        if (r.left < -1 || r.right > innerWidth + 1) warnings.push('LABEL_OVERFLOW');
      }
      return {index, expected, visible: visible(node), labels, warnings: [...new Set(warnings)],
        dates: shown.filter(b => b.hasAttribute('data-qb-label-date')).map(b => ({
          date:b.getAttribute('data-qb-label-date'), kind:b.getAttribute('data-qb-label-date-kind'),
          display:b.getAttribute('data-qb-label-date-display')})),
        reason: node.getAttribute('data-qb-label-placement') || node.getAttribute('data-qb-label-reason') || 'legacy_unclassified'};
    });
    return {checked: true, advisory: true, coverage: modules.length ? 'recognized_modules_only' : 'unrecognized', modules, total: modules.length,
      labeled: modules.filter(m => m.labels.length).length,
      unknown: modules.filter(m => m.expected === 'unknown').length,
      warnings: modules.length ? [...new Set(modules.flatMap(m => m.warnings))] : ['LABEL_MODULES_UNRECOGNIZED']};
  } catch (_) {
    return {checked: false, advisory: true, modules: [], warnings: ['LABEL_CHECK_UNAVAILABLE']};
  }
}

export async function readDataLabels(evaluate) {
  try { return await evaluate(dataLabelMetrics); }
  catch (_) { return {checked: false, advisory: true, modules: [], warnings: ['LABEL_CHECK_UNAVAILABLE']}; }
}

export function summarizeDataLabels(browser) {
  try {
    const viewports = (browser?.viewports || []).map(v => ({viewport: v.viewport || v.width,
      ...(v.data_labels || {checked: false, warnings: ['LABEL_CHECK_NOT_RUN']})}));
    return {advisory: true, checked: viewports.some(v => v.checked), viewports,
      warnings: [...new Set(viewports.flatMap(v => v.warnings || []))]};
  } catch (_) { return {advisory: true, checked: false, warnings: ['LABEL_CHECK_UNAVAILABLE']}; }
}
