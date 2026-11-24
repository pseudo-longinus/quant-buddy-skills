# fast_query_option_minute — 国内期货/股指/ETF期权槽位1分钟行情

后端 `POST /skill/fastQueryOptionMinute`。优先直接调用同名原生工具；没有原生绑定时沿用 `scripts/call.py fast_query_option_minute @params.json`。

## 职责与支持标的

本工具返回**国内期权 8 个槽位**（`E1/E2 × ATM-CALL/ATM-PUT/25C/25P`）对应的原始 1 分钟 bar（OHLCVA + 持仓量 + `self_iv` + `self_delta`），并支持按需附带同区间/同槽位的合约映射与换约信息。

- **标的传连续代码或品种名（不传具体月份期货或期权合约）**：
  - **国内商品期货期权**：SHF / DCE / CZC / INE / GFE 80 个商品品种（如 `螺纹钢` / `RB.SHF`、`AU.SHF`、`M.DCE`、`LC.GFE`），次主力 `_S.` 自动归一为连续品种代码。
  - **国内股指期权（3 个）**：`IF.CFE`（沪深 300 / `IO`）、`IH.CFE`（上证 50 / `HO`）、`IM.CFE`（中证 1000 / `MO`）。
  - **国内 ETF 期权（3 个）**：`SH510500`（中证 500ETF 南方）、`SH588000`（科创 50ETF 华夏）、`SZ159915`（创业板 ETF 易方达）。
- **与标的行情分钟接口隔离**：同一个 `RB.SHF` / `IF.CFE` / `SH510500` 在 `fast_query_minute*` 查的是期货或 ETF 现货本身；在本工具查的是对应的**期权槽位分钟行情**。
- **与 `query_option_contracts` 的关系**：只查合约身份/换约用 `query_option_contracts`；查期权分钟行情用本工具，若需同时关联换约与真实合约，直接传 `include_contracts: true`。

> 股指与 ETF 期权在 `skill_server` 准入层已默认放行；若后台数据服务尚未开放对应标的，会返回 `UPSTREAM_UNDERLYING_NOT_YET_SUPPORTED`（不扣 RU），待后台上线后自动生效。

## 参数

| 参数 | 合同 |
|---|---|
| `asset` / `assets` / `market` | 必须且只能选一个。`asset` 为单个名称/简称/代码；`assets` 为 1～500 项数组；`market` 支持 `cn_commodity_option` / `cn_index_option` / `cn_etf_option` / `cn_option_all` |
| `slots` | 可选，1～8 个不重复合法槽位：`E1-ATM-CALL`、`E1-ATM-PUT`、`E1-25C`、`E1-25P`、`E2-ATM-CALL`、`E2-ATM-PUT`、`E2-25C`、`E2-25P`（禁用下划线写法）；省略查全部 8 槽 |
| `date_mode` | `current_trade_day`（不传 `start_date` 时默认）/ `rolling` / `absolute`（传 `start_date` 时默认） |
| `start_date` / `end_date` | 仅 `absolute`；`start_date` 必填，`end_date` 默认同日；`YYYY-MM-DD` 或 `YYYYMMDD`，含首尾最多 **373 自然日** |
| `lookback_trade_days` | 仅 `rolling`，1～373 整数，默认 1，按中国交易日历取已完成交易日 |
| `end_trade_offset` | 仅 `rolling`，-372～0 整数，默认 0=最近已完成且过收盘缓冲期（15:45）的交易日 |
| `start_minute` / `end_minute` | 可选，日内过滤窗口（含边界）；`HH:MM` 或 `HHMM` 整数/字符串；`null` 不限，`0`=00:00。反向窗口（如 `21:00`～`02:30`）仅支持含夜盘商品品种 + `Asia/Shanghai`，纯无夜盘标的（股指/ETF/无夜盘商品）禁止反向窗口 |
| `timezone` | 默认 `Asia/Shanghai`，仅过滤分钟，不改变 `trade_date` 归属（国内有夜盘商品 21:00 起夜盘归属下一交易日） |
| `include_contracts` | 可选布尔值，默认 `false`；为 `true` 时并发附带同区间/同槽位真实合约与换约信息（单次最多 10 个标的，禁止与 `market` 同传） |
| `contracts_mode` | 仅 `include_contracts: true` 时允许；`changes`（默认：首条基准 + 换约/空槽变化）或 `daily`（逐日完整映射） |

禁止 `tickers`、`fields`、`format` 及其他未知参数；服务端根据 `标的数 × 槽位数 × 交易日数` 预估规模自动决定内联 JSON 或 CSV。

```json
{"asset": "螺纹钢", "slots": ["E1-ATM-CALL", "E1-25C"], "date_mode": "current_trade_day", "include_contracts": true}
```

```json
{"assets": ["RB.SHF", "AU.SHF"], "slots": ["E1-ATM-CALL", "E1-ATM-PUT"], "date_mode": "rolling", "lookback_trade_days": 3, "start_minute": "21:00", "end_minute": "02:30"}
```

```json
{"assets": ["IF.CFE", "SH510500"], "slots": ["E1-ATM-CALL", "E1-25C", "E1-25P"], "date_mode": "absolute", "start_date": "2026-11-10", "end_date": "2026-11-19"}
```

## 返回与口径

先检查 HTTP 状态和外层 `code === 0`。业务结果在 `data` 中：

- **统一 13 列结构**（无论单标的/多标的，JSON 与 CSV 均对齐）：
  `trade_date, ticker, slots, timestamp, open, high, low, close, volume, amount, open_interest, self_iv, self_delta`
- **合槽规则**：同一真实期权合约同时被多个槽位选中时，同一分钟**只返回一行**，`slots` 列逗号合并（如 `"E1-25C,E2-25C"`）。按槽位画图可拆开归属，统计总成交量时不要对合并行重复累加。
- **不复权、不补齐、不填零**：
  - `self_iv` / `self_delta` 为分钟收盘价口径自算值，无解或无同步标的价时为 `null`，不能填 0 或当成盘口 mid IV；
  - 国内期权分钟不做历史回补，空槽、无成交或早于采集起点的区间返回 `empty: true` + `EMPTY_WINDOW` warning，不代表服务故障；
  - 换约前后价格差不等于持有同一合约收益。
- **`option_contracts`（仅 `include_contracts: true`）**：返回 `{mode, by_ticker, errors?}`；部分或全部标的选约失败/上游暂未开放时，主行情仍完整保留，仅附 `OPTION_CONTRACTS_UNAVAILABLE` warning，不能把失败当成“无换约”。
- **`mode === "csv"`**：返回 `url`、`url_expires_at`、`shape`、`file_size`，沿用统一长表消费脚本：

```bash
python scripts/fetch_minute_range_csv.py @output/option-minute-response.json --output output/option-minute-data.json
```

## 错误与活页授权

- `UPSTREAM_UNDERLYING_NOT_YET_SUPPORTED`（400）：上游暂未开放该类标的（如股指/ETF 尚未上线），不扣 RU。
- `HISTORICAL_REALTIME_MIXED_NOT_ALLOWED`（400）：多日绝对区间混含历史日与盘中/收盘缓冲日，拆为 `rolling` 和 `current_trade_day` 两次请求。
- `CROSS_DAY_WINDOW_NOT_ALLOWED`（400）：对纯无夜盘标的（股指/ETF/无夜盘商品）传了反向夜盘窗口。
- `CONTRACTS_ASSET_LIMIT_EXCEEDED`（400）：`include_contracts: true` 时标的数超过 10 个或与 `market` 同传。
- **QBV 动态活页授权**：使用同名 `kind: "fast_query_option_minute"`，注册强制真实试跑，冻结标准 `tickers`、`slots`、日期规则与 `include_contracts`，`rolling`/`current_trade_day` 每次刷新动态解析，详见 QBV `tools/data_grant.md`。
