---
id: capital_flow_quant_signal_v1
version: reply_template_v1
output_format: markdown
default_reply_scope: full_answer
source_playbooks:
  - 05_capital_flow_quant.md
  - 09_dashboard_guidance.md
---

# Capital Flow Quant Signal Brief

Use for pages focused on capital flow, turnover, volume-price confirmation, and short-term signal judgment.

## Output Contract

- State data time and unit for every flow number.
- Separate capital-flow composition from signal judgment.
- If detailed main/large/small order data is unavailable, say so instead of inventing a breakdown.
- Do not predict next-day limit-up probability.
- Preserve capital-flow composition, volume-price confirmation, sector linkage, cited news, signal judgment, risks, and disclaimer.
- When the entire requested flow structure is unavailable, omit that optional section. For an occasional missing value inside a valid section use `--`; never replace flow with turnover or transaction amount.

## Markdown Skeleton

```markdown
【结论行】{标的} 今日资金面 {方向}，主力 {main_flow}（净流入/净流出），换手 {turnover}。

## 资金流构成

| 资金类型 | 净流入 | 占成交额 | 数据时点 |
|----------|--------|----------|----------|
| 主力 | {main_flow} | {main_pct} | {time} |
| 大单 | {large_order_flow} | {large_order_pct} | {time} |
| 中单 | {mid_order_flow} | {mid_order_pct} | {time} |
| 小单 | {small_order_flow} | {small_order_pct} | {time} |

## 量价配合

| 指标 | 最新值 | 对比口径 | 信号 |
|------|--------|----------|------|
| 成交额 | {amount} | {amount_compare} | {signal} |
| 换手率 | {turnover} | {turnover_compare} | {signal} |
| 振幅 | {amplitude} | {amplitude_compare} | {signal} |
| 放量状态 | {volume_state} | {volume_reference} | {signal} |

## 板块联动

| 板块 | 当日表现 | 强度排名 | 与标的关系 |
|------|----------|----------|------------|
| {sector} | {sector_return} | {rank} | {relationship} |

## 消息面

| 时间 | 来源 | 摘要 | 影响 |
|------|------|------|------|
| {date} | {source} | {summary} | {impact} |

## 信号判定

| 策略/条件 | 是否命中 | 证据 |
|-----------|----------|------|
| {signal_rule} | {yes_no} | {evidence} |

## 筛选 / 排行结果（名单、TopN 或策略页面保留）

| 排名 | 标的 | 代码 | 信号/得分 | 触发条件 | 关键风险 |
|------|------|------|-----------|----------|----------|
| 1 | {name} | {ticker} | {signal_or_score} | {rule_evidence} | {risk} |

> 只展示当前页面真实命中的名单和口径；不得添加用户未要求的筛选条件。

## 风险与声明

- {risk_1}
- {risk_2}

> 数据截至 {computed_at 日期}；不构成投资建议。
```
