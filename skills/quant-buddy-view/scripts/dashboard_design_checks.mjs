// Serialized into the browser by both verification engines; keep self-contained.
export function dashboardDesignMetrics(required = false) {
  const problems = [];
  const metadataKeys = new Set(['total_assets', 'valid_assets', 'returned_assets', 'is_truncated', 'warning']);
  for (const table of document.querySelectorAll('table')) {
    if (!/股票|证券|代码|资产|行业/.test(table.querySelector('tr')?.textContent || '')) continue;
    for (const row of table.querySelectorAll('tbody tr')) {
      const identity = [...row.querySelectorAll('td')].slice(0, 3).map(cell => cell.textContent.trim());
      if (identity.some(value => metadataKeys.has(value))) {
        problems.push('数据解析错误：统计元数据被渲染为资产行；按实际 read_mode 读取 last_column_full.values 或 last_day_stats.top_values，禁止遍历统计对象生成榜单');
        break;
      }
    }
  }
  const root = document.querySelector('[data-qb-page-design]');
  if (!root) return { required, problems: [...problems, ...(required ? ['缺少自建页设计根节点，不能跳过设计验收'] : [])] };
  if (/排名|强弱|榜单/.test(root.querySelector('h1')?.textContent || '')) {
    const primaryTables = [...root.querySelectorAll('table')].filter(t=>!t.closest('details,.text-panel'));
    if (primaryTables.length > 1 && !root.querySelector('.body.bar')) problems.push('排名页不能堆叠多张全量表；先呈现强弱柱图，再保留一张可展开的完整对照表');
    if (primaryTables.length && !root.querySelector('table[data-qb-rank-order],.body.bar')) problems.push('排名页缺少明确排序的主榜单，不能按代码原序交付');
  }
  for (const el of root.querySelectorAll('[data-qb-rank-error]')) {
    if (el.dataset.qbRankError) problems.push('排名表排序字段不存在；请按实际列名或output_labels映射修正rank_by');
  }
  for (const table of root.querySelectorAll('table[data-qb-rank-order]')) {
    const values = [...table.querySelectorAll('tbody tr[data-qb-rank-value]')].map(row=>Number(row.dataset.qbRankValue));
    const direction = table.dataset.qbRankOrder === 'asc' ? 1 : -1;
    if (values.some((v,i)=>i && direction*(v-values[i-1]) < 0)) problems.push('排名表未按声明的强弱方向排序');
  }
  for (const cell of root.querySelectorAll('table th')) {
    if (/^(asset|value|name|date|close|pct_chg|pe_ttm)$/.test(cell.textContent.trim()))
      problems.push('表头暴露内部字段名；请使用业务列名（名称、代码、观察日、数值等）或output_labels');
  }
  if (root.querySelector('[data-qb-binding-error]')) problems.push('动态正文绑定失败');
  // Market opening hours alone do not establish an upstream field's freshness.
  // Describe the verified provider/field cadence instead of this blanket claim.
  for (const sentence of root.textContent.split(/[。；;\n]/)) {
    if (/交易(?:时段|时间)内[^。；;\n]{0,30}(?:为|是|代表)[^。；;\n]{0,12}盘中(?:最新值|截面|数据)/.test(sentence) && !/不代表|不能|未确认|未核实|未必|不一定/.test(sentence))
      problems.push("不能仅凭交易时段断言数据是盘中截面；默认写明数据日期按来源返回，未确认本字段的盘中/收盘状态，除非有具体字段更新频率与观测时点证据");
    if (/收盘后[^。；;\n]{0,20}(?:即|就|必然|保证)[^。；;\n]{0,20}(?:收盘|最新|当日)/.test(sentence) && !/不能|不保证|无法保证|未必|不一定/.test(sentence))
      problems.push('不能承诺收盘后刷新即得到当日收盘数据；刷新只保证重新请求，上游更新时间须按字段核验');
  }
  let observationDates = [];
  try { observationDates = JSON.parse(root.dataset.qbObservationDates || '[]'); } catch {}
  if (Array.isArray(observationDates) && observationDates.length) {
    for (const prose of root.querySelectorAll('.text-panel, [data-qb-prose]')) {
      const text = prose.textContent || '';
      for (const claim of text.matchAll(/(?:截至|对应|观察日(?:为)?|完整交易日)[^。；\n]{0,32}?(20\d{2}[-/]\d{2}[-/]\d{2})/g)) {
        const date = claim[1].replaceAll('/', '-');
        if (!observationDates.includes(date)) problems.push(`观察日声明 ${date} 与数据源返回日期不一致；按字段返回日期展示，不从系统时间反推上一交易日或收盘状态`);
      }
    }
  }
  const rankingGroups = [];
  for (const el of root.querySelectorAll('.body.bar')) {
    const chart = window.echarts?.getInstanceByDom(el);
    if (!chart) continue;
    const option = chart.getOption();
    for (const series of option.series || []) {
      if (series.type !== 'bar' || !series.data?.length) continue;
      const valueAxis = option.xAxis?.[series.xAxisIndex || 0]?.type === 'value' ? 'xAxis' : 'yAxis';
      const extent = chart.getModel().getComponent(valueAxis, series[valueAxis === 'xAxis' ? 'xAxisIndex' : 'yAxisIndex'] || 0)?.axis?.scale?.getExtent();
      if (extent && (extent[0] > 0 || extent[1] < 0)) problems.push('柱图缺少零基线，柱长会误导数值比较');
    }
    const card = el.closest('.card, .qb-compose-panel');
    const copy = card?.textContent || '';
    const title = card?.querySelector('h2,h3')?.textContent?.trim() || '';
    const kind = /最弱/.test(title) ? 'bottom' : /最强/.test(title) ? 'top' : null;
    const axis = option.yAxis?.[0]?.type === 'category' ? option.yAxis[0] : option.xAxis?.[0];
    if (kind && axis?.type === 'category' && Array.isArray(axis.data) && axis.data.length) {
      rankingGroups.push({title, kind, limit:axis.data.length, members:axis.data.map(v=>String(typeof v==='object'?v.value:v))});
    }

    if (/最弱|弱势|落后|后\s*10/.test(copy) && /跌幅大小|越长.{0,8}越弱/.test(root.textContent))
      problems.push('弱势排名必须保留原始涨跌幅及正负号，禁止取反后用柱长解释强弱');
    if (/最弱|弱势|落后/.test(copy) && /升序.{0,8}(?:后|末|最后)\s*10/.test(copy))
      problems.push('最弱榜应为原始数值升序取前10；升序取末10与最弱的定义矛盾');
  }
  const visible = el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';
  // Measure document positions, not the current scroll position: opening a details
  // table during acceptance must not change what was visible on initial load.
  const evidence = [...root.querySelectorAll('.body.bar, .body.line, .body.radar, .body.table tbody tr, .card-number .big, [data-qb-metric]')];
  const firstScreenEvidence = evidence.some(el => {
    if (!visible(el) || el.closest('details:not([open])')) return false;
    const rect = el.getBoundingClientRect();
    const top = rect.top + window.scrollY;
    const chart = el.matches('.body.bar, .body.line, .body.radar');
    if (chart && !window.echarts?.getInstanceByDom(el)?.getOption()?.series?.some(s=>s.data?.length)) return false;
    if (!chart && !/\d/.test(el.textContent || '')) return false;
    const minimum = chart ? 120 : Math.min(rect.height, 32);
    return rect.width > 0 && rect.height >= minimum && minimum > 0 && top >= 0 && top + minimum <= window.innerHeight;
  });
  if (evidence.length && !firstScreenEvidence)
    problems.push('首屏缺少可读的核心数据证据：将真实关键值、主图或榜单前移，压缩导语并把详细口径后置；Compose 保留借鉴外壳，调整内部面板顺序，不能缩小正文或放置假指标绕过');
  const label = el => (el.textContent || '').trim().slice(0, 36);
  if (![...root.querySelectorAll('h1')].some(visible)) problems.push('缺少可见主标题');
  if (!root.querySelector('.card, [data-qb-prose], [data-qb-metric], table, canvas, svg')) problems.push('缺少正文或核心证据');
  const checkSize = (selector, min, name) => {
    for (const el of root.querySelectorAll(selector)) {
      if (visible(el) && parseFloat(getComputedStyle(el).fontSize) < min - 0.1) problems.push(`${name}小于 ${min}px：${label(el)}`);
    }
  };
  checkSize('h1', window.innerWidth <= 680 ? 28 : 36, '主标题');
  checkSize('.card:not(.card-number) .card-head :is(h2,h3), [data-qb-module-title]', 18, '模块标题');
  checkSize('.text-panel, [data-qb-prose]', 18, '正文');
  checkSize('th, td', 14, '表格文字');
  for (const el of root.querySelectorAll('.text-panel, [data-qb-prose]')) {
    if (!visible(el)) continue;
    const style = getComputedStyle(el);
    if (el.scrollHeight > el.clientHeight + 3 && /(auto|scroll|hidden|clip)/.test(style.overflowY)) problems.push(`正文被裁切或嵌套滚动：${label(el)}`);
    if (el.dataset.qbTextFormat !== 'plain' && /\*\*[^*\n]+\*\*|\|\s*:?-{3,}/.test(el.textContent)) problems.push(`正文残留 Markdown 格式符：${label(el)}`);
  }
  for (const el of root.querySelectorAll('.card-head, .big, h1, [data-qb-module-title], [data-qb-metric]')) {
    if (visible(el) && el.scrollWidth > el.clientWidth + 3) problems.push(`标题或指标横向溢出：${label(el)}`);
  }
  if (root.scrollWidth > root.clientWidth + 3) problems.push('正文区域横向溢出');
  const assets = new Set(rankingGroups.flatMap(g=>g.members));
  for (const table of root.querySelectorAll('table')) {
    const headers = [...table.querySelectorAll('thead th')].map(c=>c.textContent.trim());
    const nameIndex = headers.findIndex(h=>/^(名称|行业|行业名称|资产名称)$/.test(h));
    if (nameIndex < 0) continue;
    for (const row of table.querySelectorAll('tbody tr')) {
      const name = row.querySelectorAll('td')[nameIndex]?.textContent.trim();
      if (name) assets.add(name);
    }
  }
  return { required: true, version: root.dataset.qbPageDesign, firstScreenEvidence, problems: [...new Set(problems)],
    rankingEvidence: {version:1, groups:rankingGroups, assets:[...assets], observationDates} };

}
