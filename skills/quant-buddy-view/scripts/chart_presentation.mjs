/** Executed in the inspected browser; keep this function self-contained. */
export async function inspectChartPresentation() {
  const deadline=Date.now()+10000;
  while(document.querySelector('[data-qb-presentation="pending"]') && Date.now()<deadline)
    await new Promise(resolve=>setTimeout(resolve,50));
  const panels=[];
  const visible=el=>!!el && !!(el.getClientRects().length) && getComputedStyle(el).visibility!=='hidden';
  for(const el of document.querySelectorAll('[data-qb-presentation], [data-qb-render-error]')) {
    const state=el.dataset.qbPresentation || 'failed';
    const item={title:el.dataset.qbPanelTitle || el.id || '面板',type:el.dataset.qbChartType || null,state,reason:el.dataset.qbFallbackReason || null,problems:[]};
    const evidence=el.__qbPresentationEvidence;
    if(el.dataset.qbRenderError)item.problems.push('PANEL_RENDER_ERROR: '+el.dataset.qbRenderError);
    if(state==='pending')item.problems.push('CHART_PRESENTATION_PENDING');
    else if(state==='failed')item.problems.push('CHART_PRESENTATION_FAILED');
    else if(state==='chart_ready') {
      const lib=window.__QB_ECHARTS_LOADER__?.library || window.echarts;
      const chart=lib?.getInstanceByDom?.(el);
      const option=chart?.getOption?.();
      const numeric=v=>typeof v==='number' && Number.isFinite(v) || Array.isArray(v)&&v.some(numeric) || v&&typeof v==='object'&&numeric(v.value);
      if(!chart || chart!==evidence?.chart || !option?.series?.some(s=>s.data?.some(numeric)))item.problems.push('CHART_INSTANCE_OR_SERIES_MISSING');
      if(![...el.querySelectorAll('canvas,svg')].some(node=>visible(node)&&node.getBoundingClientRect().width>0&&node.getBoundingClientRect().height>0))item.problems.push('CHART_DRAWING_MISSING');
    } else if(state==='table_fallback') {
      const headers=[...el.querySelectorAll('thead th')].map(c=>c.textContent);
      const rows=[...el.querySelectorAll('tbody tr')].map(r=>[...r.cells].map(c=>c.textContent));
      const notice=el.querySelector('[data-qb-chart-fallback-notice]');
      if(!visible(notice) || !notice.textContent.includes('已改为数据表展示'))item.problems.push('FALLBACK_NOTICE_MISSING');
      if(!evidence?.rows?.length || JSON.stringify(headers)!==JSON.stringify(evidence.headers) || JSON.stringify(rows)!==JSON.stringify(evidence.rows))item.problems.push('FALLBACK_DATA_MISMATCH');
      if(!visible(el.querySelector('table')))item.problems.push('FALLBACK_TABLE_HIDDEN');
      if(evidence?.dataLabel != null && el.getAttribute('data-qb-label-module')!==evidence.dataLabel)item.problems.push('FALLBACK_DATA_LABEL_CHANGED');
    }
    panels.push(item);
  }
  const attempts=window.__QB_ECHARTS_LOADER__?.attempts || [];
  return {status:panels.some(p=>p.problems.length)?'failed':panels.some(p=>p.state==='table_fallback')?'degraded':'normal',panels,source:window.__QB_ECHARTS_LOADER__?.source || null,dependencyAttempts:attempts};
}

export function chartPresentationProblems(presentation) {
  return (presentation?.panels || []).flatMap(p=>p.problems.map(problem=>`${p.title}: ${problem}`));
}
