# fast_query — 快速查询（单次合并接口）

一次调用完成资产解析 + 字段解析 + 公式执行 + 取值。  
适用：≤3 资产，标准字段，行情/估值/财务标量或短窗序列。  
**不适用**：选股、回测、行业聚合、事件研究、≥4 资产、K线。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `assets` | ✅ | 1~3 个资产，中文名/代码均可 |
| `query_type` | ✅ | `"snapshot"`最新行情 / `"window"`近N日序列 / `"report"`最近报告期财务（仅A股） |
| `fields` | ✅ | 字段意图数组，见下方白名单 |
| `window_days` | window必填 | 1~60 |

`options.partial_ok` 默认 true（部分失败仍返回其余结果）。

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

```
success / query_type
results[]:
  asset_name / ticker
  fields[]: intent / value（snapshot/report）/ series[]（window）/ unit / date / date_type
  field_errors[]
asset_errors[] / field_errors[] / date_warnings[]
meta: query_time_ms / partial_ok
```

## 错误处理

| Layer | 触发 | 处理 |
|---|---|---|
| 1 | 参数不合法（整体拒绝） | 退出 fast path，走完整链路 |
| 2 | 资产无法识别 | 告知，其余资产继续 |
| 3 FIELD_UNRESOLVABLE | 字段不可解析 | 见下方恢复策略 |
| 3 FIELD_MARKET_MISMATCH | 字段不支持该市场 | 告知，其余字段继续 |
| 4 | 数据为空/公式失败 | 告知该字段暂无数据 |

**FIELD_UNRESOLVABLE 恢复**（partial_ok: true）：保留已成功字段，仅对失败字段补 `confirmDataMulti` → `runMultiFormula`（公式：`"字段全名"*取出(资产名)`，**禁止 LAST() 语法**），不得重读任何 workflow .md。若 field_error 带 `fallback_hint`，按其操作。

## ⚠️ 注意

- **无需 newSession**：服务端管理固定 session
- **涨跌幅**：返回值已是百分比数（如 `-2.74`），直接加 `%`，不再乘 100
- **总市值/流通市值**：单位已是亿元
- **window series**：已按日期升序，长度 = window_days
