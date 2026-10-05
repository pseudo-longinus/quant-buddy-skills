# quant-buddy-skills

<p align="center">
  <img src="https://www.quantbuddy.cn/home/use-cases/research-companion.webp" alt="QuantBuddy 官网研究活页场景：让系统持续跟踪投资逻辑" width="100%" />
</p>

<p align="center">
  <a href="README.md">中文</a> ·
  <a href="README.en.md">English</a> ·
  <a href="https://www.quantbuddy.cn">官网</a> ·
  <a href="https://tcn8bvcbyokw.feishu.cn/wiki/E1zswck3oiiJjJkP07QcmSG3nle?from=from_copylink">新手教程</a>
</p>

<p align="center">
  <a href="https://github.com/pseudo-longinus/quant-buddy-skills/stargazers"><img alt="GitHub stars" src="https://img.shields.io/github/stars/pseudo-longinus/quant-buddy-skills?style=social"></a>
  <a href="https://github.com/pseudo-longinus/quant-buddy-skills/blob/main/LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-green"></a>
  <img alt="Python" src="https://img.shields.io/badge/Python-3.8%2B-blue">
  <img alt="Markets" src="https://img.shields.io/badge/Markets-A%E8%82%A1%20%2F%20%E6%B8%AF%E8%82%A1%20%2F%20%E7%BE%8E%E8%82%A1%20%2F%20%E6%9C%9F%E8%B4%A7-orange">
</p>

## 🔥 3 秒快速安装

如果你熟悉 Agent 工具（Claude Code、Cursor、OpenClaw 等），可以直接对 AI Agent 说：

> 帮我安装这个 skill：

```bash
npx skills add pseudo-longinus/quant-buddy-skills -g -a claude-code -s quant-buddy-skill -y
```

安装 `quant-buddy-skill`（QBS）时，支持 companion 的版本会在首次 `newSession` 调用 QBV（`quant-buddy-view`）检查，并按需自动安装或更新它。QBS 负责理解问题、查数和计算，QBV 负责把结果发布成可分享的研究活页；QBV 安装失败不会影响 QBS 的行情、财务、公式、筛选和回测。

如果希望立即启用活页发布能力，也可以显式安装 QBV：

```bash
npx skills add pseudo-longinus/quant-buddy-skills -g -a claude-code -s quant-buddy-view -y
```

把命令中的 `claude-code` 换成你正在使用的 Agent ID 即可。只有在明确希望把仓库内全部 skill 安装到全部 Agent 时，才使用 `--all`。

如果你不懂如何使用 Agent 和 skill，可以按照[小白图文教程](https://tcn8bvcbyokw.feishu.cn/wiki/E1zswck3oiiJjJkP07QcmSG3nle?from=from_copylink)一步步展开。

---

> **QuantBuddy Skills 是一套给 AI Agent 使用的底层量化研究基础设施。**
> 把投研想法交给 Agent，把数据、计算、口径和交付交给一套可以持续运行的研究底座。

它不是只回答行情的聊天 Skill，也不是把原始表格丢给模型的数据接口。它把**数据接入、指标口径、公式计算、横截面筛选、因子研究、策略回测、结果验证和研究活页交付**沉淀成 AI Agent（智能代理）可直接调用的底层能力。

覆盖 A 股、港股、美股、指数、ETF、境内期货，以及宏观策略、A 股期权隐含波动率、美国期权行情、龙虎榜标签和 GICS 行业等数据；不同市场的字段以实际接口返回为准。

传统数据 API 只负责"把数据拉出来"；quant-buddy-skills 负责让 AI Agent 把自然语言投研想法转成**可执行公式、平台侧计算、结构化结果和可复用任务**。

官网：https://www.quantbuddy.cn

> 本项目用于金融数据分析、量化研究、策略验证和教育用途，不构成投资建议、交易建议、收益承诺或自动交易服务。

## 先理解它是什么：一套可运行的研究底层

QuantBuddy Skills 把一次投研拆成四层。每层都能被 Agent 调用，也能把结果交给下一层继续使用：

| 底层 | 提供什么 | 解决什么问题 |
|---|---|---|
| **数据层** | 四类市场行情、财务、估值、资金、情绪、期货供需、宏观和另类数据 | 不再为每个问题临时拼数据源和字段 |
| **指标层** | 18 个研究维度、280+ 已落地指标、明确窗口、口径和打分方式 | 同一个概念有统一定义，结果可以追溯和比较 |
| **计算层** | 公式、窗口、横截面筛选、因子、事件研究、回测、净值和图表 | 把“大表搬运”变成平台侧计算，只返回判断所需结果 |
| **交付层** | 公式任务包、Data Grant、QBV 研究活页、免费托管和持续更新 | 一次研究可以分享、复用、下载和继续运行 |

官网把这两部分概括为 **“千维计划 × 范式库”**：千维计划负责“怎么算”，把维度拆成有口径的指标；范式库负责“怎么用”，把验证过的研究流程固定成可复用活页。底层框架因此同时保留计算细节和研究方法，而不是只输出一张静态图片。

这套底层框架带来几个直接好处：

- **透明可核验**：保留数据日期、报告期、指标口径、公式链和结果证据，方便复盘与审计。
- **把算力留给判断**：大规模矩阵在平台侧计算，Agent 只接收 TopN、统计量、图表或结构化证据，降低上下文和传输成本。
- **跨市场可比较**：A 股、港股、美股、期货在各自市场内按同一研究维度计算和排序，避免把不同市场字段强行混用。
- **一次研究，多次复用**：公式、指标和页面结构可以沉淀为任务包、范式或活页，下一次从已有方法继续。
- **结果会继续更新**：活页按交易日刷新；RSI、RSRS、选股和回测研究还可以在富余算力时申请免费自动进化。
- **端侧足够轻**：数据和计算在云端，页面可以分享、下载为自包含 HTML，并嵌入网站、课程、桌面屏幕或自己的应用。

## QBS + QBV：从问题到持续更新的研究活页

QBS 和 QBV 是一条完整链路：QBS 把自然语言投研问题转成数据查询、公式、筛选或回测；QBV 把经过验证的结果发布成可以反复打开、分享和更新的研究活页。

能力边界和调用顺序以仓库内的 [QBS SKILL.md](skills/quant-buddy-skill/SKILL.md) 与 [QBV SKILL.md](skills/quant-buddy-view/SKILL.md) 为准；README 只提炼当前版本已经验证过的公开能力。

| 阶段 | 负责组件 | 你得到的结果 |
|---|---|---|
| 提出问题 | `quant-buddy-skill` | 行情、财务、估值、全市场筛选、因子、回测和图表结果 |
| 沉淀方法 | QBS → QBV | 公式任务包、数据合同和可复用的研究结构 |
| 发布与更新 | `quant-buddy-view` | `pages.quantbuddy.cn` 上的可分享活页，按同一口径持续取数和更新 |

QBV 提供免费的研究空间和托管地址，不需要自己部署后端或购买网页服务器。活页也可以下载为自包含 HTML；联网打开时仍能按页面绑定的公式继续取最新数据。

官网当前展示的能力进展包括 **18 个研究维度、280+ 个已落地指标、A 股 / 港股 / 美股 / 期货 4 类市场**，以及按交易日自动更新的研究活页；具体字段和可用范围以实际接口返回为准。

### RSI / RSRS 与研究页自动进化

QBV 支持把 RSI、RSRS、选股逻辑或回测研究提交给自动进化。活页会按内容成熟度进入 L1–L5 研究进化路径；登记的是进化意愿，不是立即创建任务。平台会在有富余算力时不定期免费运行较长的研究任务，用来补充数据、做历史比较、检查计算口径或改进页面呈现。进化按后台资源排队，不承诺立即完成；结果生成后可以查看独立版本变化和 RU 变化，再决定是否采用。

### 先看官网演示视频

<p align="center">
  <video controls preload="metadata" poster="https://www.quantbuddy.cn/videos/quantbuddy-research-demo-poster.jpg" src="https://www.quantbuddy.cn/videos/quantbuddy-research-demo.mp4" width="86%">
    <source src="https://www.quantbuddy.cn/videos/quantbuddy-research-demo.mp4" type="video/mp4" />
    <a href="https://www.quantbuddy.cn/videos/quantbuddy-research-demo.mp4">播放 QuantBuddy 研究活页演示视频</a>
  </video>
  <br/>
  <a href="https://www.quantbuddy.cn/videos/quantbuddy-research-demo.mp4"><img src="https://www.quantbuddy.cn/videos/quantbuddy-research-demo-poster.jpg" alt="点击播放 QuantBuddy 研究活页演示视频" width="86%" /></a>
  <br/>
  <sub>如果当前 GitHub 客户端不显示播放器，请点击<a href="https://www.quantbuddy.cn/videos/quantbuddy-research-demo-poster.jpg">视频海报</a>或<a href="https://www.quantbuddy.cn/videos/quantbuddy-research-demo.mp4">直接打开 MP4</a>。视频和海报均托管在 quantbuddy.cn，方便国内用户访问。</sub>
</p>

## 能力全景：市场、资产与研究动作

QBS 的市场范围不是“只有 A 股”。它会先识别资产和市场，再按工具实际返回的字段、日期和覆盖状态交付结果。A 股的估值、财务、资金流和公式目录最完整；港股、美股、指数、ETF、期货、宏观和期权数据按各自数据合同提供能力。

| 资产 / 市场 | 可直接查询的内容 | 可做的研究动作 | 需要知道的边界 |
|---|---|---|---|
| A 股股票、ETF | 行情、估值、报告期财务、行业、资金流、龙虎榜、市场/个股情绪 | 公式计算、横截面筛选、因子、回测、行业聚合、K 线和分钟任务 | 字段最丰富；ETF 也在资产库中 |
| 港股 | 行情、窗口收益、部分估值和报告期财务、南向持仓字段 | 已物化指标的横截面筛选；对实际可用字段做公式、比较和页面 | 不提供 A 股专属资金流/行业字段；财务与估值按接口返回 |
| 美股、境外 ETF | 行情、窗口收益、部分估值和报告期财务 | 已物化指标的横截面筛选；对实际可用字段做公式、比较、因子和页面 | 字段覆盖按资产和接口返回；不把 A 股字段强套到美股 |
| 指数 | A 股、行业/主题及海外指数行情和窗口序列 | 基准对比、收益比较、行业排名、事件研究、活页图表 | 境内指数分钟数据与海外指数分钟数据的覆盖不同 |
| 境内期货 | 主力/连续/次主力行情、窗口、现货、库存和换月事件 | 期货横截面筛选（需有对应物化指标）、供需研究、连续合约比较、部分分钟任务 | 当前不承诺期货估值、财务或股票式 K 线；美港期货分钟不支持 |
| 宏观、期权及研究数据 | 宏观/策略数据、A 股期权隐含波动率、美国期权行情、GICS 分类等 | 宏观背景、波动率、分类聚合、策略研究 | 这些是按数据集提供的专项能力，不等同于所有市场都有完整财务字段 |

### 选股能力：四个市场都能筛，方式不同

1. **当前横截面筛选**：`selectByComposition` 的 `universe.asset_scope` 支持 `A股`、`港股`、`美股`、`期货`。它可以把已物化的 score/screen 指标组合成 TopN、排序、条件交集，并返回每只资产的分项解释；日期和指标若不完全同日，会明确披露实际 `as_of`。
2. **公式选股与因子排序**：QBS 可以生成多条件公式、窗口统计、掩码、排名和复合因子，再由平台侧计算后只返回名单、指标或图表。A 股公式目录最完整，其他市场按资产库和字段可用性执行；用户应在问题中指定市场和资产池。
3. **财务与价格联合筛选**：日频财务筛选会按报告期/发布日期对齐财务条件，再叠加价格、均线、突破、成交量等条件。仓库里的完整示例目前以 A 股为例，这是示例的数据合同，不代表所有筛选只能做 A 股。
4. **历史研究与回测**：历史筛选、因子 IC、分组收益、策略回测、净值曲线和基准比较走量化研究工作流；它们与“当前 TopN 选择器”分开，避免把实时横截面结果误当成历史回测。

### 18 个研究维度与可复用指标

官网和仓库目录目前展示 **18 个研究维度、280+ 个已落地指标**；仓库本地指标目录记录了 327 个指标候选，覆盖范围记录含 A 股、港股、美股和期货。维度包括：趋势结构、动量与反转、相对强度、量能与流动性、资金流向、形态/波动/风控、估值性价比、盈利能力、盈利成长、现金流质量、财务安全、运营效率、财务爆雷风险、期货供需、异动监控、龙虎榜资金席位、市场情绪、个股情绪。

这些指标可以用于单资产画像、跨市场筛选、因子组合、行业/主题聚合、事件研究、回测和研究活页。指标是否已物化、支持哪个市场和哪个日期，以服务端的 `selection_ready`、`asset_scope`、`as_of` 和实际返回为准。

### 数据粒度与分钟覆盖

- 快照、窗口、报告期查询单次最多处理 1000 个资产；大结果会走 CSV/数据授权通道，避免把原始大表塞进 LLM 上下文。
- `fast_query_minute` 用于单个资产当前或最近完整交易日的分钟 OHLCVA；`fast_query_minute_range` 用于单资产、跨交易日的原始 1 分钟 CSV，最长约三个月，不自动改成 5 分钟、不静默裁剪日期。
- 当前分钟覆盖以平台合同为准：A/美股股票和境内期货自 2026-05-13 起，港股自 2026-05-20 起，境内指数自 2026-08-13 起；美港指数和美港期货分钟数据不支持。覆盖不足时会返回提示。

### QBV 交付的不只是一个链接

QBV 可以把 QBS 的验证结果或已有 JPG、PNG、HTML、PDF 先发布到免费托管空间，再按需接入公式包或 Data Grant（数据授权）成为可持续更新的活页。常见交付包括：个股画像、估值/财务页、指数异动、跨资产比较、行业/主题机会、资金流信号、基金/ETF/债券画像、商品日报、K 线和策略净值看板。

活页使用页面绑定的数据合同和签名取数，不把 API Key 放到浏览器；可以分享、下载自包含 HTML，并在联网打开时刷新到最新数据。QBV 还支持保留已有页面结构、追加基准序列、编辑图表、复用页面壳、页面质量验收和结果版本管理。

## 一套底层框架，承载不同的研究产品

官网把同一套数据与计算底座延伸到不同场景。你可以把它当作自己的研究系统，也可以把它嵌进已有产品：

| 场景 | 交付形态 | 典型结果 |
|---|---|---|
| 研报复现 / 策略测试 | 可回放的公式和回测活页 | 用历史数据复核假设，持续重算信号和净值 |
| 财经内容 / 行业周报 | 可嵌入的研究活页 | 行业拥挤度、TopN 口径和图表随数据更新 |
| 桌面机器人 / 金融屏幕 | 条件变化监控页 | 只呈现值得关注的变化，每条信号可回到证据 |
| 网站 / 小程序 / App | 自己的方法页或选股页 | 组合低估值、盈利质量、趋势观察，持续跟踪候选变化 |
| 金融顾问 / 资产配置 | 面向客户的交互式方案页 | 把期限、风险和流动性偏好接进可更新的配置逻辑 |
| 投资教育 | 可实验的课程活页 | 学生调整条件、查看公式、比较有效与失效情景 |

<p align="center">
  <img src="https://www.quantbuddy.cn/home/use-cases/course-campus.webp" alt="QuantBuddy 官网课程与研究场景截图" width="78%" />
  <br/>
  <sub>官网场景图：研究方法可以作为 HTML 活页嵌入课程、内容和产品。</sub>
</p>

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
- **适合跨市场横截面计算**：A 股、港股、美股、期货都可以进入已物化指标的选择器；平台侧完成大规模计算，只把结果返回给 AI Agent（智能代理）。
- **能沉淀为可复用任务**：今天探索出的公式，明天可以固定时间重复运行。
- **从计算到交付一条链路**：安装 QBS 时会检查并调用 QBV；QBV 提供免费托管空间，把验证后的结果变成可分享活页。
- **研究可以继续进化**：RSI / RSRS、选股和回测活页可提交后台自动进化；富余算力可用时不定期免费运行。
- **面向 AI Agent（智能代理）工作流设计**：适配 Claude Code（编程智能代理）、Cursor（智能编辑器）、Codex（编程智能代理）、GitHub Copilot（编程助手）、Windsurf（智能编辑器）等环境。
- **四类市场各有研究路径**：A 股覆盖最完整；港股、美股支持行情、窗口、部分估值/财务和横截面选择；境内期货支持行情、现货、库存、连续合约和部分供需研究；具体字段以接口返回为准。
- **覆盖更多投研数据**：支持 A 股财务、港美股财务、龙虎榜标签、GICS 行业等常用投研数据。

## 一句话能做什么

| 你对 AI Agent（智能代理）说 | quant-buddy-skills 做什么 |
|---|---|
| “查贵州茅台最新收盘价、涨跌幅、成交额” | 调用行情数据，返回结构化结果 |
| “筛全 A 股放量突破 60 日新高的前 10 只” | 平台侧执行全市场公式、筛选、排序，只返回 Top10（前十名） |
| “在港股 / 美股 / 期货里按已上线动量或波动指标取 TopN” | 按 `asset_scope` 调用横截面选择器，返回名单、分项分数和数据日期 |
| “回测低 PE（市盈率）+ 高 ROE（净资产收益率）组合，相对沪深 300 画净值” | 执行策略回测、基准对比、输出净值曲线 |
| “把这个选股条件每天 14:30 跑一遍” | 将验证过的公式沉淀为可复用任务 |
| “把这组算好的指标发布成一个网页能直接读的数据包” | 注册成公式任务包，返回凭证，前端/第三方免 API Key 流式取最新值 |
| “上传我的 CSV（逗号分隔值文件）因子，和 ROE（净资产收益率）一起做排序” | 上传自有因子并参与公式计算、选股和图表输出 |

## Skill Matrix（能力矩阵）

| 能力 | 支持范围 | 典型提示词 |
|---|---|---|
| 快速行情查询 | A 股 / 港股 / 美股 / 指数 / 可识别期货（行情以工具返回为准） | “查一下贵州茅台最新收盘价、涨跌幅和成交额” |
| 估值与财务 | A 股 / 港股 / 美股部分字段（以接口返回为准） | “列出宁德时代最近报告期 ROE、净利润和资产负债率” |
| 常用投研数据 | A 股财务、港美股财务、龙虎榜标签、GICS 行业等 | “查一下归母净利润、EBITDA、龙虎榜净买额、GICS 行业” |
| 全市场公式计算 | A 股、港股、美股、指数、ETF、境内期货按字段支持 | “计算指定市场 20 日收益和 60 日收益，并按动量排序” |
| 多条件选股 | `selectByComposition` 支持 A 股 / 港股 / 美股 / 期货的已物化指标；公式筛选按数据字段执行 | “筛选指定市场的低估值、高质量、动量或波动条件” |
| 因子分析 | 18 个研究维度、已物化 score/screen 指标、自有 CSV 因子；A 股目录最完整 | “用股息率、ROE、动量做复合因子排序” |
| 策略回测 | A 股工作流最完整；其他市场按公式和历史数据支持情况执行 | “回测低 PE + 高 ROE 组合，相对沪深 300 画净值” |
| 盘中与历史分钟 | A/美股股票、港股、境内期货、境内指数按覆盖日期提供分钟能力 | “查询某资产最近完整交易日分钟 OHLCVA，或读取历史 1 分钟 CSV” |
| 个股 / 资产画像 | 单资产开放式画像，估值、财务、资金、波动、宏观胜率和走势维度按市场返回 | “生成腾讯控股 / 苹果 / 黄金期货的最新画像” |
| 行业、主题与事件 | 行业/主题精确成分、收益排名、事件研究和情景窗口 | “比较申万行业近 20 日表现并做事件前后收益” |
| 期权与宏观研究 | A 股期权 IV、美国期权行情、宏观策略数据和 GICS 分类 | “按到期日、执行价、IV 或宏观情景整理研究数据” |
| 图表渲染 | K 线、净值、基准对比 | “把策略净值和沪深 300 画成图” |
| 公式任务包 | 把公式组注册成长期包，对外免 API Key（接口密钥）SSE 取数 | “把这组选股公式发布成一个数据页，前端直接取最新结果” |
| 研究活页与托管 | QBS 结果交给 QBV 发布到免费研究空间，支持分享、下载和持续更新 | “把这次研究做成一个能反复打开的活页” |
| 自动进化 | QBV 在富余算力可用时不定期免费运行 RSI / RSRS、选股或回测研究的进化任务 | “继续检查这张活页并自动进化” |
| 自有数据 | CSV（逗号分隔值文件）因子上传 | “上传我的因子 CSV，和 ROE 一起排序” |

## 最近的能力进展

- **当前版本**：仓库远端当前记录为 QBS `4.25.49`、QBV `0.6.87`；安装 QBS 时，支持 companion 的版本会在首次 `newSession` 检查并按需安装/更新 QBV。
- **大结果读取更可控**：QBS 现在按场景区分 `signature`、`last_column_full`、`last_day_stats`、`range_data`、`per_asset_sample` 等读取模式；QBV 公式包会检查 `is_truncated`，不把摘要结果当完整名单。
- **K 线已走实时运行时**：普通 K 线活页使用同一份 OHLCV Data Grant 绘制蜡烛、成交量和均线；只有明确要求图片时才走 PNG 渲染路径。
- **QBS → QBV 交接更完整**：验证过的计算结果、数据范围和页面意图可以一起交给 QBV，减少重复查数和手工拼页面。
- **已有文件可以先活页化**：JPG、PNG、HTML、PDF 等已有材料可以先原样托管为可阅读页面，再继续做数据增强或研究改造。
- **分钟数据覆盖更清晰**：历史分钟区间查询会区分完整覆盖、部分覆盖和越界情况，并返回覆盖提示，不把空结果误当成有效数据。
- **资产与专项数据继续扩展**：资产目录包含约 5316 个 A 股、2858 个港股、1069 个美股/境外 ETF、513 个指数和 239 个期货条目；同时补充美股期权、A 股期权 IV、宏观策略和 GICS 分类目录，实际可用字段仍以服务端返回为准。
- **公式任务更适合长期复用**：公式包支持指定日期或偏移读取，适合把探索过的指标接到看板、网页和调度任务中。
- **页面交付有验收边界**：QBV 会在页面发布和可访问性确认后再交付最终活页链接，避免把草稿或未验证页面当成成品。

## 适合谁

- **A 股、港股、美股和期货研究员**：想快速验证选股、因子、事件研究、回测或供需想法。
- **AI Agent（智能代理）和 AI 编程工具用户**：想让 Claude Code（编程智能代理）、Cursor（智能编辑器）、Codex（编程智能代理）、GitHub Copilot（编程助手）直接完成投研任务。
- **投研自动化开发者**：想把每日复盘、盘中筛选、策略监控固化为可重复运行的任务。
- **金融数据分析师 / 内容创作者**：想从自然语言直接得到结构化数据、TopN（前 N 名）名单和图表。

## 不适合谁

- 只需要完全自定义底层数据管道的人。
- 需要加密货币数据，或要求期货估值/财务、美股完整基本面数据库的人；当前版本提供的是按专项数据集和接口字段返回的研究能力。
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

## 公式任务包（Formula Package）：把验证过的公式组对外发布

示例 3 把公式固化成「Agent / 调度自己重复跑」的任务；**公式任务包**再往前一步——把一组验证过的公式**注册成一个长期数据服务**，让你自己的网页、看板或第三方**无需 API Key（接口密钥）**就能反复取到最新结果。

注册一次（需 API Key），拿到一对凭证 `package_id` + `signature`；之后任何能发 HTTP（超文本传输协议）请求的地方，凭这对凭证就能以 **SSE（服务器推送事件）流式**取数。底层数据一更新，服务端**自动按依赖关系重算**，取数永远拿最新值、绝不返回过期数据。

> 与 `runMultiFormulaBatchStream`（全市场公式批算）的区别：后者是 Agent / 调度在**你自己的账号侧**执行、读 `data_id`（数据标识）；公式任务包是把算好的产出**以凭证形式对外只读开放**，取数方无需 API Key、也不消耗其配额，费用始终计入**包所有者**。两者执行池与计费相互独立。

**典型场景**

- **自建投研日报 / 数据看板**：把每天复盘要看的指标（选股名单、因子排序、估值分位、资金流向……）注册成一个包，用一个静态 HTML（网页）页面 `fetch`（浏览器取数）渲染。打开页面即当日最新，**无需后端、无需每天手动重跑公式**。
- **给团队 / 客户一个只读数据页**：发出去的是 `package_id` + `signature`，不是 API Key；对方只能读你固定的产出，改不了公式、拿不到账号权限，可随时撤销。
- **嵌进已有网站 / Notion / 飞书 / 大屏**：任何能跑 `fetch` 的地方都能把 quant-buddy（量化投研平台）的计算结果接进你自己的页面。
- **第三方 / 轻量集成**：把一个算好的指标包交给合作方只读对接，零配置接入。

**它能搭出什么：两个用公式任务包做的真实页面**

下面两个页面都是**纯静态 HTML（网页）**——没有后端、没有数据库，只在浏览器里 `fetch`（取数）一个公式任务包，把返回的 `outputs`（产出）渲染成表格和图表。底层数据一更新，刷新页面即当日最新值，**API Key（接口密钥）不进前端**。

<p align="center">
  <img src="assets/demo_market_bubble.png" alt="全球市场温度 / 估值泡沫看板" width="78%" />
  <br/>
  <sub><b>全球市场温度看板</b>　·　七大股指涨跌、全市场估值「泡沫温度」、商品与债券走势——整页数据来自一个公式任务包的单次取数。</sub>
</p>

<p align="center">
  <img src="assets/demo_hs300_monitor.png" alt="沪深300 个股异动监控" width="78%" />
  <br/>
  <sub><b>沪深300 个股异动监控</b>　·　涨跌幅榜、换手 / 量能异动、个股半年价格轨迹——同样一个 <code>fetch</code> 取数渲染。</sub>
</p>

> ⚠️ 以上页面仅为公式任务包的**示例展示**，所示数字均为历史 / 示例数据，**不构成任何投资或交易建议**。

**两段式用法**

```powershell
cd skills/quant-buddy-skill

# 1. 注册（需 API Key）：params.json 写 formulas + reads，中文公式用 @file 传避免编码截断
python scripts/formula_package.py register @params.json

# 2. 取数（无需 API Key）：只需 package_id，signature 可由本地落盘凭证自动补全
$env:FP_PARAMS='{"package_id":"pkg_xxx"}'
python scripts/formula_package.py query

# 管理：列表 / 撤销 / 刷新（轮换签名）
python scripts/formula_package.py list    '{"page":1,"page_size":20}'
python scripts/formula_package.py revoke  '{"package_id":"pkg_xxx"}'
python scripts/formula_package.py refresh '{"package_id":"pkg_xxx","rotate_signature":true}'
```

注册用的 `params.json` 示例（公式语法与 `runMultiFormulaBatchStream` 同款）：

```json
{
  "formulas": [
    "排序值 = 涨跌幅(\"全市场每日收盘价\")",
    "放量突破Top10 = 取前(\"排序值\", 10, 返回数值)"
  ],
  "reads": [
    { "output": "放量突破Top10", "read_mode": "last_day_stats" }
  ],
  "ttl_days": 365
}
```

- 未列入 `reads` 的公式只作中间变量参与计算、不对外返回。
- 同一个包里不同产出可用**不同读取模式**：`range_data`（区间完整序列）/ `last_day_stats`（最新截面统计）/ `last_valid_per_asset`（每个资产最后一个有效值）。
- 单包最多 100 条公式、20 个对外产出，默认有效期 365 天。

**前端直接取数（无需 API Key）**

取数接口走 SSE，浏览器用 `fetch` 读流（签名放 body、不进 URL，不要用 `EventSource`）：

```js
const resp = await fetch('https://www.quantbuddy.cn/skill/queryFormulaPackage', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ package_id, signature }),
})
const reader = resp.body.getReader()
const decoder = new TextDecoder()
const outputs = {}
let buf = ''
for (;;) {
  const { value, done } = await reader.read()
  if (done) break
  buf += decoder.decode(value, { stream: true })
  const blocks = buf.split('\n\n'); buf = blocks.pop()
  for (const block of blocks) {
    const ev = (block.match(/event:\s*(.*)/) || [])[1]
    const dt = JSON.parse((block.match(/data:\s*([\s\S]*)/) || [])[1])
    if (ev === 'result') outputs[dt.output] = dt        // outputs["放量突破Top10"].data ...
    else if (ev === 'error') throw new Error(`${dt.code}: ${dt.message}`)
  }
}
```

> 注册 / 列表 / 撤销 / 刷新需 API Key，**必须放在服务端**；只有取数接口（`queryFormulaPackage`）可暴露给浏览器。完整参数、读取模式结构与错误码见 `tools/formula_package.md`，端到端用法见 `recipes/formula-package.md`。

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
| 跨市场横截面筛选 | 弱 | 需要自行写代码 | 需要自行拼数据 | 已物化指标支持 A 股 / 港股 / 美股 / 期货 |
| 因子 / 回测 | 通常需要外部实现 | 帮写框架 | 需要用户实现 | 内置工作流 |
| token（模型文本计量单位）消耗 | 中 | 中 / 高 | 高，常塞数据 | 低，只返回结果 |
| 适合用户 | 内容 / 研报 / 事件跟踪 | 量化开发者 | 数据工程 / 自定义管道 | 量化研究员、投研自动化、AI Agent（智能代理）用户 |
| 最佳场景 | “这条新闻影响什么” | “QMT 接口怎么写” | “我要原始数据” | “跨市场筛选 / 因子 / 回测 / 图表 / 活页” |

## 数据覆盖范围

| 市场 / 资产 | 行情与窗口 | 估值 / 财务 | 横截面筛选 | 因子 / 回测 |
|---|---|---|---|---|
| A 股股票 / ETF | 支持 | 支持 | 支持 | 支持 |
| 港股 | 支持 | 部分 TTM 估值和报告期字段（以接口返回为准） | 已物化指标支持 | 按字段和历史数据支持 |
| 美股 / 境外 ETF | 支持 | 部分 TTM 估值和报告期字段（以接口返回为准） | 已物化指标支持 | 按字段和历史数据支持 |
| A 股、行业/主题及海外指数 | 支持 | 部分支持 | 可作股池或排序对象 | 基准、收益比较、事件研究 |
| 可识别境内期货品种 | 行情、连续/主力、现货、库存、换月事件 | 不提供股票式估值/财务 | 已物化指标支持 | 供需、窗口、连续合约和部分策略 |
| 宏观 / A 股期权 / 美国期权 | 按专项数据集提供 | 以数据集为准 | 以数据集为准 | 宏观、IV、到期日/执行价等研究 |

> 选股列中的“已物化指标支持”指 `selectByComposition` 当前截面选择器：服务端还会检查指标启用状态、删除状态、物化向量、支持的 `asset_scope` 和有效 `as_of`。它与自定义公式筛选、历史回测、分钟排名是不同路径。港股和美股的价格类字段通常包括收盘价、开盘价、最高价、最低价、涨跌幅、成交量和成交额；估值和财务字段以接口实际返回为准。期货不承诺股票式估值、财务或 K 线图。

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
        <img src="assets/wechat_qr3.png" width="180" alt="个人微信二维码" />
        <br/>
        <sub>个人微信</sub>
      </td>
      <td align="center">
        <img src="assets/wechat_group_qr10.png" width="180" alt="QuantBuddy投研科学讨论微信群二维码" />
        <br/>
        <sub>QuantBuddy 投研科学讨论群</sub>
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
