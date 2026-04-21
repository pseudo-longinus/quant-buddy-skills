# 示例二：低PE价值选股，对比沪深300基准

## 用户意图

> "帮我筛选出全市场PE最低的20%股票，做等权回测，看看跑不跑得过沪深300"

---

## 工具调用序列

### Step 0 — 初始化会话

```bash
python scripts/call.py newSession
```

---

### Step 1 — 查案例（cases_index 优先）

**1a. 读取 `presets/cases_index.yaml`**，搜索 tags 含 `低价值`、`PE`、`估値因子`、`回测` 的卡片。

**1b.** 找到后调 `getCardFormulas` 批量拉取：

```bash
python scripts/call.py getCardFormulas '{"card_ids": ["<相关卡片id>"]}'
```

**1c.** 目录中未找到才 fallback：

```bash
python scripts/call.py searchSimilarCases '{"query": "低价値因子选股等权回测", "top_k": 3}'
```

**LLM 操作**：理解案例中低价値选股的公式结构（PE过滤、百分位阈值、负 PE 处理），提炼思路后针对用户需求重新组织公式。

---

### Step 2 — 确认指数代码

```bash
python scripts/call.py confirmMultipleAssets '{"intentions": ["沪淳300"]}'
```

**预期返回**：
```json
[{"name": "沪深300", "code": "000300.SH", "type": "index"}]
```

**LLM 操作**：记录 `code = "000300.SH"`，用于回测公式中的基准参数。

---

### Step 3 — 确认数据名称

```bash
python scripts/call.py confirmDataMulti '{"data_desc": "A股市盈率, 非ST股, 开盘非涨停"}'
```

**预期返回**：
- `A股市盈率（PE）〔估值数据〕` → dimension=two
- `非ST股` → dimension=two, is_bool=true
- `开盘非涨停` → dimension=two, is_bool=true

---

### Step 4 — 执行公式

```bash
python scripts/call.py runMultiFormula '{
  "task_id": "<Step 0 的 task_id>",
  "begin_date": 20150101,
  "formulas": [
    "Filter=缺失填零(\"非ST股\")*缺失填零(\"开盘非涨停\")",
    "PE_valid=\"A股市盈率（PE）〔估值数据〕\"*(\"A股市盈率（PE）〔估值数据〕\">0)*\"Filter\"",
    "Signal=(\"PE_valid\">0)*(排名(\"PE_valid\",升序)<百分比(板块(万得全A),0.2))*\"Filter\"",
    "NAV=回测(\"Signal\",当天收盘买入,返回复利净值,信号按列归一)",
    "BenchmarkNAV=回测(指数(000300.SH),当天收盘买入,返回复利净值)"
  ],
  "intents": ["过滤条件", "有效PE（排除负PE）", "PE最低20%信号", "策略净值", "沪深300基准净值"]
}'
```

**关键点**：
- PE > 0 排除负值/亏损股
- `排名(..., 升序) < 百分比(...)` 选出最小的 20%
- `指数(000300.SH)` 用 Step 2 确认的 code

---

### Step 5 — 同时验证策略和基准

```bash
python scripts/call.py readData '{"ids": ["<NAV的data_id>", "<BenchmarkNAV的data_id>"], "mode": "precheck"}'
```

**预期返回**：两条净值曲线的 `first_value / last_value / total_return`，可直接对比超额收益。

---

### Step 6（可选）— 画对比图

```bash
python scripts/call.py renderChart '{
  "title": "低PE策略 vs 沪深300（2015至今）",
  "lines": [
    {"id": "<NAV的data_id>", "name": "低PE 20% 等权", "axis": "left"},
    {"id": "<BenchmarkNAV的data_id>", "name": "沪深300", "axis": "left"}
  ]
}'
```

---

## 注意事项

- PE 为负代表公司亏损，必须 `PE > 0` 过滤，否则负PE股也会被误选为"低PE"
- `百分比(板块(万得全A), 0.2)` 返回全市场20分位的阈值，与 `排名` 结合选出最低20%
- 若某日 Signal 全零（极端市场），回测会产生 NaN，属正常；readData 会报告 NaN 率
