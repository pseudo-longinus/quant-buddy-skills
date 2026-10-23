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

## 一句话总结合同

`一句话总结` 是全篇唯一面向用户原问题收口的模块，必须综合四类输入，缺一不可机械摘要：

1. 用户原问题原话；
2. 预研阶段形成的增强任务说明（补充背景、市场关注点、矛盾点、隐含需求）；
3. 本轮联网检索得到的可靠外部信息（必须有来源链接和发布日期）；
4. 本报告前文已验证的平台数据。

生成规则：

- 共 2–4 个分句，总长 80–200 字；第一句必须直接回答用户原问题，给出核心状态或判断，不复述问题本身。
- 平台数据只选最有决策价值的 1–2 个，带日期口径，不堆叠数字。
- 外部检索结果最多选 1 条最有决策价值的写入总结，格式为「外部报道（来源，发布日期）显示……」；时点或口径与平台数据不同必须点明；本轮没有可靠外部结果则省略该分句，不得编造。
- 最后一个分句给条件式观察条件（若……则……），不预测明日涨跌、不给目标价或精确点位。
- 不描述搜索、读取、模板、工具等过程；不得出现前文没有的指标和结论。

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

**一句话总结**：{首句直接回答用户原问题；接 1–2 个关键平台数据；有可靠外部结果时带来源与发布日期；以条件式观察条件收尾}

## 风险

- {market_risk}
- {fx_or_policy_risk}
- {data_availability_risk}

> 数据截至 {computed_at 日期}；海外市场数据字段以平台实际返回为准，不构成投资建议。
```
