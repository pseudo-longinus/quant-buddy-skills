# Composition Select Workflow — 已物化维度组合选股

> 目标：对“某个已上线维度分最高/最低/名单”类问题，直接读取 `presets/dimensions.yaml` 选择 `indicator_id`，调用 `selectByComposition`。本流程不写公式、不调 `confirmDataMulti`、不调 `runMultiFormulaBatchStream`。

## 1. 命中条件

同时满足：
- 用户要的是当前截面 TopN / 排名 / 名单 / 推荐；
- 用户语义能匹配 `presets/dimensions.yaml` 中已有的 score 或 screen 指标；
- 不要求回测、历史曲线、IC、下载、自定义公式、盘中分钟级实时排名。

不能满足任一条件时，退回 `quant-standard.md`。

## 2. 执行步骤

1. 调 `newSession`。
2. 读取 `presets/dimensions.yaml`，按市场和语义选择指标。禁止自造 `indicator_id`。
3. 构造参数并调用 `selectByComposition`：
   - score 指标：`mode:"score"`，传 `composition:[{indicator_id, weight}]`；
   - screen 指标：`mode:"screen"`，传 `screens:[{indicator_id}]`，需要排序时传 `sort_by`；
   - `universe.asset_scope` 按 `dimensions.yaml` 中的市场传入，如 `A股` / `港股` / `美股` / `期货`；
   - `top_n` 从用户问题取，未给则 10；
   - 默认 `with_breakdown:true`。
4. 输出 TopN 表格，并标注 `last_date`、`composition_used` 或 `screens_used`。
5. 若 `selectByComposition` 失败：
   - `INDICATOR_NOT_FOUND` 表示本地 `dimensions.yaml` 中的 `indicator_id` 与服务端 `qw_indicator` 当前可用记录不一致（缺记录、未启用、非 `status:"success"` 或非综合指标），不是“没读到本地 preset”；
   - 404 / Unknown tool / Not Found 表示当前服务端或工具 schema 尚未部署本接口；
   - 对可由公式复刻的 score 排名（如动量与反转、趋势结构类价格/量价指标），立即退回 `quant-standard.md`，并按原公式路径完成；
   - 对无法公式复刻的已物化专有指标，输出受控失败，说明“组合选股接口当前不可用”；
   - 最终正常回答中不要暴露接口切换过程，除非两条路径都失败。

## 3. 默认映射

| 用户说法 | indicator_id | mode |
|---|---|---|
| A股动量与反转 / 动量反转分数 | `ind_a_share_momentum_reversal` | score |
| A股趋势结构 | `ind_a_share_trend_structure` | score |
| A股相对强度 | `ind_a_share_relative_strength` | score |
| A股当日交易异动 / 异动名单 | `ind_a_share_daily_trading_abnormal` | screen |
| A股当日异动评分 | `ind_a_share_daily_abnormal_score` | score |

若 `dimensions.yaml` 与本表冲突，以 `dimensions.yaml` 为准。

## 4. 输出格式

首句直接给结论或标题，例如：`A股动量与反转 Top10（数据截至 YYYYMMDD）`。

表格至少包含：
- 排名
- 名称(代码)
- score 或命中状态
- 主要贡献/口径（有则展示）

结尾声明：已物化维度分只代表该指标口径，不构成投资建议。
