# 维度指标库 — 列指标 / 取公式

> 工具名：`listDimensionIndicators`、`getIndicatorFormulas`
> 用途：查平台**已建好的维度指标库**——有哪些维度、每个维度下有哪些指标、某个指标的口径公式到底怎么写的。
>
> ⚠️ **这两个不是平台原生工具**，必须通过 `python scripts/call.py <工具名> '<JSON>'` 调用。
> 这属于硬规则 #2 的「平台明确不存在等价原生工具」情形，是许可路径，不算包装原生工具；
> 同理不要去试 `listDimensionIndicators` 之类的原生工具名，会直接 unknown tool。

---

## 一、先搞清楚「维度指标」是什么

平台维护着一套**分好类、已经算好的指标库**，三层结构：

```
维度(dimension)  ──包含──▶  指标(indicator)  ──定义于──▶  公式组(formulas)
   当前目录以在线返回为准         当前实际指标示例                 每个指标一组公式
   趋势结构                    A股_20日高点接近突破          A股_前高20=最大(...)
   动量与反转                  A股_均线多头排列              A股_20日高点接近突破比例=...
   估值性价比                  A股估值性价比                 A股_20日高点接近突破得分=...
   ...                        ...
```

**维度**只是分组容器（趋势结构、动量与反转、资金流向、盈利能力、异动监控…），本身不带权重、不是一个可计算的东西。

**指标**分两类，这个区分很重要：

| `indicator_type` | 是什么 | 典型用途 |
|---|---|---|
| `细分` | 单一口径的基础指标，如「A股_20日高点接近突破」「A股_均线多头排列」 | 取公式改口径、做变体；若已物化且当前可选，也可直接用于 `selectByComposition` |
| `综合` | 该维度的**维度分**，由维度内多个细分指标按内在权重聚合而成，如「A股动量与反转」 | 可直接用于 `selectByComposition`，也可作为高层维度分做解释或组合 |

还有一个正交的属性 `output_type`：`score`（连续分，可加权排序）/ `screen`（0-1 布尔，可取集合）。`selectByComposition` 的请求位置由 `output_type` 决定，而不是由 `indicator_type` 决定。

**新目录对外使用语义名称**：

| 字段 | 例子 | 谁在用 |
|---|---|---|
| `indicator_id` | `A股_20日高点接近突破得分` | 完整语义标识（与 `index_title` 一致）；`selectByComposition` 和 `getIndicatorFormulas` 直接使用 |
| `name` | `A股_20日高点接近突破` | 上游展示别名，也可直接用于查公式和选股 |
| `index_title` | `A股_20日高点接近突破得分` | 公式里的变量名，也是这组公式最后一行的左侧；由 `getIndicatorFormulas` 返回 |

两种语义名称 `getIndicatorFormulas` 和 `selectByComposition` 都认，不要传平台数字 ID（如 `id_123` 或公式组数字 ID），也不要自行去掉市场前缀。

### 和 `presets/dimensions.yaml` 的关系

`presets/dimensions.yaml` 保留在 Skill 中，收录了千维业务维度与指标的完整语义标识、别名、类型和说明。按需检索命中且市场、`output_type` 明确时，**可直接拿 `indicator_id` 调用 `getIndicatorFormulas` 或 `selectByComposition`**，不必先多查一次在线目录；skill_server 不读取该文件。

`listDimensionIndicators` 是**在线全量目录，细分 + 综合都有**。两者分工如下：

- 本地 `presets/dimensions.yaml` 命中明确指标 → 直接调用查公式或选股；
- 本地未收录、需看当前平台最新增量/实时 `selection_ready`/`as_of`，或直调报 `INDICATOR_NOT_FOUND`/`INDICATOR_AMBIGUOUS` → 调 `listDimensionIndicators` 窄查询确认；
- 想知道指标口径、需要修改公式或构造自定义指标 → 用本组工具取得公式后走公式链路。

---

## 二、什么时候用

✅ 适用：

- 「平台有哪些维度 / 指标」「趋势结构这个维度下面有什么指标」
- 「XX 指标是怎么算的」「XX 的公式是什么」「XX 的口径」
- 想在现成指标基础上改参数（如把 20 日改成 30 日）——先取公式再改，比从零写准得多
- 需要发现可直接用于 `selectByComposition` 的细分指标，或本地 `dimensions.yaml` 没有合适候选

❌ 不适用：

- 直接要 TopN 选股结果 → `composition-select.md` + `selectByComposition`
- 要已物化指标的历史快照 / 历史序列 / 多资产对比 → 本工具只给**定义**不给数据；已落库全历史千维指标直接走 `fast_query`（传 `indicator_id` 或 `name`，支持 `snapshot`/`window` 及 CSV）；仅改参数或自算公式变体才走 `runMultiFormulaBatchStream`
- 要查平台有哪些**数据集**（`全市场每日收盘价` 之类）→ 那是 `presets/data_catalog.yaml` 和 `index_info_catalog/`，不是这里

---

## 三、`listDimensionIndicators` — 按维度列指标

### 调用

```bash
# 先看有哪些维度（约 1.6KB，最省）
python scripts/call.py listDimensionIndicators '{"with_indicators": false}'

# 看某个维度下的指标
python scripts/call.py listDimensionIndicators '{"dimension": "趋势结构"}'

# 按市场 + 类型筛
python scripts/call.py listDimensionIndicators '{"asset_scope": "期货", "indicator_type": "综合"}'

# 关键词找指标
python scripts/call.py listDimensionIndicators '{"keyword": "突破"}'
```

> **取公式前的名称规则**：`with_indicators:false` 只返回维度和数量，不能用于确定指标参数。需要取公式时，先按维度或关键词查询 `compact:true`，再原样使用返回的 `indicator_id` 或完整 `name`；不要根据文档示例自行去掉市场前缀、拼接 `通用_`，也不要把 `indexinfo_id` 当作指标参数。

### 参数（全部可选，不传 = 全量约 29KB）

| 参数 | 类型 | 说明 |
|---|---|---|
| `dimension` | string \| string[] | 维度名或维度 `_id`，**精确匹配**（不是模糊搜索） |
| `asset_scope` | string | `A股` / `港股` / `美股` / `期货` |
| `indicator_type` | string | `细分` \| `综合` |
| `output_type` | string | `score` \| `screen` |
| `keyword` | string | 对指标名/说明/口径做包含匹配，不区分大小写 |
| `with_indicators` | boolean | 默认 `true`；`false` 只返回维度目录 + 计数（约 1.6KB） |
| `compact` | boolean | 默认 `false`；`true` 仅保留精简发现字段，适合只需名称和 ID 的目录浏览 |
| `verbose` | boolean | 默认 `false`；`true` 补回 `indicator_type` / `index_title` / `calculation` / `window` / `formula_count` 及完整 `selection` 信息（约 58KB） |

> 不传任何参数会一次拉回 29KB。**先用 `with_indicators:false` 看目录，再按维度取**，不要无脑全量拉。
> 想知道某指标口径**不要用 `verbose`**，直接 `getIndicatorFormulas`——那里有 `calculation` 和完整公式。

### 返回要点

```json
{
  "code": 0,
  "data": {
    "dimensions": [{
      "name": "趋势结构",
      "description": "价格是否已经进入可交易的强趋势结构，而不是震荡或假突破？",
      "indicator_count": 43,
      "indicators": [{
        "indicator_id": "A股_20日高点接近突破得分",
        "name": "A股_20日高点接近突破",
        "output_type": "score",
        "selection_ready": true,
        "selection_mode": "score",
        "as_of": 20261123,
        "description": "高分表示接近或突破短期高点",
        "asset_scope": ["A股"],
        "last_date": 20261123
      }]
    }],
    "total_dimensions": 18,
    "total_indicators": 325,
    "filters_applied": {}
  }
}
```

维度层返回名字 / 说明 / 指标数；默认指标条目可用于候选发现。要取得完整口径和公式，使用 `getIndicatorFormulas`。

> ⚠️ **选择器准入不由 `indicator_type:"综合"` 决定。**
> 对选股，先按用户需要的请求角色使用 `output_type:"score"` 或 `output_type:"screen"` 缩小查询；只有用户明确要求细分或综合类别时才额外传 `indicator_type`。在线目录中的 `selection_ready`、`selection_mode`、`as_of` 用于预检，`selectByComposition` 才是启用、删除、物化和快照日期有效性的最终校验。
> ```bash
> # 查询可作为 A 股 screen 条件的细分候选
> python scripts/call.py listDimensionIndicators '{"asset_scope": "A股", "indicator_type": "细分", "output_type": "screen"}'
> ```
> ```bash
> # 查询可作为 A 股排序/组合得分的 score 候选
> python scripts/call.py listDimensionIndicators '{"asset_scope": "A股", "output_type": "score"}'
> ```

**异常字段与选择器预检字段**：

| 字段 | 含义 | 怎么办 |
|---|---|---|
| `selection_ready` | 当前目录观察到的选择向量是否可用 | 仅 `true` 的候选可进入选择器预检；最终仍以选择器响应为准 |
| `selection_mode` | 服务端选择向量角色，`score` 或 `screen` | 与 `output_type` 对齐后，放入正确请求位置 |
| `as_of` | 当前选择向量快照日期 | 必须存在；可与其他参与指标不同，最终按选择器返回的 `date_alignment` 披露 |
| `status`（值非 `"success"`） | 指标状态异常 | 不作为选择器候选；公式定义仍可能有效 |
| `has_formula: false` | 该指标取不到公式（全库只有 2 个） | 别对它调 `getIndicatorFormulas`，会返回 `FORMULA_NOT_AVAILABLE` |

取公式时应使用列表返回的**完整 `name`**或 `indicator_id`，不需要先拿到 `index_title`。跨市场同名指标优先使用 `indicator_id`，不要自行截短或拼接名称。

过滤后为空不是错误，看 `filters_applied` 判断是被哪个条件筛没的。

### 错误码

| code | 含义 |
|---|---|
| `DIMENSION_NOT_FOUND` | `dimension` 一个都没匹配上，响应里带 `available_dimensions`，照着改重试一次 |
| `INVALID_INDICATOR_TYPE` / `INVALID_OUTPUT_TYPE` / `INVALID_DIMENSION_FILTER` | 参数值写错，按上表改 |

---

## 四、`getIndicatorFormulas` — 按指标名取公式

### 调用

```bash
# 推荐：使用本地 dimensions.yaml 或 listDimensionIndicators 中的完整语义名称
python scripts/call.py getIndicatorFormulas '{"indicators": ["A股_20日高点接近突破得分"]}'

# 也可以使用上游明确别名（name）
python scripts/call.py getIndicatorFormulas '{"indicators": ["A股_20日高点接近突破"]}'

# 一次取多个（≤10）
python scripts/call.py getIndicatorFormulas '{"indicators": ["A股_20日高点接近突破得分", "A股_PE估值吸引力得分"]}'
```

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `indicators` | string[] | ✅ | 1~10 个；`name` / `ind_id` / `index_title` 三种写法均可混用 |
| `merge` | boolean | | 默认 `false`；多个指标时额外返回一份去重合并的公式组 |

### 返回

```json
{
  "code": 0,
  "data": {
    "indicators": [{
      "query": "A股_20日高点接近突破",
      "matched_by": "name",
      "indicator_id": "A股_20日高点接近突破得分",
      "name": "A股_20日高点接近突破",
      "index_title": "A股_20日高点接近突破得分",
      "dimension_name": "趋势结构",
      "indicator_type": "细分",
      "output_type": "score",
      "target": "A股_20日高点接近突破得分",
      "formula_count": 4,
      "formulas": [
        "A股_基础可用池=去除零值(有值(\"全市场每日收盘价\")*板块(万得全A))",
        "A股_前高20=最大(前几天(\"全市场每日最高价\",1),20)*\"A股_基础可用池\"",
        "A股_20日高点接近突破比例=(\"全市场每日收盘价\"/\"A股_前高20\")*\"A股_基础可用池\"",
        "A股_20日高点接近突破得分=按市场排序分(\"A股_20日高点接近突破比例\"*\"A股_基础可用池\")*\"A股_基础可用池\""
      ],
      "external_datasets": ["全市场每日收盘价", "全市场每日最高价"]
    }]
  }
}
```

**`formulas` 是 `runMultiFormulaBatchStream` 的执行输入，不超过 20 条可原样整组传入，超过时遵循下面的切批规则**：

- 顺序已经排好——每个中间变量都在被引用之前定义，最后一行就是最终产出（`target`）；
- 表达式一个字符都没改，就是平台公式引擎的原始输入；
- `external_datasets` 是公式引用的底层数据集（如 `全市场每日收盘价`），它们不是公式行，平台已有这些数据，**不要为它们编造定义**。

### 公式超 20 条时

接口只返回一份完整 `formulas`，不再返回 `batch_hint` 或分批公式副本。分批在执行时处理：

1. 单次最多 **20 条公式**，限制的是条数，不是字符串长度。按返回的原顺序每 20 条切批，依次调用 `runMultiFormulaBatchStream`；无需按依赖深度分层，同批可有前后依赖。
2. 各批沿用**同一个 `task_id`**，并保持 `begin_date`、`use_minute_data` 和任务级 `execution_profile`（如有）一致；`intents`、`actions` 如有，按公式相同位置切分。
3. 每批的 `force_reusable_array` 填**本批全部公式的输出变量名**（等号左侧，多输出全部填写），保证后续批次能复用结果；不要填写此前批次的变量。
4. 前一批全部成功后再执行下一批。排队态按执行工具规则等待完成，失败或部分失败时停止，修复后再继续。
5. `merge:true` 返回有效的 `merged_formulas` 时，只对合并数组应用上述规则，不要再执行各指标的原公式组。

### 错误码

请求级（整个请求失败）：`INDICATORS_REQUIRED`（没传）、`INDICATORS_LIMIT_EXCEEDED`（超 10 个）、`INVALID_INDICATORS`（类型不对）。

项级（只影响那一项，其余照常返回，落在 `data.indicators[i].error`）：

| code | 处理 |
|---|---|
| `INDICATOR_NOT_FOUND` | 名字对不上。先用 `listDimensionIndicators` 的 `keyword` 找准确名字，**不要换着花样重试同一个词** |
| `INDICATOR_AMBIGUOUS` | 命中多条，响应里给了 `candidates`（含三种名字）。从中选一个准确名重试一次；**不许自己猜一个** |
| `FORMULA_NOT_AVAILABLE` | 该指标没有关联公式（库里有 2 个这样的），换指标或退回 `quant-standard.md` 自己写公式 |
| `FORMULA_HIDDEN` | 公式被标记为不公开，不要试图绕过 |

模糊匹配命中、`status != success` 等情况会进 `warnings`，不影响返回。

---

## 五、典型串联

**「趋势结构维度里有什么指标？A股 20 日高点接近突破怎么算的？」**

```bash
python scripts/call.py listDimensionIndicators '{"dimension": "趋势结构", "compact": true}'
python scripts/call.py getIndicatorFormulas '{"indicators": ["A股_20日高点接近突破得分"]}'
```
直接把 `calculation`（人话口径）+ `formulas`（公式）讲给用户。

**「按 A股_20日高点接近突破的口径，但改成 30 日，选出 A 股 Top20」**

```bash
# 1. 取现成公式作骨架（使用完整语义名称）
python scripts/call.py getIndicatorFormulas '{"indicators": ["A股_20日高点接近突破得分"]}'
# 2. 把 20 改成 30、变量名改掉，走 quant-standard.md 的公式路径执行
# 3. runMultiFormulaBatchStream → readData
```
比从零写公式准得多——函数名、数据集名、嵌套写法都是平台验证过的。

**「A股动量与反转分数最高的10只」** → 不用本工具，直接 `composition-select.md` 读 `presets/dimensions.yaml` 走 `selectByComposition`。

---

## 六、输出要求

把指标口径讲给用户时：

- 优先用 `calculation`（人话）解释，公式作为佐证，不要甩一堆公式了事；
- 带上 `dimension_name` 和 `indicator_type`，让用户知道这是哪个维度的、是细分还是维度分；
- 涉及数值时带 `last_date`；`status != "success"` 要说明数据可能不是最新；
- 声明：指标口径只代表该指标定义，不构成投资建议。
