# Composition Select Workflow — 已物化指标组合选股

> 目标：对已物化、当前可选的指标做当前截面 TopN、排名或名单筛选，调用 `selectByComposition`。本流程不写公式、不调 `confirmDataMulti`、不调 `runMultiFormulaBatchStream`。

## 1. 命中条件

同时满足：
- 用户要的是当前截面 TopN / 排名 / 名单 / 推荐；
- 用户条件可映射为已物化的 `score` 或 `screen` 指标；
- 不要求回测、历史曲线、IC、下载、自定义公式、盘中分钟级实时排名。

不能满足任一条件时，退回 `quant-standard.md`。

> `presets/dimensions.yaml` 是本地候选快照，不是服务端可选状态的权威来源。它适合零网络开销的常见指标映射；细分指标、本地未命中的指标，或快照失效后的替代候选，必须通过 `listDimensionIndicators` 在线确认后才能调用选择器。

## 2. 指标可选性与角色

`indicator_type`（`细分` / `综合`）只描述指标分类，**不是** `selectByComposition` 的准入条件。服务端在执行时校验：指标已启用、未删除、`status:"success"`、已物化且向量可用、支持 `universe.asset_scope`，并要求同一请求内的 `as_of` 对齐。

请求位置由 `output_type` 决定：

| `output_type` | 可用位置 |
|---|---|
| `score` | score 模式的 `composition`、`score_filters`；screen 模式的 `sort_by` |
| `screen` | `screens` |

不能把 screen 指标放入 `composition`，也不能把 score 指标放入 `screens`。

## 3. 执行步骤

1. 调 `newSession`。
2. 先从 `presets/dimensions.yaml` 解析明确的常见候选；禁止凭名称自造 `indicator_id`。
3. 出现以下任一情形时，使用 `listDimensionIndicators` 做窄查询：用户指定细分指标、本地快照无匹配项、或上次选择器返回可选性错误。
   - 按实际需要组合 `asset_scope`、`keyword`、`output_type` 和 `indicator_type`；`indicator_type` 仅用于缩小检索范围。
   - 读取候选的 `output_type`、`selection_ready`、`selection_mode`、`as_of`、`asset_scope` 和异常 `status` 字段。
   - 在线目录用于预检；`selectByComposition` 才是启用、删除、物化和日期一致性的最终权威。
4. 按角色构造请求：
   - 需要按分数排名时使用 `mode:"score"`，`composition` 至少包含一个 score 指标；可同时传 `screens` 求交集，及用 `score_filters` 限制 score 指标的归一化数值。
   - 需要返回满足条件的集合时使用 `mode:"screen"`，将条件放入 `screens`；可选的 score 指标放入 `sort_by` 仅用于排序。screen 模式不得传 `composition` 或 `score_filters`。
   - `universe.asset_scope` 使用目标市场（`A股` / `港股` / `美股` / `期货`）；它会限制最终返回的实际证券范围。
   - `top_n` 使用用户指定数量，未指定时取 10；每个 `composition`、`screens`、`score_filters` 最多 8 项。
   - 需要贡献解释时在 score 模式传 `with_breakdown:true`；默认返回 `breakdown_format:"compact"`，需要旧式完整贡献对象时显式传 `"verbose"`。
5. 输出结果时使用服务端返回的 `as_of`、`date_alignment`、`composition_used` 或 `screens_used`，不要自行推断数据日期。
6. 失败处理：
   - `INDICATOR_NOT_FOUND`：指标 ID 不存在；重新通过在线目录定位准确候选。
   - `INDICATOR_NOT_SELECTABLE`：读取服务端返回的 `reasons`（如 `disabled`、`not_materialized`、`unsupported_scope`）；禁止原参数重试，可换已确认候选或退回公式路径。
   - `INDICATOR_DATE_MISMATCH`：参与指标的 `as_of` 不一致；不得输出混合日期的排名。
   - `INVALID_SCORE_INDICATOR`、`INVALID_SCREEN_INDICATOR`、`INVALID_SCORE_FILTER`、`INVALID_SORT_INDICATOR`：按 `output_type` 重新分配请求位置。
   - 404 / Unknown tool / Not Found：服务端或工具 schema 未部署；对可公式复刻的需求退回 `quant-standard.md`，否则输出受控失败。

## 4. 默认映射

| 用户说法 | indicator_id | `output_type` |
|---|---|---|
| A股动量与反转 / 动量反转分数 | `ind_a_share_momentum_reversal` | score |
| A股趋势结构 | `ind_a_share_trend_structure` | score |
| A股相对强度 | `ind_a_share_relative_strength` | score |
| A股当日交易异动 / 异动名单 | `ind_a_share_daily_trading_abnormal` | screen |
| A股当日异动评分 | `ind_a_share_daily_abnormal_score` | score |

本表仅为常见映射；以本地快照或在线目录实际返回的 `indicator_id` 与 `output_type` 为准。

## 5. 输出格式

首句直接给结论或标题，例如：`A股动量与反转 Top10（数据截至 YYYYMMDD）`。

表格至少包含：
- 排名；
- 名称（代码）；
- score，或 screen 的命中状态与可选排序分；
- 主要贡献/口径（服务端返回且用户需要时展示）。

结尾声明：已物化指标只代表对应指标口径，不构成投资建议。
