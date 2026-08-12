---
id: market_event_impact_v1
version: reply_template_v1
output_format: markdown
default_reply_scope: full_answer
source_playbooks:
  - 01_macro_event.md
  - 09_dashboard_guidance.md
---

# Macro Market And Event Impact Brief

Use for broad market, index, commodity, or event-impact pages where the answer should explain current market direction and map the event to affected assets.

## Output Contract

- Anchor every interpretation to index, sector, commodity, or event-study data returned by the page or tools.
- Separate market facts from interpretation.
- Keep the conclusion, index table, sector moves, capital conditions, event transmission, positioning framework, risks, and disclaimer in that order.
- Omit structurally unavailable funding, index, sector, or positioning sections. Use `--` only for an occasional missing cell inside a section backed by real data; never substitute turnover for capital flow.
- Do not give precise index targets. Use qualitative positioning and risk framing.
- Append `dashboard_guidance_appendix_v1` only when the current data contains a sustainable tracking signal.

## Markdown Skeleton

```markdown
【结论行】{时间范围} 大盘 {方向}，主线 {赛道/资产}，关键变量 {事件/宏观因素}。

## 指数表

| 指数 | 当日涨跌 | 近5日 | 近20日 | 估值/分位 | 信号 |
|------|----------|-------|--------|-----------|------|
| {index_name} | {day_return} | {ret_5} | {ret_20} | {valuation_pct} | {signal} |

## 板块异动

| 方向 | 板块 | 涨跌幅 | 触发因素 | 备注 |
|------|------|--------|----------|------|
| 涨幅前列 | {sector} | {return} | {driver} | {note} |
| 跌幅前列 | {sector} | {return} | {driver} | {note} |

## 资金面

| 指标 | 最新值 | 变化 | 口径 |
|------|--------|------|------|
| 融资余额 | {margin_balance} | {change} | {source} |
| 北向资金 | {northbound_flow} | {change} | {source} |
| 主力资金 | {main_flow} | {change} | {source} |

## 事件解读

| 影响链条 | 短期影响 | 中期变量 | 受益/受压方向 |
|----------|----------|----------|----------------|
| {event_channel} | {short_term} | {mid_term_variable} | {asset_or_sector} |

## 操作框架

| 账户状态 | 定性框架 |
|----------|----------|
| 低仓位 | {risk_budget_view} |
| 中性仓位 | {rebalance_view} |
| 高仓位 | {risk_control_view} |

## 风险

- {risk_1}
- {risk_2}
- {risk_3}

> 数据截至 {computed_at 日期}；事件解读仅代表历史统计和当前数据口径，不构成投资建议。
```
