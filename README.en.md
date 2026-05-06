# quant-buddy-skills

[中文](README.md) | [English](README.en.md)

An Agent Skill for quantitative analysis of A-shares, HK stocks, and US stocks. It supports A-share market data, valuation, financial data, stock screening, factor analysis, backtesting, NAV comparison, and chart rendering. HK and US stocks currently support market/price data queries only.

Official website: [https://www.quantbuddy.cn](https://www.quantbuddy.cn)

## Skills

| Skill | Description |
|-------|-------------|
| quant-buddy-skill | Query A-share market, valuation, and financial data; query HK/US stock market and price data; supports A-share screening, factor analysis, backtesting, NAV comparison, industry aggregation ranking, custom factor CSV upload, and chart rendering |

## Features

- Stock and index market data: close, open, price change, turnover, volume, turnover rate, and more.
- A-share valuation and financial data: PE, PB, market capitalization, revenue, net profit, net profit attributable to shareholders, ROE, total assets, debt-to-asset ratio, and more.
- A-share quantitative research: stock screening, factor analysis, strategy backtesting, NAV comparison, and industry aggregation ranking.
- Data and visualization: upload custom factor CSV files, download data, render NAV curves and market charts.

## Data Coverage

| Market | Market Data | Valuation (PE/PB/Market Cap) | Financial Data | Screening / Backtesting |
|--------|-------------|------------------------------|----------------|-------------------------|
| A-shares (Main Board / ChiNext / STAR Market / Beijing Stock Exchange) | Yes | Yes | Yes | Yes |
| HK stocks | Yes | No | No | No |
| US stocks (NASDAQ / NYSE / AMEX) | Yes | No | No | No |
| Major broad-based indices (CSI 300, CSI 500, etc.) | Yes | Partially supported | — | Can be used as benchmark / universe |

> HK and US stocks currently support market/price data only, such as close, open, high, low, price change, volume, and turnover. Valuation and financial data are not supported yet.

## Installation

### npx (Recommended)

```bash
# First-time installation — install globally to all detected Agents (Claude Code, Cursor, Copilot, etc.)
npx skills add pseudo-longinus/quant-buddy-skills -g --all

# Update for existing users
npx skills update pseudo-longinus/quant-buddy-skills -y
```

If Windows reports a symlink or permission error during installation, retry with `--copy`:

```bash
npx skills add pseudo-longinus/quant-buddy-skills -g --all --copy
```

If you are not sure where the skill is installed, run:

```bash
npx skills list -g --json
```

During installation, the CLI will ask you to choose target IDEs or Agents, such as Claude Code, GitHub Copilot, Cursor, and Windsurf, and whether to install globally or at the project level.

### Manual Installation

**Claude Code**

```bash
git clone https://github.com/pseudo-longinus/quant-buddy-skills.git
cp -r quant-buddy-skills/skills/quant-buddy-skill ~/.claude/skills/
```

**GitHub Copilot**

```bash
cp -r quant-buddy-skills/skills/quant-buddy-skill ~/.copilot/skills/
```

**Cursor / Windsurf / Others**

See the [IDE list supported by npx skills](https://www.npmjs.com/package/skills#supported-agents), then copy `skills/quant-buddy-skill/` into the corresponding skills directory.

## Configure API Key

You need to configure a quant-buddy API Key before first use:

1. Sign up or log in at [https://www.quantbuddy.cn](https://www.quantbuddy.cn) and get your API Key.
2. Edit `config.json` in the skill directory and fill in the `api_key` field.
3. Or, in an Agent environment that can write local files, send: `帮我配置 APIkey：sk-xxxxxxxx`.

Advanced usage: `config.local.json` or the `QUANT_BUDDY_API_KEY` environment variable can override the `api_key` in `config.json`.

## Requirements

- Python 3.8+, Python 3.11 recommended.
- Core market data, financial data, screening, and backtesting features only require the Python standard library.
- Optional dependencies:
  - `python-dateutil`: used by event-study helper features.
  - `Pillow`: used for chart image format conversion; if missing, the skill falls back to saving raw image bytes.
  - `requests`: used by the event-news search helper.
- Optional environment variable: `BOCHA_API_KEY`, used only by the event-news search helper.

## Security and Privacy

- The quant-buddy API Key is used to call quant-buddy platform APIs.
- The default config file is `config.json` in the skill directory; local overrides can be stored in `config.local.json`.
- The API Key is sent only as an HTTP `Authorization` header to quant-buddy domains. It is not written to logs or forwarded to third-party hosts.
- The optional `BOCHA_API_KEY` is used only when the event-news search feature is enabled.

## Troubleshooting

See:

- [Environment](skills/quant-buddy-skill/references/environment.md)
- [Troubleshooting](skills/quant-buddy-skill/references/troubleshooting.md)
- [RU Billing](skills/quant-buddy-skill/references/ru-billing.md)

## Contact

<p align="center">
  <img src="assets/wechat_qr.jpg" width="180" alt="WeChat QR code" />
  <br/>
  <sub>Scan to add WeChat. Quant research discussions are welcome.</sub>
</p>

## License

MIT
