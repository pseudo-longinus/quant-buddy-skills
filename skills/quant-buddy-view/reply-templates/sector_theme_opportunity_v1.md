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

## Markdown Skeleton

```markdown
【结论行】{赛道/主题} 当前景气 {定性}，核心标的 {N} 只（按 {排序维度} 排序）。

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
