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

## Markdown Skeleton

```markdown
【结论行】{基金/ETF}（{代码}）当前 {价格/净值}，跟踪 {指数/资产}，核心估值分位 {valuation_pct}。

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
