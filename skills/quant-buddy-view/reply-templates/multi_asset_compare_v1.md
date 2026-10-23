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
- Check each highest/lowest claim against the complete comparison column, including the opening paragraph. PE and PB may have different winners; never generalize one ranking into “两项估值都最高”. Equal displayed values are ties; lower multiples alone do not establish investment superiority.
- Keep qualitative advice separate from numeric comparison.
- Keep calculation-dimension comparison and volatility comparison as separate sections.
- Preserve every compared asset; a failed asset is shown with `⚫` / `--` cells instead of silently disappearing.
- Choose conclusion rows from verified metrics only. Price return is not revenue/earnings growth; market capitalization is not trading liquidity. With only prices, valuation and capitalization, use “区间收益 / 当前回撤 / 估值 / 规模”, and omit unsupported growth, funds and liquidity conclusions.
- Count finite dated observations separately from the calendar axis length. `range_data.dates` may include weekends and holidays with null values; its length is not a trading-day count. Without an exchange calendar use “有效观测数”, state the first/last valid dates, and never call all calendar points trading days.

## 一句话总结合同

`一句话总结` 是面向用户原问题收口的模块，综合四类输入：用户原问题原话；预研增强任务说明（背景/关注点/矛盾/隐含需求）；本轮联网检索可靠信息（必须有来源和发布日期）；前文已验证平台数据。

- 2–4 个分句，总长 120–250 字；第一句直接回答原问题，不复述问题本身。
- 平台数据只选最有决策价值的 1–2 个，带日期口径，不堆数字。
- 外部检索最多 1 条，格式「外部报道（来源，发布日期）显示……」；与平台数据时点或口径不同必须点明；无可靠外部结果则省略，不得编造。
- 末句给条件式观察（若……则……），不预测明日涨跌、不给目标价或精确点位。
- 不描述搜索、读取、模板、工具等过程；不得出现前文没有的指标和结论。
- 用户未指定偏好时不给唯一 winner，按稳健/成长/估值修复/风控优先分别给倾向，并点明各标的的一票否决风险。

## Markdown Skeleton

```markdown
**{比较主题} 对比分析**

时间：截至 {computed_at 日期} | 数据来源：QB / 活页实时数据

{一句话：只比较本轮实际验证的指标，指出有证据支持的差异；没有财务、波动或资金数据时不填写这些判断。}

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
| {已验证的指标维度，如区间收益} | {asset} | {该指标数值、日期和口径} |
| {另一已验证的指标维度，如当前回撤} | {asset} | {该指标数值、日期和口径} |

**一句话总结**：{按用户目标给偏好结论；点明各标的一票否决风险；有可靠外部结果时带来源与发布日期；条件式收尾}

> 数据截至 {computed_at 日期}；不构成投资建议。
```
