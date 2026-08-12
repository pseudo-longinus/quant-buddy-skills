---
id: hk_us_overseas_asset_v1
version: reply_template_v1
output_format: markdown
default_reply_scope: full_answer
source_playbooks:
  - 07_hk_us_overseas.md
  - 09_dashboard_guidance.md
---

# HK US Overseas Asset Brief

Use for Hong Kong, US, and overseas listed assets where market suffix, currency, and data availability must be explicit.

## Output Contract

- Start with market and suffix confirmation.
- State currency and trading venue.
- If financial fields are unavailable for the market, say so and keep the analysis to available price, valuation, and cited public information.
- Do not apply A-share-only fields or assumptions to overseas assets.
- Keep original currency unless the user explicitly asks for conversion and provides a rate convention.
- Omit an overseas data section that is structurally unavailable. Use `--` only for an occasional missing field inside a valid section; do not estimate it from A-share conventions.

## Markdown Skeleton

```markdown
【市场 / 后缀确认行】{标的}: {ticker}（{市场}，{币种}计价）

## 核心行情

| 指标 | 最新值 | 口径 |
|------|--------|------|
| 现价 | {price} | {currency} |
| 涨跌幅 | {return} | {date} |
| 市值 | {market_cap} | {currency} |
| PE | {pe} | {source} |
| PB | {pb} | {source} |

## 区间表现

| 区间 | 标的 | 对比指数/行业 | 相对表现 |
|------|------|---------------|----------|
| 近5日 | {ret_5} | {bench_ret_5} | {relative} |
| 近20日 | {ret_20} | {bench_ret_20} | {relative} |
| 近60日 | {ret_60} | {bench_ret_60} | {relative} |

## 财务与业务信息

| 项目 | 当前值/要点 | 来源 |
|------|-------------|------|
| 最近报告期 | {period} | {source} |
| 收入/利润 | {financial_value} | {source_or_unavailable} |
| 财报电话会要点 | {call_summary} | {source} |

## K 线 / 趋势观察

{基于已返回的趋势或图表内容给 2-3 句解释，不给精确目标价。}

## 资金 / 交易特征

| 指标 | 最新值 | 对比口径 | 信号 |
|------|--------|----------|------|
| 成交量/成交额 | {volume_or_amount} | {period_compare} | {signal} |
| 换手率 | {turnover} | {period_compare} | {signal} |
| 做空比例 | {short_ratio} | {period_compare} | {signal} |

> 港美股未返回 A 股“主力/散户”口径时删除该资金结构，不得用成交额替代。

## 计算维度

### {维度名}得分：{score} {signal}

| 指标 | 最新值 | 说明/口径 | 信号 |
|------|--------|-----------|------|
| {indicator_name} | {value} | {description} | {signal} |

{其余非空维度重复上述小标题和表格；没有额外维度时写“本轮无额外计算维度”。}

## 波动率与风险

| 指标 | 最新值 | 1Y分位 | 3Y分位 | 5Y分位 | 信号 |
|------|--------|--------|--------|--------|------|
| 年化波动率 | {volatility} | {pct_1y} | {pct_3y} | {pct_5y} | {signal} |
| 标准差 | {stddev} | {pct_1y} | {pct_3y} | {pct_5y} | {signal} |

## 消息面 / 披露

| 时间 | 来源 | 事件 | 影响 |
|------|------|------|------|
| {date} | {SEC/交易所/公司公告等} | {summary} | {signal} |

{无一手来源时写“本轮未纳入可核验消息面”，不杜撰。}

## 综合观察

**估值与经营**：{基于已返回估值和财务的一句话}

**相对表现**：{基于区间收益和基准比较的一句话}

**交易与风险**：{基于成交、做空和波动率的一句话}

**一句话总结**：{有数据支撑的核心判断，不预测明日涨跌}

## 风险

- {market_risk}
- {fx_or_policy_risk}
- {data_availability_risk}

> 数据截至 {computed_at 日期}；海外市场数据字段以平台实际返回为准，不构成投资建议。
```
