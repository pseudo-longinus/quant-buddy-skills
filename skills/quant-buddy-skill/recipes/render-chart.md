# 示例四：生成多策略净值对比图

## 用户意图

> "我已经跑了两个策略的回测，帮我把净值曲线画成一张图，并和沪深300比较"

---

## 前置条件

假设已通过 `runMultiFormula` 得到以下 `data_id`：
- 策略A净值：`nav_aaa111`
- 策略B净值：`nav_bbb222`
- 沪深300净值：`nav_ccc333`

如果还没跑，先参考示例一（均线策略）或示例二（低PE策略）的 Step 3~4。

---

## 工具调用序列

### Step 1 — 验证三条净值曲线的基本情况

```bash
python scripts/call.py readData '{
  "ids": ["nav_aaa111", "nav_bbb222", "nav_ccc333"],
  "mode": "precheck",
  "sample_points": 50
}'
```

**LLM 操作**：
- 确认三条曲线的起止日期一致（都从 `begin_date` 开始）
- 检查 `last_value` 对比，判断哪个策略更优
- 若曲线出现异常（如 last_value=0 或 NaN 率过高），先排查公式错误

---

### Step 2 — 渲染对比图

```bash
python scripts/call.py renderChart '{
  "title": "策略A vs 策略B vs 沪深300 净值对比",
  "lines": [
    {"id": "nav_aaa111", "name": "策略A：均线金叉", "axis": "left"},
    {"id": "nav_bbb222", "name": "策略B：低PE 20%", "axis": "left"},
    {"id": "nav_ccc333", "name": "沪深300基准", "axis": "left"}
  ],
  "width": 1400,
  "height": 600,
  "start_date": 20150101
}'
```

**预期返回**：
```json
{
  "success": true,
  "data": {
    "base64": "iVBORw0KGgoAAAANSUhEUgAA...",
    "lines_count": 3,
    "width": 1400,
    "height": 600,
    "errors": []
  }
}
```

---

### Step 3 — 保存图片（Python 示例）

LLM 可以把 base64 解码并保存：

```python
import base64
b64 = "<返回的 base64 字符串>"
with open("strategy_comparison.png", "wb") as f:
    f.write(base64.b64decode(b64))
print("图片已保存到 strategy_comparison.png")
```

---

## 二维数据绑定资产（非净值曲线的画法）

如果要画某只个股的价格走势（二维数据中的某一列），需要额外传 `ticker`：

```bash
python scripts/call.py renderChart '{
  "title": "贵州茅台收盘价",
  "lines": [
    {"id": "<收盘价data_id>", "name": "600519.SH", "axis": "left", "ticker": "600519.SH"}
  ]
}'
```

---

## 注意事项

| 场景 | 处理 |
|------|------|
| `errors` 非空 | 某条 line 的 id 不存在或数据类型不支持渲染 |
| 净值曲线起点不一致 | 用 `start_date` 截断至同一起点再渲染 |
| 图片太小看不清 | 调大 `width`（最大建议 1800）和 `height`（最大建议 900） |
| 需要左右双轴 | 把量纲差异大的曲线（如换手率 vs 净值）设为 `"axis": "right"` |
