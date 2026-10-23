---
id: sector_theme_opportunity_v1
version: reply_template_v1
output_format: markdown
default_reply_scope: full_answer
source_playbooks:
  - 02_sector_theme.md
  - 09_dashboard_guidance.md
---

# Sector Theme Opportunity Report

Use for a sector, industry, or theme page that identifies a stock pool, ranks candidates, and explains catalysts and risks.

## Output Contract

- The stock pool must come from verified Quant Buddy assets or explicit page data.
- Rank by the metric named in the page or user request; state the ranking criterion.
- Do not include unverified companies in the core stock pool.
- Distinguish listed-stock data from non-listed-company background.
- Preserve the conclusion, sector overview, verified stock pool, sub-themes, catalysts/risks, and disclaimer.
- Missing values stay `--`; an unverified company must not be promoted into the core pool.

## 一句话总结合同

`一句话总结` 是面向用户原问题收口的模块，综合四类输入：用户原问题原话；预研增强任务说明（背景/关注点/矛盾/隐含需求）；本轮联网检索可靠信息（必须有来源和发布日期）；前文已验证平台数据。

- 2–4 个分句，总长 150–300 字；第一句直接回答原问题，不复述问题本身。
- 平台数据只选最有决策价值的 1–2 个，带日期口径，不堆数字。
- 外部检索最多 1 条，格式「外部报道（来源，发布日期）显示……」；与平台数据时点或口径不同必须点明；无可靠外部结果则省略，不得编造。
- 末句给条件式观察（若……则……），不预测明日涨跌、不给目标价或精确点位。
- 不描述搜索、读取、模板、工具等过程；不得出现前文没有的指标和结论。
- 必须回答主线是否仍有效、主要分歧是什么、什么条件下退潮；不得把主题热度等同于业绩兑现。

## Markdown Skeleton

```markdown
**一句话总结**：{直接回答主线是否有效与核心矛盾；接 1–2 个关键平台数据；有可靠外部催化时带来源与发布日期；给退潮/延续条件}

## 赛道概览

{产业链上下游一句话；当前景气信号，标注来源和时点。}

## 核心标的池

| 排名 | 标的 | 代码 | 现价 | 涨跌幅 | 市值 | PE | 近20日 | 近60日 | 财务速览 | 入选理由 |
|------|------|------|------|--------|------|----|--------|--------|----------|----------|
| 1 | {name} | {ticker} | {price} | {return} | {market_cap} | {pe} | {ret_20} | {ret_60} | {financial_snapshot} | {reason} |

## 主线 / 子方向

| 子方向 | 代表标的 | 产业逻辑 | 数据证据 |
|--------|----------|----------|----------|
| {sub_theme} | {assets} | {logic} | {evidence} |

## 催化与风险

| 类型 | 内容 | 观察指标 |
|------|------|----------|
| 催化 | {catalyst} | {monitor_metric} |
| 风险 | {risk} | {monitor_metric} |

## 声明

> 数据截至 {computed_at 日期}；不构成投资建议。
```
