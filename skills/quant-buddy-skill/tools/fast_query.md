# fast_query — 快速查询（单次合并接口）

一次调用完成资产解析 + 字段解析 + 公式执行 + 取值。  
适用：≤1000 资产，标准字段，行情/估值/财务标量、固定区间序列或窗口序列；期货仅尝试行情字段，是否可得以工具返回为准。
**不适用**：选股、回测、行业聚合、事件研究、K线、开放式个股指标画像或全维度指标概览（此类走 `stockProfile`）；期货估值/财务/K线不在本接口承诺范围内。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `assets` | ✅ | ≤1000 个资产，中文名/代码均可 |
| `query_type` | ✅ | `"snapshot"`最新行情 / `"window"`近N日或固定区间序列 / `"report"`最近报告期财务（A/US/HK 部分字段，以返回为准） |
| `fields` | ✅ | 字段意图数组，见下方白名单 |
| `window_days` | ❌ | 1~2500，`window` 模式可用；与 `start_date`/`end_date` 二选一（同时传时优先使用日期范围） |
| `start_date` | ❌ | 固定日期范围起始日，格式 `YYYYMMDD` / `YYYY-MM-DD`；三种 `query_type` 均可用 |
| `end_date` | ❌ | 固定日期范围结束日，同格式；不传时默认当天 |
| `result_mode` | ❌ | `"value"` / `"series"`，默认 `"value"`；`snapshot`/`report` 固定日期范围需要完整序列时传 `"series"`，`window` 固定返回序列无需传 |

`options.partial_ok` 默认 true（部分失败仍返回其余结果）。

日期范围规则：
- 三种 `query_type` 均可传 `start_date` + `end_date`；`window` 模式中与 `window_days` 二选一，同时传时优先使用日期范围。
- `snapshot`/`report` 仅传 `end_date` 时自动补齐 `start_date = end_date`；`result_mode=series` 且未传 `start_date` 时报 `MISSING_START_DATE`。
- `start_date > end_date` 会返回 `INVALID_DATE_RANGE`。
- 日期早于系统最早数据日期 `20050104` 会返回 `DATE_BEFORE_SYSTEM_LIMIT`。
- `result_mode="value"` 返回区间最后有效值；`result_mode="series"` 返回区间完整序列。

## 日内刷新行为

- **`snapshot` 模式（不传 `start_date`）**：行情字段（收盘价/涨跌幅/成交额等）自动启用日内刷新（等效后端 `use_minute_data: true`）。  
  - 盘中：返回最后一分钟更新值（实时行情）  
  - 收盘后：返回当日收盘价（与日线一致）  
  - 历史数据不受影响
- **`snapshot` + `start_date` 模式** / **`window` 模式**：不启用分钟刷新，只取日线数据。
- 估值字段（PE/PB/市值等）及财务字段始终为日线口径，不受分钟刷新影响。

## fields 白名单（直接命中，零额外开销）

**行情**（snapshot/window）：`收盘价` `开盘价` `最高价` `最低价` `收盘价（不复权）` `涨跌幅` `成交额` `成交量`  
英文：`close` `open` `high` `low` `pct_change` `回报率` `amount` `volume`

**估值**（snapshot/window）：
- A/US/HK 均支持（TTM〔估值数据〕，日频）：`PE` `PE_TTM` `市盈率TTM` `PB` `市净率` `PS_TTM` `市销率` `股息率` `PCF` `市现率` `PCF_现金净流量`（港美股自动映射到对应市场的 TTM 估值数据）
- 仅 A 股：`总市值`（英文：`market_cap`，亿元）`流通市值` `换手率`（英文：`turnover`）——港股/美股查询这些字段返回 `FIELD_MARKET_MISMATCH`
- A/US/HK 均支持（港美股专用单季口径）：`PE_单季` `PB_单季` `PS_单季` `股息率_单季`（显式查询季频数据时使用）
- PE（静态）：A 股用静态 PE，港美股自动映射到 TTM 版（HK/US 无静态 PE）

**财务**（report，所有财务字段统一返回**单季**数据，A/US/HK 一致）：
- A/US/HK 均支持：`营业收入` `净利润` `归母净利润` `营业成本` `总资产` `净资产` `ROE`（`roe`）`净利率` `毛利率`（`gross_margin`）；现金流：`经营现金流`（`operating_cashflow`）`投资活动现金流`（`investing_cashflow`）`筹资活动现金流`（`financing_cashflow`）；英文：`revenue` `net_profit` `cogs` `total_assets` `equity`

**派生**（服务端自动计算，A/US/HK 均支持）：`资产负债率`（英文：`debt_ratio`，公式：`(总资产 - 净资产) / 总资产 × 100`）

不在白名单 → 服务端自动调 confirmDataMulti 解析（+2s）；无法解析则 FIELD_UNRESOLVABLE。

## 限流

| 维度 | 上限 | 错误码 |
|------|------|--------|
| 最大资产数 | 1,000 | `ASSETS_EXCEED_LIMIT` |
| 最大交易日数 | 2,500 | `WINDOW_DAYS_EXCEED_LIMIT` / `DATE_RANGE_EXCEED_LIMIT` |
| 单次最大数据点 | 200,000 | `DATA_POINTS_EXCEED_LIMIT` |
| 每日数据点（用户级） | 1,000,000 | `DAILY_DATA_POINTS_EXCEEDED` |
| 每日 CSV 下载 | 50 次 | `DAILY_CSV_DOWNLOADS_EXCEEDED` |

数据点 = 资产数 × (日频字段数 × 日频日期数 + 季频字段数 × 季频日期数)。超过 500 数据点自动切换 CSV 格式返回。

## 返回结构（compact 格式，默认）

顶层公共信息：
```
success / query_type
fields_meta: { 字段名: {unit, date_type} }   ← 每个字段的单位和日期类型，只声明一次
meta: query_time_ms / latest_trade_date / partial_ok
```

`result_mode="value"`（默认）— 表格化字典：
```
dates: { trade_date: "YYYY-MM-DD", report_period: "YYYY-MM-DD" }   ← 公共日期按 date_type 提升
results: {
  "资产名": { ticker, 字段1: 值, 字段2: 值, ... }   ← 日期已提升时直接是数字
}
```
若字段日期与公共日期不同（fallback 等），该字段值为 `{v: 数值, d: "日期", fallback: true}`。

`result_mode="series"` 或 `query_type="window"` — 列式存储：
```
results: {
  "资产名": {
    ticker,
    dates: ["YYYY-MM-DD", ...],           ← 共享日期轴（多数字段共用）
    字段1: [值, 值, ...],                   ← 与 dates 等长的值数组
    字段2: [值, 值, ...],
    字段3: { dates: [...], values: [...] }  ← 日期轴不同的字段各自带 dates+values
  }
}
```

非空时才出现的字段：`asset_errors[]` / `field_errors[]` / `warnings[]`（空时省略）。

## 返回结构 — CSV 模式（数据点 > 500 时自动触发）

当数据点超过 500，服务端自动切换 CSV 格式。返回结构变为：

```
success: true
query_type / mode: "csv"
csv_fields: [
  { intent: "收盘价", index_title: "...", csv_url: "https://...", csv_expires_at: "...", tickers: [...] },
  ...
]
summary: {
  total_data_points: 156468,
  assets: ["贵州茅台", ...],
  fields: ["收盘价", ...],
  csv_count: 5
}
asset_errors / field_errors / warnings
```

处理规则：
- 检查 `mode` 字段：若为 `"csv"`，按 CSV 模式处理
- 向用户汇报 `summary`（资产数、字段数、总数据点数）
- 展示 `csv_fields[].csv_url` 供用户下载（链接有过期时间）
- **禁止**在对话中逐行展开 CSV 内容
- 若用户追问具体数值，建议下载 CSV 查看

## 错误处理

| Layer | 触发 | 处理 |
|---|---|---|
| 1 | 参数不合法（整体拒绝） | 退出 fast path，走完整链路 |
| 1 ASSETS_EXCEED_LIMIT | 资产数超过 1000 | 告知用户分批查询 |
| 1 WINDOW_DAYS_EXCEED_LIMIT | `window_days` 超过 2500 | 告知用户缩小范围 |
| 1 DATE_RANGE_EXCEED_LIMIT | 日期范围估算超过 2500 交易日 | 告知用户缩小范围 |
| 1 DATA_POINTS_EXCEED_LIMIT | 预估数据点超过 200,000 | 告知用户减少资产/字段/日期 |
| 1 DAILY_DATA_POINTS_EXCEEDED | 今日累计数据点超过 1,000,000 | 告知用户明天再试 |
| 1 DAILY_CSV_DOWNLOADS_EXCEEDED | 今日 CSV 下载次数超过 50 | 告知用户明天再试或缩小查询 |
| 1 MISSING_START_DATE | `result_mode=series`（非 window）且未传 `start_date` | 补传 `start_date` 或改用 `window` 模式 |
| 1 INVALID_DATE_RANGE | `start_date > end_date` | 告知用户日期范围无效 |
| 1 DATE_BEFORE_SYSTEM_LIMIT | 日期早于 `20050104` | 告知用户调整日期范围 |
| 1 INVALID_RESULT_MODE | `result_mode` 非 `value/series` | 修正为合法值后再调用 |
| 2 | 资产无法识别 | 告知，其余资产继续 |
| 3 FIELD_UNRESOLVABLE | 字段不可解析 | 见下方恢复策略 |
| 3 FIELD_MARKET_MISMATCH | 字段不支持该市场（如港/美股请求总市值/流通市值/换手率等仅 A 股字段） | 告知用户该字段仅支持 A 股；其余字段继续 |
| 4 | 数据为空/公式失败/派生字段计算失败（`DERIVED_COMPUTE_FAILED`） | 告知该字段暂无数据 |

**FIELD_UNRESOLVABLE 恢复**（partial_ok: true）：保留已成功字段，仅对失败字段补 `confirmDataMulti` → `runMultiFormulaBatchStream`（公式：`"字段全名"*取出(资产名)`，**禁止 LAST() 语法**），不得重读任何 workflow .md。若 field_error 带 `fallback_hint`，按其操作。

## ⚠️ 注意

- **须先调 newSession**：每轮新问题都应先调 `newSession` 建立 session，`user_query` 再随 `fast_query` 参数一并传入
- **涨跌幅**：返回值已是百分比数（如 `-2.74`），直接加 `%`，不再乘 100
- **总市值/流通市值**：单位已是亿元
- **result_mode**：默认 `value`；需要固定区间完整序列时才传 `result_mode="series"`
- **window series**：已按日期升序；`window` 可传 `window_days`，也可传 `start_date/end_date` 固定日期范围（二选一）。`window` 固定返回序列，不需要传 `result_mode`。
