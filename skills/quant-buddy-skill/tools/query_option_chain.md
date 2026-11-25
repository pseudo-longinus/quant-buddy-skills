# query_option_chain — 国内期货/股指/ETF期权链合约列表与截面

后端 `POST /skill/queryOptionChain`。优先直接调用同名原生工具；没有原生绑定时沿用 `scripts/call.py query_option_chain @params.json`。

## 职责与支持标的

查询单标的某交易日的**完整期权链合约清单与最新（或指定时刻）截面行情**，并自动叠加同日 8 槽位标识（`slots` 列，未命中为 `null`）。适用于 T 型报价、合约发现、筛选活跃合约及查看各到期月/行权价分布。

- **支持标的**（传品种名、简称或连续代码，不传具体期权或月份期货合约）：
  - **国内商品期货期权**：SHF / DCE / CZC / INE / GFE 品种（如 `螺纹钢`/`RB.SHF`、`AU.SHF`、`LC.GFE`），次主力 `_S.` 自动归一。
  - **国内股指期权（3 个）**：`IF.CFE`（沪深 300 / `IO`）、`IH.CFE`（上证 50 / `HO`）、`IM.CFE`（中证 1000 / `MO`）。
  - **国内 ETF 期权（3 个）**：`SH510500`（中证 500ETF）、`SH588000`（科创 50ETF）、`SZ159915`（创业板 ETF）。
- **与 `fast_query_option_minute` / `query_option_contracts` 的分工**：
  - 查 8 槽位连续分钟行情用 `fast_query_option_minute`；查 8 槽位历史换约用 `query_option_contracts`；
  - 查全链合约列表、T 型报价截面用本工具；拉具体合约或局部链分钟 K 线用 [fast_query_option_chain_minute](fast_query_option_chain_minute.md)。

## 参数

| 参数 | 合同 |
|---|---|
| `asset` | 必填，单个标的名称、简称或代码（如 `"沪深300"`、`"RB.SHF"`、`"SH510500"`） |
| `date_mode` | `current_trade_day`（不传 `trade_date` 默认）/ `rolling` / `absolute`（传 `trade_date` 默认） |
| `trade_date` | `absolute` 必填，`YYYY-MM-DD` 或 `YYYYMMDD`；其他模式禁止传入 |
| `end_trade_offset` | 仅 `rolling` 允许，`-372～0` 整数，默认 `0` |
| `as_of_minute` | 可选 `HH:MM` 或 `HHMM`；省略取当日最新快照时刻，传值取不晚于该时刻各合约最近一次已存储快照（夜盘品种按夜盘→日盘会话顺序，避免部分分钟半写漏合约） |
| `timezone` | 可选 IANA 时区，默认 `Asia/Shanghai` |
| `expirations` / `expiry_ranks` | 互斥，全可选。`expirations` 为 1～12 个精确到期日；`expiry_ranks` 为 1～12 个相对到期月序号（`1`=最近到期月，**活页长期授权推荐**） |
| `call_put` | 可选 `"C"` / `"P"`（兼容 `"call"` / `"put"`），省略返回认购 + 认沽 |
| `strike_min` / `strike_max` | 可选正数行权价区间（含），与 `atm_strike_steps` 互斥 |
| `atm_strike_steps` | 可选 `1～30` 整数，以各到期日 `forward` 为中心上下各取 N 档行权价（大链品种如 `LC.GFE` 及活页推荐） |
| `active_only` | 可选 boolean，默认 `false`；`true` 时过滤成交量和持仓量均为 0 的合约 |
| `include_snapshot` | 可选 boolean，默认 `true`；`false` 时只返回合约静态列（不含行情列） |

禁止 `assets`、`tickers`、`market`、`slots`、`fields`、`format` 及其他未知参数。

```json
{"asset": "沪深300", "date_mode": "current_trade_day", "expiry_ranks": [1, 2], "atm_strike_steps": 5}
```

```json
{"asset": "SH510500", "trade_date": "2026-11-24", "expiry_ranks": [1], "active_only": true}
```

```json
{"asset": "螺纹钢", "trade_date": "2026-11-24", "as_of_minute": "14:45", "include_snapshot": false}
```

## 返回与口径

检查 HTTP 200 且外层 `code === 0`，业务结果在 `data` 中，结构精简扁平：

```json
{
  "ticker": "IF.CFE",
  "trade_date": 20261124,
  "timestamp": 1795503540,
  "expirations": [20261218, 20270115, 20270219],
  "columns": [
    "contract_id", "underlying_contract", "expiration", "strike", "option_type", "slots",
    "close", "volume", "amount", "open_interest", "forward", "self_iv", "self_delta"
  ],
  "data": [...]
}
```

- **列集合自适应**：
  - 商品/股指：`include_snapshot: true` 为上述 13 列；`false` 为前 6 列（`contract_id` 到 `slots`）。
  - **ETF 期权**：在 `option_type` 后自动增加 `product_name`、`adjustment_series`（标准 `M` vs 除权调整 `A/B`）、`contract_multiplier` 3 列（共 16 列；静态 9 列）。做 ETF T 型报价须结合 `adjustment_series` 区分标准合约与除权调整合约。
- **`slots` 槽位标识**：严格按同日 `cn_future_option_slot_assignment` 最新 `active` 批次叠加；命中多槽按标准槽序逗号拼接（如 `"E1-ATM-CALL,E1-25C"`），未命中或当日尚未入库选约返回 `null`（不跨日回退旧选约）。
- **数据口径**：按库内真实采集的 1m 快照返回，不补齐、不前填；无异常降级时不返回 `warnings`。
- **QBV 动态活页授权**：使用 `kind: "option_chain"`，推荐配合 `date_mode: "current_trade_day"` + `expiry_ranks` + `atm_strike_steps` 实现换月与价格变动自动滚动，详见 QBV `tools/data_grant.md`。
