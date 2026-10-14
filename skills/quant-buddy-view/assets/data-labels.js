// Presentation only: no requests, timers, refresh listeners or data mutation.
function qbApplyDataLabel(panel, body) {
  let badge = null;
  try {
    const proof = panel._qb_data_label;
    if (!proof || !body) return;
    const names = panelOutputNames(panel);
    const current = proof.kind === (panel.type || 'table') &&
      JSON.stringify(proof.outputs) === JSON.stringify(names);
    const mode = current ? proof.mode : 'unknown';
    body.setAttribute('data-qb-label-module', mode);
    body.setAttribute('data-qb-label-reason', current ? proof.reason : 'binding_changed');
    if (!['live', 'snapshot'].includes(mode)) return;
    // Known generated shells only. Never guess where a bespoke chart's title lives.
    const card = body.closest('section.card, article.card');
    let heading = card && card.querySelector(':scope > .card-head > h2, :scope > .card-head > h3');
    if (!heading && card && card.classList.contains('card-unheaded')) {
      heading = card.closest('.qb-compose-module')?.querySelector(':scope > h2');
    }
    if (!heading) {
      body.setAttribute('data-qb-label-reason', 'no_safe_heading');
      return;
    }
    const old = heading.querySelector('[data-qb-data-label]');
    if (old) {
      if (old.hasAttribute('data-qb-label-generated')) old.remove();
      else { body.setAttribute('data-qb-label-placement', 'existing'); return; }
    }
    const title = heading.textContent || '';
    const existingLive = /\bLIVE\b|实时(?:数据|取数|更新)/i.test(title);
    const existingSnapshot = /\bSNAPSHOT\b|研究快照|数据快照|静态(?:数据|快照|内容)/i.test(title);
    if (existingLive || existingSnapshot) {
      const correct = mode === 'live' ? existingLive && !existingSnapshot : existingSnapshot && !existingLive;
      body.setAttribute('data-qb-label-placement', correct ? 'existing' : 'conflicting_existing');
      return;
    }
    const before = heading.getBoundingClientRect();
    const beforeWidth = heading.scrollWidth;
    badge = document.createElement('span');
    badge.setAttribute('data-qb-data-label', mode);
    badge.setAttribute('data-qb-label-generated', 'v2');
    const dated = mode === 'snapshot' && /^\d{4}-\d{2}-\d{2}$/.test(proof.date || '');
    const dateCaption = dated ? (proof.date_kind === 'analysis' ? '分析日 ' : '截至 ') + proof.date : '';
    const shortName = mode === 'live' ? 'Live' : 'Snapshot';
    const fullText = shortName + (dated ? ' · ' + dateCaption : '');
    badge.textContent = fullText;
    badge.title = mode === 'live' ? '已接入刷新；数据日期以来源为准'
      : (dated ? dateCaption + '；固定内容不会自动更新，各字段日期以正文为准' : '固定内容快照；数据日期或分析日以正文为准');
    if (dated) {
      badge.setAttribute('data-qb-label-date', proof.date);
      badge.setAttribute('data-qb-label-date-kind', proof.date_kind);
    }
    badge.tabIndex = 0;
    badge.setAttribute('aria-label', fullText + '：' + badge.title);
    const color = mode === 'live' ? '#426252' : '#77596d';
    const background = mode === 'live' ? '#e6eee4' : '#ece3e9';
    badge.style.cssText = 'display:inline-block;font:500 12px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;vertical-align:baseline;margin-inline-start:8px;padding:1px 6px;border:0;border-radius:3px;white-space:nowrap;max-width:100%;color:' + color + ';background:' + background + ';';
    heading.appendChild(badge);
    const fits = () => {
      const after = heading.getBoundingClientRect();
      return before.width > 0 && after.height <= before.height + 1 &&
        heading.scrollWidth <= Math.max(beforeWidth, heading.clientWidth) + 1;
    };
    let dateDisplay = dated ? 'full' : 'none';
    if (!fits() && dated) {
      badge.textContent = shortName + ' · ' + proof.date;
      dateDisplay = 'date';
    }
    if (!fits() && dated) {
      badge.textContent = shortName;
      dateDisplay = 'tooltip';
    }
    badge.setAttribute('data-qb-label-date-display', dateDisplay);
    // A label must not wrap the title, enlarge the card or cause overflow.
    if (!fits()) {
      badge.remove();
      body.setAttribute('data-qb-label-placement', 'insufficient_space');
    } else body.setAttribute('data-qb-label-placement', 'added');
  } catch (_) {
    try {
      if (badge) badge.remove();
      if (body) body.setAttribute('data-qb-label-placement', 'label_error');
    } catch (_) { /* The original renderer always continues. */ }
  }
}
