---
id: single_stock_valuation_quality_v1
version: reply_template_v1
output_format: markdown
default_reply_scope: full_answer
source_playbooks:
  - 03_single_stock_deep_dive.md
  - 09_dashboard_guidance.md
---

# Single Stock Valuation And Quality Report

Use for a single listed stock page or answer focused on valuation, financial quality, capital flow, risk, and qualitative holding posture.

## Output Contract

- Start directly with the report title. Do not expose routing, tool, file, or data-fetch process notes.
- Keep the seven major sections in order. Preserve Markdown tables for numeric sections.
- Use the data actually available from the page, formula outputs, grants, or stock profile. If a field is missing, write `--` or state that the dimension was not returned; do not infer a precise value.
- Separate `## 四、计算维度` and `## 五、波动率与风险`.
- End with a data-date disclaimer and no investment-advice claim.
- If the page metadata or current analysis calls for a dashboard appendix, append `dashboard_guidance_appendix_v1` after the disclaimer.

## Markdown Skeleton

```markdown
**{股票名}（{代码}）全面分析**

时间：截至 {computed_at 日期} | 数据来源：QB / 活页实时数据

---

## 一、行情与估值

**最新价**：{close_price} | **近20日**：{ret_20}% | **近60日**：{ret_60}% | **近120日**：{ret_120}% | **近250日**：{ret_250}%

| 指标 | 最新值 | 1Y 分位 | 3Y 分位 | 5Y 分位 | 信号 |
|------|--------|---------|---------|---------|------|
| PE(TTM) | {pe_ttm} | {pe_1y_pct} | {pe_3y_pct} | {pe_5y_pct} | {signal} |
| PB | {pb_ratio} | {pb_1y_pct} | {pb_3y_pct} | {pb_5y_pct} | {signal} |
| PS(TTM) | {ps_ttm} | {ps_1y_pct} | {ps_3y_pct} | {ps_5y_pct} | {signal} |
| 股息率 | {dividend_yield} | {dy_1y_pct} | {dy_3y_pct} | {dy_5y_pct} | {signal} |

> 分位接近 100% = 估值历史高位；接近 0% = 历史低位；40%~60% = 中性区间。

---

## 二、财务分析

> 最近报告期：{financial_latest_date}

| 指标 | 单季最新 | 单季 YoY | 单季 QoQ | TTM | TTM YoY | 年度 | 年度 YoY | 信号 |
|------|---------|----------|----------|-----|---------|------|----------|------|
| 收入增速 | {revenue_growth} | {revenue_q_yoy} | {revenue_q_qoq} | {revenue_ttm} | {revenue_ttm_yoy} | {revenue_annual} | {revenue_annual_yoy} | {signal} |
| 扣非增速 | {non_recurring_profit_growth} | {profit_q_yoy} | {profit_q_qoq} | {profit_ttm} | {profit_ttm_yoy} | {profit_annual} | {profit_annual_yoy} | {signal} |
| 毛利率 | {gross_margin} | {gross_q_yoy} | {gross_q_qoq} | {gross_ttm} | {gross_ttm_yoy} | {gross_annual} | {gross_annual_yoy} | {signal} |
| 净利率 | {net_margin} | {net_q_yoy} | {net_q_qoq} | {net_ttm} | {net_ttm_yoy} | {net_annual} | {net_annual_yoy} | {signal} |
| ROE | {roe} | {roe_q_yoy} | {roe_q_qoq} | {roe_ttm} | {roe_ttm_yoy} | {roe_annual} | {roe_annual_yoy} | {signal} |
| ROIC(TTM) | -- | -- | -- | {roic_ttm} | {roic_ttm_yoy} | {roic_annual} | {roic_annual_yoy} | {signal} |
| 经营现金流 | {operating_cash_flow} | {cash_q_yoy} | {cash_q_qoq} | {cash_ttm} | {cash_ttm_yoy} | {cash_annual} | {cash_annual_yoy} | {signal} |

{1-2 句财务定性点评，只基于上表与已引用资料。}

---

## 三、资金 / 交易特征

| 指标 | 最新值 | 5日均线 | 60日趋势 | 3Y分位 | 信号 |
|------|--------|---------|----------|--------|------|
| 成交额占比 | {turnover_ratio} | {turnover_ma_5} | {turnover_trend_60} | {turnover_3y_pct} | {signal} |
| 做空比例 | {short_selling_ratio} | -- | {short_trend_60} | {short_3y_pct} | {signal} |
| 基金持仓比例 | {fund_holding_ratio} | -- | {fund_trend_60} | {fund_3y_pct} | {signal} |

{1 句资金特征结论。}

---

## 四、计算维度

{按返回维度分组；每个维度一个小标题和一张指标表。没有额外维度时写“本轮无额外计算维度”。}

### {维度名}得分：{score} {signal}

| 指标 | 最新值 | 说明/口径 | 信号 |
|------|--------|-----------|------|
| {indicator_name} | {value} | {description} | {signal} |

---

## 五、波动率与风险

| 指标 | 最新值 | 1Y分位 | 3Y分位 | 5Y分位 | 信号 |
|------|--------|--------|--------|--------|------|
| 年化波动率 | {annualized_volatility} | {vol_1y_pct} | {vol_3y_pct} | {vol_5y_pct} | {signal} |
| 标准差 | {stddev} | {std_1y_pct} | {std_3y_pct} | {std_5y_pct} | {signal} |

---

## 六、消息面（近 30 日）

| 时间 | 事件 | 影响 |
|------|------|------|
| {YYYY-MM-DD} | {来源 + 事件摘要} | {impact_signal} |

---

## 七、综合观察

**估值定性**：{基于 PE/PB/PS 分位的一句话}

**财务趋势**：{基于收入、利润率、ROE、现金流的一句话}

**资金特征**：{基于成交额占比、基金持仓、做空比例的一句话}

**计算维度**：{基于计算维度表的一句话}

**风险因子**：{基于波动率、现金流、估值高低的一句话}

| 持仓情况 | 定性建议 |
|---------|---------|
| 空仓 | {基于估值分位 + 财务趋势的定性描述，不给具体价位} |
| 已持有 | {基于波动率分位 + 财务趋势的定性描述，不给具体价位} |
| 高位浮盈 | {基于估值高位 + 波动率的定性描述，不给具体价位} |

**一句话总结**：{最核心判断，必须有数据支撑，不预测明日涨跌}

---

> 数据截至 {computed_at 日期}；不构成投资建议。
```
