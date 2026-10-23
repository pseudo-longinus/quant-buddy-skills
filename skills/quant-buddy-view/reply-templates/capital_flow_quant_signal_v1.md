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
- 资金流向为交易分类代理指标，不等同真实主力意图；总结不得使用「主力进场/出逃」式断言。
- Preserve capital-flow composition, volume-price confirmation, sector linkage, cited news, signal judgment, risks, and disclaimer.
- When the entire requested flow structure is unavailable, omit that optional section. For an occasional missing value inside a valid section use `--`; never replace flow with turnover or transaction amount.

## 一句话总结合同

`一句话总结` 是面向用户原问题收口的模块，综合四类输入：用户原问题原话；预研增强任务说明（背景/关注点/矛盾/隐含需求）；本轮联网检索可靠信息（必须有来源和发布日期）；前文已验证平台数据。

- 2–4 个分句，总长 80–180 字；第一句直接回答原问题，不复述问题本身。
- 平台数据只选最有决策价值的 1–2 个，带日期口径，不堆数字。
- 外部检索最多 1 条，格式「外部报道（来源，发布日期）显示……」；与平台数据时点或口径不同必须点明；无可靠外部结果则省略，不得编造。
- 末句给条件式观察（若……则……），不预测明日涨跌、不给目标价或精确点位。
- 不描述搜索、读取、模板、工具等过程；不得出现前文没有的指标和结论。
- 资金流为交易分类代理而非真实主力意图；信号只给条件与置信边界，不做方向承诺。

## Markdown Skeleton

```markdown
**一句话总结**：{直接回答资金/信号状态；1–2 个关键资金数据（带时点）；有可靠外部背景时带来源与发布日期；给需连续确认的观察条件}

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
