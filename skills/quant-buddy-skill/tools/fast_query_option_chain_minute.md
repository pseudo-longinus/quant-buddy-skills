# fast_query_option_chain_minute — 国内期货/股指/ETF期权链分钟行情

后端 `POST /skill/fastQueryOptionChainMinute`。优先直接调用同名原生工具；没有原生绑定时沿用 `scripts/call.py fast_query_option_chain_minute @params.json`。

## 职责与支持标的

查询国内商品期货、3 个股指（`IF.CFE`/`IH.CFE`/`IM.CFE`）和 3 个 ETF（`SH510500`/`SH588000`/`SZ159915`）期权链中**指定若干合约（多腿策略）或动态筛选局部链**的 1 分钟行情快照。

- 先查合约列表/T型报价请用 [query_option_chain](query_option_chain.md)；查 8 槽位连续分钟请用 [fast_query_option_minute](fast_query_option_minute.md)。

## 参数与分级保护

两种合约范围模式**互斥二选一**，日期上限随范围分级：

| 模式 | 参数 | 合约上限 | 最大日期跨度 |
|---|---|---|---|
| **精准合约模式** | `contracts`（如 `["IO2612C3850","IO2612P3850"]` 或 ETF `["10012629"]`） | 50 | **60 天 / 60 交易日** |
| **局部动态链模式** | 至少传 `expirations` / `expiry_ranks` / `strike_min..max` / `atm_strike_steps` 之一 | 逐日动态裁剪 | **10 天 / 10 交易日** |
| **整链全量模式** | 不传 `contracts` 且无任何到期日/行权价过滤 | 全链 | **1 天 / 1 交易日** |

| 参数 | 合同 |
|---|---|
| `asset` | 必填，单个国内期权标的名称、简称或代码（用于主键剪枝与夜盘判定；具体期权合约请放 `contracts`） |
| `contracts` | 1～50 个不重复具体合约代码；与所有链筛选参数互斥 |
| `expirations` / `expiry_ranks` | 互斥，1～12 个精确到期日或相对到期月序号（`1`=最近到期月） |
| `call_put` | 可选 `"C"` / `"P"`（兼容 `"call"` / `"put"`） |
| `strike_min` / `strike_max` | 可选正数行权价区间（含），与 `atm_strike_steps` 互斥 |
| `atm_strike_steps` | 可选 `1～20` 整数，按交易日逐日以 `forward` 为中心上下各取 N 档行权价（活页长期滚动推荐） |
| `active_only` | 可选 boolean，默认 `false`；动态链模式下过滤当日全天无成交且无持仓合约 |
| `date_mode` | `current_trade_day`（不传 `start_date` 默认）/ `rolling` / `absolute`（传 `start_date` 默认） |
| `start_date` / `end_date` | 仅 `absolute`；`start_date` 必填，`end_date` 默认同日 |
| `lookback_trade_days` / `end_trade_offset` | 仅 `rolling`；`lookback_trade_days` 默认 `1`（上限按上表分级），`end_trade_offset` 为 `-372～0` 默认 `0` |
| `start_minute` / `end_minute` | 可选日内 `HH:MM` 或 `HHMM`（含边界）；反向跨零点（如 `21:00～02:30`）仅支持含夜盘商品 + `Asia/Shanghai` |
| `timezone` | 可选 IANA 时区，默认 `Asia/Shanghai` |

禁止 `assets`、`tickers`、`market`、`slots`、`fields`、`format` 及其他未知参数；大结果由服务端自动切换 CSV。

```json
{"asset": "IF.CFE", "contracts": ["IO2612C3850", "IO2612P3850"], "date_mode": "rolling", "lookback_trade_days": 5}
```

```json
{"asset": "SH510500", "date_mode": "current_trade_day", "expiry_ranks": [1], "atm_strike_steps": 2, "start_minute": "14:00", "end_minute": "15:00"}
```

## 返回与口径

检查 HTTP 200 且外层 `code === 0`，业务结果在 `data` 中：

- **统一 16 列扁平结构**（JSON 与 CSV 完全一致，单次调用即可直接区分 ETF/商品/股指的到期日、行权价与认购认沽）：
  `trade_date, contract_id, expiration, strike, option_type, timestamp, open, high, low, close, volume, amount, open_interest, forward, self_iv, self_delta`
- **JSON 模式**：`{ticker, start_date, end_date, mode: "json", columns, data}`（无多余嵌套字段，按 `trade_date, contract_id, timestamp` 升序）。
- **CSV 模式**（超 5 万行或 5MB 自动切换）：`{ticker, start_date, end_date, mode: "csv", shape, file_size, url, url_expires_at}`，沿用长表消费脚本：

```bash
python scripts/fetch_minute_range_csv.py @output/option-chain-minute-response.json --output output/option-chain-minute-data.json
```

- **数据口径**：仅返回表内真实采集的 1m 快照，不补齐、不前填、不复权；`self_iv`/`self_delta` 无解为 `null`。历史日与当日盘中混合多日区间会返回 `HISTORICAL_REALTIME_MIXED_NOT_ALLOWED`，需拆为 `rolling` 与 `current_trade_day`。
- **QBV 动态活页授权**：使用 `kind: "option_chain_minute"`，长期活页推荐用 `expiry_ranks` + `atm_strike_steps` 避免合约到期后数据为空，详见 QBV `tools/data_grant.md`。
