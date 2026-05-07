# fast_query — 快速查询（单次合并接口）

一次调用完成资产解析 + 字段解析 + 公式执行 + 取值。  
适用：≤3 资产，标准字段，行情/估值/财务标量、固定区间序列或短窗序列。
**不适用**：选股、回测、行业聚合、事件研究、≥4 资产、K线。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `assets` | ✅ | 1~3 个资产，中文名/代码均可 |
| `query_type` | ✅ | `"snapshot"`最新行情 / `"window"`近N日序列 / `"report"`最近报告期财务（仅A股） |
| `fields` | ✅ | 字段意图数组，见下方白名单 |
| `window_days` | window必填 | 1~60 |
| `start_date` | ❌ | 固定日期范围起始日，格式 `YYYYMMDD`；仅 `snapshot` / `report` 可用 |
| `end_date` | ❌ | 固定日期范围结束日，格式 `YYYYMMDD`；传入时必须同时传 `start_date` |
| `result_mode` | ❌ | `"value"` / `"series"`，默认 `"value"`；仅固定日期范围场景需要显式传 `"series"` |

`options.partial_ok` 默认 true（部分失败仍返回其余结果）。

日期范围规则：
- `snapshot` / `report` 可传 `start_date` + `end_date`。
- 只传 `end_date` 会返回 `MISSING_START_DATE`。
- `start_date > end_date` 会返回 `INVALID_DATE_RANGE`。
- `window` 不能传 `start_date` / `end_date`，否则返回 `DATE_RANGE_WINDOW_CONFLICT`。
- `result_mode="value"` 返回区间最后有效值；`result_mode="series"` 返回区间完整序列。

## fields 白名单（直接命中，零额外开销）

**行情**（snapshot/window）：`收盘价` `开盘价` `最高价` `最低价` `收盘价（不复权）` `涨跌幅` `成交额` `成交量`  
英文：`close` `open` `high` `low` `pct_change` `回报率` `amount` `volume`

**估值**（仅A股，snapshot）：`PE` `PE_TTM` `市盈率TTM` `PB` `市净率` `PS_TTM` `市销率` `总市值` `流通市值` `换手率` `股息率`  
英文：`market_cap` `turnover` `dividend_yield`

**财务**（仅A股，report）：`营业收入` `净利润` `归母净利润` `营业成本` `总资产` `净资产` `ROE` `净利率`  
现金流：`经营现金流`（别名：`operating_cashflow`）  
　　　　`投资活动现金流`（别名：`investing_cashflow`）  
　　　　`筹资活动现金流`（别名：`financing_cashflow`）  
英文：`revenue` `net_profit` `cogs` `total_assets` `equity` `roe`

**派生**（服务端自动计算）：`资产负债率` `毛利率`（英文：`debt_ratio` `gross_margin`）

不在白名单 → 服务端自动调 confirmDataMulti 解析（+2s）；无法解析则 FIELD_UNRESOLVABLE。

## 返回结构（关键字段）

`result_mode="value"`（默认，含最新快照 / 最近报告期 / 固定区间最后有效值）：

```
success / query_type
results[]:
  asset_name / ticker
  fields[]: intent / value / unit / date / date_type
  field_errors[]
asset_errors[] / field_errors[] / date_warnings[]
meta: query_time_ms / partial_ok
```

`result_mode="series"` 或 `query_type="window"`：

```
success / query_type
results[]:
  asset_name / ticker
  fields[]: intent / series[] / unit / date_type
  field_errors[]
asset_errors[] / field_errors[] / date_warnings[]
meta: query_time_ms / partial_ok
```

`series[]` 结构为 `[{"date": "YYYY-MM-DD", "value": number}, ...]`，按日期升序。

## 错误处理

| Layer | 触发 | 处理 |
|---|---|---|
| 1 | 参数不合法（整体拒绝） | 退出 fast path，走完整链路 |
| 1 MISSING_START_DATE | 只传 `end_date` 未传 `start_date` | 退出 fast path，走完整链路 |
| 1 INVALID_DATE_RANGE | `start_date > end_date` | 告知用户日期范围无效 |
| 1 DATE_RANGE_WINDOW_CONFLICT | `window` 同时传日期范围 | 改用 `snapshot/report + result_mode="series"` 或走完整链路 |
| 1 INVALID_RESULT_MODE | `result_mode` 非 `value/series` | 修正为合法值后再调用 |
| 2 | 资产无法识别 | 告知，其余资产继续 |
| 3 FIELD_UNRESOLVABLE | 字段不可解析 | 见下方恢复策略 |
| 3 FIELD_MARKET_MISMATCH | 字段不支持该市场 | 告知，其余字段继续 |
| 4 | 数据为空/公式失败 | 告知该字段暂无数据 |

**FIELD_UNRESOLVABLE 恢复**（partial_ok: true）：保留已成功字段，仅对失败字段补 `confirmDataMulti` → `runMultiFormulaBatch`（公式：`"字段全名"*取出(资产名)`，**禁止 LAST() 语法**），不得重读任何 workflow .md。若 field_error 带 `fallback_hint`，按其操作。

## ⚠️ 注意

- **须先调 newSession**：每轮新问题都应先调 `newSession` 建立 session，`user_query` 再随 `fast_query` 参数一并传入
- **涨跌幅**：返回值已是百分比数（如 `-2.74`），直接加 `%`，不再乘 100
- **总市值/流通市值**：单位已是亿元
- **result_mode**：默认 `value`；需要固定区间完整序列时才传 `result_mode="series"`
- **window series**：已按日期升序，长度 = window_days；`window` 不传 `result_mode`，也不能传 `start_date/end_date`
