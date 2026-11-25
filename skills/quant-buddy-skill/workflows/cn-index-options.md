# 国内股指及ETF期权槽位行情

适用于数据覆盖咨询，以及以下股指和ETF的期权价格、IV、持仓量、成交额查询。先读 `global-rules.md`；实际平台查询前遵守 `newSession / beginTurn`。

## 已有数据范围

`国内期货期权-*` 是数据集名称，其资产维度包含部分商品及以下三种股指期权、三种ETF期权。ETF期权与股指期权分别计数，即使追踪同一指数也不能互相替代。

| 股指标的 | 数据列名称 | 数据列 ticker | 期权品种代码 |
|---|---|---|---|
| 沪深300 | 沪深300主连 | IF.CFE | IO |
| 上证50 | 上证50主连 | IH.CFE | HO |
| 中证1000 | 中证1000主连 | IM.CFE | MO |

列名沿用平台连续品种维度，不表示股指期权以该期货合约为法律标的。期权品种代码 IO/HO/MO 不得替换为数据列代码；未确认的其他标的不要自行加入覆盖范围。

| ETF期权标的 | 数据列名称 | 数据列 ticker |
|---|---|---|
| 南方中证500ETF | 中证500ETF南方 | SH510500 |
| 华夏科创50ETF | 科创50ETF华夏 | SH588000 |
| 易方达创业板ETF | 创业板ETF易方达 | SZ159915 |

同一个 ETF 代码也用于查询 ETF 现货；用数据集或工具区分请求。ETF 现货日线走 `fast_query`，1分钟行情走 `fast_query_minute` 或对应的历史分钟接口。ETF 期权日频槽位行情走 `国内期货期权-*` 数据集；现货分钟行情不能证明期权合约分钟行情可查。

目录 [cn_future_option_market_data.yaml](../presets/index_info_catalog/cn_future_option_market_data.yaml) 列有 E1/E2 × ATM-CALL/ATM-PUT/25C/25P × 收盘价/隐含波动率/持仓量/成交额，共32项。例如精确标题 `国内期货期权-E1-25C-收盘价`、`国内期货期权-E1-25C-隐含波动率`。该数量是字段数，不是全合约数量，也不保证每标的、每槽、每日都有有效值。

## 槽位口径

日频槽位记录每日按规则选出的真实期权合约行情。同一槽位对应的合约可能随日期变化，且可能空缺。例如，`E1-25C-隐含波动率` 是 E1 选约层级下、Delta 约为 0.25 的代表认购合约当天的 IV；没有实际映射时不猜合约代码。`ATM-CALL/PUT` 对应接近平值的认购/认沽，`25P` 对应 Delta 绝对值约为 0.25 的认沽；E1/E2 的定义以源规则为准。

同一选约口径的日频序列可以跟踪波动率、持仓和成交活跃度；期限和口径可比时，可对照 25C 与 25P 的 IV 看偏斜。这样可持续比较代表位置，不必逐个查看行权价和到期月。对外解释沿用 [全局数据口径规则](global-rules.md#解释数据口径与用途)。

## 选择查询路径

- 要具体数值或时序：按用户所需字段检索目录，用 `confirmDataMulti` 确认精确标题与维度；股指期权的数据列检索 `presets/assets_db/future.yaml`；ETF 代码检索 `presets/assets_db/stock_a.yaml`。接口参数分别见 [confirmDataMulti](../tools/confirm_data_multi.md)、[readData](../tools/read_data.md)、[公式执行](../tools/run_multi_formula.md)。
- 二维数据可直接 `readData(range_data)`，使用本轮确认返回的实际数据 ID、资产标识和用户日期范围。需提取单标的、计算或交接动态页时，用已确认标题构造公式，例如 `中证1000_E1_25C_IV = "国内期货期权-E1-25C-隐含波动率" * 取出(中证1000主连)`；保留原执行合同与验证收据，不为已有原始字段套用普通行情 `fast_query` 白名单。ETF 可用已确认的数据列限定 `readData` 的 `assets`，例如 `assets:["SH510500","SH588000","SZ159915"]`。
- 仅指定标的、未指定期权 IV 口径时，可按实际需求对照多个可用槽位；需要一个确定值且无法从上下文判断时，再确认期限和槽位。不能把单槽 IV 当作整个标的的唯一 IV。
- 要期权槽位 1 分钟行情与分钟 `self_iv`/`self_delta`：直接走 [tools/fast_query_option_minute.md](../tools/fast_query_option_minute.md)（`fast_query_option_minute`），传标的连续代码（如 `RB.SHF`、`IF.CFE`）或 ETF 代码（如 `SH510500`），禁止用现货 `fast_query_minute*` 代替期权分钟。若上游尚未开放股指/ETF 分钟会返回 `UPSTREAM_UNDERLYING_NOT_YET_SUPPORTED`，如实报告即可。
- 要所选槽位的具体合约、到期日、行权价或换约：按 [合约映射工具](../tools/query_option_contracts.md) 判断（或在 `fast_query_option_minute` 中传 `include_contracts: true`）。当前 Skill 公共合约映射未开放股指和 ETF 时仅报告该接口边界，不能撤销已存在的行情数据。
- 要“完整期权链”（T 型报价、某到期月/行权价清单、具体期权合约分钟或日内波动率微笑）：走 [tools/query_option_chain.md](../tools/query_option_chain.md)（`query_option_chain`，返回合约列表与最新/指定时刻截面，并叠加同日 `slots` 槽位标识，ETF 自动带名称/除权系列/乘数）和 [tools/fast_query_option_chain_minute.md](../tools/fast_query_option_chain_minute.md)（`fast_query_option_chain_minute`，16 列自带 `expiration/strike/option_type`，支持精准合约和动态链裁剪）；仍不能用 8 个日频槽位替代全链，实际日期覆盖以实查为准。

## 结果与页面

保留实际行情日期、有效样本和缺口。self-IV 原始小数0.25显示为25%；价格、持仓量、成交额按本轮元数据说明单位，不猜单位。E1/E2不等于期货主力/次主力，拼接价变化不等于持有同一合约的收益。

画图、监控或明确建页时沿 `answer-first.md` 先答后交接 QBV。槽位行情使用经过 QBS 验证的公式合同登记 Formula Package；`option_contracts` Grant 只用于已开放的合约映射。标的/字段缺值只说明本轮缺口，不扩写为该类期权全部不支持。
