# quant-buddy-skills

[中文](README.md) | [English](README.en.md)

A 股、港股、美股量化分析 Agent Skill。支持 A 股行情、估值、财务数据查询、选股筛选、因子计算、策略回测、净值对比和图表渲染；港股、美股当前支持行情价格类数据查询。

官网：[https://www.quantbuddy.cn](https://www.quantbuddy.cn)

## Skills

| Skill | 描述 |
|-------|------|
| quant-buddy-skill | 查询 A 股行情、估值、财务数据；查询港股、美股行情价格数据；支持 A 股选股筛选、因子计算、策略回测、净值对比、行业聚合排名、上传自有因子 CSV 和图表渲染 |

## 功能特性

- 股票与指数行情查询：收盘价、开盘价、涨跌幅、成交额、成交量、换手率等。
- A 股估值与财务数据：PE、PB、市值、营业收入、净利润、归母净利润、ROE、总资产、资产负债率等。
- A 股量化研究：选股筛选、因子计算、策略回测、净值对比、行业聚合排名。
- 数据与图表：支持上传自有因子 CSV、下载数据、渲染净值曲线和行情图表。

## 数据覆盖范围

| 市场 | 行情 | 估值（PE/PB/市值） | 财务数据 | 选股/回测 |
|------|------|-------------------|---------|----------|
| A 股（沪深主板/创业板/科创板/北交所） | ✅ | ✅ | ✅ | ✅ |
| 港股 | ✅ | ❌ | ❌ | ❌ |
| 美股（NASDAQ / NYSE / AMEX） | ✅ | ❌ | ❌ | ❌ |
| 主要宽基指数（沪深300、中证500等） | ✅ | 部分支持 | — | 可作为基准/股池 |

> 港股、美股目前仅支持行情价格类数据，例如收盘价、开盘价、最高价、最低价、涨跌幅、成交量、成交额。估值和财务数据暂不支持。

## 安装

### npx（推荐）

```bash
# 首次安装（新用户）——一次装到全局所有检测到的 Agent（Claude Code、Cursor、Copilot 等）
npx skills add pseudo-longinus/quant-buddy-skills -g --all

# 版本更新（已安装过的老用户）
npx skills update pseudo-longinus/quant-buddy-skills -y
```

Windows 用户若安装时报 symlink / 权限错误，可在安装命令末尾追加 `--copy` 重试：

```bash
npx skills add pseudo-longinus/quant-buddy-skills -g --all --copy
```

不知道当前安装位置时，可运行：

```bash
npx skills list -g --json
```

安装时会提示选择目标 IDE（Claude Code、GitHub Copilot、Cursor、Windsurf 等），以及全局安装或项目级安装。

### 手动安装

**Claude Code**

```bash
git clone https://github.com/pseudo-longinus/quant-buddy-skills.git
cp -r quant-buddy-skills/skills/quant-buddy-skill ~/.claude/skills/
```

**GitHub Copilot**

```bash
cp -r quant-buddy-skills/skills/quant-buddy-skill ~/.copilot/skills/
```

**Cursor / Windsurf / 其他**

参考 [npx skills 支持的 IDE 列表](https://www.npmjs.com/package/skills#supported-agents)，将 `skills/quant-buddy-skill/` 目录复制到对应路径。

## 配置 API Key

首次使用前需要配置 quant-buddy API Key：

1. 前往官网 [https://www.quantbuddy.cn](https://www.quantbuddy.cn) 注册并获取 API Key。
2. 编辑 skill 目录下的 `config.json`，将 `api_key` 字段填入你的 Key。
3. 或在支持写入本地文件的 Agent 对话中发送：`帮我配置 APIkey：sk-xxxxxxxx`。

高级用法：也可以通过 `config.local.json` 或环境变量 `QUANT_BUDDY_API_KEY` 覆盖 `config.json` 中的 `api_key`。

## 运行环境

- Python 3.8+，推荐 Python 3.11。
- 核心行情、财务、选股和回测能力仅依赖 Python 标准库。
- 可选依赖：
  - `python-dateutil`：事件研究辅助功能使用。
  - `Pillow`：图表图片格式转换时使用；未安装时会降级保存原始图片数据。
  - `requests`：事件新闻搜索辅助功能使用。
- 可选环境变量：`BOCHA_API_KEY`，仅事件新闻搜索辅助功能使用。

## 安全与隐私

- quant-buddy API Key 用于请求 quant-buddy 平台接口。
- 默认配置文件为 skill 目录下的 `config.json`；本地覆盖文件为 `config.local.json`。
- API Key 仅作为 HTTP `Authorization` 头发送给 quant-buddy 域名，不会写入日志，也不会转发给第三方主机。
- 可选的 `BOCHA_API_KEY` 仅在事件新闻搜索功能启用时使用。

## 故障排查

常见问题见：

- [环境依赖说明](skills/quant-buddy-skill/references/environment.md)
- [故障排查](skills/quant-buddy-skill/references/troubleshooting.md)
- [RU 计费说明](skills/quant-buddy-skill/references/ru-billing.md)

## 联系作者

<p align="center">
  <img src="assets/wechat_qr.jpg" width="180" alt="微信二维码" />
  <br/>
  <sub>扫码添加微信，欢迎交流量化投研</sub>
</p>

## License

MIT
