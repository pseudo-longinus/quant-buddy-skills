# selectByComposition 工具说明

> 工具名：`selectByComposition`
> 用途：读取已物化的千维综合指标最后一列，做横截面组合选股/筛选。它是“已上线维度分 TopN”的快速路径，不走公式引擎。

## 何时使用

用户的问题可以映射到 `presets/dimensions.yaml` 中已有的 score/screen 指标时，优先使用本工具。例如：
- “A股动量与反转分数最高的10个股票”
- “A股趋势结构最高的20只”
- “今日交易异动名单”

以下情况不要使用本工具，改走 `quant-standard.md`：
- 用户指定了临时公式口径，如“近60日涨幅减近20日涨幅”；
- 需要回测、净值曲线、IC、历史时序、下载公式结果；
- `presets/dimensions.yaml` 中找不到可解释的指标；
- 用户要求盘中/实时分钟级横截面排名，而不是已物化日频维度。

## 必要前置

1. 先调用 `newSession`。
2. 读取 `presets/dimensions.yaml`，只使用文件里真实存在的 `indicator_id`，禁止自造 ID。
3. 按用户问题选择 `mode`：
   - `score`：按一个或多个 score 指标加权排序；
   - `screen`：按 screen 指标取集合，可选 `sort_by` 排序。

## 参数

```json
{
  "mode": "score",
  "universe": { "asset_scope": "A股" },
  "composition": [
    { "indicator_id": "ind_a_share_momentum_reversal", "weight": 1 }
  ],
  "screens": [],
  "sort_by": { "indicator_id": "ind_a_share_trend_structure", "order": "desc" },
  "top_n": 10,
  "with_breakdown": true,
  "task_id": "<newSession 返回的 task_id>",
  "user_query": "<用户原问题>"
}
```

字段说明：
- `mode`：`score` 或 `screen`，默认 `score`。
- `universe.asset_scope`：市场范围；按 `dimensions.yaml` 中的 `asset_scope` 传入，例如 `"A股"` / `"港股"` / `"美股"` / `"期货"`。
- `composition`：score 模式必填；每项只传 `indicator_id` 和 `weight`。权重为正数，服务端会归一化。
- `screens`：screen 模式必填；score 模式可选作交集过滤。
- `sort_by`：screen 模式可选，用 score 指标排序筛选结果。
- `top_n`：返回数量，默认 30，最大 500。
- `with_breakdown`：score 模式是否返回贡献拆解。

## 典型调用

### A股动量与反转 Top10

```powershell
$env:GZQ_PARAMS='{"mode":"score","universe":{"asset_scope":"A股"},"composition":[{"indicator_id":"ind_a_share_momentum_reversal","weight":1}],"top_n":10,"with_breakdown":true,"task_id":"<task_id>","user_query":"A股中选出动量与反转分数最高的10个股票"}'
python scripts/call.py selectByComposition
```

### A股趋势结构 Top10

```json
{
  "mode": "score",
  "universe": { "asset_scope": "A股" },
  "composition": [
    { "indicator_id": "ind_a_share_trend_structure", "weight": 1 }
  ],
  "top_n": 10,
  "with_breakdown": true
}
```

## 输出要点

最终回答必须展示：
- 数据时点：优先使用返回的 `last_date`；
- 组合口径：来自 `composition_used`；
- TopN 表格：排名、名称、代码、score；
- 若有 `top_contributors`，可用一列或简短说明解释贡献；
- 声明：已物化维度分只代表该指标口径，不构成投资建议。

## 失败处理

若返回 404 / Not Found / Unknown tool，说明当前服务端或工具 schema 尚未部署本接口。若返回 `INDICATOR_NOT_FOUND`，说明本地 `dimensions.yaml` 的 `indicator_id` 未在服务端当前可用指标库中命中（可能未部署、未启用、非 success 或非综合指标）。不要反复重试同名工具；回到 `composition-select.md` 的失败规则，能用公式复刻则退回 `quant-standard.md`，否则输出受控失败。
