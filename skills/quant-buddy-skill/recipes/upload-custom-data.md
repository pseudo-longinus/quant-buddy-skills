# 示例三：上传自有因子数据，并在公式中引用

## 用户意图

> "我有一份自己计算好的因子数据（CSV格式），想上传到平台后，直接在公式里和其他数据组合使用"

---

## 工具调用序列

### Step 0 — 初始化会话

```bash
python scripts/call.py newSession
```

---

### Step 1 — 上传因子数据（两阶段：preview → confirm）

`uploadData` 自动处理两阶段。调用一次即可：

```bash
python scripts/call.py uploadData '{
  "file_path": "C:/Users/you/Desktop/my_factor.csv",
  "name": "我的动量因子",
  "dimension": "two"
}'
```

**CSV 格式要求**：
- 二维数据：第一列为日期（格式 `20230101`），其余列标题为股票代码（如 `600519.SH`）
- 一维数据：两列——日期 + 数值

**预期返回**：
```json
{
  "success": true,
  "data_id": "upload_abc123",
  "name": "我的动量因子",
  "rows": 250,
  "cols": 1800
}
```

**LLM 操作**：记录 `data_id = "upload_abc123"` 和 `name = "我的动量因子"`。

---

### Step 2 — 确认上传后数据可查（可选验证）

```bash
python scripts/call.py readData '{"ids": ["upload_abc123"], "mode": "signature"}'
```

**预期返回**：dimension、覆盖率、NaN 率。确认数据已入库、维度正确。

---

### Step 3 — 查案例理解自定义因子公式写法

**3a. 读取 `presets/cases_index.yaml`**，搜索 tags 含 `自定义因子`、`上传`、`选股回测` 的卡片。

**3b.** 找到后调 `getCardFormulas` 拉取。**3c.** 目录中未找到才 fallback：

```bash
python scripts/call.py searchSimilarCases '{"query": "自定义因子选股分组回测"}'
```

---

### Step 4 — 确认配合使用的平台数据

```bash
python scripts/call.py confirmDataMulti '{"data_desc": "非ST股, 开盘非涨停"}'
```

---

### Step 5 — 在公式中用 data_id 引用自有数据

```bash
python scripts/call.py runMultiFormula '{
  "task_id": "<Step 0 的 task_id>",
  "begin_date": 20200101,
  "formulas": [
    "Filter=缺失填零(\"非ST股\")*缺失填零(\"开盘非涨停\")",
    "Factor=取出(\"upload_abc123\")*\"Filter\"",
    "Signal=(排名(\"Factor\",降序)<百分比(板块(万得全A),0.1))*\"Filter\"",
    "NAV=回测(\"Signal\",当天收盘买入,返回复利净值,信号按列归一)"
  ],
  "intents": ["过滤条件", "引用上传因子", "因子最高10%选股", "等权回测净值"]
}'
```

**关键点**：
- `取出("upload_abc123")` — 用 data_id 引用上传数据，不用确认数据名称
- 上传数据与平台数据的维度（资产×日期）必须对齐，否则排名结果会有大量 NaN

---

### Step 6 — 验证回测结果

```bash
python scripts/call.py readData '{"ids": ["<NAV的data_id>"], "mode": "precheck"}'
```

---

## 常见问题

| 问题 | 处理 |
|------|------|
| 上传后 NaN 率过高（>50%） | 检查 CSV 列标题格式（需带交易所后缀，如 `.SH`/`.SZ`） |
| `取出` 返回全零 | begin_date 早于上传数据的起始日期，缩短回测区间 |
| 上传超时（大文件） | 拆分为多个文件，分批上传 |
