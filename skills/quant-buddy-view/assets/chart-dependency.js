/* Shared by full pages, embeds and chart_edit. No network work until a chart needs it. */
function chartLibrary() {
  return window.__QB_ECHARTS_LOADER__?.library || window.echarts || globalThis.echarts;
}
function ensureChartLibrary() {
  const usable = lib => !!lib && typeof lib.init === 'function' && typeof lib.getInstanceByDom === 'function';
  const shared = window.__QB_ECHARTS_LOADER__ ||= {library:null, promise:null, attempts:[], source:null};
  if (usable(shared.library)) return Promise.resolve(shared.library);
  if (shared.promise) return shared.promise;
  if (usable(window.echarts)) {
    shared.library=window.echarts; shared.source='host';
    return shared.promise=Promise.resolve(shared.library);
  }
  const sources = __CHART_SOURCES__;
  const load = (url, timeout) => new Promise(resolve => {
    const script=document.createElement('script');
    const attempt={url, status:'pending'}; shared.attempts.push(attempt);
    let finished=false;
    const finish=(lib,status)=>{
      if(finished)return; finished=true; clearTimeout(timer);
      script.onload=null; script.onerror=null; attempt.status=status; resolve(lib);
    };
    const timer=setTimeout(()=>finish(null,'timeout'),timeout);
    script.onload=()=>finish(usable(window.echarts)?window.echarts:null,usable(window.echarts)?'ready':'invalid_api');
    script.onerror=()=>finish(null,'error');
    script.src=url; script.async=true; script.dataset.qbChartDependency='true';
    document.head.appendChild(script);
  });
  const hostWait = () => new Promise(resolve=>{
    const started=Date.now();
    const scripts=[...document.scripts];
    const finish=lib=>{clearInterval(poll);scripts.forEach(s=>s.removeEventListener('load',check));resolve(lib);};
    const check=()=>{if(usable(window.echarts))finish(window.echarts);else if(Date.now()-started>=8000)finish(null);};
    const poll=setInterval(check,50);
    scripts.forEach(s=>s.addEventListener('load',check));
  });
  shared.promise=(async()=>{
    if(BOOT.include_echarts_cdn === false){
      shared.library=await hostWait(); shared.source=shared.library?'host':null;
    }else{
      for(const source of sources){
        const lib=await load(source.url,source.timeout);
        if(lib){shared.library=lib;shared.source=source.name;break;}
      }
    }
    if(!shared.library) throw new Error('ECHARTS_DEPENDENCY_UNAVAILABLE');
    return shared.library;
  })();
  return shared.promise;
}
const CHART_TYPES = new Set(['line','bar','radar','candlestick']);
function chartOption(el,tab,panel) {
  let option;
  const recorder={setOption:o=>{option=o;}};
  if(panel.type==='candlestick') renderCandlestickChart(el,tab,panel,recorder);
  else if(panel.type==='radar') renderRadarChart(el,tab,panel,recorder);
  else renderChart(el,tab,panel,recorder);
  return option;
}
function chartTable(option,tab,panel) {
  const series=option.series;
  if(panel.type==='radar') return {columns:['维度', panel.unit ? '数值（'+panel.unit+'）':'数值'],rows:option.radar.indicator.map((v,i)=>[v.name,series[0].data[0].value[i]])};
  if(panel.type==='candlestick') {
    const ix=candleColumns(tab,panel);
    const columns=['日期','开盘价','最高价','最低价','收盘价'];
    const rows=option.xAxis[0].data.map((d,i)=>[d,series[0].data[i][0],series[0].data[i][3],series[0].data[i][2],series[0].data[i][1]]);
    if(panel.unit) for(let i=1;i<columns.length;i++) columns[i]+='（'+panel.unit+'）';
    for(const s of series.slice(1)){columns.push(s.name+(s.yAxisIndex===1&&panel.volume_unit?'（'+panel.volume_unit+'）':''));rows.forEach((r,i)=>r.push(s.data[i]));}
    // show_volume=false hides the volume plot, not the underlying validated data.
    if(ix.volume>=0 && panel.show_volume===false){columns.push('成交量'+(panel.volume_unit?'（'+panel.volume_unit+'）':''));const byDate=new Map(tab.rows.map(r=>[dailyKey(r[ix.date]),r[ix.volume]]));rows.forEach(r=>r.push(byDate.get(r[0])));}
    return {columns,rows};
  }
  const horizontal=option.yAxis?.type==='category';
  const dates=(horizontal?option.yAxis:option.xAxis).data;
  return {columns:[panel.x || tab.columns[0],...series.map(s=>s.name+(panel.unit?'（'+panel.unit+'）':''))],rows:dates.map((d,i)=>[d,...series.map(s=>s.data[i])])};
}
function setChartError(body,error) {
  body.dataset.qbPresentation='failed'; body.dataset.qbRenderError=String(error);
  delete body.__qbPresentationEvidence;
  body.innerHTML='<p class="empty err">渲染失败: '+esc(error)+'</p>';
}
function renderChartPanel(body,tab,panel,span) {
  const token={}; body.__qbChartToken=token;
  body.dataset.qbChartType=panel.type;
  body.dataset.qbPanelTitle=panel.title || panel.output || panel.type;
  body.dataset.qbPresentation='pending';
  delete body.dataset.qbRenderError;
  delete body.__qbPresentationEvidence;
  const old=chartLibrary()?.getInstanceByDom?.(body); if(old)old.dispose();
  let option, table;
  try {
    if(!tab.rows.length) throw new Error('图表展示窗口内无有效数据');
    option=chartOption(body,tab,panel); table=chartTable(option,tab,panel);
  } catch(error){setChartError(body,error);return;}
  const current=()=>body.__qbChartToken===token && body.isConnected;
  ensureChartLibrary().then(lib=>{
    if(!current())return;
    try{
      body.innerHTML='';body.style.overflow='';body.style.maxHeight='';
      body.style.height=(panel.height || (panel.type==='candlestick'?(span==='full'?560:420):(span==='full'?360:300)))+'px';
      const chart=lib.init(body); chart.setOption(option);
      if(body.__qbResize)window.removeEventListener('resize',body.__qbResize);
      body.__qbResize=()=>{if(body.isConnected && body.__qbChartToken===token)chart.resize();};
      window.addEventListener('resize',body.__qbResize);
      body.__qbPresentationEvidence={option,chart};
      body.dataset.qbPresentation='chart_ready';
      delete body.dataset.qbFallbackReason;
    }catch(error){lib.getInstanceByDom?.(body)?.dispose();setChartError(body,error);}
  },error=>{
    if(!current())return;
    try{
      renderTable(body,table,{output_labels:{}});
      const headers=[...body.querySelectorAll('thead th')].map(c=>c.textContent);
      const rows=[...body.querySelectorAll('tbody tr')].map(r=>[...r.cells].map(c=>c.textContent));
      if(rows.length!==table.rows.length || !rows.length)throw new Error('降级表格数据不完整');
      body.__qbPresentationEvidence={headers,rows,dataLabel:body.getAttribute('data-qb-label-module')};
      body.insertAdjacentHTML('afterbegin','<p data-qb-chart-fallback-notice>图表资源暂不可用，已改为数据表展示</p>');
      body.style.height='auto'; body.style.maxHeight='600px'; body.style.overflow='auto';body.style.minWidth='0';
      body.dataset.qbPresentation='table_fallback';body.dataset.qbFallbackReason=String(error.message);
      delete body.dataset.qbRenderError;
    }catch(err){setChartError(body,err);}
  });
}
