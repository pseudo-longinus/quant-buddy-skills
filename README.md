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

## 与第三方数据接口的区别

quant-buddy 不是简单的数据下载接口，而是面向 Agent 的量化投研 Skill。它将行情、估值、财务、选股、因子计算、回测、净值对比和图表渲染等能力封装成结构化工具，适合让 AI Agent 直接完成完整的投研任务。

| 对比维度 | quant-buddy | 传统第三方数据接口 | quant-buddy 优势 |
|---------|-------------|------------------|-----------------|
| 使用方式 | Agent 通过结构化工具和公式语言完成查询、筛选、回测和图表输出 | 通常需要用户或 Agent 编写代码调用 API | 更适合自然语言驱动的投研流程，减少手写代码 |
| 简单行情查询 | 支持股票、指数的价格、涨跌幅、成交额、成交量等查询 | 通常也支持，需要自行组织查询结果 | 将常用行情指标封装为 Agent 可直接调用的能力 |
| 多条件选股 | 支持全 A 股池、估值、财务、行情和掩码条件组合筛选 | 通常需要手写数据拉取、清洗、合并和排序逻辑 | 复杂筛选更易表达，执行流程更稳定 |
| 因子与回测 | 支持因子计算、信号构建、策略回测、净值曲线和基准对比 | 通常需要自行编写数据处理和回测逻辑 | 平台侧完成计算，Agent 只需声明策略逻辑 |
| 行业/板块分析 | 支持行业聚合、排名、板块内筛选等分析 | 依赖数据源覆盖范围和用户代码实现 | 更适合直接完成行业比较和聚合分析 |
| 事件研究 | 支持事件日期、交易日偏移、区间涨跌幅等分析流程 | 通常需要自行处理事件日期、交易日历和收益计算 | 降低事件研究的代码复杂度 |
| 图表渲染 | 支持净值曲线、行情图表等可视化输出 | 多数数据接口只返回数据，不负责 Agent 侧图片产出 | 可直接生成面向汇报或内容输出的图表 |
| Agent 适配 | 面向 Claude Code、Cursor、Copilot、Windsurf 等 Agent 环境设计 | 多为开发者 API，需要 Agent 自己组织代码和状态 | 更适合在对话中完成端到端任务 |
| 适合场景 | 自然语言选股、策略验证、事件复盘、图表输出、投研自动化 | 数据下载、底层数据拉取、用户自定义代码研究 | quant-buddy 更偏完整投研工作流 |

> quant-buddy-skill 的核心优势在于把数据查询、指标计算、条件筛选、策略回测和图表输出整合为 Agent 可直接执行的完整投研工作流，让自然语言需求更稳定地转化为可验证的量化分析结果。

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
