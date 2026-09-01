# selectByComposition 工具说明

> 工具名：`selectByComposition`
> 用途：读取已物化且当前可选的千维指标末列，做横截面组合选股或筛选。不走公式引擎。

## 何时使用

当用户的问题可以映射到一个或多个已物化的 score / screen 指标时，优先使用本工具。例如：

- “A股动量与反转分数最高的10只股票”；
- “短期高低点抬升、RSI强而不过热的10只 A 股”；
- “今日交易异动名单”。

以下情况改走 `quant-standard.md`：

- 用户指定了临时公式口径，如“近60日涨幅减近20日涨幅”；
- 需要回测、净值曲线、IC、历史时序、下载公式结果；
- 本地快照和在线目录均找不到已物化、可选且角色匹配的指标；
- 用户要求盘中/实时分钟级横截面排名，而不是已物化日频指标。

`indicator_type` 的“综合 / 细分”是分类信息；两个分类都可以进入本工具。是否可执行取决于服务端的启用、删除、状态、物化、市场范围及日期对齐校验，指标放在何处则取决于 `output_type`。

## 必要前置

1. 先调用 `newSession`。
2. 本地 `presets/dimensions.yaml` 可用于快速发现已知候选；它不是实时可选性的证明，不能据此自造 ID。
3. 细分指标、本地未命中项或可选性错误时，使用 `listDimensionIndicators` 在线确认候选的 `indicator_id`、`output_type`、`selection_ready`、`selection_mode`、`as_of` 和 `asset_scope`。
4. 按 `output_type` 组织请求：
   - `score`：放入 score 模式的 `composition` 或 `score_filters`；在 screen 模式中仅能作为 `sort_by`；
   - `screen`：放入 `screens`。

## 参数

### score 模式：分数排名，可叠加 screen 交集和 score 阈值

```json
{
  "mode": "score",
  "universe": { "asset_scope": "A股" },
  "composition": [
    { "indicator_id": "ind_a_share_momentum_reversal", "weight": 1 }
  ],
  "screens": [
    { "indicator_id": "<screen-indicator-id>" }
  ],
  "score_filters": [
    {
      "indicator_id": "ind_a_share_relative_strength",
      "op": ">=",
      "value": 0.8
    }
  ],
  "top_n": 10,
  "with_breakdown": true,
  "breakdown_format": "compact",
  "task_id": "<newSession 返回的 task_id>",
  "user_query": "<用户原问题>"
}
```

### screen 模式：筛选集合，可选按 score 排序

```json
{
  "mode": "screen",
  "universe": { "asset_scope": "A股" },
  "screens": [
    { "indicator_id": "ind_a_share_daily_trading_abnormal" }
  ],
  "sort_by": {
    "indicator_id": "ind_a_share_trend_structure",
    "order": "desc"
  },
  "top_n": 10,
  "task_id": "<newSession 返回的 task_id>",
  "user_query": "<用户原问题>"
}
```

字段说明：

- `mode`：`score` 或 `screen`，默认 `score`。
- `universe.asset_scope`：目标市场，使用 `A股` / `港股` / `美股` / `期货`。服务端将它用于指标范围校验，也会限制返回的实际证券范围。
- `composition`：score 模式必填。每项为一个 score 指标及正权重；权重默认 1，服务端会归一化。
- `screens`：screen 模式必填；score 模式可选，用于与排名对象求交集。
- `score_filters`：仅 score 模式可用。每项是 score 指标与 `>=`、`>`、`<=`、`<` 之一，阈值范围为 `[0, 1]`，比较的是服务端归一化后的数值。
- `sort_by`：仅 screen 模式可用，必须为 score 指标；`order` 可取 `asc`、`desc` 或 `abs_desc`，默认 `desc`。
- `top_n`：返回数量，默认 30，最大 500；`composition`、`screens`、`score_filters` 各最多 8 项。
- `with_breakdown`：仅 score 模式生效，控制是否返回贡献拆解。
- `breakdown_format`：`compact`（默认）或 `verbose`。compact 的 `top_contributors[].composition_index` 对应顶层 `composition_used` 的数组下标。

同一请求中的所有指标必须具有一致的 `as_of`；否则服务端返回 `INDICATOR_DATE_MISMATCH`。

## 典型调用

### A股动量与反转 Top10

```powershell
$env:GZQ_PARAMS='{"mode":"score","universe":{"asset_scope":"A股"},"composition":[{"indicator_id":"ind_a_share_momentum_reversal","weight":1}],"top_n":10,"with_breakdown":true,"task_id":"<task_id>","user_query":"A股中选出动量与反转分数最高的10个股票"}'
python scripts/call.py selectByComposition
```

### 短期高低点抬升且 RSI 强而不过热的 A 股 Top10

```json
{
  "mode": "score",
  "universe": { "asset_scope": "A股" },
  "composition": [
    { "indicator_id": "ind_a_share_rsi_strong_not_overheated", "weight": 1 }
  ],
  "screens": [
    { "indicator_id": "ind_a_share_short_term_high_low_lift" }
  ],
  "score_filters": [
    {
      "indicator_id": "ind_a_share_rsi_strong_not_overheated",
      "op": ">",
      "value": 0
    }
  ],
  "top_n": 10
}
```

该请求使用细分 screen 指标限制“短期高低点抬升”，以细分 score 指标筛掉 RSI 非正样本并完成排序；提交前仍需用在线目录确认两项指标处于可选且同日期的物化状态。

## 输出要点

最终回答必须展示：

- 数据时点：优先使用返回的 `as_of` 与 `date_alignment`；
- 组合口径：来自 `composition_used` 或 `screens_used`；
- TopN 表格：排名、名称、代码、score，或 screen 的命中状态与 `sort_score`；
- 若有 `top_contributors`，可用一列或简短说明解释贡献；
- 声明：已物化指标只代表对应指标口径，不构成投资建议。

## 失败处理

- `INDICATOR_NOT_FOUND`：请求的指标 ID 不存在。使用在线目录找到准确 ID，不要原样重试。
- `INDICATOR_NOT_SELECTABLE`：指标已知但当前不可执行。读取响应中的 `reasons`，例如 `disabled`、`deleted`、`status_not_success`、`not_materialized`、`vector_not_ready`、`unsupported_scope`；换用新的已确认候选或退回公式路径。
- `INDICATOR_DATE_MISMATCH`：参与指标的 `as_of` 不一致；不得将不同快照拼接为同一结果。
- `INVALID_SCORE_INDICATOR`、`INVALID_SCREEN_INDICATOR`、`INVALID_SCORE_FILTER`、`INVALID_SORT_INDICATOR`：指标放错了 `output_type` 对应的请求位置，按本文件“必要前置”重新组织。
- 404 / Not Found / Unknown tool：当前服务端或工具 schema 未部署本接口。可公式复刻的需求退回 `quant-standard.md`，否则输出受控失败。
