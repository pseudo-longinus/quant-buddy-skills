# quant-buddy-skills

[中文](README.md) | [English](README.en.md)

> **让 AI Agent（智能代理）直接在全 A 股上跑公式、选股、因子和回测。**  
> A-share quant execution layer（A 股量化执行层）for Claude Code（编程智能代理）、Cursor（智能编辑器）、Codex（编程智能代理）、GitHub Copilot（编程助手）、Windsurf（智能编辑器）等 AI Agent（智能代理）。

quant-buddy-skills 不是普通股票数据 API（应用程序接口）。它把**行情、估值、财务、公式引擎、全市场筛选、因子计算、策略回测、净值对比和图表渲染**封装成 AI Agent（智能代理）可直接调用的投研工作流。

传统数据 API（应用程序接口）只负责“把数据拉出来”；quant-buddy-skills 负责让 AI Agent（智能代理）把自然语言投研想法转成**可执行公式、平台侧计算、结构化结果和可复用任务**。

官网：https://www.quantbuddy.cn

```bash
# Claude Code 用户
npx skills add pseudo-longinus/quant-buddy-skills -g -a claude-code -s quant-buddy-skill -y
```

Cursor、OpenClaw 或其他 AI Agent（智能代理）用户见下方「安装」章节。

> 本项目用于金融数据分析、量化研究、策略验证和教育用途，不构成投资建议、交易建议、收益承诺或自动交易服务。

## 30 秒示例

你可以直接对 AI Agent（智能代理）说：

```text
筛选今天 14:30 全 A 股中，近 60 个交易日创新高、
成交额高于过去 20 日均值 2 倍、且涨幅排名靠前的公司。
```

AI Agent（智能代理）会生成公式链，由 quant-buddy（量化投研平台）在平台侧完成全市场计算，然后只返回 TopN（前 N 名）名单、指标、排序和图表。

不用把几千只股票的大表塞进 LLM（大语言模型）上下文，也不用手写数据清洗、字段 join（连接）和回测代码。

## 为什么值得安装

- **不是只查数据**：支持公式、窗口统计、条件筛选、因子排序和策略回测。
- **适合全 A 股横截面计算**：平台侧完成大规模计算，只把结果返回给 AI Agent（智能代理）。
- **能沉淀为可复用任务**：今天探索出的公式，明天可以固定时间重复运行。
- **面向 AI Agent（智能代理）工作流设计**：适配 Claude Code（编程智能代理）、Cursor（智能编辑器）、Codex（编程智能代理）、GitHub Copilot（编程助手）、Windsurf（智能编辑器）等环境。
- **A 股能力最完整**：行情、估值、财务、选股、因子、回测、图表；港股和美股当前以行情价格查询为主。

## 一句话能做什么

| 你对 AI Agent（智能代理）说 | quant-buddy-skills 做什么 |
|---|---|
| “查贵州茅台最新收盘价、涨跌幅、成交额” | 调用行情数据，返回结构化结果 |
| “筛全 A 股放量突破 60 日新高的前 10 只” | 平台侧执行全市场公式、筛选、排序，只返回 Top10（前十名） |
| “回测低 PE（市盈率）+ 高 ROE（净资产收益率）组合，相对沪深 300 画净值” | 执行策略回测、基准对比、输出净值曲线 |
| “把这个选股条件每天 14:30 跑一遍” | 将验证过的公式沉淀为可复用任务 |
| “上传我的 CSV（逗号分隔值文件）因子，和 ROE（净资产收益率）一起做排序” | 上传自有因子并参与公式计算、选股和图表输出 |

## Skill Matrix（能力矩阵）

| 能力 | 支持范围 | 典型提示词 |
|---|---|---|
| 快速行情查询 | A 股 / 港股 / 美股 / 指数 | “查一下贵州茅台最新收盘价、涨跌幅和成交额” |
| 估值与财务 | A 股为主 | “列出宁德时代最近报告期 ROE、净利润和资产负债率” |
| 全市场公式计算 | A 股为主 | “计算全 A 20 日收益和 60 日收益，并按动量排序” |
| 多条件选股 | A 股为主 | “筛选非 ST、低 PE、高 ROE、成交额放大的股票” |
| 因子分析 | A 股为主 | “用股息率、ROE、动量做复合因子排序” |
| 策略回测 | A 股为主 | “回测低 PE + 高 ROE 组合，相对沪深 300 画净值” |
| 盘中任务 | A 股分钟数据能力，以实际接口为准 | “今天 14:30 筛选放量突破 60 日新高的前 30 名” |
| 图表渲染 | K 线、净值、基准对比 | “把策略净值和沪深 300 画成图” |
| 自有数据 | CSV（逗号分隔值文件）因子上传 | “上传我的因子 CSV，和 ROE 一起排序” |

## 适合谁

- **A 股量化研究员**：想快速验证选股、因子、事件研究、回测想法。
- **AI Agent（智能代理）和 AI 编程工具用户**：想让 Claude Code（编程智能代理）、Cursor（智能编辑器）、Codex（编程智能代理）、GitHub Copilot（编程助手）直接完成投研任务。
- **投研自动化开发者**：想把每日复盘、盘中筛选、策略监控固化为可重复运行的任务。
- **金融数据分析师 / 内容创作者**：想从自然语言直接得到结构化数据、TopN（前 N 名）名单和图表。

## 不适合谁

- 只需要完全自定义底层数据管道的人。
- 主要研究加密货币、期货或美股基本面深度估值的人。
- 期待自动交易下单、收益承诺或个性化投资建议的人。

## 真实调用示例

以下示例由 quant-buddy-skill 在 2026-05-18 实际调用生成。行情会随市场刷新变化，但可以看到它的核心工作方式：自然语言进入 AI Agent（智能代理），公式引擎在平台侧完成计算，最后只把结构化结果返回给 LLM（大语言模型）。

### 示例 1：自然语言查数，一次返回多个指标

用户可以直接问：

```text
查一下贵州茅台最新收盘价、涨跌幅和成交额。
```

AI Agent（智能代理）会生成并执行公式：

```text
贵州茅台收盘 = "全市场每日收盘价" * 取出(贵州茅台)
贵州茅台涨跌幅 = "全市场每日回报率" * 取出(贵州茅台)
贵州茅台成交额 = "全市场每日成交额" * 取出(贵州茅台)
```

实际返回结果：

| 日期 | 股票 | 收盘价 | 涨跌幅 | 成交额 |
|---|---|---:|---:|---:|
| 2026-05-18 | 贵州茅台 | 1323.69 | -0.70% | 46.01 亿元 |

这个例子展示的是“自然语言提问 -> 公式生成 -> 平台侧取数 -> 结构化结果返回”的最短路径。

### 示例 2：全市场公式计算，不把大表塞进上下文

用户可以问：

```text
筛选全 A 股中，今天突破 60 日新高、成交额高于过去 20 日均值 2 倍，并按当日涨跌幅排序的前 10 名。
```

AI Agent（智能代理）会生成公式链：

```text
A股池 = 板块(万得全A) * 缺失填零("非ST股")
60日高基准 = 昨天(最大("全市场每日最高价", 60))
放量基准 = 昨天(平均("全市场每日成交额", 20))
突破60日新高 = ("全市场每日最高价" > "60日高基准") * "A股池"
成交额放量 = ("全市场每日成交额" > 2 * "放量基准") * "A股池"
排序值 = "突破60日新高" * "成交额放量" * 涨跌幅("全市场每日收盘价")
放量突破Top10 = 取前("排序值", 10, 返回数值)
```

实际返回结果：

| 排名 | 股票 | 代码 | 当日涨跌幅 |
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

这里没有把全市场几千只股票的原始矩阵塞进 LLM（大语言模型）上下文。平台侧先完成全市场计算、筛选和排序，最终只返回 Top10（前十名）结果。实际调用中，读取最终 Top10（前十名）明细只返回 10 行，`readData`（读取数据）响应显示 `cost`（消耗字段）=2 RU（资源用量单位）。

### 示例 3：探索后把公式固化，后续直接调用

第一次使用时，用户可以自然语言探索：

```text
帮我设计一个 14:30 盘中选股条件：突破 60 日新高，同时成交额超过过去 20 日均值 2 倍，输出涨幅前 10。
```

当这个条件被验证后，可以把公式保存为固定任务：

```json
{
  "name": "volume_breakout_60d_intraday",
  "description": "14:30 盘中放量突破 60 日新高选股",
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

之后可以跳过反复解释需求，直接由 AI Agent（智能代理）或调度系统在每天 14:30 调用同一套公式：

```bash
GZQ_PARAMS='<上面的 params JSON（数据交换格式）>' python scripts/call.py runMultiFormulaBatchStream
```

执行后，从返回的 `data_id`（数据标识）读取最终结果：

```bash
GZQ_PARAMS='{"ids":["<data_id>"],"mode":"last_column_full"}' python scripts/call.py readData
```

这就是“探索阶段”和“使用阶段”的区别：探索阶段用自然语言快速改想法，使用阶段直接复用公式和接口，把投研流程固化为可重复执行的生产任务。

## 为什么不是普通数据 API

普通数据 API（应用程序接口）主要解决“把数据拉出来”。但在真实投研里，用户更常遇到的问题是：

- 我想临时构造一个全市场指标，能不能直接算？
- 我想验证一个选股想法，能不能不用手写数据清洗和回测代码？
- 我今天探索出的公式，明天能不能在 14:30 用日内数据再跑一遍？
- 我不想把大表塞进模型上下文，能不能只把计算结果返回给 LLM（大语言模型）？

quant-buddy-skills 的核心思路是：让 AI Agent（智能代理）负责理解目标和组织任务，让 quant-buddy（量化投研平台）负责数据调用、公式计算、金融 SOP（标准作业流程）和结果输出。

## 核心优势

### 1. 公式引擎：从查数据到算指标

quant-buddy-skills 支持通过公式语言组合行情、估值、财务、窗口统计、掩码条件和排序逻辑。用户不只是在查基础数据，而是在让 AI Agent（智能代理）生成可执行的全市场计算公式。

### 2. 探索阶段与使用阶段分离

投研不是一次性问答。一个想法通常要经历两个阶段：

| 阶段 | 用户目标 | quant-buddy-skills 的作用 |
|---|---|---|
| 探索阶段 | 用自然语言试想法、改条件、看结果 | AI Agent（智能代理）生成公式，平台侧执行计算和回测 |
| 使用阶段 | 固定公式，每天重复运行 | 将公式沉淀为可复用任务，可接入 AI Agent（智能代理）或外部调度 |

### 3. RU（资源用量单位）计费，提升 token efficiency（文本用量效率）

传统“数据 + LLM（大语言模型）”模式通常会把大量原始数据塞进上下文，让模型自己处理。这样 token（模型文本计量单位）消耗高、速度慢，也更容易出现上下文污染。

quant-buddy-skills 采用“平台侧计算 + 结果返回”的方式：大规模数据不进入 LLM（大语言模型）上下文，公式计算在平台侧完成，返回的是结构化结果、名单、统计值或图表。

### 4. 内置金融 SOP（标准作业流程）

量化投研不只是算数，还需要处理交易日、复权、窗口、排序、基准、事件日期、净值曲线和图表输出等细节。quant-buddy-skills 将常见金融 SOP（标准作业流程）封装成 AI Agent（智能代理）可调用能力，降低用户自己写流程时的错误率。

### 5. 更适合作为 AI Agent（智能代理）基础设施

一般模式是：

```text
数据 + LLM（大语言模型）
```

quant-buddy-skills 的模式是：

```text
数据 + 计算 + LLM（大语言模型）
```

区别在于：计算层不再临时交给 LLM（大语言模型）用上下文和代码拼出来，而是由平台提供稳定的结构化能力。

## 对比

| 维度 | 新闻 / 研报型金融 Skill（技能） | 量化框架文档 Skill（技能） | 数据 API（应用程序接口） | quant-buddy-skills |
|---|---|---|---|---|
| 核心价值 | 解读新闻、生成观点 | 帮 AI Agent（智能代理）查文档、写代码 | 拉取数据 | 平台侧执行投研计算 |
| A 股全市场筛选 | 弱 | 需要自行写代码 | 需要自行拼数据 | 强 |
| 因子 / 回测 | 通常需要外部实现 | 帮写框架 | 需要用户实现 | 内置工作流 |
| token（模型文本计量单位）消耗 | 中 | 中 / 高 | 高，常塞数据 | 低，只返回结果 |
| 适合用户 | 内容 / 研报 / 事件跟踪 | 量化开发者 | 数据工程 / 自定义管道 | 量化研究员、投研自动化、AI Agent（智能代理）用户 |
| 最佳场景 | “这条新闻影响什么” | “QMT 接口怎么写” | “我要原始数据” | “全 A 筛选 / 因子 / 回测 / 图表” |

## 数据覆盖范围

| 市场 | 行情 | 估值 | 财务数据 | 选股 / 回测 |
|---|---|---|---|---|
| A 股 | 支持 | 支持 | 支持 | 支持 |
| 港股 | 支持 | 暂不支持 | 暂不支持 | 暂不支持 |
| 美股 | 支持 | 暂不支持 | 暂不支持 | 暂不支持 |
| 主要宽基指数 | 支持 | 部分支持 | - | 可作为基准或股池 |

> 港股和美股当前重点支持行情价格类数据，例如收盘价、开盘价、最高价、最低价、涨跌幅、成交量和成交额。估值、财务、选股和回测能力以 A 股为主。

## 安装

### npx（Node.js 包执行工具，推荐）

建议新用户**只安装到自己正在使用的 AI Agent（智能代理）**，不要默认使用 `--all`。`--all` 等价于安装全部 skill 到全部支持的 agent，可能在本机创建多处目录或符号链接。

| 你使用的 Agent | 推荐命令 |
|---|---|
| Claude Code | `npx skills add pseudo-longinus/quant-buddy-skills -g -a claude-code -s quant-buddy-skill -y` |
| Cursor | `npx skills add pseudo-longinus/quant-buddy-skills -g -a cursor -s quant-buddy-skill -y` |
| OpenClaw | `npx skills add pseudo-longinus/quant-buddy-skills -g -a openclaw -s quant-buddy-skill -y` |

如果你使用其他支持的 Agent，把 `-a` 后面的值替换为对应 agent id；不要省略 `-a`，避免 CLI 自动安装到多个 Agent。

如果你同时使用多个 Agent，可以重复指定 `-a`：

```bash
npx skills add pseudo-longinus/quant-buddy-skills -g -s quant-buddy-skill -a claude-code -a cursor -y
```

先查看仓库里有哪些 skill（只列出，不安装）：

```bash
npx skills add pseudo-longinus/quant-buddy-skills --list
```

已安装用户更新：

```bash
npx skills update quant-buddy-skill -g -y
```

Windows（微软桌面操作系统）用户如果遇到 symlink（符号链接）或权限错误，可以在对应 Agent 命令后追加 `--copy`，例如：

```bash
npx skills add pseudo-longinus/quant-buddy-skills -g -a claude-code -s quant-buddy-skill -y --copy
```

只有在你明确希望安装到所有支持的 Agent 时，才使用：

```bash
npx skills add pseudo-longinus/quant-buddy-skills -g --all
```

查看当前安装位置：

```bash
npx skills list -g --json
```

## 配置 API Key（接口密钥）

首次使用前需要配置 quant-buddy API Key（接口密钥）：

1. 前往 https://www.quantbuddy.cn 注册并获取 API Key（接口密钥）。
2. 编辑 skill（技能包）目录下的 `config.json`，将 `api_key` 字段填入你的 Key（密钥）。
3. 或在支持写入本地文件的 AI Agent（智能代理）对话中发送：

```text
帮我配置 APIkey：sk-xxxxxxxx
```

## 运行环境

- Python（编程语言）3.8+，推荐 Python（编程语言）3.11。
- 核心行情、财务、选股和回测能力仅依赖 Python（编程语言）标准库。
- 可选依赖：
  - `python-dateutil`：事件研究辅助功能使用。
  - `Pillow`：图表图片格式转换时使用。
  - `requests`：事件新闻搜索辅助功能使用。
- 可选环境变量：`BOCHA_API_KEY`，仅事件新闻搜索辅助功能使用。

## 安全、隐私与免责声明

- quant-buddy API Key（接口密钥）仅用于请求 quant-buddy（量化投研平台）接口。
- API Key（接口密钥）只作为 HTTP（超文本传输协议）`Authorization` 头发送到 quant-buddy（量化投研平台）声明域名，不写入日志，不转发给第三方主机。
- 可选 `BOCHA_API_KEY` 仅在事件新闻搜索功能启用时使用。
- 本项目用于金融数据分析、量化研究、策略验证和教育用途，不构成投资建议、交易建议、收益承诺或自动交易服务。
- 回测结果不代表未来收益。用户应自行核验数据口径、交易成本、滑点、风险暴露和合规要求。

## 故障排查

- 环境依赖说明：`references/environment.md`
- 故障排查：`references/troubleshooting.md`
- RU（资源用量单位）计费说明：`references/ru-billing.md`

## 联系作者

想看更多策略案例、接入问题、更新路线和真实投研工作流，欢迎添加微信或加入交流群。

<p align="center">
  <table>
    <tr>
      <td align="center">
        <img src="assets/wechat_qr2.jpg" width="180" alt="个人微信二维码" />
        <br/>
        <sub>个人微信</sub>
      </td>
      <td align="center">
        <img src="assets/wechat_group_qr4.jpg" width="180" alt="微信群二维码" />
        <br/>
        <sub>微信群</sub>
      </td>
      <td align="center">
        <img src="assets/feishu_group_qr2.png" width="180" alt="飞书群二维码" />
        <br/>
        <sub>飞书群</sub>
      </td>
    </tr>
  </table>
  <br/>
  <sub>扫码添加微信或加入交流群，欢迎交流量化投研、AI Agent（智能代理）工作流和策略验证案例。</sub>
</p>

## Star History

<a href="https://www.star-history.com/?repos=pseudo-longinus%2Fquant-buddy-skills&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=pseudo-longinus/quant-buddy-skills&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=pseudo-longinus/quant-buddy-skills&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=pseudo-longinus/quant-buddy-skills&type=date&legend=top-left" />
 </picture>
</a>

## License（开源许可证）

MIT（麻省理工开源许可证）
