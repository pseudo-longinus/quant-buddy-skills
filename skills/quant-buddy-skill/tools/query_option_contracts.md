# query_option_contracts — 美股期权槽位合约

新版skill_server部署后使用，dataServer保持原有日期范围任务，无需新增query_type参数；Skill 文档变更不代表服务已经上线。
`POST /skill/queryOptionContracts`。只读 assignment 与必要同表前序，不查询行情/检查点，不重选、不前填、不复权。

## 何时调用

查询槽位当前对应合约、最近换约/换月、或解释拼接 IV/价格/持仓量跳变时使用。
只查询 IV 值时不强制附加本工具；不能把拼接价变动解释为持有同一合约的收益。

## 参数

- `asset` 必填，单个名称、简称或代码，如 苹果、Apple、AAPL、AAPL.O；复用既有多字段匹配，不强制市场后缀。目前仅支持部分美股标的期权。
- `query_type` 必填：`snapshot` 或 `window`。
- `slots` 可选，省略查全部八槽；指定时1～8个合法不重复值：E1/E2分别搭配ATM-CALL、ATM-PUT、25C、25P，不传ATM_CALL。
- `snapshot` 只传asset/query_type及可选slots，**禁止 lookback_days/mode**。返回每槽不晚于纽约当地今天的最新已生效映射，每槽最多一条。
- `window` 必须传整数 `lookback_days:1～366`，按**自然日**、包含纽约当地今天，不是交易日；`mode` 默认 `daily`，也可 `changes`。
- 公开查询只使用上述动态参数。固定历史日需求可在window支持范围内按真实日期匹配；超过动态窗口范围时明确说明限制。

```json
{"asset":"苹果","slots":["E1-ATM-CALL","E1-25C"],"query_type":"snapshot"}
```

```json
{"asset":"苹果","slots":["E1-ATM-CALL"],"query_type":"window","lookback_days":90,"mode":"changes"}
```

query_type/lookback_days只用于skill_server参数转换；Celery仍只传ticker/start_date/end_date/slots/mode。snapshot复用原当天查询及baselines，缺当天时按实际映射日分组补查同一daily任务以取真实前序，不新增检查任务。

每次执行按 `America/New_York` 日期计算。纽约日期为2026-10-12时，90天窗口为2026-07-15～2026-10-12。

## 简洁结果

`data` 只有 `ticker`、`records` 及必要时的 `notes`。每行11项扁平重点字段：
`trade_date/slot/contract/expiration/strike/call_put/changed/previous_date/previous_contract/previous_expiration/previous_strike`。

- `trade_date` 是映射实际生效日，snapshot可能早于今天，不保证合约仍可交易，不统一改成查询日；不同槽可能日期不同。
- `changed` 表示该条相对同槽前一条实际记录的合约代码是否变化，无前序为null；snapshot不代表“今天换约”。
- 前序日期/代码/到期日/行权价来自真实前序记录，缺失为null，不解析代码猜测；strike保留精确字符串。
- `changes` 只返回合约代码变化，另保留每槽窗口首条基准；额外基准行带 `is_baseline:true`，首条已经换约则不重复。
- 正常不展示固定warnings或审计树。确有缺槽/日期衔接缺口才有简短notes，缺失日不前填。
- 空records只代表本映射数据源未查到，不等于市场没有期权。映射存在不代表close/IV行情更新。
- 返回当前修订历史；未核验交易日历、乘数、交割物或调整状态，不把它用作交易合约规格证明。

## 活页持续更新

活页走 `quant-buddy-view` 数据授权 `kind:option_contracts`，payload原样使用上述新参数。
先通过QBV bridge验证真实数据，再注册授权；网页只嵌入grant_id/signature，不放API Key。
授权冻结标准资产/槽位/窗口规则，每次queryDataGrant重算日期，不冻结注册当天日期。
QBV `build_dashboard` 已把records转换为合约表；显示真实trade_date并支持既有刷新。
详细流程见QBV `tools/data_grant.md`；无需公式包和附加检查任务。

## 错误

- HTTP400：按 `error.parameter/error.usage` 改正；有两种示例和合法槽位，不原样重试。
- 非美股资产提示“目前仅支持部分美股标的的期权合约查询”；名称未找到可换简称或代码，不能要求强制后缀。
- HTTP502：上游数据/合同异常，不猜测结果。
- HTTP503/504：服务不可用或排队/执行/回传超时；后台任务可能还在执行，不立即重复提交。
- 404未知接口/工具：配套未部署，停止并说明，不编造已查到结果。
