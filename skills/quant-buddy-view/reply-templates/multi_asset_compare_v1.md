---
id: multi_asset_compare_v1
version: reply_template_v1
output_format: markdown
default_reply_scope: full_answer
source_playbooks:
  - 04_multi_asset_compare.md
  - 09_dashboard_guidance.md
---

# Multi Asset Comparison Report

Use for comparing two or more stocks, indexes, funds, or assets with a shared set of dimensions.

## Output Contract

- Use side-by-side tables. Do not turn comparison output into separate single-asset reports.
- If one asset lacks a field, mark only that cell as `--`; do not drop the whole table.
- Explicitly name the comparison winner only for metrics supported by data.
- Keep qualitative advice separate from numeric comparison.
- Keep calculation-dimension comparison and volatility comparison as separate sections.
- Preserve every compared asset; a failed asset is shown with `⚫` / `--` cells instead of silently disappearing.

## Markdown Skeleton

```markdown
**{比较主题} 对比分析**

时间：截至 {computed_at 日期} | 数据来源：QB / 活页实时数据

{一句话：N 只标的中，估值最高 / 增长最快 / 波动最大 / 资金最活跃 分别是谁；核心分歧点是什么。}

---

## 一、行情与估值对比

| 标的 | 现价 | 近20日 | 近60日 | 近250日 | PE(TTM) | PE 3Y分位 | PB | PS(TTM) | 股息率 |
|------|------|--------|--------|---------|---------|-----------|----|---------|--------|
| {asset_a} | {price} | {ret_20} | {ret_60} | {ret_250} | {pe} | {pe_3y_pct} | {pb} | {ps} | {dy} |
| {asset_b} | {price} | {ret_20} | {ret_60} | {ret_250} | {pe} | {pe_3y_pct} | {pb} | {ps} | {dy} |

## 二、财务质量对比

| 标的 | 报告期 | 收入增速 | 扣非增速 | 毛利率 | 净利率 | ROE | ROIC(TTM) | 经营现金流 |
|------|--------|----------|----------|--------|--------|-----|-----------|------------|
| {asset_a} | {date} | {value} | {value} | {value} | {value} | {value} | {value} | {value} |
| {asset_b} | {date} | {value} | {value} | {value} | {value} | {value} | {value} | {value} |

## 三、资金 / 交易特征对比

| 标的 | 成交额占比 | 5日均线 | 60日趋势 | 做空比例 | 基金持仓 |
|------|------------|---------|----------|----------|----------|
| {asset_a} | {turnover_ratio} | {turnover_ma_5} | {trend_60} | {short_ratio} | {fund_holding} |
| {asset_b} | {turnover_ratio} | {turnover_ma_5} | {trend_60} | {short_ratio} | {fund_holding} |

## 四、计算维度对比

### {dimension_name}

| 指标 | {asset_a} | {asset_b} | {asset_c} | 说明/口径 |
|------|-----------|-----------|-----------|-----------|
| 综合分/最终得分 | {score_signal} | {score_signal} | {score_signal} | {description} |
| {indicator_name} | {value_signal} | {value_signal} | {value_signal} | {description} |

## 五、波动率与风险对比

| 标的 | 年化波动率 | 1Y分位 | 3Y分位 | 5Y分位 | 信号 |
|------|------------|--------|--------|--------|------|
| {asset_a} | {vol} | {vol_1y_pct} | {vol_3y_pct} | {vol_5y_pct} | {signal} |
| {asset_b} | {vol} | {vol_1y_pct} | {vol_3y_pct} | {vol_5y_pct} | {signal} |

## 六、综合结论

| 维度 | 更优标的 | 数据依据 |
|------|----------|----------|
| 估值 | {asset} | {evidence} |
| 成长 | {asset} | {evidence} |
| 资金 | {asset} | {evidence} |
| 风险 | {asset} | {evidence} |

> 数据截至 {computed_at 日期}；不构成投资建议。
```
