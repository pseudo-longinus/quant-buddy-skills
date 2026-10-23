---
id: fund_etf_bond_profile_v1
version: reply_template_v1
output_format: markdown
default_reply_scope: full_answer
source_playbooks:
  - 06_fund_etf_bond.md
  - 09_dashboard_guidance.md
---

# Fund ETF Bond Profile

Use for fund, ETF, index fund, bond fund, and similar vehicle pages.

## Output Contract

- Make the tracked index or underlying asset explicit.
- Distinguish fund price/net value, premium/discount, and underlying index valuation.
- Use holding and industry distribution only when available from verified data or cited disclosure.
- Avoid stock-style single-company fundamental claims.
- State the valuation percentile window and original currency/price-vs-NAV convention.
- Missing holdings, premium/discount, tracking error, or bond terms stay `--`; do not estimate them.

## 一句话总结合同

`一句话总结` 是面向用户原问题收口的模块，综合四类输入：用户原问题原话；预研增强任务说明（背景/关注点/矛盾/隐含需求）；本轮联网检索可靠信息（必须有来源和发布日期）；前文已验证平台数据。

- 2–4 个分句，总长 100–220 字；第一句直接回答原问题，不复述问题本身。
- 平台数据只选最有决策价值的 1–2 个，带日期口径，不堆数字。
- 外部检索最多 1 条，格式「外部报道（来源，发布日期）显示……」；与平台数据时点或口径不同必须点明；无可靠外部结果则省略，不得编造。
- 末句给条件式观察（若……则……），不预测明日涨跌、不给目标价或精确点位。
- 不描述搜索、读取、模板、工具等过程；不得出现前文没有的指标和结论。
- 必须说清基金价格、净值与底层估值的关系；有溢价/折价时必须点明。

## Markdown Skeleton

```markdown
**一句话总结**：{直接回答用户问题；说清价格/净值/底层估值关系与溢价状态；1–2 个关键数据（带日期口径）；条件式收尾}

## 核心数据

| 指标 | 最新值 | 口径 |
|------|--------|------|
| 现价/净值 | {price_or_nav} | {date} |
| 规模 | {aum} | {date} |
| 折溢价 | {premium_discount} | 场内价格 vs 净值 |
| 跟踪误差 | {tracking_error} | {period} |

## 收益对比

| 区间 | 本基金 | 标的指数 | 同类均值 | 排名/分位 |
|------|--------|----------|----------|-----------|
| 近1月 | {fund_ret_1m} | {index_ret_1m} | {peer_ret_1m} | {rank} |
| 近3月 | {fund_ret_3m} | {index_ret_3m} | {peer_ret_3m} | {rank} |
| 近1年 | {fund_ret_1y} | {index_ret_1y} | {peer_ret_1y} | {rank} |
| 近3年 | {fund_ret_3y} | {index_ret_3y} | {peer_ret_3y} | {rank} |

## 估值定位

| 指标 | 最新值 | 历史分位 | 说明 |
|------|--------|----------|------|
| PE | {pe} | {pe_pct} | 跟踪指数口径 |
| PB | {pb} | {pb_pct} | 跟踪指数口径 |
| 股息率 | {dividend_yield} | {dy_pct} | 跟踪指数口径 |

## 持仓 / 行业分布

| 类型 | 名称 | 占比 | 来源 |
|------|------|------|------|
| 前十大持仓 | {holding} | {weight} | {source} |
| 行业 | {industry} | {weight} | {source} |

## 可转债专项（仅可转债页面保留）

| 指标 | 最新值 | 口径 |
|------|--------|------|
| 转股价值 | {conversion_value} | {date} |
| 纯债价值 | {bond_floor} | {date} |
| 转股溢价率 | {conversion_premium} | {date} |
| 剩余年限 | {remaining_years} | {date} |

{任一字段未返回时填 `--`，不得估算。}

## 建议

| 状态 | 定性建议 |
|------|----------|
| 超买 | {view} |
| 合理 | {view} |
| 低估 | {view} |

## 风险

- {risk_1}
- {risk_2}

> 数据截至 {computed_at 日期}；不构成投资建议。
```
