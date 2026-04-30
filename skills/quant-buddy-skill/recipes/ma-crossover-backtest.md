# 示例一：均线策略选股 + 回测

## 用户意图

> "帮我做一个5日均线上穿20日均线的选股策略，看看历史回测表现怎么样"

---

## 工具调用序列

### Step 0 — 初始化会话

```bash
python scripts/call.py newSession
```

---

### Step 1 — 查案例（cases_index 优先）

**1a. 读取 `presets/cases_index.yaml`**，搜索 tags 含 `均线`、`MA`、`金叉`、`回测` 的卡片。

**1b.** 找到后调 `getCardFormulas` 批量拉取：

```bash
python scripts/call.py getCardFormulas '{"card_ids": ["<相关卡片id>"]}'  
```

**1c.** 目录中未找到才 fallback：

```bash
python scripts/call.py searchSimilarCases '{"query": "均线金叉买入区间持仓回测", "top_k": 3}'
```

**LLM 操作**：理解案例中均线/金叉公式结构，提炼思路后针对用户的 5/20 均线需求重新组织公式，不照抄案例。

---

### Step 2 — 确认数据名称

```bash
python scripts/call.py confirmDataMulti '{"data_desc": "全市场每日收盘价, 非ST股"}'
```

**预期返回**：
- `全市场每日收盘价` → `index_title: "全市场每日收盘价"`（dimension=two）
- `非ST股` → `index_title: "非ST股"`（dimension=two, is_bool=true）

**LLM 操作**：用返回的 `index_title` 写进公式，不要用原始查询词。

---

### Step 3 — 执行公式（生成信号 + 回测）

```bash
python scripts/call.py runMultiFormulaBatch '{
  "task_id": "<Step 0 的 task_id>",
  "begin_date": 20150101,
  "formulas": [
    "MA5=平均(\"全市场每日收盘价\", 5)",
    "MA20=平均(\"全市场每日收盘价\", 20)",
    "金叉信号=(\"MA5\">\"MA20\")*(昨天(\"MA5\")<=昨天(\"MA20\"))*板块(万得全A)*缺失填零(\"非ST股\")",
    "死叉信号=(\"MA5\"<\"MA20\")*(昨天(\"MA5\")>=昨天(\"MA20\"))*板块(万得全A)*缺失填零(\"非ST股\")",
    "持仓区间=进出场区间(\"金叉信号\",\"死叉信号\")",
    "NAV=回测(\"持仓区间\",当天收盘买入,返回复利净值,信号按列归一)"
  ],
  "intents": ["5日均线", "20日均线", "金叉信号（排除ST）", "等权回测净值"]
}'
```

**关键点**：
- 4 个公式共享同一个 `task_id`，后面的公式才能引用前面的变量
- 返回每条公式的 `data_id`，记录 `NAV` 对应的 `data_id`

---

### Step 4 — 验证回测结果

```bash
python scripts/call.py readData '{"ids": ["<NAV的data_id>"], "mode": "precheck"}'
```

**预期返回**：
```json
{
  "type": "nav_1d",
  "first_value": 1.0,
  "last_value": 3.xx,
  "total_return": 2.xx,
  "curve_samples": [[20150101, 1.0], ..., [20260227, 3.xx]]
}
```

---

### Step 5（可选）— 渲染净值曲线图

```bash
python scripts/call.py renderChart '{
  "title": "均线金叉策略净值（2015至今）",
  "lines": [{"id": "<NAV的data_id>", "name": "MA5/20金叉策略"}],
  "width": 1400,
  "height": 600
}'
```

**LLM 操作**：返回 `data.base64`，解码后保存为 PNG 文件，或直接展示给用户。

---

## 常见错误与处理

| 错误 | 原因 | 处理 |
|------|------|------|
| `公式变量未找到` | task_id 不一致，Signal 找不到 MA5 | 确保 4 个公式用同一个 task_id |
| `数据名不存在` | 公式里写的名称和 confirmDataMulti 返回的 index_title 不一致 | 以 index_title 为准 |
| `matchQuality=low` | searchSimilarCases 没搜到好模板 | 换 query 关键词重试一次 |
