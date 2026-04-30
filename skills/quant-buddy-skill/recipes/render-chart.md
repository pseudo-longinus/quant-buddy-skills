# 示例四：生成多策略净值对比图

## 用户意图

> "我已经跑了两个策略的回测，帮我把净值曲线画成一张图，并和沪深300比较"

---

## 前置条件

假设已通过 `runMultiFormulaBatch` 得到以下 `data_id`：
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
| **本地自绘净值曲线**（不走 renderChart，直接用 `curve_samples` / `last_column_full` 点序列 matplotlib 画图） | **必须**先做交易日补齐 + 前向填充，否则稀疏点直接连线会跨缺口斜连，出现视觉上的阶梯/折断（详见下方「本地自绘净值曲线兜底规则」） |

---

## 本地自绘净值曲线兜底规则（硬规则）

**触发场景**：LLM 拿到 `readData` 返回的 `curve_samples` / `last_column_full.values` 等**稀疏点序列**（非完整日频）后，在本地用 matplotlib 自行画图（例如批量回测出图、落盘 PNG 用于报告）。

**问题**：`curve_samples` 是等间距采样点，不是逐交易日序列；`last_column_full` 对"持仓区间外"的日期也可能没有点。直接 `plt.plot(dates, navs)` 会把两个相距数月的点用一条斜线连起来，视觉上就是用户反馈的「曲线阶梯状/长斜线」异常。

**强制兜底**：绘图函数内必须做一次交易日重建 + ffill，**仅用于画图，不要回写到落盘数据或指标计算**（年化/夏普/回撤必须用原始 `curve`）。

```python
import pandas as pd
import matplotlib.pyplot as plt

def plot_nav_curve(curve, title, out_path):
    """curve: List[Tuple[int, float]]  如 [[20240423, 1.0], [20240918, 0.998], ...]"""
    df = pd.DataFrame(curve, columns=["date", "nav"])
    df["date"] = pd.to_datetime(df["date"].astype(str))
    df = df.sort_values("date").drop_duplicates("date")

    # —— 画图层兜底：按工作日重建 + 前向填充 ——
    full_idx = pd.bdate_range(df["date"].min(), df["date"].max())
    df = (df.set_index("date")
            .reindex(full_idx)
            .ffill()
            .rename_axis("date")
            .reset_index())

    fig, ax = plt.subplots(figsize=(14, 4.5))
    ax.plot(df["date"], df["nav"], linewidth=1.2)
    ax.axhline(1.0, color="gray", linestyle=":", linewidth=0.8)
    ax.set_title(title)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
```

**使用边界**：
- `bdate_range` 按自然工作日生成，遇节假日会多几天，ffill 后是水平段，不会再出现跨缺口斜连，视觉已修复。
- 不要把填充后的序列回写到 JSON/Excel，更不要用它重新计算年化/夏普/最大回撤——这些指标必须使用原始 `curve` 的真实成交点。
- 质量自检（可选但推荐）：出图前统计 `coverage_ratio = len(curve) / expected_trading_days` 与 `max_gap_days`，若 `coverage_ratio < 0.5` 或 `max_gap_days > 30` 应提示"数据稀疏，建议改用 `readData` 完整模式重取"。
- 若需要更严格的 A 股交易日历，可把 `pd.bdate_range` 替换成真实交易日序列；否则保持最小改动即可。
