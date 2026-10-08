// Self-contained so both Playwright and raw CDP run exactly this function.
export function pageTitleMetrics() {
  const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
  const visible = el => {
    if (el.closest('template,script,style,noscript,[hidden],[inert],[aria-hidden="true"],[data-qb-live-card-title]')) return false;
    for (let node = el; node; node = node.parentElement) {
      if (Array.from(node.attributes).some(a => a.name.startsWith('data-qb-card-'))) return false;
      const style = getComputedStyle(node);
      if (style.display === 'none' || style.visibility === 'hidden' || style.visibility === 'collapse') return false;
    }
    return el.getClientRects().length > 0;
  };
  const marked = Array.from(document.body?.querySelectorAll('[data-qb-page-title]') || []).filter(visible);
  const nodes = marked.length ? marked : Array.from(document.body?.querySelectorAll('h1') || []).filter(visible);
  return { headingCount: nodes.length,
    heading: nodes.length === 1 ? normalize(nodes[0].innerText) : null,
    documentTitle: normalize(document.title),
    locator: marked.length ? '[data-qb-page-title]' : 'h1' };
}

export function pageTitleProblems(metrics, expected) {
  if (expected == null) return [];
  const problems = [];
  if (!metrics || metrics.headingCount !== 1) problems.push('PAGE_TITLE_AMBIGUOUS: 无法唯一定位可见页面主标题');
  else if (metrics.heading !== expected) problems.push(`PAGE_TITLE_MISMATCH: 页面主标题 ${JSON.stringify(metrics.heading)} != ${JSON.stringify(expected)}`);
  if (metrics?.documentTitle !== expected) problems.push(`PAGE_TITLE_MISMATCH: document.title ${JSON.stringify(metrics?.documentTitle)} != ${JSON.stringify(expected)}`);
  return problems;
}
