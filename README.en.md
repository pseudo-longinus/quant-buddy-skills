# quant-buddy-skills

[中文](README.md) | [English](README.en.md)

> **Run formulas, stock screens, factors, and backtests across the full A-share market from an AI Agent.**  
> A-share quant execution layer for Claude Code, Cursor, Codex, GitHub Copilot, Windsurf, and other AI agents.

quant-buddy-skills is not a generic stock data API. It packages **market data, valuation data, financial data, a formula engine, full-market screening, factor calculation, strategy backtesting, NAV comparison, and chart rendering** into agent-callable research workflows.

Traditional data APIs only get raw data out. quant-buddy-skills helps an AI agent turn natural-language research ideas into **executable formulas, platform-side computation, structured results, and reusable tasks**.

Official site: https://www.quantbuddy.cn

```bash
# For Claude Code users
npx skills add pseudo-longinus/quant-buddy-skills -g -a claude-code -s quant-buddy-skill -y
```

Cursor, OpenClaw, and other AI agent users should see the Installation section below.

> This project is for financial data analysis, quantitative research, strategy validation, and educational use only. It is not investment advice, trading advice, a return guarantee, or an automated trading service.

## 30-Second Demo

Tell your AI agent:

```text
Screen all A-shares at 14:30 today. Find companies hitting a 60-trading-day high,
with turnover above 2x the past 20-day average, ranked by intraday return.
```

The agent generates a formula chain. quant-buddy runs the full-market computation on the platform side, then returns only the TopN stock list, metrics, ranking, and charts.

No need to push thousands of rows into the LLM context. No need to manually write data cleaning, field joins, or backtesting code.

## Why Install It

- **Not just data lookup**: formulas, rolling-window statistics, condition filters, factor ranking, and strategy backtesting.
- **Built for full-market A-share cross-sectional computation**: heavy computation runs on the platform side; only results are returned to the agent.
- **Reusable by design**: formulas explored today can be scheduled and rerun tomorrow.
- **Designed for agent workflows**: works with Claude Code, Cursor, Codex, GitHub Copilot, Windsurf, and similar environments.
- **Deepest coverage for A-shares**: market data, valuation, financials, screening, factors, backtesting, and charts. HK and US support currently focuses on market price data.

## What Can You Do In One Sentence

| What You Tell The Agent | What quant-buddy-skills Does |
|---|---|
| “Check Kweichow Moutai's latest close, return, and turnover” | Queries market data and returns structured results |
| “Find the top 10 A-shares breaking above 60-day highs with volume expansion” | Runs full-market formulas, filters, and ranking on the platform side |
| “Backtest a low PE + high ROE portfolio and compare it with CSI 300” | Runs strategy backtesting, benchmark comparison, and NAV chart output |
| “Run this screen every day at 14:30” | Saves validated formulas as reusable tasks |
| “Upload my CSV factor and rank it together with ROE” | Uploads custom factors and uses them in formulas, screening, and charts |

## Skill Matrix

| Capability | Coverage | Example Prompt |
|---|---|---|
| Fast market data lookup | A-shares / HK stocks / US stocks / indices | “Check Kweichow Moutai's latest close, return, and turnover” |
| Valuation and financials | Mainly A-shares | “List CATL's latest ROE, net profit, and debt ratio” |
| Full-market formula computation | Mainly A-shares | “Calculate 20-day and 60-day returns for all A-shares and rank by momentum” |
| Multi-condition stock screening | Mainly A-shares | “Screen non-ST stocks with low PE, high ROE, and expanding turnover” |
| Factor analysis | Mainly A-shares | “Build a composite factor from dividend yield, ROE, and momentum” |
| Strategy backtesting | Mainly A-shares | “Backtest a low PE + high ROE portfolio against CSI 300” |
| Intraday tasks | A-share minute-data capability, subject to actual API support | “At 14:30 today, screen the top 30 stocks breaking above 60-day highs with volume expansion” |
| Chart rendering | Candlestick, NAV, benchmark comparison | “Plot the strategy NAV and CSI 300 benchmark” |
| Custom data | CSV factor upload | “Upload my factor CSV and rank it together with ROE” |

## Who Is This For

- **A-share quant researchers** who want to validate screening, factor, event-study, and backtesting ideas quickly.
- **AI agent and coding-tool users** who want Claude Code, Cursor, Codex, or GitHub Copilot to complete research tasks directly.
- **Research automation developers** who want daily review, intraday screens, and strategy monitoring as repeatable jobs.
- **Financial data analysts and content creators** who want structured data, TopN lists, and charts from natural language.

## Who Is This Not For

- Users who need a fully custom low-level data pipeline.
- Users focused mainly on crypto, futures, or deep US fundamental valuation.
- Users expecting automated order execution, return guarantees, or personalized investment advice.

## Real Invocation Examples

The following examples were generated by actual quant-buddy-skill calls on 2026-05-18. Market data changes over time, but the examples show the core workflow: natural language enters the AI agent, formulas are computed on the platform side, and only structured results are returned to the LLM.

### Example 1: Ask In Natural Language, Return Multiple Indicators

User prompt:

```text
Check Kweichow Moutai's latest close price, daily return, and turnover.
```

The agent generates and runs:

```text
贵州茅台收盘 = "全市场每日收盘价" * 取出(贵州茅台)
贵州茅台涨跌幅 = "全市场每日回报率" * 取出(贵州茅台)
贵州茅台成交额 = "全市场每日成交额" * 取出(贵州茅台)
```

Actual result:

| Date | Stock | Close | Daily Return | Turnover |
|---|---|---:|---:|---:|
| 2026-05-18 | Kweichow Moutai | 1323.69 | -0.70% | RMB 4.601B |

This is the shortest path: natural-language prompt -> formula generation -> platform-side data retrieval -> structured result.

### Example 2: Full-Market Formula Computation Without Sending Huge Tables To The LLM

User prompt:

```text
Screen all A-shares that break above their 60-day high today, with turnover greater than 2x the past 20-day average, then rank the top 10 by daily return.
```

The agent generates a formula chain:

```text
A股池 = 板块(万得全A) * 缺失填零("非ST股")
60日高基准 = 昨天(最大("全市场每日最高价", 60))
放量基准 = 昨天(平均("全市场每日成交额", 20))
突破60日新高 = ("全市场每日最高价" > "60日高基准") * "A股池"
成交额放量 = ("全市场每日成交额" > 2 * "放量基准") * "A股池"
排序值 = "突破60日新高" * "成交额放量" * 涨跌幅("全市场每日收盘价")
放量突破Top10 = 取前("排序值", 10, 返回数值)
```

Actual result:

| Rank | Stock | Ticker | Daily Return |
|---:|---|---|---:|
| 1 | 凡拓数创 | SZ301313 | 20.00% |
| 2 | 索辰科技 | SH688507 | 20.00% |
| 3 | 隆达股份 | SH688231 | 18.23% |
| 4 | 蓝思科技 | SZ300433 | 13.97% |
| 5 | 长盈通 | SH688143 | 13.21% |
| 6 | 广信材料 | SZ300537 | 13.12% |
| 7 | 卡倍亿 | SZ300863 | 12.70% |
| 8 | 佰奥智能 | SZ300836 | 11.79% |
| 9 | 线上线下 | SZ300959 | 11.68% |
| 10 | 中巨芯 | SH688549 | 10.48% |

The full-market raw matrix is not pushed into the LLM context. quant-buddy performs the computation, filtering, and ranking on the platform side, then returns only the Top 10 result. In the actual call, reading the final Top 10 detail returned only 10 rows, and the `readData` response showed `cost` = 2 RU.

### Example 3: Explore Once, Save The Formula, Reuse It Later

During exploration, the user can ask:

```text
Design a 14:30 intraday screening condition: break above the 60-day high, turnover above 2x the past 20-day average, and output the top 10 by return.
```

After validation, the formula can be saved as a reusable task:

```json
{
  "name": "volume_breakout_60d_intraday",
  "description": "14:30 intraday 60-day-high breakout with volume expansion",
  "params": {
    "formulas": [
      "A股池 = 板块(万得全A) * 缺失填零(\"非ST股\")",
      "60日高基准 = 昨天(最大(\"全市场每日最高价\", 60))",
      "放量基准 = 昨天(平均(\"全市场每日成交额\", 20))",
      "突破60日新高 = (\"全市场每日最高价\" > \"60日高基准\") * \"A股池\"",
      "成交额放量 = (\"全市场每日成交额\" > 2 * \"放量基准\") * \"A股池\"",
      "排序值 = \"突破60日新高\" * \"成交额放量\" * 涨跌幅(\"全市场每日收盘价\")",
      "放量突破Top10 = 取前(\"排序值\", 10, 返回数值)"
    ],
    "begin_date": 20260101,
    "include_description": true,
    "use_minute_data": true,
    "force_reusable_array": ["放量突破Top10"]
  }
}
```

After that, an agent or scheduler can run the same formula at 14:30 every day:

```bash
GZQ_PARAMS='<the params JSON above>' python scripts/call.py runMultiFormulaBatchStream
```

Then read the final result from the returned `data_id`:

```bash
GZQ_PARAMS='{"ids":["<data_id>"],"mode":"last_column_full"}' python scripts/call.py readData
```

This separates exploration from usage: explore and iterate with natural language first, then reuse stable formulas as production research tasks.

## Why Not Just Another Data API

Most data APIs solve one problem: getting raw data out. In real investment research, users usually need more than that:

- Can I quickly build a custom full-market indicator?
- Can I validate a stock-screening idea without writing data cleaning and backtesting code?
- Can the formula I explored today be reused tomorrow at 14:30 with intraday data?
- Can I avoid pushing huge tables into the LLM context and return only computed results?

The core idea behind quant-buddy-skills is simple: the agent understands the goal and organizes the task, while quant-buddy handles data access, formula computation, financial SOPs, and result delivery.

## Core Advantages

### 1. Formula Engine: From Data Lookup To Indicator Computation

quant-buddy-skills supports formulas that combine market data, valuation data, financial data, window statistics, masks, and ranking logic. Users are not just querying basic fields. They are asking the agent to generate executable full-market formulas.

### 2. Separate Exploration From Reuse

Investment research is not a one-off chat. An idea usually has two stages:

| Stage | User Goal | What quant-buddy-skills Provides |
|---|---|---|
| Exploration | Try ideas, adjust conditions, inspect results | Agent-generated formulas, platform-side computation and backtesting |
| Usage | Reuse a validated formula every day | Stable formula tasks that can be called by agents or schedulers |

### 3. RU-Based Usage And Better Token Efficiency

The common “data + LLM” pattern often pushes large raw tables into the model context and asks the model to process them. That consumes many tokens, slows down responses, and increases context noise.

quant-buddy-skills uses “platform-side computation + result return”: large datasets do not enter the LLM context, formula computation happens on the platform side, and the agent receives structured results, stock lists, statistics, or charts.

### 4. Built-In Financial SOPs

Quantitative research is not only arithmetic. It also requires careful handling of trading calendars, adjusted prices, rolling windows, ranking, benchmarks, event dates, net value curves, and chart output. quant-buddy-skills packages common financial SOPs into agent-callable capabilities.

### 5. Better Infrastructure For Financial Agents

The common pattern is:

```text
Data + LLM
```

quant-buddy-skills uses:

```text
Data + Computation + LLM
```

The difference is that computation is not improvised inside the LLM context with ad hoc code. It is provided as stable platform capability.

## Comparison

| Dimension | News / Research-Report Finance Skill | Quant Framework Documentation Skill | Data API | quant-buddy-skills |
|---|---|---|---|---|
| Core value | Interpret news, generate views | Help agents find docs and write code | Pull raw data | Run research computation on the platform side |
| Full-market A-share screening | Weak | Requires custom code | Requires data stitching | Strong |
| Factors / backtesting | Usually external | Helps write frameworks | User implements it | Built-in workflows |
| Token usage | Medium | Medium / high | High when raw data enters context | Low, returns only results |
| Best users | Content, reports, event tracking | Quant developers | Data engineering, custom pipelines | Quant researchers, research automation, agent users |
| Best scenario | “What does this news affect?” | “How do I call the QMT API?” | “I need raw data” | “A-share screening / factors / backtesting / charts” |

## Data Coverage

| Market | Market Data | Valuation | Financial Data | Screening / Backtesting |
|---|---|---|---|---|
| A-shares | Supported | Supported | Supported | Supported |
| Hong Kong stocks | Supported | Not supported | Not supported | Not supported |
| US stocks | Supported | Not supported | Not supported | Not supported |
| Major broad-based indices | Supported | Partially supported | - | Can be used as benchmarks or universes |

> Hong Kong and US stocks currently focus on market price data, such as close, open, high, low, return, volume, and turnover. Valuation, financial, screening, and backtesting features are mainly available for A-shares.

## Installation

### npx Recommended

New users should install the skill only into the AI agent they actually use. Avoid using `--all` by default: it installs all skills into all supported agents and may create multiple directories or symlinks on the machine.

| Agent you use | Recommended command |
|---|---|
| Claude Code | `npx skills add pseudo-longinus/quant-buddy-skills -g -a claude-code -s quant-buddy-skill -y` |
| Cursor | `npx skills add pseudo-longinus/quant-buddy-skills -g -a cursor -s quant-buddy-skill -y` |
| OpenClaw | `npx skills add pseudo-longinus/quant-buddy-skills -g -a openclaw -s quant-buddy-skill -y` |

If you use another supported agent, replace the value after `-a` with that agent id. Do not omit `-a`, otherwise the CLI may auto-install into multiple agents.

If you use multiple agents, repeat `-a`:

```bash
npx skills add pseudo-longinus/quant-buddy-skills -g -s quant-buddy-skill -a claude-code -a cursor -y
```

List the skills in this repository without installing anything:

```bash
npx skills add pseudo-longinus/quant-buddy-skills --list
```

Update an existing installation:

```bash
npx skills update quant-buddy-skill -g -y
```

If Windows users encounter symlink or permission errors, add `--copy` to the command for the target agent, for example:

```bash
npx skills add pseudo-longinus/quant-buddy-skills -g -a claude-code -s quant-buddy-skill -y --copy
```

Use this only when you explicitly want to install into every supported agent:

```bash
npx skills add pseudo-longinus/quant-buddy-skills -g --all
```

Check the current install location:

```bash
npx skills list -g --json
```

## Configure API Key

Before first use, configure your quant-buddy API key:

1. Go to https://www.quantbuddy.cn to register and get an API key.
2. Edit `config.json` under the skill directory and fill in the `api_key` field.
3. Or send this to an agent environment that can write local files:

```text
Help me configure APIkey: sk-xxxxxxxx
```

## Runtime Requirements

- Python 3.8+, Python 3.11 recommended.
- Core market data, financial data, screening, and backtesting features only depend on the Python standard library.
- Optional dependencies:
  - `python-dateutil`: used by event-study helpers.
  - `Pillow`: used for chart image conversion.
  - `requests`: used by optional event-news search helpers.
- Optional environment variable: `BOCHA_API_KEY`, only used by event-news search helpers.

## Security, Privacy, And Disclaimer

- The quant-buddy API key is only used to request quant-buddy platform APIs.
- The API key is only sent as an HTTP `Authorization` header to declared quant-buddy domains. It is not written to logs and is not forwarded to third-party hosts.
- Optional `BOCHA_API_KEY` is only used when event-news search is enabled.
- This project is for financial data analysis, quantitative research, strategy validation, and educational use only. It is not investment advice, trading advice, a return guarantee, or an automated trading service.
- Backtest results do not represent future returns. Users should verify data definitions, transaction costs, slippage, risk exposure, and compliance requirements independently.

## Troubleshooting

- Environment dependencies: `references/environment.md`
- Troubleshooting: `references/troubleshooting.md`
- RU billing: `references/ru-billing.md`

## Contact

For more strategy examples, integration questions, roadmap updates, and real research workflows, scan the QR codes below to connect or join the community.

<p align="center">
  <table>
    <tr>
      <td align="center">
        <img src="assets/wechat_qr2.jpg" width="180" alt="Personal WeChat QR code" />
        <br/>
        <sub>Personal WeChat</sub>
      </td>
      <td align="center">
        <img src="assets/wechat_group_qr4.jpg" width="180" alt="WeChat group QR code" />
        <br/>
        <sub>WeChat Group</sub>
      </td>
      <td align="center">
        <img src="assets/feishu_group_qr2.png" width="180" alt="Feishu group QR code" />
        <br/>
        <sub>Feishu Group</sub>
      </td>
    </tr>
  </table>
  <br/>
  <sub>Scan to connect and discuss quantitative research, AI agent workflows, and strategy validation cases.</sub>
</p>

## Star History

<a href="https://www.star-history.com/?repos=pseudo-longinus%2Fquant-buddy-skills&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=pseudo-longinus/quant-buddy-skills&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=pseudo-longinus/quant-buddy-skills&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=pseudo-longinus/quant-buddy-skills&type=date&legend=top-left" />
 </picture>
</a>

## License

MIT
