# 连续期货：换月、价格尺度与局部数据差异

使用国内主连/次主连或海外期货主力连续做跨日、跨频、指标、回测或活页时读取。国内主力如 `A.DCE`，次主力如 `A_S.DCE`；外盘主力如 `ES.CME`、`HG.CMX`、`TU.CBT`，仅 `rank=1`，不将外盘 `_S` 或具体月份合约当作主连。先确认字段口径，再完成用户任务；局部缺失与跨频差异按下述影响范围处理。

**海外期货日频拼接与换月覆盖边界（2026-11-20 对齐）**：
- 平台已对 **53 个**海外期货主力连续（ClickHouse `os_future_daily_bar`，`rank=1`）的日频价格（`全市场每日收盘价`等）实施**比例前复权**，分为两类（其余未迁移外盘仍走旧源且不复权）：
  1. **14 个自有分钟聚合品种**（`ES.CME`、`NQ.CME`、`MES.CME`、`MNQ.CME`、`RTY.CME`、`GC.CMX`、`HG.CMX`、`SI.CMX`、`MGC.CMX`、`CL.NYM`、`NG.NYM`、`TY.CBT`、`FV.CBT`、`TU.CBT`）：日频由两段拼接而成——**自聚合起点起**（见 [分钟覆盖表](minute-data-coverage.md#外盘期货主力连续)，大多在 2016-10，其中 `TU.CBT` 2016-01-04、`HG.CMX` 2016-10-19、`RTY.CME` 2017-07-10、`MES/MNQ` 2019-05-06、`MGC.CMX` 2021-12-01）由自有分钟聚合生成，**具备对应换月事件与来源合约**；**早于自聚合起点的历史段**来自外部数据源，**没有对应的换月合约信息**。
  2. **39 个纯日频海外品种**（含 LME/IPE/NYB/EUX 及部分 CME/CBT/NYM）：早期为外部日线历史（无换月合约明细），2026-11 起接新日 K 后仅新段有来源合约；日频 `fast_query` 暂不提供 `future_context`。
- **无换月历史段只省略换月信息，日频行情数据照常返回**：上述 14 品种在日频 `fast_query` 中已与国内期货一样自动提供 `future_context`；早于自聚合起点的历史区间**日频行情数据仍按原请求正常完整返回，绝不因缺少换月信息而拒绝查询、裁剪窗口或丢弃行情**，只是不提供对应的换月/合约信息——整段早于起点时不返回 `future_context`，跨起点窗口仍返回全段日频行情、仅将 `roll_events.start_date` 截齐至起点并标注 `partial_coverage: true` / `unavailable_before`，跨起点多日期 `snapshot` 仅对起点及之后日期返回合约并标注 `unavailable_before`。其余 39 个纯日频及未迁移外盘品种同样正常返回日频行情，仅不附带 `future_context`。

## 新版换月事件

国内期货主连/次主连与 14 个自聚合外盘主力在 `fast_query` 中的 `future_context[ticker].roll_events`，以及国内/外盘分钟 `fast_query_minute_range` / 单资产 `fast_query_minute_range_multi` 的 `roll_events` 均保留服务端返回的 `columns + data`。新版列为：

```json
["decision_trade_date", "effective_trade_date", "old_contract", "new_contract", "old_close", "new_close"]
```

| 字段 | 含义 |
|---|---|
| `decision_trade_date` | 换月决策交易日，当日盘后确定换月；也是两条参考收盘价的实际取价交易日 |
| `effective_trade_date` | 换月生效交易日；国内为决策日下一交易日，从归属于此交易日的首根 bar 开始切换到新合约；外盘为包含换约时刻的 Chicago 会话日，同一 `effective_trade_date` 可能有多条不同换月事件，须保留返回顺序，不按日期去重 |
| `old_contract` / `new_contract` | 换月前后两条具体合约 |
| `old_close` / `new_close` | **决策日**旧、新合约各自的原始参考收盘价（未复权）；不冒充分钟成交价 |

事件窗口按 `effective_trade_date` 过滤，因此首条事件的决策日可以早于窗口起点。夜盘按行情 `trade_date` 归属（国内按国内交易日，外盘按 `America/Chicago` 会话日），不能按 UTC 或本地自然日截断。

按 `columns` 建立列名到索引的映射，不硬编码五列或固定位置，不把新字段改名、合并或丢弃。旧版五列事件中的 `trade_date` 表示生效日，可在内部作为 `effective_trade_date` 的兼容别名；旧版未返回决策日时，不用自然日减一伪造取价日。行情行及 `contract_info.contracts[].trade_date` 仍表示行情所属交易日，不应一律改名为决策日。

单日 `fast_query_minute` 仍只提供所选交易日和简洁 `contract_info`，不期待它返回事件表。外盘 RangeMulti 仅解析去重后单资产时在 `roll_events` 读取事件；多资产和 `market` 请求不附事件，缺事件不当作无换月。`inferred` 是基于已生效事件推导，不表示独立实时核验。

## 价格尺度和复权算法

国内期货与已迁移的 53 个海外主力连续在日频 `results` 中的连续价格字段（`收盘价/开盘价/最高价/最低价`）均为**比例前复权**价格（锚定最新有效发布日）；显式 `收盘价（不复权）` 为原始价格（其余未迁移海外品种仍为不复权）。分钟 OHLC 保留原始未复权报价，事件中的两个 `close` 也未复权。比较前必须统一尺度，不能仅因复权日价与原始分钟/参考价不相等就判定数据错误。

例如生效日 2025-11-13、决策日 2025-11-12，`old_close=945.76`、`new_close=948.74`：这两个数均为 11 月 12 日各自合约的原始收盘；它们不要求等于 11 月 13 日的日频收盘。不能仅凭数值相等或不同推断另一个字段是否复权，应以实际请求字段为准。

需要从原始分钟构造连续参考序列时，默认采用与平台日频一致的**比例复权（乘法）**。对每个有效换月事件 i（`old_close_i`、`new_close_i` 均有限且大于 0），事件按生效顺序排列，bar 所属位置为 t、切换生效点为 s_i：

- **前复权（默认，锚定最新段 A）**：`P_front(t) = P_raw(t) × ∏(new_close_i / old_close_i)`，仅乘入 `t < s_i <= A` 的事件。
- **后复权（锚定最早段 B）**：`P_back(t) = P_raw(t) × ∏(old_close_i / new_close_i)`，仅乘入 `B < s_i <= t` 的事件。

若某换月事件的 `old_close` 或 `new_close` 缺失、非有限或 ≤ 0，该接缝不适用比例法（不得填 1、取绝对值或静默切换加法法），须保留原始行情并披露受影响区间。保留原始 OHLC，另生成派生参考 OHLC 并标注算法、锚点与事件覆盖窗口；不覆盖原报价、不重复复权、不改成交量/持仓量。仅当用户明确要求价差平移口径时才使用加法价差（`jump_i = new_close_i - old_close_i`），二者不得混用。

前复权的最新段锚点以已取得的完整目标事件窗口为准；全历史后复权需覆盖起点之前所需的全部事件，不能把局部窗口事件当完整历史链。复现平台日频 `results` 时仍需匹配其发布锚点与独立历史段边界（例如国内 `FU.SHF` 2018-07-16、`WR.SHF` 2018-10-16 分段，以及海外 14 品种各自的自聚合起点）；不能未经核实就承诺分钟自算与日频严格相等。

换月日新开新平且未跨合约边界的交易可正常分析，不整日排除。跨月参考变化可以研究，真实账户损益需具体换仓报价、手数和成本；日频参考价不能冒充分钟成交价。历史参考重放可继续完成；实时信号仅在所用信息当时已可得时成立，决策日字段不是精确的首次发布时间。

## 日分钟对账的适用范围

- 正常构建的日线OHLC来自当天同一来源合约的统一口径，不是open用旧合约、close用新合约的混合拼接。
- 日线可能直接取供应商日线，也可能由原始分钟聚合；日频与分钟频来源/构建流程可能不同，不承诺等于当前对外连续分钟的重聚合结果。
- 日量等于分钟量之和，只在同来源口径、同实际合约、同交易日完整时段、无缺失/重复、单位及单/双边统计一致、版本一致时作为相等校验。条件未确认时，差异是待解释项，不直接判错。
- 当前代码直接传递供应商volume，未统一做单/双边除二转换；全部历史来源的单双边口径尚未独立核验。少数日期数值一致不能扩大为全历史保证。

## 局部问题默认非阻断

发现少量分钟缺失、端点差异、日分钟价格或量不齐时，记录受影响的日期、字段和计算路径，继续完成可用部分、首答和页面交付。不得自行把“跨频严格相等”加成用户任务的全局门禁，不因此删除全年数据、整段窗口或无限重查，也不必等待厂商答复才能继续不受影响的分析。

按任务依赖处理，而非按缺失条数一刀切：

| 情况 | 处理 |
|---|---|
| 量不齐，但任务只分析价格趋势 | 保留价格分析，披露量的来源差异；不阻断 |
| 个别分钟缺尾，日线来自独立有效日频结果 | 日频分析继续；分钟图标出缺口，不用最后现存分钟冒充正式日收盘 |
| 缺失bar恰好影响止损/目标是否先触发 | 仅该笔交易路径/收益标未知，继续其他可验证交易，并报告有效/未知数量 |
| 换月元信息缺失（含外盘早于自聚合起点的历史段），原始行情已成功 | 继续行情展示和不跨接缝的分析；明确标注该区间无换月合约记录，不把缺失当作无换月 |
| 所有核心输入都不可用，目标结果确实无法计算 | 明确说明无法完成的部分，并交付仍可完成的内容 |

原始缺口、null和端点行保留；不补0、不删端点凑量、不把缺失收益当0、不静默改策略参数或请求窗口。页面和回答简要披露有效范围、缺失及其实际影响，不把一般告警写成“整年数据不合格”或“任务失败”。

## 外盘换月返回入口（2026-11-20 更新）

外盘行情与换月事件为两个上游任务，`skill_server` 复用既有附加查询；客户端不添加开关，也没有新增名为 `fast_query_future_roll_events` 的公开 Skill 工具。

| 已有工具 | 外盘换月 / 合约字段 |
|---|---|
| `fast_query`（日频 window/series） | **14 个自聚合主力连续**在自聚合起点及之后返回 `future_context[ticker].roll_events`（结构与国内一致，不标 `data_frequency=minute`）。早于自聚合起点的历史段**日频行情照常返回，仅不提供换月信息**：整段早于起点时不返回 `future_context`；跨起点窗口仍返回全段行情，仅将 `roll_events.start_date` 截齐至起点并附 `partial_coverage: true`、`unavailable_before`。其余 39 个纯日频及未迁移外盘照常返回行情，仅不附 `future_context` |
| `fast_query`（日频 snapshot/value） | **14 个自聚合主力连续**按实际取值日期返回 `future_context[ticker].contract_info`；早于自聚合起点的日期**行情值照常返回**，仅省略对应合约信息（全部早于起点时不返回 `future_context`，部分省略时附 `unavailable_before`） |
| `fast_query_minute_range` | `data.roll_events`：原请求会话日区间内的分钟换月事件表，标注 `data_frequency=minute` |
| `fast_query_minute_range_multi`，解析去重后单资产 | `data.roll_events`，与单资产 Range 同结构，标注 `data_frequency=minute`；不使用按 ticker 分组的新字段 |
| `fast_query_minute_range_multi`，多资产或 `market` | 不查询、不附带换月事件；即使实际只返回一个资产也不附带 |
| `fast_query_minute` | 不返回换月事件表；`contract_info` 为所选分钟 `trade_date` 的来源合约推导 |

例如 `fast_query_minute_range({"asset":"ES.CME","start_date":"2024-09-01","end_date":"2024-09-30"})` 和 `fast_query_minute_range_multi({"assets":["ES.CME"],"start_date":"2024-09-01","end_date":"2024-09-30"})` 均读取 `data.roll_events` 的 `columns`/`data`；日频 `fast_query({"assets":["ES.CME"],"query_type":"window","start_date":"2024-09-01","end_date":"2024-09-30","fields":["收盘价"]})` 读取 `data.future_context["ES.CME"].roll_events`。Multi 的 `asset` 单值、`assets` 单元素，或解析去重后为同一 ticker 的别名输入均按单资产处理。`assets` 含多个不同 ticker、`market` 全市场请求不附事件，不根据响应 `asset_count=1` 改判成单资产，也不为补换月而擅自拆分用户请求。

JSON 或 CSV 成功结果的换月事件均作为附加 JSON 返回，不拼入行情 CSV、不放入冻结 payload；分钟接口标注 `data_frequency=minute`，日频接口不标此字段。主行情命中缓存时仍可补换月；事件成功沿用 60 秒短缓存、失败不缓存。附加失败在 `roll_events_error`/`future_context[ticker].error`/`warnings` 披露，保留成功行情；缺事件或 `partial_coverage=true` 不表示此前区间无换月，只有覆盖段内成功事件表 `data=[]` 才表示该覆盖窗口未返回事件。

日频与分钟的 Grant 查询均复用同一条件与返回结构。外盘事件匹配使用所属 Chicago 会话 `trade_date` 及 `effective_trade_date`，不按 UTC 或北京自然日重分组；部分历史外盘换月在会话中段（UTC 零点）切换，且同一 `effective_trade_date` 可能有多条不同事件，分钟级精细复权需注意切换边界并按返回顺序累乘。

依赖生产 `task.fetch.fast_query_future_roll_events` 支持外盘主力 `rank=1`。明确不支持时 `UPSTREAM_ROLL_EVENTS_UNSUPPORTED`（`retryable=false`）提示核对任务版本或品种覆盖；其他失败、超时、格式异常沿用原警告。`contract_info` 的 `inferred` 是基于已生效事件推导，不是独立实时映射；缺历史锚点时为 `unavailable`。
