/* QB_DATA_KERNEL_START:v2 */
/* ============================================================
   观照量化 · 取数内核 (data-kernel)  —— 所有手搓页面共用的一份
   ------------------------------------------------------------
   只做一件事：把“去服务器拿数据”做对，让页面只管“长什么样”。
     连服务器 → 读 SSE 流 → 组装 outputs → 解包清洗 → 出错就喊
   口径与 build_dashboard 的渲染器一致，别再每页各抄各的、各踩各的坑。

   用法（把本段整体内联进页面 <script>，再调）：
     const out = await QB.query({ endpoint, package_id, signature });
     const px  = QB.series(out, 'SC_px', { dropZero:true }); // 价格：扔掉 0/空缺口
     const chg = QB.lastValue(out, 'IDXRET');                // 单值
     const top = QB.topValues(out, 'GAIN');                  // 榜单
     const d   = QB.fmtDate(QB.lastDate(out, 'IDXRET'));     // 日期 → 'YYYY-MM-DD'

     // 数据授权（免 key，凭 grant_id + signature；表单 POST 免跨域预检，不重算）：
     // 返回值同样是 out 直查表，key 用 grant_id，上面这些取值器直接复用。
     const gOut = await QB.queryGrant({ endpoint, grant_id, signature });
     const last = QB.lastValue(gOut, grant_id);

   设计取舍：
     · endpoint 由调用方传入、不写死 —— 测试环境填测试地址、正式环境填正式地址，保持灵活。
     · 清洗只统一“数据层”：缺口(null/NaN)永远扔；价格的假 0 按需扔；涨跌幅的 0 是合法平盘值不扔。
     · 出错（HTTP 失败 / 服务端 error 事件 / 三件套没填）一律 throw，页面 catch 后塞进自己的错误槽——
       绝不闷头返回空数据让页面画出一张“看着成功其实是错的”假图。
   ============================================================ */
const QB = (function () {
  'use strict';

  // 构建时由 compile_bespoke_page.py 注入本次生成所用的 quant-buddy-view 版本；
  // 未经编译（仍是占位符）时不发版本头，避免上报无意义的占位串。
  const SKILL_VERSION = '__QBV_SKILL_VERSION__';
  const SKILL_NAME = 'quant-buddy-view';
  const _hasSkillVer = SKILL_VERSION && SKILL_VERSION.indexOf('__QBV_') !== 0;
  const _runtimeHost = typeof window !== 'undefined' ? window :
    (typeof globalThis !== 'undefined' ? globalThis : null);
  const _runtimeTransports = new Set();

  function _runtimeState() {
    if (!_runtimeHost) return null;
    if (!_runtimeHost.QB_DATA_RUNTIME || typeof _runtimeHost.QB_DATA_RUNTIME !== 'object') {
      _runtimeHost.QB_DATA_RUNTIME = {
        pending: 0,
        status: 'idle',
        transport: 'none',
        error: null,
      };
    }
    return _runtimeHost.QB_DATA_RUNTIME;
  }

  function _safeError(error) {
    return String(error && error.message ? error.message : error || '未知错误')
      .replace(/https?:\/\/[^\s)'"<>]+/gi, '[URL]')
      .replace(/([?&](?:x-amz-[^=]+|signature)\s*=)[^&\s]+/gi, '$1[REDACTED]');
  }

  function _runtimeTransport(transport) {
    if (!transport || transport === 'none') return;
    _runtimeTransports.add(transport);
    const state = _runtimeState();
    if (state) state.transport = _runtimeTransports.size > 1 ? 'mixed' : Array.from(_runtimeTransports)[0];
  }

  function _runtimeBegin(transport) {
    const state = _runtimeState();
    if (!state) return;
    if (!Number.isFinite(state.pending) || state.pending <= 0) {
      state.pending = 0;
      state.error = null;
      state.transport = 'none';
      _runtimeTransports.clear();
    }
    state.pending += 1;
    state.status = 'loading';
    _runtimeTransport(transport);
  }

  function _runtimeFail(error) {
    const state = _runtimeState();
    if (state && !state.error) state.error = _safeError(error);
  }

  function _runtimeEnd() {
    const state = _runtimeState();
    if (!state) return;
    state.pending = Math.max(0, (Number(state.pending) || 0) - 1);
    if (state.pending === 0) state.status = state.error ? 'error' : 'ready';
  }

  async function _withRuntime(transport, fn) {
    _runtimeBegin(transport);
    try {
      return await fn();
    } catch (error) {
      _runtimeFail(error);
      throw error;
    } finally {
      _runtimeEnd();
    }
  }

  // —— 有效数值：非 null、是有限数（NaN / Infinity 都不算）——
  const num = v => (typeof v === 'number' && isFinite(v)) ? v : null;

  function apiUrl(endpoint, path) {
    endpoint = String(endpoint || '').replace(/\/+$/, '');
    path = '/' + String(path || '').replace(/^\/+/, '');
    if (endpoint.endsWith('/skill') && path.startsWith('/skill/')) {
      path = path.slice('/skill'.length);
    }
    return endpoint + path;
  }

  function dateAlias(value) {
    const raw = String(value == null ? '' : value).trim();
    if (/^\d{8}$/.test(raw)) return raw.slice(0, 4) + '-' + raw.slice(4, 6) + '-' + raw.slice(6, 8);
    if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw;
    return value;
  }

  function hasUsefulData(data) {
    if (data == null) return false;
    if (Array.isArray(data)) return data.length > 0;
    if (typeof data !== 'object') return data !== '';
    for (const k of ['range_data', 'last_value', 'last_day_stats', 'last_column_full', 'last_valid_per_asset']) {
      if (data[k] != null) return hasUsefulData(data[k]);
    }
    if (Array.isArray(data.values)) return data.values.some(v => Array.isArray(v) ? v.some(x => x != null) : v != null);
    if (Array.isArray(data.top_values) || Array.isArray(data.items) || Array.isArray(data.records)) {
      return (data.top_values || data.items || data.records).length > 0;
    }
    if ('value' in data) return data.value != null;
    return Object.keys(data).length > 0;
  }

  /* 连服务器并兼容 Formula Package 的 SSE / 直接 JSON 响应，组装成 outputs 直查表
     （out['变量名'] 即该产出）。元信息（stale / recomputed）挂在 out.__done 上。 */
  async function _queryRaw(cfg, opts) {
    const { endpoint, package_id, signature } = cfg || {};
    if (!endpoint || !package_id || !signature)
      throw new Error('取数内核：endpoint / package_id / signature 三者必填');

    // 温和提醒（不强改）：https 页面连 http 地址，发布到线上会被浏览器拦（mixed-content）
    if (typeof location !== 'undefined' &&
        location.protocol === 'https:' && /^http:\/\//i.test(endpoint)) {
      console.warn('[取数内核] 页面是 https，endpoint 却是 http：' + endpoint +
        '\n  本地双击打开能用，但发布到 https 网站会被浏览器拦截（mixed-content）。' +
        '\n  发布前请把 endpoint 换成 https 地址。');
    }

    const status = opts && opts.status;
    const expectedOutputs = (Array.isArray(cfg.outputs) ? cfg.outputs : (Array.isArray(opts && opts.outputs) ? opts.outputs : []))
      .filter(value => typeof value === 'string' && value.trim())
      .map(value => value.trim());
    if (status) {
      status.package_id = package_id;
      status.loading = true;
      status.ok = false;
      status.error = null;
      status.progress = [];
      status.startedAt = Date.now();
    }

    const resp = await fetch(apiUrl(endpoint, '/skill/queryFormulaPackage'), {
      method: 'POST',
      headers: Object.assign(
        { 'Content-Type': 'application/json' },
        _hasSkillVer ? { 'x-skill-version': SKILL_VERSION, 'x-skill-name': SKILL_NAME } : {}
      ),
      body: JSON.stringify({ package_id, signature, outputs: expectedOutputs.length ? expectedOutputs : undefined }),
    });
    if (!resp.ok || !resp.body) throw new Error('HTTP ' + resp.status);

    const reader = resp.body.getReader(), dec = new TextDecoder();
    const out = {}; let buf = '', rawBody = '';
    function acceptEvent(ev, dt) {
      if (!dt || typeof dt !== 'object') return false;
      if (ev === 'result') {
        if (!dt.output || typeof dt.output !== 'string') return false;
        out[dt.output] = dt;
        if (status) status.lastOutput = dt.output;
        return true;
      }
      if (ev === 'progress') {
        out.__progress = out.__progress || [];
        out.__progress.push(dt);
        if (status) status.progress.push(dt);
        return true;
      }
      if (ev === 'error') {
        const msg = (dt.code || 'ERROR') + ': ' + (dt.message || '');
        if (status) status.error = msg;
        throw new Error(msg);
      }
      if (ev === 'done') { out.__done = dt; return true; }
      return false;
    }
    function acceptSseBlock(block) {
      const lines = String(block || '').replace(/\r\n/g, '\n').split('\n');
      let eventName = '', dataLines = [];
      for (const line of lines) {
        if (line.indexOf('event:') === 0) eventName = line.slice(6).trim();
        else if (line.indexOf('data:') === 0) dataLines.push(line.slice(5).trimStart());
      }
      if (!eventName || !dataLines.length) return false;
      let payload; try { payload = JSON.parse(dataLines.join('\n')); } catch (e) { return false; }
      return acceptEvent(eventName, payload);
    }
    function acceptDirectJson(payload) {
      const values = Array.isArray(payload) ? payload : (Array.isArray(payload && payload.outputs) ? payload.outputs : [payload]);
      let accepted = false;
      for (const value of values) accepted = acceptEvent('result', value) || accepted;
      return accepted;
    }
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      const chunk = dec.decode(value, { stream: true });
      rawBody += chunk;
      buf += chunk;
      const blocks = buf.split(/\r?\n\r?\n/); buf = blocks.pop();
      for (const block of blocks) acceptSseBlock(block);
    }
    const tail = dec.decode();
    if (tail) { rawBody += tail; buf += tail; }
    if (buf.trim()) acceptSseBlock(buf);
    const directText = rawBody.trim();
    if (directText && /^[{[]/.test(directText)) {
      try { acceptDirectJson(JSON.parse(directText)); } catch (e) { /* SSE body is not JSON as a whole. */ }
    }

    const receivedOutputs = Object.keys(out).filter(k => k.indexOf('__') !== 0);
    const missingOutputs = expectedOutputs.filter(name => !Object.prototype.hasOwnProperty.call(out, name));
    if (!receivedOutputs.length || missingOutputs.length) {
      const detail = missingOutputs.length
        ? '缺少请求的输出 ' + missingOutputs.join(', ')
        : '未识别到任何 Formula Package 输出';
      const error = new Error('公式包响应不完整：' + detail);
      if (status) Object.assign(status, { loading: false, ok: false, error: error.message });
      throw error;
    }
    const failed = receivedOutputs.filter(k => out[k] && out[k].error);
    out.__status = {
      package_id,
      ok: failed.length === 0 && !(out.__done && out.__done.code && out.__done.code !== 0),
      error: failed.length ? failed.map(k => k + ': ' + out[k].error).join('; ') : null,
      failed,
      done: out.__done || null,
      progress: out.__progress || [],
    };
    if (status) Object.assign(status, out.__status, { loading: false });
    return out;
  }

  async function query(cfg, opts) {
    return _withRuntime('sse', () => _queryRaw(cfg, opts));
  }

  function _parseWideCsvPayload(payload) {
    const intent = String((payload && payload.intent) || '未知字段');
    let text = payload && payload.text;
    if (typeof text !== 'string') throw new Error('CSV 内容类型无效（字段=' + intent + '）');
    if (text.charCodeAt(0) === 0xFEFF) text = text.slice(1);

    function records(source) {
      const out = [];
      let row = [], cell = '', quoted = false, quoteClosed = false;
      for (let i = 0; i < source.length; i++) {
        const ch = source[i];
        if (quoted) {
          if (ch === '"') {
            if (source[i + 1] === '"') { cell += '"'; i += 1; }
            else { quoted = false; quoteClosed = true; }
          } else cell += ch;
          continue;
        }
        if (ch === '"') {
          if (cell.length || quoteClosed) throw new Error('CSV 引号格式无效（字段=' + intent + '）');
          quoted = true;
        } else if (ch === ',') {
          row.push(cell); cell = ''; quoteClosed = false;
        } else if (ch === '\n' || ch === '\r') {
          if (ch === '\r' && source[i + 1] === '\n') i += 1;
          row.push(cell); out.push(row); row = []; cell = ''; quoteClosed = false;
        } else {
          if (quoteClosed && !/\s/.test(ch)) throw new Error('CSV 引号后存在非法字符（字段=' + intent + '）');
          if (!quoteClosed) cell += ch;
        }
      }
      if (quoted) throw new Error('CSV 引号未闭合（字段=' + intent + '）');
      if (cell.length || row.length) { row.push(cell); out.push(row); }
      return out;
    }

    function normalDate(value) {
      const raw = String(value || '').trim();
      let y, m, d;
      if (/^\d{8}$/.test(raw)) { y = +raw.slice(0, 4); m = +raw.slice(4, 6); d = +raw.slice(6, 8); }
      else if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) { y = +raw.slice(0, 4); m = +raw.slice(5, 7); d = +raw.slice(8, 10); }
      else throw new Error('CSV 日期列无效: ' + (raw || '<empty>'));
      const date = new Date(Date.UTC(y, m - 1, d));
      if (date.getUTCFullYear() !== y || date.getUTCMonth() !== m - 1 || date.getUTCDate() !== d)
        throw new Error('CSV 日期列无效: ' + raw);
      return String(y).padStart(4, '0') + '-' + String(m).padStart(2, '0') + '-' + String(d).padStart(2, '0');
    }

    function number(value, rowNumber, date) {
      const raw = String(value == null ? '' : value).trim();
      if (/^(?:|null|none|nan|[+-]?(?:infinity|inf))$/i.test(raw)) return null;
      const parsed = Number(raw);
      if (!Number.isFinite(parsed))
        throw new Error('CSV 数值无效（字段=' + intent + ', 行=' + rowNumber + ', 日期=' + date + '）');
      return parsed;
    }

    const parsedRecords = records(text);
    const header = parsedRecords.shift();
    if (!header || header.length < 3 || String(header[0]).trim().toLowerCase() !== 'ticker' ||
        String(header[1]).trim().toLowerCase() !== 'name')
      throw new Error('CSV 表头异常（字段=' + intent + '）：期望 ticker,name,<日期...>');
    const dates = header.slice(2).map(normalDate);
    if (new Set(dates).size !== dates.length) throw new Error('CSV 日期列重复（字段=' + intent + '）');
    const rows = [], seen = new Set();
    parsedRecords.forEach((row, index) => {
      if (!row.length || row.every(item => !String(item || '').trim())) return;
      const rowNumber = index + 2;
      if (row.length !== header.length) throw new Error('CSV 列数不一致（字段=' + intent + ', 行=' + rowNumber + '）');
      const ticker = String(row[0] || '').trim();
      const name = String(row[1] || '').trim() || ticker;
      if (!ticker) throw new Error('CSV ticker 为空（字段=' + intent + ', 行=' + rowNumber + '）');
      if (seen.has(ticker)) throw new Error('CSV ticker 重复（字段=' + intent + ', ticker=' + ticker + '）');
      seen.add(ticker);
      const values = row.slice(2).map((value, valueIndex) => number(value, rowNumber, dates[valueIndex]));
      if (!values.some(value => value !== null))
        throw new Error('CSV 字段无有效数据（字段=' + intent + ', ticker=' + ticker + '）');
      rows.push({ ticker, name, values });
    });
    if (!rows.length) throw new Error('CSV 无资产数据（字段=' + intent + '）');
    return { dates, rows };
  }

  async function _parseCsvPayloads(fields, texts, useWorker) {
    const payloads = fields.map((field, index) => ({ intent: field.intent, text: texts[index] }));
    if (!useWorker || typeof Worker === 'undefined' || typeof Blob === 'undefined' ||
        typeof URL === 'undefined' || typeof URL.createObjectURL !== 'function') {
      return payloads.map(_parseWideCsvPayload);
    }
    try {
      return await new Promise((resolve, reject) => {
        const workerSource = 'const parse=' + _parseWideCsvPayload.toString() + ';' +
          'self.onmessage=function(e){try{self.postMessage({ok:true,value:e.data.map(parse)})}' +
          'catch(err){self.postMessage({ok:false,error:String(err&&err.message||err)})}};';
        const objectUrl = URL.createObjectURL(new Blob([workerSource], { type: 'text/javascript' }));
        let worker;
        try { worker = new Worker(objectUrl); }
        catch (error) { URL.revokeObjectURL(objectUrl); error.code = 'WORKER_UNAVAILABLE'; reject(error); return; }
        const finish = () => { try { worker.terminate(); } catch (e) {} URL.revokeObjectURL(objectUrl); };
        worker.onmessage = event => {
          const message = event.data || {};
          finish();
          if (message.ok) resolve(message.value);
          else { const error = new Error(message.error || 'CSV Worker 解析失败'); error.code = 'CSV_PARSE'; reject(error); }
        };
        worker.onerror = () => { finish(); const error = new Error('CSV Worker 不可用'); error.code = 'WORKER_UNAVAILABLE'; reject(error); };
        worker.postMessage(payloads);
      });
    } catch (error) {
      if (error && error.code === 'WORKER_UNAVAILABLE') return payloads.map(_parseWideCsvPayload);
      throw error;
    }
  }

  function _fieldUnit(field, ticker) {
    if (field.unit_per_asset) {
      const unit = field.units && field.units[ticker];
      if (unit == null) throw new Error('CSV 缺少资产单位（字段=' + field.intent + ', ticker=' + ticker + '）');
      return unit;
    }
    return field.unit;
  }

  function _mergeHydratedCsv(data, parsedFields) {
    const fields = data.csv_fields || [], assets = new Map(), order = [];
    fields.forEach((field, fieldIndex) => {
      const intent = String(field.intent || '').trim();
      if (!intent) throw new Error('CSV 字段缺少 intent');
      const parsed = parsedFields[fieldIndex];
      const rowsByTicker = new Map(parsed.rows.map(row => [row.ticker, row]));
      const declared = (field.tickers || []).map(String).filter(Boolean);
      const missing = declared.filter(ticker => !rowsByTicker.has(ticker));
      if (missing.length) throw new Error('CSV 缺少声明 ticker（字段=' + intent + ', ticker=' + missing[0] + '）');
      parsed.rows.forEach(row => {
        if (!assets.has(row.ticker)) {
          assets.set(row.ticker, { asset_intent: row.name, asset_name: row.name, ticker: row.ticker, fields: [] });
          order.push(row.ticker);
        } else if (assets.get(row.ticker).asset_name !== row.name) {
          throw new Error('CSV 资产名称不一致（ticker=' + row.ticker + '）');
        }
        const series = parsed.dates.map((date, index) => ({ date, value: row.values[index] }));
        const hydratedField = {
          intent,
          index_title: field.index_title,
          unit: _fieldUnit(field, row.ticker),
          date_type: field.date_type,
          series,
        };
        if (String(data.query_type || '').toLowerCase() !== 'window') {
          for (let i = series.length - 1; i >= 0; i--) {
            if (series[i].value !== null) { hydratedField.date = series[i].date; hydratedField.value = series[i].value; break; }
          }
        }
        assets.get(row.ticker).fields.push(hydratedField);
      });
    });
    return Object.assign({}, data, { source_mode: 'csv', results: order.map(ticker => assets.get(ticker)) });
  }

  async function _downloadCsvField(field, controllers) {
    const intent = String(field.intent || '未知字段');
    if (!field.csv_url) throw new Error('CSV 下载地址缺失（字段=' + intent + '）');
    const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    if (controller) controllers.add(controller);
    const timer = controller ? setTimeout(() => controller.abort(), 20000) : null;
    let response;
    try {
      response = await fetch(field.csv_url, {
        method: 'GET',
        cache: 'no-store',
        credentials: 'omit',
        signal: controller ? controller.signal : undefined,
      });
      if (!response.ok) {
        const error = new Error('CSV 下载失败（字段=' + intent + ', HTTP ' + response.status + '）');
        error.status = response.status;
        error.retryable = [401, 403, 404].includes(response.status);
        throw error;
      }
      return await response.text();
    } catch (error) {
      if (error && error.status) throw error;
      const wrapped = new Error('CSV 下载失败（字段=' + intent + ', 网络或超时）');
      wrapped.code = 'CSV_NETWORK';
      throw wrapped;
    } finally {
      if (timer) clearTimeout(timer);
      if (controller) controllers.delete(controller);
    }
  }

  async function _downloadCsvFields(fields) {
    const texts = new Array(fields.length), controllers = new Set();
    let next = 0;
    async function worker() {
      for (;;) {
        const index = next++;
        if (index >= fields.length) return;
        texts[index] = await _downloadCsvField(fields[index], controllers);
      }
    }
    try {
      await Promise.all(Array.from({ length: Math.min(4, fields.length) }, worker));
      return texts;
    } catch (error) {
      controllers.forEach(controller => { try { controller.abort(); } catch (e) {} });
      throw error;
    }
  }

  async function _hydrateFastQueryCsv(data) {
    const fields = data && data.csv_fields;
    if (!Array.isArray(fields) || !fields.length) throw new Error('CSV 字段清单为空');
    const texts = await _downloadCsvFields(fields);
    const points = Number(data.summary && data.summary.total_data_points) || 0;
    const parsed = await _parseCsvPayloads(fields, texts, points > 20000);
    return _mergeHydratedCsv(data, parsed);
  }

  async function _requestGrantBody(cfg) {
    const { endpoint, grant_id, signature } = cfg;
    // 跨域取数改用表单 POST（CORS 安全列表内的 Content-Type）且不带自定义头，
    // 避免页面(pages.quantbuddy.cn)->接口(www.quantbuddy.cn)时触发 OPTIONS 预检被拦；
    // grant_id/signature 语义不变，服务端按表单字段解析，响应仍是 JSON。
    const formBody = 'grant_id=' + encodeURIComponent(grant_id) +
      '&signature=' + encodeURIComponent(signature);
    const resp = await fetch(apiUrl(endpoint, '/skill/queryDataGrant'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: formBody,
    });
    let body = null;
    try { body = await resp.json(); } catch (e) {}
    if (!resp.ok || !body || body.code !== 0) {
      const err = (body && body.error) || {};
      throw new Error((err.code || ('HTTP ' + resp.status)) + (err.message ? (': ' + err.message) : ''));
    }
    return body;
  }

  /* 数据授权取数：免 key，凭 grant_id + signature；表单 POST 免跨域预检（不重算，永远反映当下数据）。
     成功/失败都走同一份 throw-on-error 约定；成功时返回的 out 直查表与 query() 同形状，
     key 用 grant_id，series/lastValue/topValues/perAsset 等取值器直接复用。 */
  async function queryGrant(cfg) {
    const { endpoint, grant_id, signature } = cfg || {};
    if (!endpoint || !grant_id || !signature)
      throw new Error('取数内核：endpoint / grant_id / signature 三者必填');

    if (typeof location !== 'undefined' &&
        location.protocol === 'https:' && /^http:\/\//i.test(endpoint)) {
      console.warn('[取数内核] 页面是 https，endpoint 却是 http：' + endpoint +
        '\n  本地双击打开能用，但发布到 https 网站会被浏览器拦截（mixed-content）。' +
        '\n  发布前请把 endpoint 换成 https 地址。');
    }

    return _withRuntime('none', async () => {
      let body = await _requestGrantBody({ endpoint, grant_id, signature });
      for (let attempt = 0; attempt < 2; attempt++) {
        if (body && body.data && String(body.data.mode || '').toLowerCase() === 'csv') {
          _runtimeTransport('csv');
          try {
            body = Object.assign({}, body, { data: await _hydrateFastQueryCsv(body.data) });
          } catch (error) {
            if (attempt === 0 && error && error.retryable) {
              body = await _requestGrantBody({ endpoint, grant_id, signature });
              continue;
            }
            throw error;
          }
        } else _runtimeTransport('inline');
        const out = {};
        out[grant_id] = { output: grant_id, data: body.data, error: null, kind: body.kind };
        out.__status = { grant_id, kind: body.kind, ok: true, error: null };
        return out;
      }
      throw new Error('CSV 刷新后仍无法取数');
    });
  }

  async function queryMany(packagesByRole, opts) {
    const entries = Object.entries(packagesByRole || {}).filter(([, cfg]) => cfg);
    const outputsByRole = {};
    const statusByRole = {};
    const onStatus = opts && typeof opts.onStatus === 'function' ? opts.onStatus : null;
    const slowMs = (opts && opts.slowMs) || 9000;

    await Promise.all(entries.map(async ([role, cfg]) => {
      const status = statusByRole[role] = { role, loading: true, ok: false, progress: [] };
      let slowTimer = null;
      if (onStatus) {
        onStatus({ role, phase: 'start', status });
        slowTimer = setTimeout(() => {
          if (status.loading) onStatus({ role, phase: 'slow', message: '取数仍在进行，可能正在重算公式包', status });
        }, slowMs);
      }
      try {
        const out = await query(cfg, { status });
        outputsByRole[role] = out;
        Object.assign(status, out.__status || {}, { role, loading: false });
        if (onStatus) onStatus({ role, phase: 'done', status, outputs: out });
      } catch (e) {
        status.loading = false;
        status.ok = false;
        status.error = e && e.message ? e.message : String(e);
        outputsByRole[role] = { __status: status };
        if (onStatus) onStatus({ role, phase: 'error', status });
      } finally {
        if (slowTimer) clearTimeout(slowTimer);
      }
    }));

    return {
      outputsByRole,
      statusByRole,
      outputs: outputsByRole,
      status: statusByRole,
    };
  }

  // —— 取某产出的原始 data 包 ——
  const _data = (out, key) => (out && out[key] && out[key].data) || null;

  function outputStatus(out, key) {
    if (!key) {
      const st = out && out.__status;
      return st || { ok: !!out, error: out ? null : 'empty output', hasData: !!out };
    }
    const item = out && out[key];
    if (!item) return { ok: false, output: key, error: 'missing output', hasData: false };
    const hasData = hasUsefulData(item.data);
    return {
      ok: !item.error && hasData,
      output: key,
      read_mode: item.read_mode,
      data_id: item.data_id,
      error: item.error || (hasData ? null : 'empty data'),
      hasData,
    };
  }

  /* 单值：last_value.{date,value}。value 必须是有效数值，否则返回 null（不吐 NaN/占位 0）。 */
  function lastValue(out, key) {
    const d = _data(out, key);
    return d && d.last_value ? num(d.last_value.value) : null;
  }
  function lastDate(out, key) {
    const d = _data(out, key);
    return d && d.last_value && d.last_value.date != null ? d.last_value.date : null;
  }

  /* 序列：range_data.{dates,values} → [{ d:日期, v:数值 }]（兼容别名 p.date / p.value）
       · 永远扔掉 null / NaN（缺口）
       · dropZero=true 时把 0 也当缺口扔 —— 价格 / 成交额这类“不可能为 0”的数据要开；
         涨跌幅 / 收益率这类 0 是合法平盘值的，别开。 */
  function series(out, key, opts) {
    const dropZero = !!(opts && opts.dropZero);
    const d = _data(out, key);
    const r = d && d.range_data;
    if (!r || !r.values) return [];
    const pts = [];
    for (let i = 0; i < r.values.length; i++) {
      const v = num(r.values[i]);
      if (v === null) continue;           // 缺口
      if (dropZero && v === 0) continue;   // 价格的假 0
      const point = { d: r.dates ? r.dates[i] : i, v };
      // Historical bespoke pages used the grant-series shape ({date,value}) here.
      // Keep the documented enumerable {d,v} contract while allowing those pages to
      // consume Formula Package range_data safely during their normal live refresh.
      Object.defineProperties(point, {
        date: { value: dateAlias(point.d), enumerable: false },
        value: { value: point.v, enumerable: false },
      });
      pts.push(point);
    }
    return pts;
  }
  // 只要数值数组（画 sparkline 常用）：QB.values(out,'SC_px',{dropZero:true})
  function values(out, key, opts) { return series(out, key, opts).map(p => p.v); }

  function sectionRows(section, allowObjectMap) {
    if (!section) return [];
    if (Array.isArray(section)) return section;
    for (const k of ['items', 'records', 'rows', 'values']) {
      if (Array.isArray(section[k])) return section[k];
    }
    if (allowObjectMap && typeof section === 'object') {
      return Object.keys(section).map(asset => {
        const v = section[asset];
        return (v && typeof v === 'object') ? Object.assign({ asset }, v) : { asset, value: v };
      });
    }
    return [];
  }

  /* 榜单：优先 last_day_stats.top_values[]，完整截面则读取 last_column_full.values[]。 */
  function topValues(out, key) {
    const d = _data(out, key);
    const stats = d && d.last_day_stats;
    if (stats && Array.isArray(stats.top_values)) return stats.top_values;
    return sectionRows(d && d.last_column_full, false);
  }
  function statDate(out, key) {
    const d = _data(out, key);
    return (d && d.last_day_stats && d.last_day_stats.date) ||
      (d && d.last_column_full && d.last_column_full.date) || null;
  }

  function perAsset(out, key) {
    const d = _data(out, key);
    if (d && d.last_valid_per_asset) return sectionRows(d.last_valid_per_asset, true);
    return sectionRows(d && d.last_column_full, false);
  }

  function perAssetMap(out, key) {
    const m = {};
    perAsset(out, key).forEach(row => {
      const asset = row && (row.asset || row.ticker || row.code || row.symbol || row.name);
      if (asset) m[asset] = row;
    });
    return m;
  }

  /* 日期：整数/字符串 YYYYMMDD → 'YYYY-MM-DD'（分隔符可换）。非 8 位原样返回，空值给占位。 */
  function fmtDate(d, sep) {
    if (d == null || d === '') return '—';
    const s = String(d), q = sep || '-';
    if (!/^\d{8}$/.test(s)) return s;
    return s.slice(0, 4) + q + s.slice(4, 6) + q + s.slice(6, 8);
  }

  return {
    query, queryMany, queryGrant, apiUrl,
    runtime: { begin: _runtimeBegin, transport: _runtimeTransport, fail: _runtimeFail, end: _runtimeEnd },
    num, outputStatus,
    lastValue, lastDate, series, values, topValues, statDate,
    perAsset, perAssetMap,
    fmtDate
  };
})();
/* QB_DATA_KERNEL_END:v2 */
