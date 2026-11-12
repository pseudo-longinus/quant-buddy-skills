/* QB_ECHARTS_RUNTIME_V1 */
(function () {
  // Pure renderer/normalizer consumers can execute the bundle outside a browser.
  if (typeof window === 'undefined') return;
  if (window.QBCharts?.version === 1 && window.QBCharts.prepare) return;
  const sources = __CHART_SOURCES__;
  const usable = lib => !!lib && typeof lib.init === 'function' && typeof lib.getInstanceByDom === 'function';
  function ensureLibrary(options = {}) {
    const shared = window.__QB_ECHARTS_LOADER__ ||= {library:null, promise:null, attempts:[], source:null};
    if (usable(shared.library)) return Promise.resolve(shared.library);
    // A caller that forbids external loading must not inherit another caller's network policy.
    if (options.external === false) {
      if (usable(window.echarts)) {
        shared.library = window.echarts; shared.source = 'host';
        return Promise.resolve(shared.library);
      }
      return new Promise((resolve, reject) => {
        const started = Date.now();
        const poll = setInterval(() => {
          if (usable(window.echarts)) { clearInterval(poll); shared.library = window.echarts; shared.source = 'host'; resolve(shared.library); }
          else if (Date.now() - started >= 8000) { clearInterval(poll); reject(new Error('ECHARTS_DEPENDENCY_UNAVAILABLE')); }
        }, 50);
      });
    }
    if (shared.promise) return shared.promise;
    if (usable(window.echarts)) {
      shared.library = window.echarts; shared.source = 'host';
      return shared.promise = Promise.resolve(shared.library);
    }
    const load = source => new Promise(resolve => {
      const controller = new AbortController();
      const attempt = {url:source.url, status:'pending', startedAt:Date.now()};
      shared.attempts.push(attempt);
      let finished = false;
      const finish = (lib, status) => {
        if (finished) return;
        finished = true; clearTimeout(timer);
        attempt.status = status; attempt.elapsedMs = Date.now() - attempt.startedAt;
        resolve(lib);
      };
      const timer = setTimeout(() => { finish(null, 'timeout'); controller.abort(); }, source.timeout);
      // Even an async external script delays window.load and the enclosing
      // Playground iframe's ready message. Fetch does not hold that event and
      // can actually abort a hung source. Both pinned sources allow CORS.
      fetch(source.url, {signal:controller.signal, credentials:'omit'}).then(response => {
        if (!response.ok) throw new Error('ECHARTS_HTTP_' + response.status);
        return response.text();
      }).then(code => {
        if (finished) return;
        const script = document.createElement('script');
        script.dataset.qbChartDependency = 'true';
        script.textContent = code;
        document.head.appendChild(script);
        finish(usable(window.echarts) ? window.echarts : null, usable(window.echarts) ? 'ready' : 'invalid_api');
      }).catch(() => finish(null, 'error'));
    });
    shared.promise = (async () => {
      for (const source of sources) {
        const lib = await load(source);
        if (lib) { shared.library = lib; shared.source = source.name; return lib; }
      }
      throw new Error('ECHARTS_DEPENDENCY_UNAVAILABLE');
    })();
    return shared.promise;
  }
  const cell = value => value == null || typeof value === 'number' && !Number.isFinite(value) ? '—' : String(value);
  function finishLoading(el) {
    el.__qbLoadingNotice?.remove(); delete el.__qbLoadingNotice;
    if (el.__qbLoadingPosition !== undefined) {
      el.style.position = el.__qbLoadingPosition; delete el.__qbLoadingPosition;
    }
    el.setAttribute('aria-busy', 'false');
  }
  function dispose(el) {
    el.__qbPresentationEvidence?.chart?.dispose();
    if (el.__qbResize) { window.removeEventListener('resize', el.__qbResize); delete el.__qbResize; }
    delete el.__qbPresentationEvidence;
  }
  function loading(el, text) {
    el.setAttribute('aria-busy', 'true');
    if (el.__qbPresentationEvidence) {
      if (!el.__qbLoadingNotice) {
        const notice = document.createElement('p'); notice.dataset.qbChartLoadingNotice = '';
        notice.setAttribute('role', 'status');
        notice.textContent = '正在更新数据，暂显示上次结果（日期以图表为准）';
        // Keep the notice inside the chart so a grid/flex parent gains no item.
        if (getComputedStyle(el).position === 'static') {
          el.__qbLoadingPosition = el.style.position; el.style.position = 'relative';
        }
        notice.style.cssText = 'position:absolute;top:0;right:0;max-width:100%;box-sizing:border-box;margin:0;padding:4px 8px;font:12px/1.5 sans-serif;background:var(--qb-chart-loading-bg,#fff);z-index:1;pointer-events:none';
        el.appendChild(notice); el.__qbLoadingNotice = notice;
      }
    } else {
      el.dataset.qbPresentation = 'pending'; el.textContent = text;
    }
  }
  // Declare containers before fetching data: loading feedback and library fetch
  // start together, without coupling independent data requests to each other.
  function prepare(targets = '[data-qb-chart]', options = {}) {
    const elements = typeof targets === 'string' ? [...document.querySelectorAll(targets)] :
      targets?.nodeType === 1 ? [targets] : Array.from(targets || []);
    const connected = elements.filter(el => el?.nodeType === 1 && el.isConnected);
    if (!connected.length) return Promise.resolve(null);
    for (const el of connected) { el.__qbPrepared = true; loading(el, '正在加载数据…'); }
    // Data still has to arrive before a complete fallback table can be shown.
    // A preload failure is handled by render, never an unhandled rejection.
    return ensureLibrary(options).catch(() => null);
  }
  function tableData(table) {
    if (!Array.isArray(table?.columns) || !table.columns.length || !Array.isArray(table.rows) || !table.rows.length ||
        table.rows.some(row => !Array.isArray(row) || row.length !== table.columns.length)) throw new Error('CHART_FALLBACK_DATA_INVALID');
    return {headers:table.columns.map(cell), rows:table.rows.map(row => row.map(cell))};
  }
  function failed(el, error) {
    dispose(el); finishLoading(el);
    el.replaceChildren();
    const message = document.createElement('p'); message.textContent = '图表渲染失败：' + error.message;
    el.appendChild(message); el.dataset.qbPresentation = 'failed'; el.dataset.qbRenderError = String(error);
    delete el.__qbPresentationEvidence;
  }
  function fallback(el, data, error) {
    dispose(el); finishLoading(el);
    el.replaceChildren();
    const notice = document.createElement('p'); notice.dataset.qbChartFallbackNotice = '';
    notice.textContent = '图表资源暂不可用，已改为数据表展示'; el.appendChild(notice);
    const table = document.createElement('table'); table.style.cssText = 'width:100%;table-layout:fixed;border-collapse:collapse';
    const row = (values, tag) => { const tr = document.createElement('tr'); for (const value of values) {
      const td = document.createElement(tag); td.textContent = value; td.style.cssText = 'overflow-wrap:anywhere;padding:6px;font-size:12px'; tr.appendChild(td);
    } return tr; };
    const head = table.createTHead(); head.appendChild(row(data.headers, 'th'));
    const body = table.createTBody(); for (const values of data.rows) body.appendChild(row(values, 'td'));
    el.appendChild(table); el.style.height = 'auto'; el.style.maxHeight = '600px'; el.style.overflowY = 'auto'; el.style.minWidth = '0';
    el.__qbPresentationEvidence = {headers:data.headers, rows:data.rows};
    el.dataset.qbPresentation = 'table_fallback'; el.dataset.qbFallbackReason = error.message;
  }
  async function render(el, config) {
    if (!el) throw new Error('CHART_CONTAINER_REQUIRED');
    const token = {}; el.__qbChartToken = token;
    const current = () => el.__qbChartToken === token && el.isConnected;
    const height = config.height || (el.dataset.qbChartHeight ||= String(el.getBoundingClientRect().height || 360));
    el.dataset.qbPanelTitle = config.title || el.id || '图表'; el.dataset.qbChartType = config.type || 'custom';
    delete el.dataset.qbRenderError; delete el.dataset.qbFallbackReason;
    loading(el, '正在加载图表…');
    let data;
    try { data = tableData(config.table); } catch (error) { failed(el, error); return null; }
    let lib;
    try { lib = await ensureLibrary(); } catch (error) {
      if (current()) fallback(el, data, error);
      return null;
    }
    if (!current()) return null;
    try {
      dispose(el); finishLoading(el);
      el.replaceChildren(); el.style.height = height + 'px'; el.style.maxHeight = ''; el.style.overflowY = '';
      const chart = config.draw ? config.draw(lib) : lib.init(el);
      if (!config.draw) chart.setOption(config.option);
      if (!chart || lib.getInstanceByDom(el) !== chart) throw new Error('CHART_INSTANCE_REQUIRED');
      el.__qbPresentationEvidence = {chart, option:chart.getOption()}; el.dataset.qbPresentation = 'chart_ready';
      el.__qbResize = () => { if (current()) chart.resize(); }; window.addEventListener('resize', el.__qbResize);
      return chart;
    } catch (error) { lib.getInstanceByDom(el)?.dispose(); failed(el, error); return null; }
  }
  window.QBCharts = {version:1, ensureLibrary, prepare, render};
  const prepareDeclared = () => {
    const elements = [...document.querySelectorAll('[data-qb-chart]')]
      .filter(el => !el.__qbPrepared && !el.__qbChartToken);
    if (elements.length) prepare(elements);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', prepareDeclared, {once:true});
  else prepareDeclared();
})();
