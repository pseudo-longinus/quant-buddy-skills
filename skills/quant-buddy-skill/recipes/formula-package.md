# Recipe — 公式任务包：注册一组公式 → 本地 HTML 直连取数渲染

> 场景：把一组公式（一个"公式组"）固化成长期可用的**只读取数接口**，前端页面凭
> `package_id` + `signature` 直接渲染，**无需 API Key**、数据自动保鲜。
> 工具参数手册见 `tools/formula_package.md`；接口原文见
> `docs/formulaPackage 相关文档/对外接口文档.md`。

## 何时用

- 用户要"做一个能直接打开的页面/看板，用接口实时取数"
- 要把某张卡片的公式组（`getCardFormulas`）或自己设计的公式组对外只读发布
- 取数方不该拿到 api_key（浏览器本地 HTML、第三方接入）

## 端到端步骤

### 1. 设计公式组并选定对外产出

公式语法与 `runMultiFormulaBatchStream` 完全一致。每个对外产出对应一条公式的左值，
并为其选一个 `read_mode`（见 `tools/formula_package.md`）：

- 单资产/单序列最新值 → `last_day_stats`（1维序列返回 `last_value{date,value}`）
- 单序列一段时间走势（画 sparkline / 折线）→ `range_data`（返回 `range_data{dates,values}`）
- 全市场截面 TopN / 覆盖率 → `last_day_stats`（2维返回 `top_values` 等）
- 每资产最后有效值 → `last_valid_per_asset`

> 约束：单包公式 ≤ 100、对外产出 ≤ 20；**每个 output 只能一个 read_mode**。

### 2. 注册（需 api_key，落盘凭证）

把公式组写进 `params.json`（Windows 用 `@file` 传中文）：

```json
{
  "formulas": [
    "SC_ret = 涨跌幅(收盘价(沪原油主连)) * 100",
    "AG_ret = 涨跌幅(收盘价(沪银主连)) * 100",
    "SC_px  = 收盘价(沪原油主连)"
  ],
  "reads": [
    { "output": "SC_ret", "read_mode": "last_day_stats" },
    { "output": "AG_ret", "read_mode": "last_day_stats" },
    { "output": "SC_px",  "read_mode": "range_data",
      "mode_params": { "start_date": 20260501, "end_date": 20260605 } }
  ],
  "begin_date": 20260101,
  "ttl_days": 365
}
```

```bash
python scripts/formula_package.py register @params.json
# → { code:0, package_id:"pkg_xxx", signature:"...64hex...", outputs:[...], expires_at, _saved_credential }
```

凭证自动保存到 `output/formula_packages/<package_id>.json`（`signature` 服务端不可再取，勿丢）。

### 3. 取数（无需 api_key）

```bash
# signature 可由本地凭证自动补全，传 package_id 即可
FP_PARAMS='{"package_id":"pkg_xxx"}' python scripts/formula_package.py query
# → { code:0, outputs:{ SC_ret:{data:{last_value:{date,value}}}, SC_px:{data:{range_data:{dates,values}}}, ... }, done:{stale,...} }
```

### 4. 前端直连（本地 HTML 直接打开即可渲染）

取数端点 **无需 Authorization、已支持跨域**。用 `fetch` 读 SSE 流（**不要用 `EventSource`**，
它只支持 GET 会把凭证暴露到 URL）。最小内核：

```js
const ENDPOINT  = 'http://test.guanzhao12.com:3010';
const PACKAGE_ID = 'pkg_xxx';
const SIGNATURE  = '...64hex...';   // 这是只读取数凭证，嵌进前端是预期用法

async function queryPackage() {
  const resp = await fetch(`${ENDPOINT}/skill/queryFormulaPackage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ package_id: PACKAGE_ID, signature: SIGNATURE }),
  });
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  const outputs = {};
  let buf = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const blocks = buf.split('\n\n'); buf = blocks.pop();
    for (const block of blocks) {
      const ev = (block.match(/event:\s*(.*)/) || [])[1];
      const m  = block.match(/data:\s*([\s\S]*)/);
      if (!ev || !m) continue;
      const dt = JSON.parse(m[1]);
      if (ev === 'result')      outputs[dt.output] = dt;      // {output, read_mode, data_id, data}
      else if (ev === 'error')  throw new Error(`${dt.code}: ${dt.message}`);
      // 'progress' / 'done' 可按需处理
    }
  }
  return outputs;
}
// outputs.SC_ret.data.last_value.value   → 原油当日涨跌幅
// outputs.SC_px.data.range_data.{dates,values} → 原油价格走势（非交易日为 null，画图前过滤）
```

### 5. 管理

```bash
python scripts/formula_package.py list   '{"page":1,"page_size":20}'   # 我的包
python scripts/formula_package.py refresh '{"package_id":"pkg_xxx","rotate_signature":true}'  # 强制重算/轮换签名
python scripts/formula_package.py revoke '{"package_id":"pkg_xxx"}'    # 立即失效
```

## 一个可参考的页面型用法

把「一个看板需要的所有数据」收敛成一个公式包，前端就只剩"取数 + 画图"：

- 选 N 个品种/资产，每个用 `<名>_ret = 涨跌幅(收盘价(资产)) * 100` 产出当日涨跌幅（`last_day_stats` → `last_value`），用于横截面/排名/异动板；
- 头部几个再加 `<名>_px = 收盘价(资产)` 产出近一段价格（`range_data` → `dates/values`），用于画 sparkline / 折线；
- 合计产出 ≤ 20、公式 ≤ 100，注册一次拿到 `package_id`+`signature`；
- 单文件 HTML 用上面 §4 的 `fetch` 内核取数，把 `outputs` 映射到你自己的 DOM/SVG 即可本地直接打开渲染，数据自动保鲜。

> 产出变量名（如 `AG_ret`）只是 key，中文名 / 板块 / 单位等展示元数据由前端自己维护一份清单来映射。
