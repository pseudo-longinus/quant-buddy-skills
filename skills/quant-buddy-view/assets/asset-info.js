/* Page-only adapter. All identity, estimates, generation and billing stay in the official SDK. */
;(function () {
  'use strict';
  if (window.QBAssetInfoPanel) return;
  const configElement = document.querySelector('[data-qb-asset-info-config]');
  if (!configElement) return;
  const config = JSON.parse(configElement.textContent);
  const root = document.querySelector(config.target_selector);
  if (!root) return;
  const status = root.querySelector('[data-qb-asset-info-status]');
  const list = root.querySelector('[data-qb-asset-info-items]');
  const navigation = root.querySelector('[data-qb-asset-info-pagination]');
  const forceButton = root.querySelector('[data-qb-llm-force]');
  const publicPage = location.protocol === 'https:' && location.hostname === 'pages.quantbuddy.cn';
  const cache = new Map();
  let members = [], page = 0, revision = 0, pending = null, running = null, waiting = true, fingerprint = '', disclosureId = 0;
  let selectionStatus = 'unbound';
  const text = (tag, value, className) => {
    const node = document.createElement(tag); node.textContent = value;
    if (className) node.className = className;
    return node;
  };
  function disableForce(disabled) {
    forceButton.disabled = disabled || !publicPage || waiting || !members.length || !window.QBAssetInfo?.getContext().execution_allowed;
  }
  async function sdkReady() {
    if (!publicPage) throw Error('公司信息将在公开活页中加载；本地预览不发起生成。');
    const officialScript = document.querySelector('script[src$="/asset-info-bridge.js"]');
    const start = Date.now();
    while (Date.now() - start < 15000) {
      // The real shell assigns src after selection may already have arrived.
      // An empty iframe is not an environment; wait, then validate before load.
      const frame = document.getElementById('qbLivePageHeaderFrame');
      const frameSrc = frame?.getAttribute('src')?.trim();
      let pageId = null;
      if (officialScript && frameSrc && frameSrc !== 'about:blank') {
        const header = new URL(frameSrc, location.href);
        if (new URL(officialScript.src).origin !== header.origin || header.pathname !== '/embed/live-page-header') throw Error('公司信息桥接脚本与官方页头环境不一致');
        pageId = header.searchParams.get('page_id');
      }
      const sdk = window.QBAssetInfo;
      if (sdk && (!(sdk.schedulerVersion >= 2) || typeof sdk.cancelPending !== 'function')) throw Error('公司信息暂不可用：官方桥接脚本需要更新。量化结果不受影响。');
      // Do not enter SDK.load's unbounded identity wait before a trusted context exists.
      const context = sdk?.getContext();
      // An explicit unknown identity (e.g. an expired login) may still read cache.
      // The SDK's initial unknown placeholder has no page_id and is not ready.
      if (pageId && context && context.page_id === pageId) return sdk;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    throw Error('公司信息暂不可用：官方页头身份未就绪。量化结果不受影响。');
  }
  function localDate(value, dateOnly = false) {
    if (!value) return null;
    const raw = String(value);
    const calendar = /^\d{4}-\d{2}-\d{2}/.test(raw) ? new Date(raw.slice(0, 10) + 'T00:00:00Z') : null;
    if (!calendar || !Number.isFinite(calendar.getTime()) || calendar.toISOString().slice(0, 10) !== raw.slice(0, 10)) return '日期待核实';
    // Calendar dates have no timezone. Never let the browser infer one for naive timestamps.
    if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw;
    if (!/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw)) return '日期待核实';
    const date = new Date(raw);
    if (!Number.isFinite(date.getTime())) return '日期待核实';
    const parts = new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Shanghai', year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hourCycle:'h23'}).formatToParts(date);
    const part = name => parts.find(p => p.type === name).value;
    const day = `${part('year')}-${part('month')}-${part('day')}`;
    return dateOnly ? day : `${day} ${part('hour')}:${part('minute')}`;
  }
  function renderContent(element, value) {
    // The SDK writes plain text into this same element before dispatching its result.
    // Only recognise explicit section labels; never infer or summarise financial claims.
    const raw = String(value || '');
    const marker = /(?:近期重大事件(?:方面)?[：:，]|近期[（(][^）)\n]{1,60}[）)][^：。\n]{0,20}[：:]|近\d+个自然日内已发生事项[：:])/.exec(raw)
      || /近期重大事件(?=集中在)/.exec(raw);
    const split = marker && marker.index > 0 && /主营|主要从事/.test(raw.slice(0, marker.index));
    const blocks = split ? [
      {label:'主营业务', value:raw.slice(0, marker.index).trim(), kind:'business'},
      {label:marker[0].replace(/[：:，]$/, ''), value:raw.slice(marker.index + marker[0].length).trim(), kind:'events'}
    ] : [{label:'公司资料', value:raw, kind:'full'}];
    element.className = 'qb-info-body';
    element.replaceChildren();
    for (const block of blocks) {
      const section = text('div', '', `qb-info-section qb-info-section--${block.kind}`);
      const copy = text('div', '', 'qb-info-copy qb-info-copy--collapsed');
      const paragraphs = block.value.split(block.kind === 'events'
        ? /\n\s*\n|(?<=[。；])(?=(?:\d{4}年)?\d{1,2}月)/ : /\n\s*\n/);
      for (const paragraph of paragraphs) {
        const p = text('p', '');
        // Emphasise literal dates only. Do not infer timelines, event titles or importance.
        const dates = /(?:\d{4}年)?\d{1,2}月(?:\d{1,2}日|初|末|上旬|中旬|下旬)|\b\d{4}-\d{2}-\d{2}\b/g;
        let end = 0;
        for (const match of paragraph.matchAll(dates)) {
          p.append(document.createTextNode(paragraph.slice(end, match.index)), text('span', match[0], 'qb-info-inline-date'));
          end = match.index + match[0].length;
        }
        p.append(document.createTextNode(paragraph.slice(end))); copy.append(p);
      }
      const toggle = text('button', '展开全文', 'qb-info-expand');
      toggle.type = 'button'; toggle.setAttribute('aria-expanded', 'false'); toggle.hidden = true;
      toggle.setAttribute('aria-label', `展开${block.label}全文`);
      toggle.addEventListener('click', () => {
        const expanded = toggle.getAttribute('aria-expanded') !== 'true';
        copy.classList.toggle('qb-info-copy--collapsed', !expanded);
        toggle.setAttribute('aria-expanded', String(expanded));
        toggle.textContent = expanded ? '收起全文' : '展开全文';
        toggle.setAttribute('aria-label', `${expanded ? '收起' : '展开'}${block.label}全文`);
      });
      section.append(text('h4', block.label), copy, toggle); element.append(section);
      const measure = () => {
        if (toggle.getAttribute('aria-expanded') !== 'true') toggle.hidden = copy.scrollHeight <= copy.clientHeight + 2;
      };
      requestAnimationFrame(measure);
      if (window.ResizeObserver) {
        const observer = new ResizeObserver(() => {
          if (!element.isConnected) { observer.disconnect(); return; }
          measure();
        });
        observer.observe(copy);
      }
    }
  }
  function costState(result) {
    const data = result?.data || {}, billing = result?.billing || data.billing;
    // Only this request's settlement receipt proves a charge. generation_cost is historical.
    if (billing?.status === 'pending' || billing?.status === 'blocked') return '费用结算中';
    if (data.processing) return '生成中 · 费用待确认';
    const points = billing?.charged_points;
    if ((!billing?.status || billing.status === 'settled') &&
        (typeof points === 'string' && /^\d+(?:\.\d{1,2})?$/.test(points) ||
         typeof points === 'number' && Number.isFinite(points) && points >= 0)) {
      return `本次生成 · 消耗 ${typeof points === 'number' ? points.toFixed(2) : points} 积分`;
    }
    if (billing) return '费用待确认';
    if (data.content && data.cache_status === 'hit') return '缓存命中 · 本次 0 积分';
    return !data.content && data.cache_status === 'missing' ? '暂无缓存 · 未生成' : '费用待确认';
  }
  function createCostDisclosure() {
    const wrap = text('div', '', 'qb-info-cost');
    const button = text('button', '', 'qb-info-badge'); button.type = 'button';
    const label = text('span', '等待加载');
    const icon = text('span', 'ⓘ', 'qb-info-cost-icon'); icon.setAttribute('aria-hidden', 'true');
    button.append(label, icon);
    const popup = text('div', '', 'qb-info-cost-popup'); popup.id = `qb-info-cost-${++disclosureId}`; popup.hidden = true;
    const rules = text('div', '', 'qb-info-cost-rules');
    rules.append(text('strong', '积分与缓存规则'),
      text('p', '缓存命中免费，每只股票独立缓存。首次生成、缓存过期后重新生成及确认后的强制更新，按实际 Token 和搜索费用扣除页面作者积分。'),
      text('p', '缓存于北京时间每日 04:00、16:00 过期；过期后首次符合权限的访问才触发更新，到点不会自动生成或扣费。'),
      text('p', '本次费用以实际结算回执为准；历史生成成本不计为本次扣费。结算未完成或回执缺失时，不显示已扣费或免费。'));
    popup.append(rules); button.setAttribute('aria-controls', popup.id); button.setAttribute('aria-expanded', 'false');
    let pinned = false;
    const show = open => { popup.hidden = !open; button.setAttribute('aria-expanded', String(open)); };
    wrap.closeCost = () => { pinned = false; show(false); };
    button.addEventListener('click', () => { pinned = !pinned; show(pinned); });
    button.addEventListener('focus', () => show(true));
    wrap.addEventListener('pointerenter', event => { if (event.pointerType === 'mouse') show(true); });
    wrap.addEventListener('pointerleave', () => { if (!pinned && !wrap.contains(document.activeElement)) show(false); });
    wrap.addEventListener('focusout', event => { if (!wrap.contains(event.relatedTarget)) wrap.closeCost(); });
    wrap.addEventListener('keydown', event => { if (event.key === 'Escape') { event.stopPropagation(); wrap.closeCost(); } });
    wrap.append(button, popup); return wrap;
  }
  document.addEventListener('pointerdown', event => {
    for (const disclosure of root.querySelectorAll('.qb-info-cost')) if (!disclosure.contains(event.target)) disclosure.closeCost();
  });
  function snapshotState(data) {
    const expired = data.expires_at && Number.isFinite(Date.parse(data.expires_at)) && Date.parse(data.expires_at) <= Date.now();
    const state = data.processing ? '生成中' : data.content ? expired ? '缓存已过期 · 保留已有内容' : ({hit:'缓存内容',miss:'本次生成'}[data.cache_status] || '已有内容') : '暂无缓存';
    return `${data.content ? '内容快照 · ' : ''}${state}`;
  }
  function resultMetadata(card, result) {
    const data = result?.data || {};
    card.qbInfoData = data;
    const meta = card.querySelector('.qb-info-meta');
    const badge = card.querySelector('.qb-info-badge');
    const fee = costState(result);
    badge.querySelector('span').textContent = fee;
    badge.setAttribute('aria-label', `${fee}，查看积分与缓存规则`);
    meta.replaceChildren(text('span', snapshotState(data)));
    meta.append(text('span', data.generated_at ? `生成于 ${localDate(data.generated_at)} · 北京时间` : '尚未生成'));
    if (data.web_search === true || result?.web_search === true || data.web_search?.performed === true || result?.web_search?.performed === true) meta.append(text('span', '已联网检索'));
    const billing = result?.billing || data.billing;
    if (result?.success === false) meta.append(text('span', '本次加载失败，请稍后重试；量化结果不受影响'));
    if (billing?.status === 'pending' || billing?.status === 'blocked') meta.append(text('span', '本次结算尚未完成'));
    const sources = card.querySelector('.qb-info-sources'); sources.replaceChildren();
    const details = text('details', '', 'qb-info-source-details');
    const sourceList = text('ol', '', 'qb-info-source-list');
    const values = Array.isArray(data.sources) ? data.sources : [];
    for (const [index, source] of values.entries()) {
      const href = typeof source === 'string' ? source : source?.url;
      try {
        const url = new URL(href);
        if (!['https:', 'http:'].includes(url.protocol)) continue;
        const title = typeof source === 'string' ? url.hostname : source.title || source.publisher || url.hostname;
        const link = text('a', title); link.title = title;
        link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer';
        const item = text('li', '', 'qb-info-source-row'); item.value = index + 1;
        item.append(link, text('span', source.published_at ? localDate(source.published_at, true) : '日期未提供', 'qb-info-source-date'));
        sourceList.append(item);
      } catch (_) { /* Missing/unusable source URLs are not invented. */ }
    }
    const count = sourceList.children.length;
    if (count) {
      details.append(text('summary', `查看来源 · ${count} 条`), text('p', '来源日期按北京时间显示；原始顺序保留。', 'qb-info-source-note'), sourceList);
      sources.append(details);
    }
    const timing = text('details', '', 'qb-info-timing');
    timing.append(text('summary', '更新信息'), text('p', `缓存有效至：${data.expires_at ? localDate(data.expires_at) + '（北京时间）' : '未知'}`));
    sources.append(timing);
  }
  function createCard(stock, epoch, ordinal) {
    const card = text('article', '', 'qb-info-card');
    card.qbInfoEpoch = epoch;
    const header = text('header', '', 'qb-info-header');
    const identity = text('div', '', 'qb-info-identity');
    identity.append(text('h3', stock.name || stock.asset), text('span', stock.asset, 'qb-info-code'));
    header.append(text('span', String(ordinal).padStart(2, '0'), 'qb-info-ordinal'), identity, createCostDisclosure()); card.append(header);
    const content = text('section', cache.get(stock.asset)?.data?.content || '等待加载公司信息…');
    if (publicPage) {
      // Expose SDK discovery only after its managed scheduler has been verified.
      content.dataset.qbAssetInfoAsset = stock.asset; content.dataset.qbLlmGrant = config.grant_id;
      content.dataset.qbLlmSignature = config.signature; content.dataset.qbLlmAsset = stock.asset;
    }
    card.append(content, text('p', '尚未生成', 'qb-info-meta'), text('div', '', 'qb-info-sources'));
    if (cache.has(stock.asset)) {
      const {billing: oldBilling, ...data} = cache.get(stock.asset).data;
      renderContent(content, data.content);
      // A retained snapshot is not evidence of this new request's settlement.
      resultMetadata(card, {data: {...data, cache_status: 'unknown', processing: false}});
    }
    content.addEventListener('qb-asset-info-result', event => {
      if (card.qbInfoEpoch !== revision || !card.isConnected) return;
      const result = event.detail;
      if (result?.data?.content) cache.set(stock.asset, result);
      const previous = cache.get(stock.asset);
      if (!result?.data?.content && previous?.data?.content) {
        renderContent(content, previous.data.content);
        // Keep old content, but never carry its receipt or cache hit into the new request.
        const {billing: previousBilling, ...previousData} = previous.data;
        resultMetadata(card, {...result, data: {...previousData, ...result?.data,
          cache_status: result?.data?.cache_status || 'unknown',
          content: previous.data.content, generated_at: previous.data.generated_at,
          expires_at: previous.data.expires_at, sources: previous.data.sources, web_search: previous.data.web_search}});
        card.querySelector('.qb-info-meta').append(text('span', '；保留上次内容'));
      } else {
        if (result?.data?.content) renderContent(content, result.data.content);
        resultMetadata(card, result);
      }
    });
    return card;
  }
  function paint() {
    window.QBAssetInfo?.cancelPending?.();
    const epoch = ++revision;
    const visible = members.slice(page * 50, (page + 1) * 50);
    list.replaceChildren(...visible.map((stock, index) => createCard(stock, epoch, page * 50 + index + 1)));
    navigation.replaceChildren();
    if (members.length > 50) {
      const prev = text('button', '上一页'), next = text('button', '下一页');
      prev.type = next.type = 'button'; prev.disabled = page === 0; next.disabled = (page + 1) * 50 >= members.length;
      prev.addEventListener('click', () => { page--; paint(); }); next.addEventListener('click', () => { page++; paint(); });
      navigation.append(prev, text('span', `${page + 1} / ${Math.ceil(members.length / 50)} 页，共 ${members.length} 只`), next);
    }
    status.textContent = visible.length ? `本页 ${visible.length} 只；公司信息不参与筛选和排名。` : '本轮没有入选股票';
    pending = visible.length ? {epoch, elements: Array.from(list.querySelectorAll('[data-qb-asset-info-asset]'))} : null;
    disableForce(true);
    void drain();
  }
  async function drain() {
    if (running) return running;
    running = (async () => {
      while (pending) {
        const job = pending; pending = null;
        try {
          const sdk = await sdkReady();
          if (waiting || job.epoch !== revision) continue;
          for (const element of job.elements) element.dataset.qbLlm = '';
          await sdk.load(job.elements);
          if (job.epoch === revision) {
            for (const element of job.elements) {
              if (element.textContent === '等待加载公司信息…') element.textContent = '公司信息暂不可用，请稍后重试；量化结果不受影响。';
            }
          }
        } catch (error) {
          if (job.epoch === revision) status.textContent = error.message || '公司信息暂不可用';
        }
      }
    })();
    try { await running; } finally { running = null; disableForce(false); }
  }
  // Capture before the SDK's document-ready handler: use its own confirmed, quoted refresh,
  // but serialize it with selection loads and never force an old registered collection.
  forceButton.addEventListener('click', event => {
    event.preventDefault(); event.stopImmediatePropagation();
    if (running || pending || waiting || !members.length || forceButton.disabled) return;
    disableForce(true);
    running = window.QBAssetInfo.forceRefresh(list.querySelectorAll('[data-qb-llm]'));
    Promise.resolve(running).catch(() => { status.textContent = '更新结果尚未确认，请稍后读取缓存'; })
      .finally(() => { running = null; disableForce(false); if (pending) void drain(); });
  }, true);
  // The SDK may receive identity after an empty/failed selection and enable its button.
  // Reapply this module's collection/busy guard after SDK message handling.
  window.addEventListener('message', () => disableForce(Boolean(running || pending)));
  window.QBAssetInfoPanel = {
    selectionOutput: config.selection_output,
    getSelectionState: () => ({status: selectionStatus, total: members.length,
      visible_assets: members.slice(page * 50, (page + 1) * 50).map(stock => stock.asset)}),
    setTable(columns, rows) {
      const invalid = message => {
        this.unavailable(message); selectionStatus = 'invalid';
      };
      if (!Array.isArray(columns) || !Array.isArray(rows)) {
        invalid('公司信息名单格式无效：需要列名数组和数据行数组；保留上次内容。'); return;
      }
      const ai = columns.indexOf(config.asset_field), ni = columns.indexOf(config.name_field);
      if (ai < 0) { invalid('选股结果缺少股票代码字段'); return; }
      if (!rows.length) { selectionStatus = 'empty'; waiting = false; fingerprint = '[]'; members = []; page = 0; paint(); return; }
      const seen = new Set();
      const stocks = [];
      for (const row of rows) {
        const cell = field => Array.isArray(row) ? row[columns.indexOf(field)]
          : row && typeof row === 'object' && Object.hasOwn(row, field) ? row[field] : undefined;
        const value = cell(config.asset_field);
        const asset = typeof value === 'string' ? value.trim() : '';
        if (!asset) {
          invalid('公司信息名单格式无效：每行须有非空股票代码；保留上次内容。'); return;
        }
        if (seen.has(asset)) continue;
        seen.add(asset); stocks.push({asset, name: ni < 0 ? asset : String(cell(config.name_field) || asset)});
      }
      selectionStatus = 'ready';
      const next = JSON.stringify(stocks);
      waiting = false;
      if (next === fingerprint && members.length && !pending && !running) {
        // Quantitative refreshes do not generate again, but must restore this
        // collection's listeners and status after pause invalidated its epoch.
        for (const card of list.querySelectorAll('.qb-info-card')) {
          card.qbInfoEpoch = revision;
          if (card.qbInfoData) card.querySelector('.qb-info-meta').firstElementChild.textContent = snapshotState(card.qbInfoData);
        }
        status.textContent = `本页 ${list.children.length} 只；公司信息不参与筛选和排名。`;
        disableForce(false); return;
      }
      fingerprint = next; members = stocks; page = 0; paint();
    },
    pause() { selectionStatus = 'pending'; waiting = true; revision++; pending = null; window.QBAssetInfo?.cancelPending?.(); disableForce(true); status.textContent = '等待本轮选股结果'; },
    unavailable(message) { selectionStatus = 'unavailable'; waiting = true; revision++; pending = null; window.QBAssetInfo?.cancelPending?.(); disableForce(true); status.textContent = message || '本轮选股结果暂不可用，保留上次公司信息'; },
    whenIdle: () => running || Promise.resolve()
  };
})()
