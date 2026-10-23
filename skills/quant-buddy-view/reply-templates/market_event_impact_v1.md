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

## 一句话总结合同

`一句话总结` 是面向用户原问题收口的模块，综合四类输入：用户原问题原话；预研增强任务说明（背景/关注点/矛盾/隐含需求）；本轮联网检索可靠信息（必须有来源和发布日期）；前文已验证平台数据。

- 2–4 个分句，总长 150–300 字；第一句直接回答原问题，不复述问题本身。
- 平台数据只选最有决策价值的 1–2 个，带日期口径，不堆数字。
- 外部检索最多 1 条，格式「外部报道（来源，发布日期）显示……」；与平台数据时点或口径不同必须点明；无可靠外部结果则省略，不得编造。
- 末句给条件式观察（若……则……），不预测明日涨跌、不给目标价或精确点位。
- 不描述搜索、读取、模板、工具等过程；不得出现前文没有的指标和结论。
- 区分已发生事实、市场反应、传导机制与推断；收口给影响窗口与后续观察变量。

## Markdown Skeleton

```markdown
**一句话总结**：{直接回答事件影响判断；区分已验证事实与市场反应；有可靠外部结果时带来源与发布日期；给影响窗口与观察变量}

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
