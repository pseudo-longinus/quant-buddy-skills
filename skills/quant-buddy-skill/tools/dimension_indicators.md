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
   17 个                      163 个                       每个指标一组公式
   趋势结构                    20日高点接近突破              通用_前高20=最大(...)
   动量与反转                  均线多头排列                  通用_20日高点接近突破比例=...
   估值性价比                  A股动量与反转                 通用_20日高点接近突破得分=...
   ...                        ...
```

**维度**只是分组容器（趋势结构、动量与反转、资金流向、盈利能力、异动监控…），本身不带权重、不是一个可计算的东西。

**指标**分两类，这个区分很重要：

| `indicator_type` | 是什么 | 典型用途 |
|---|---|---|
| `细分` | 单一口径的基础指标，如「20日高点接近突破」「均线多头排列」 | 拿它的公式去改口径、做变体、组成自己的策略 |
| `综合` | 该维度的**维度分**，由维度内多个细分指标按内在权重聚合而成，如「A股动量与反转」 | 直接喂 `selectByComposition` 做 TopN 选股 |

还有一个正交的属性 `output_type`：`score`（连续分，可加权排序）/ `screen`（0-1 布尔，可取集合）。由 `is_bool` 推导。

**指标有两个名字，都能用来查**（这是最容易卡住的地方）：

| 字段 | 例子 | 谁在用 |
|---|---|---|
| `name` | `20日高点接近突破` | 指标库里的短名，`listDimensionIndicators` 返回的就是它 |
| `index_title` | `通用_20日高点接近突破得分` | 公式里的变量名，也是这组公式最后一行的左侧。**只在 `getIndicatorFormulas` 的响应里**，列表默认不返回 |
| `indicator_id` | `ind_20d_high_breakout_proximity` | 稳定语义键，`selectByComposition` 用它 |

三种写法 `getIndicatorFormulas` 都认，返回完全一致。用户如果直接报了 `通用_XXX得分` 这种全名，也能直接查。

### 和 `presets/dimensions.yaml` 的关系

`presets/dimensions.yaml` 是**本地快照，只含综合指标**（维度分），给 `selectByComposition` 选股用，零网络开销。

`listDimensionIndicators` 是**在线全量目录，细分 + 综合都有**。两者不冲突：

- 只是要「A股动量与反转 Top10」这种维度分选股 → 读 `dimensions.yaml`，走 `composition-select.md`，**不必调本工具**；
- 想知道某个维度下还有哪些细分指标、某个指标口径到底怎么算的、想拿现成公式改一版 → 用本组工具。

---

## 二、什么时候用

✅ 适用：

- 「平台有哪些维度 / 指标」「趋势结构这个维度下面有什么指标」
- 「XX 指标是怎么算的」「XX 的公式是什么」「XX 的口径」
- 想在现成指标基础上改参数（如把 20 日改成 30 日）——先取公式再改，比从零写准得多
- `dimensions.yaml` 里没有对得上的维度分，但可能有细分指标能拼

❌ 不适用：

- 直接要 TopN 选股结果 → `composition-select.md` + `selectByComposition`
- 要指标的历史序列 / 数值 → 本工具只给**定义**不给数据；要数值走 `runMultiFormulaBatchStream`
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

### 参数（全部可选，不传 = 全量约 29KB）

| 参数 | 类型 | 说明 |
|---|---|---|
| `dimension` | string \| string[] | 维度名或维度 `_id`，**精确匹配**（不是模糊搜索） |
| `asset_scope` | string | `A股` / `港股` / `美股` / `期货` |
| `indicator_type` | string | `细分` \| `综合` |
| `output_type` | string | `score` \| `screen` |
| `keyword` | string | 对指标名/说明/口径做包含匹配，不区分大小写 |
| `with_indicators` | boolean | 默认 `true`；`false` 只返回维度目录 + 计数（约 1.6KB） |
| `compact` | boolean | 默认 `false`；`true` 每条指标只留 4 个字段，含 `indicator_type`（约 20KB） |
| `verbose` | boolean | 默认 `false`；`true` 补回 `indicator_type` / `index_title` / `calculation` / `window` / `formula_count` 等（约 58KB） |

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
      "indicator_count": 19,
      "indicators": [{
        "indicator_id": "ind_20d_high_breakout_proximity",
        "name": "20日高点接近突破",
        "output_type": "score",
        "description": "高分表示接近或突破短期高点",
        "asset_scope": ["A股","港股","美股","期货"],
        "last_date": 20260730
      }]
    }],
    "total_dimensions": 17,
    "total_indicators": 163,
    "filters_applied": {}
  }
}
```

维度层只有 名字 / 说明 / 指标数，指标层只有 6 个字段——只够回答「用哪个指标」。口径怎么算的去 `getIndicatorFormulas` 拿，别在这里找。

> ⚠️ **要拿去喂 `selectByComposition` 时，必须带 `indicator_type:"综合"` 查。**
> 默认返回里**不含** `indicator_type`，看不出哪条是细分、哪条是维度分；而 `selectByComposition` 只接受综合指标，把细分的 `indicator_id` 传过去会返回 `INDICATOR_NOT_FOUND`。
> ```bash
> python scripts/call.py listDimensionIndicators '{"asset_scope": "A股", "indicator_type": "综合"}'
> ```
> 这样返回的每一条都可直接用于 `selectByComposition`。

**两个字段只在不正常时出现**——没有它们就是正常，不用逐条判断：

| 字段 | 出现即表示 | 怎么办 |
|---|---|---|
| `status`（值非 `"success"`） | 该指标物化数据可能不是最新 | 只影响 `selectByComposition` 那条路；**公式定义仍然有效**，取公式不受影响。回答涉及数值时要说明 |
| `has_formula: false` | 该指标取不到公式（全库只有 2 个） | 别对它调 `getIndicatorFormulas`，会返回 `FORMULA_NOT_AVAILABLE` |

取公式直接用列表里的 `name` 即可（163 条内 `name` 唯一），不需要先拿到 `index_title`。

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
# 三种写法等价，返回完全一致
python scripts/call.py getIndicatorFormulas '{"indicators": ["20日高点接近突破"]}'
python scripts/call.py getIndicatorFormulas '{"indicators": ["ind_20d_high_breakout_proximity"]}'
python scripts/call.py getIndicatorFormulas '{"indicators": ["通用_20日高点接近突破得分"]}'

# 一次取多个（≤10）
python scripts/call.py getIndicatorFormulas '{"indicators": ["20日高点接近突破", "均线多头排列"]}'
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
      "query": "20日高点接近突破",
      "matched_by": "name",
      "indicator_id": "ind_20d_high_breakout_proximity",
      "name": "20日高点接近突破",
      "index_title": "通用_20日高点接近突破得分",
      "dimension_name": "趋势结构",
      "indicator_type": "细分",
      "output_type": "score",
      "target": "通用_20日高点接近突破得分",
      "formula_count": 3,
      "formulas": [
        "通用_前高20=最大(前几天(\"全市场每日最高价\",1),20)",
        "通用_20日高点接近突破比例=\"全市场每日收盘价\"/\"通用_前高20\"",
        "通用_20日高点接近突破得分=按市场排序分(\"通用_20日高点接近突破比例\")"
      ],
      "external_datasets": ["全市场每日最高价", "全市场每日收盘价"]
    }]
  }
}
```

**`formulas` 可以原样传给 `runMultiFormulaBatchStream`**：

- 顺序已经排好——每个中间变量都在被引用之前定义，最后一行就是最终产出（`target`）；
- 表达式一个字符都没改，就是平台公式引擎的原始输入；
- `external_datasets` 是公式引用的底层数据集（如 `全市场每日收盘价`），它们不是公式行，平台已有这些数据，**不要为它们编造定义**。

### 公式超 20 条时

单批公式上限 20 条，库里有 19 个指标超过（最长 83 条）。这些指标会额外返回 `batch_hint`：

```json
"batch_hint": {
  "exceeds_batch_limit": true,
  "layers": [
    { "batch_no": 1, "formulas": ["..."], "force_reusable_array": ["通用_1日涨幅"] },
    { "batch_no": 2, "formulas": ["..."], "force_reusable_array": [] }
  ]
}
```

按 `batch_no` 顺序分批调 `runMultiFormulaBatchStream`，**沿用同一个 `task_id`**，每批把该批的 `force_reusable_array` 原样传进去。层内互不依赖，不要自己重排。

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

**「趋势结构维度里有什么指标？20日高点接近突破怎么算的？」**

```bash
python scripts/call.py listDimensionIndicators '{"dimension": "趋势结构"}'
python scripts/call.py getIndicatorFormulas '{"indicators": ["20日高点接近突破"]}'
```
直接把 `calculation`（人话口径）+ `formulas`（公式）讲给用户。

**「按 20日高点接近突破的口径，但改成 30 日，选出 A 股 Top20」**

```bash
# 1. 取现成公式作骨架
python scripts/call.py getIndicatorFormulas '{"indicators": ["20日高点接近突破"]}'
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
