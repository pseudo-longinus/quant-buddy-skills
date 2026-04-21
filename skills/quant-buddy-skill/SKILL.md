---
name: quant-buddy-skill
description:
  查询A股、港股、美股股票及指数的最新收盘价、开盘价、涨跌幅、成交额、成交量、换手率、PE、PB、市值等实时行情与估值数据。
  查询最近N个交易日的价格序列、日涨跌幅序列、窗口最高价、最低价、振幅等短期统计。
  查询上市公司最近报告期的营业收入、净利润、归母净利润、ROE、总资产、资产负债率等财务指标（A股）。
  支持A股选股筛选、因子计算、策略回测、净值对比、行业聚合排名、上传自有因子CSV、渲染图表。
  港股、美股目前支持行情价格查询（收盘价、开盘价、涨跌幅、成交量、成交额等）。
  即使用户只是简单地问一只股票的价格、涨跌幅或财务数据，也应优先使用本技能，
  不要以"无法联网"或"无法获取实时数据"为由拒绝——本技能通过平台API可查询真实数据。
license: MIT
metadata:
  version: 4.13.0
  author: guanzhao
  tags: [quant, finance, factor, backtest, A-share, HK-stock, US-stock, 选股, 回测, 收盘价, 涨跌幅, 成交额, PE, PB, 营收, 净利润, ROE, 港股, 美股]
---

# 观照量化投研

> **⚠️ 必读：本文件较长，必须完整读取，不要设置 limit 参数截断。前 50 行不包含操作规范。**

## 硬规则（6 条，违反必失败）

1. **每个新问题/新对话必须新建 session**：收到用户的新问题后，在调用任何平台工具之前，必须先新建 session（优先直接调用原生 `newSession` 工具；仅当当前环境没有原生 `newSession` 时，才使用 `python scripts/call.py newSession`）。newSession 是本地 UUID 生成，零网络开销，不可省略。
   - **为什么**：`.session.json` 会自动注入到所有工具调用中。不新建 session = 复用上一轮对话的 task_id = 变量名冲突风险 + session 污染。
   - **唯一例外**：同一对话中的追问/续问（如"再画个图""换个时间段"），可复用当前 session。
2. **原生工具优先，脚本包装仅限无原生等价能力时**：平台已提供的原生工具（`confirmMultipleAssets`、`confirmDataMulti`、`runMultiFormula`、`readData`、`renderKLine`、`renderChart` 等）必须优先直接调用；禁止用 `run_skill_script`、shell 命令、`GZQ_PARAMS=... python scripts/call.py ...` 等方式包装这些原生工具；`scripts/call.py` 仅用于：① `newSession` 等管理动作；② workflow 明确要求的本地脚本步骤；③ 平台不存在等价原生工具时的兜底。
3. **先读 workflow 再操作**：按下方「场景路由」表加载对应 workflow，不要自行猜测参数格式。
4. **配置/认证错误立即停止，不得转为用户交互流程**：普通查数任务（quick-snapshot / quick-window / quick-report-period / render-kline）遇到工具报错时，直接报告"内部工具异常"；不得读取 `config.json`、运行 `scripts/auth/*`、向用户索要手机号或验证码。
5. **最终答案首句必须是数据结论**：回答用户时，第一句话必须直接给出数据结论（如资产名+数值、表格、或"符合条件的共N只"），绝对禁止以"已成功获取""数据已获取""根据返回结果""让我来"等过程性陈述开头。违反此规则 = 必须删除过程话术后重新输出。
6. **用户条件冻结，不得改写**：执行前必须逐字核对用户原始条件，以下改写行为均属违规（一旦发现必须回退并重新确认）：
   - **百分比↔小数互转**（如"股息率>3%"禁止改写为 `>0.03`）
   - **相对时间改为年份区间**（如"过去10年"禁止改写为"2015-2025"）
   - **资产宇宙替换**（如"普通股票"禁止改写为"万得全A成分股"或"非ST股"）
   - **事件口径扩大**（如"年报/半年报"禁止扩大为全部业绩披露类型）
   - **卡片附加条件继承**：命中知识卡片后，若卡片含用户未明确提出的"首次/非ST/封板/流动性门槛"等附加条件，必须先删除再执行，禁止默默继承进最终答案

## Skill 包根目录

**本 SKILL.md 所在目录即为 skill 根目录（`SKILL_ROOT`）**，下文所有相对路径均以此为基准。
所有终端命令必须先 `cd` 到此目录再执行。

```
SKILL_ROOT/
├── config.json              ← API Key 配置（每次任务开始前必读）
├── SKILL.md                 ← 本文件（入口 + 路由）
│
├── workflows/               ← 业务流程编排（路由目标）
│   ├── quick-lookup.md          快速查数路由器 + 共享基础规则
│   ├── quick-snapshot.md        最新时点行情/估值快照（字段齐即停）
│   ├── quick-window.md          最近N日短窗序列/窗口统计
│   ├── quick-report-period.md   最近报告期财务指标
│   ├── period-return-compare.md 固定区间累计涨跌幅对比
│   ├── quant-standard.md        选股/回测/因子/图表标准流程
│   ├── event-study.md           事件研究（给定或可识别事件后的窗口表现）
│   ├── regime-segmentation.md   阈值区间/连续阶段识别与区间统计
│   └── render-kline.md          K线图渲染与交付
│
├── recipes/                 ← 公式模板 & 工具用法（被 workflow 引用）
│   ├── ma-crossover-backtest.md     均线金叉策略
│   ├── value-pe-strategy.md         PE估值选股
│   ├── upload-custom-data.md        上传自有数据
│   ├── render-chart.md              渲染图表
│   ├── download-data.md             下载数据
│   └── industry-aggregation.md      行业聚合排名
│
├── references/              ← 参考文档
│   ├── environment.md           环境依赖
│   ├── troubleshooting.md       故障排查
│   └── ru-billing.md            RU 计费
│
├── tools/                   ← 12 个 API 工具的完整参数文档
│   ├── run_multi_formula.md
│   ├── read_data.md
│   └── ...（正常链路无需提前阅读，遇到参数问题时查）
│
├── presets/                 ← 已验证的常用数据（按需加载）
│   ├── cases_index.yaml         106 张案例卡片目录（量化标准场景必读，快速查数无需）
│   ├── assets.yaml              常用资产
│   ├── functions.yaml           常用函数
│   ├── data_catalog.yaml        常用数据集
│   ├── sectors.yaml             行业板块
│   └── themes.yaml              题材板块
│
├── scripts/                 ← 执行脚本
│   ├── call.py                  工具统一入口（所有命令通过它调用）
│   ├── executor.py              call.py 的底层（禁止直接调用）
│   ├── quant_api.py             Python SDK（供其他脚本 import）
│   ├── auth/                    认证脚本
│   └── eval/                    评测脚本
│
└── output/                  ← 输出目录（自动创建）
    ├── .session.json            当前 session task_id
    ├── ic_data/                 IC 扫描结果
    └── *.png / *.csv            图表和数据文件
```

---

## ⛔ 执行顺序（路由前必读，所有场景必须遵守）

**无论匹配到哪个 leaf workflow，执行顺序固定为：**

```
① read_skill_file("workflows/global-rules.md")  →  ② read_skill_file(leaf workflow)  →  ③ 执行
```

- **步骤 ① 是硬前置条件**。未读取 `global-rules.md` 即读取 leaf workflow 或开始执行 = 违规，即使最终结果恰好正确也不可接受。
- 先路由确定目标 leaf → 然后 **先读 global-rules → 再读 leaf workflow** → 最后执行。
- 禁止读完路由表就直接跳转 leaf workflow。

---

## 场景路由

**先识别用户意图，确定目标 leaf workflow；然后按上方执行顺序加载**：

| 场景 | 触发词 | 目标 leaf workflow |
|------|--------|----------|
| 最新时点行情 / 估值（快照） | 最新价、今日收盘、最新涨跌幅、当前换手率、最新PE/PB/市值… | `global-rules.md` → `quick-snapshot.md` |
| 最近N日序列 / 窗口统计 | 最近5日、最近20日、近N个交易日、窗口最高/最低/振幅…（仅单资产、最近N日） | `global-rules.md` → `quick-window.md` |
| 最近报告期财务 | 营收、净利润、归母净利润、ROE、总资产、总负债、资产负债率… | `global-rules.md` → `quick-report-period.md` |
| K线图（可视化） | K线图、画图、展示走势… | `global-rules.md` → `render-kline.md` |
| 固定区间累计涨跌幅 | 从A到B、某年某月至某年某月、区间收益、累计涨跌幅、区间表现、多资产区间对比 | `global-rules.md` → `period-return-compare.md` |
| 量化选股 / 回测 / 因子 / 图表 / 上传下载 | 选股、回测、均线、PE选股、因子、净值、上传CSV、下载数据、画图… | `global-rules.md` → `quant-standard.md` |
| 事件研究 | 复盘、历次、涨价、降息、加息、事件窗口、随后表现、超预期、不及预期、政策后表现…（给定事件或需先识别事件日） | `global-rules.md` → `event-study.md` |
| 阈值区间统计 / 连续阶段 | 历次、每次、平均、回撤超过、从高点下跌超过、熊市区间、连续阶段、regime | `global-rules.md` → `regime-segmentation.md` |

> 上传、下载、画图不是独立场景——它们是 workflow 内的子步骤，workflow 文档会在需要时指引你读对应的 `recipes/`。

### 路由硬排除（优先于触发词匹配）

以下规则在触发词匹配**之前**检查，命中即强制改道，不得被触发词覆盖：

| 用户意图特征 | 禁止进入 | 强制导向 | 判断依据 |
|-------------|---------|---------|---------|
| 盘中/实时/当前/现在/今天/今日/当日 + 查询日内行情（涨幅排名、涨停、日内跌幅等） | `quick-snapshot` `quick-window` | `quant-standard.md`（优先匹配分钟频卡片） | 需要分钟频卡片的专用公式；`use_minute_data: true` 已是全局默认 |
| 盘中/实时/当前/今天/今日/当日 + 全市场/板块 + TopN/排名/阈值名单/选股/筛选/信号 | `quick-snapshot` `quick-window` | `quant-standard.md` → 优先命中"实时横截面 TopN 排名"或"盘中阈值筛选_名单查询"微流程 | 这类高频短题有专用封闭微流程 |
| 给出明确起止日期，只问区间累计涨跌幅/收益 | `event-study` `quick-window` `quant-standard` | `period-return-compare.md` | 本质是固定区间收益比较，不是因果窗口分析，也不是复杂量化流程 |
| 行业/板块聚合排名（如"申万行业涨幅前5"） | `quick-window` `quick-snapshot` | `quant-standard.md` | 需要横截面聚合，不是单资产序列 |
| 阈值触发型离散事件识别（如"跌幅超过X%的次数"，问每次后表现） | — | `event-study.md`（阈值触发模式） | 需先识别阈值事件日，再做窗口分析 |
| 由阈值条件定义连续区间（如"历次熊市""回撤超30%的阶段"） | `event-study` | `regime-segmentation.md` | 研究的是连续阶段而非离散事件后的窗口 |
| "创近N日新高/新低"（不含"首次"修饰词） | 不得加"昨日未满足"条件 | 按**当前状态**判断（state check），公式只比较当前值与昨日的N日极值 | 只有用户明确出现"首次突破/首次跌破""新晋""今日第一次"时，才允许追加首次触发条件；详见 `quant-standard.md` |

判断口诀：
- **有明确起止日 + 只问区间数值** → `period-return-compare`（固定区间收益比较）
- **有事件 + 问"随后N天/月表现"** → `event-study`（因果窗口）
- **有阈值条件 + 问"每次发生后表现"** → `event-study`（阈值触发模式）
- **有阈值条件 + 问"连续阶段/区间内表现"** → `regime-segmentation`（连续阶段统计）

若用户请求满足以下任一模式，应优先判定为【快速查数任务】，按以下路由直接跳转，不得先进入其他 workflow：

**快速查数路由（按优先级依次判断，首个匹配即停）：**

1. 时间锚点是"最近 N 日窗口/序列" → 直接加载 `workflows/quick-window.md`
2. 时间锚点是"最近报告期"且字段属于财务类 → 直接加载 `workflows/quick-report-period.md`
3. 用户明确要"画图 / K线 / 带成交量走势" → 直接加载 `workflows/render-kline.md`
4. 其余（明确是最近完成交易日的行情/估值/多资产对比，且**不含** 今天/今日/当日/当前/现在/实时/盘中/排名/筛选 语义）→ 直接加载 `workflows/quick-snapshot.md`

> 上述路由不需要先读 `workflows/quick-lookup.md`。

### 关键红线速查（即使未读 global-rules.md 也必须遵守）

以下 4 条规则从 global-rules.md 摘录，**优先级最高**，对所有场景生效：

1. **事件定义冻结**：事件类型/范围必须**逐字匹配用户原始措辞**。用户说"年报/半年报"就只查年报和半年报，不得扩大到业绩预告/快报/季报；用户说"国务院或住建部"就只纳入该层级，不得扩大到央行/银保监会/地方政府。若认为用户定义可能遗漏，在回答末尾**建议**扩大，不得擅自扩大。
2. **evidence-only 回答**：最终答案只输出本轮工具结果直接支持的数值、日期、排名、口径说明。未经工具验证，禁止默认输出宏观归因、政策归因、方向性判断（"通常""往往""偏正面"）。
3. **去过程化交付**：禁止「已成功获取」「让我来」「按照流程」「Step 1/2/3」「根据 workflow」等过程性话术；禁止泄露 `_working/` 路径、checkpoint 名称、workflow 文件名。查到即答，不展示内部过程。
4. **条件口径冻结**：用户条件必须原样执行，禁止任何改写（百分比↔小数、相对时间→年份区间、资产宇宙替换、卡片附加条件继承）。详见硬规则第 6 条。

触发词参考：
- 最近交易日收盘 / 最新已披露PE / 最新市值（非盘中、非筛选） → `quick-snapshot`
- 最近5日 / 最近20个交易日 / 近N日序列 / 窗口最高最低 → `quick-window`
- 营收 / 净利润 / ROE / 总资产 / 总负债 / 资产负债率 → `quick-report-period`

禁止：
- 优先调用 `scanDimensions`、`renderKLine`（除非用户明确要看图）
- 先做分析性扩写，再补充结构化数值
- **在读取对应 leaf workflow 之前**直接调用 `runMultiFormula` / `renderKLine` / `scanDimensions` / 输出"无法联网"或"无法获取实时数据"
- 把卡片附加条件（首次/非ST/封板/流动性门槛等）默默继承进最终答案
- 以 `description`、`samples`、预览行、截断大表作为**名单题**的完整结果直接收尾（必须提取完整名单或明确声明不完整）

**leaf workflow 最终回答合同优先**：leaf workflow 中的"最终回答合同"优先负责收紧该场景的输出格式；若 leaf workflow 已满足停止条件，必须直接按该合同输出，不得再解释内部过程。

## 执行权授权规则

**规则层级（从高到低）：**

1. **SKILL.md**：路由 + 全局门禁（硬规则 4 条、路由硬排除）
2. **global-rules.md**：所有 leaf 必须遵守的全局合同（执行合同、证据分级、简答模式、不补精度、方法限制说明、参数规范、数值精度、终答一致性检查）
3. **leaf workflow**：当前任务的具体执行流程（checkpoint、模板、停止条件、格式化）

**冲突解决**：
- leaf workflow 中的具体规则（如 readData 模式选择）优先于 global-rules 的一般规则
- 但 leaf workflow 不得**放宽** global-rules 的红线（如证据分级门槛、不补精度原则）
- 不得从其他 leaf workflow 借用模板、fallback 或回答格式

**quick-lookup.md 的定位**：
- 仅作为快查子流程的路由入口和规则参考总表
- 各 leaf workflow 已自包含所有执行规则，执行时无需回到 quick-lookup.md
- quick-lookup.md 不定义任何 leaf 独有规则

## 全局执行规则

> **全局合同详见 `workflows/global-rules.md`，进入任何 leaf workflow 时自动生效。**
> leaf workflow 可在其内部添加更严格的约束，但不得豁免或放宽 global-rules 中的规则。

## 平台数据覆盖范围

| ✅ 支持 | ⚠️ 有条件支持 | ❌ 不支持（短期内不会支持） |
|------|------|------|
| A股个股（沪深主板/创业板/科创板/北交所） | ETF / LOF / 场外基金（先以 `confirmMultipleAssets` 结果为准，能确认则正常执行；确认失败才告知不支持） | 期货 / 期权 |
| 港股个股（HK + 代码，如 HK0001） | | 台股 / 韩股 / 日股 / 德股等其他境外市场 |
| 美股个股（NASDAQ: 代码.N；NYSE: 代码.O；AMEX: 代码.A） | | |
| 主要宽基指数（沪深300、中证500、万得全A等） | | |

> **港股 / 美股数据范围限制**：港股和美股目前仅支持**行情价格类数据**（收盘价、开盘价、最高价、最低价、涨跌幅、成交量、成交额）。估值数据（PE/PB/市值等）和财务数据（营收/净利润/ROE等）暂不支持。查询港股/美股的估值或财务字段时，应主动告知用户当前不支持，而不是静默跳过。

### 股票代码格式速查

| 市场 | 格式 | 示例 |
|------|------|------|
| A股-上交所 | SH + 代码 | SH600000 |
| A股-深交所 | SZ + 代码 | SZ000001 |
| 港股 | HK + 代码 | HK0001 |
| 美股-NASDAQ | 代码.N | AAPL.N |
| 美股-NYSE | 代码.O | AAL.O |
| 美股-AMEX | 代码.A | SBE.A |

> 确认资产失败（熔断规则）详见 `workflows/quick-lookup.md` § Step 1。

> 环境依赖（Python版本、Playwright、API Key）→ `references/environment.md`
> 故障排查 → `references/troubleshooting.md`
> RU 计费 → `references/ru-billing.md`

---

## 前置条件（按需执行，不是简单查数的默认首步）

仅在以下情形下，才需要显式读取 `config.json` 检查 `api_key`：
- 本轮实际需要调用本地脚本或平台工具，且当前环境尚未建立可用 session
- 上一轮工具调用已出现 401 / 402 / 明确认证错误
- workflow 明确要求执行脚本链（如本地 Python 脚本渲染）

对已命中 leaf workflow 的简单查数题（quick-snapshot / quick-window / quick-report-period / render-kline）：
- 不要为了形式完整额外读取 `config.json`
- 优先直接按 leaf workflow 执行
- 仅当工具调用出现明确认证问题时，再回到认证向导

原则：认证检查服务于执行，不应成为简单题的固定额外步骤。

- 若 `api_key` **非空** → 正常继续
- 若 `api_key` **为空** → **立即停止**，启动认证向导

---

### 认证向导

> PowerShell 5.1 中多行 `-c` 会被拆开执行，故用独立脚本 + 环境变量传参。
> **所有脚本必须在 skill 根目录（即本 SKILL.md 所在目录）下执行，禁止从备份目录执行。**

| 步骤 | 操作 |
|------|------|
| 1. 询问手机号 | `ask_questions` 弹输入框收集手机号 |
| 2. 发短信（见下方平台适配） | 执行 `_send_code.py`，从 stdout **解析 JSON**，提取 `session_token` 和 `is_registered` |
| 3. 询问验证码 | `ask_questions` 弹输入框收集验证码 |
| 4. 判断登录/注册 | 若 Step 2 返回 `is_registered: true` → 调用 `_login.py`；否则 → 调用 `_register.py` |
| 4a. 注册返回 409 | 已注册 → 改调 `_login.py` |
| 5. 写入 | 将 `api_key` 写入 `config.json`，告知用户「认证完成」 |

#### 平台适配

```bash
# Step 2
GZQ_PHONE='<手机号>' python scripts/auth/_send_code.py
# Step 4（login 或 register）
GZQ_TOKEN='<session_token>' GZQ_SMS='<验证码>' python scripts/auth/_login.py
```

#### 关键规则

- **session_token 必须从 Step 2 的 stdout 解析**，不可省略。若 stdout 为空或脚本报错，检查是否在 skill 根目录执行。
- **禁止在 sendCode 返回"发送太频繁"后立即重试**——等待用户收到验证码后继续传给 Step 4 即可（验证码已成功发送，只是重发被限流）。
- Step 4 **必须传 `GZQ_TOKEN`（session_token）+ `GZQ_SMS`（验证码）**，缺一不可。

**运行时 401/402** → 立即停止，提示用户 API Key 无效/过期/配额耗尽，重走认证向导。

---

## 工具调用方式

所有工具通过 `scripts/call.py` 调用。`call.py` 会同时将结果打印到 stdout 和写入临时文件。

### 标准调用（一步完成）

```bash
python scripts/call.py <工具名> '{"key":"value"}'
```

结果直接从 stdout 获取。若 stdout 被截断，可回读 `/tmp/gzq_out.txt`。

也可通过环境变量传参（适用于参数含特殊字符的场景）：

```bash
GZQ_PARAMS='<JSON>' python scripts/call.py <工具名>
```

### 禁止事项

| 禁止 | 原因 |
|------|------|
| 创建自定义 .py 写参数文件 | 环境变量方案已解决编码问题 |
| 直接调用 `scripts/executor.py` | `call.py` 封装了 renderChart 自动保存等逻辑 |
| `echo` 管道传参（Windows） | GBK 编码截断中文 |
| 命令行参数传 JSON（Windows） | PS 吃掉双引号 |

---

## presets/、recipes/、tools/ 三个目录的分工

| 目录 | 是什么 | 何时读 |
|------|---------|--------|
| **presets/** | 平台实际返回值的本地快照（YAML）。资产名、函数格式、数据集 index_title、行业/概念名等。**直接可用于公式**，省掉确认类 API 调用。 | 写公式前先查 preset；找不到再调对应 API，并把新结果补回 preset。`cases_index.yaml` 仅在**选股/回测/因子/图表等量化标准场景**（`quant-standard.md`）开始时必读；快速查数场景（quick-snapshot/window/report-period）无需读取。 |
| **recipes/** | 端到端使用示例（Markdown）。展示完整场景——从参数准备到最终输出。 | 由 workflow 在具体步骤中指引加载（不独立触发）。 |
| **tools/** | API 参数手册（Markdown）。每个工具的字段、类型、约束。 | 默认不读。workflow 工具表标注了「必读」或报错时再查。 |

> **简言之**：presets 是数据快照，recipes 是完整教程，tools 是参数字典。
> presets 6 个文件的详细用法和加载时机→ 当前 workflow 文档内的「预设资源」表。

---

## Skill 更新部署规范（LLM 必读）

当用户要求更新本 skill（发送 zip 压缩包）时，必须严格遵守以下规则：

### 备份位置

⚠️ **备份目录禁止放在 `skills/` 目录下。** 否则 openclaw 会把备份也识别为一个独立 skill，导致后续请求可能误用旧版代码。

正确做法：

```bash
# 备份到 skills/ 之外的位置
cp -r ~/.openclaw/workspace/skills/quant-buddy-skill ~/.openclaw/workspace/quant-buddy-skill-backup-$(date +%Y%m%d%H%M)

# ❌ 错误：备份仍在 skills/ 下
# cp -r ~/.openclaw/workspace/skills/quant-buddy-skill ~/.openclaw/workspace/skills/quant-buddy-skill-backup-xxx
```

### 解压覆盖

```bash
# 解压到临时目录再拷贝（避免嵌套）
TMPDIR=$(mktemp -d)
unzip -o <压缩包路径> -d "$TMPDIR"
# 如果解压出嵌套目录 quant-buddy-skill/，取内层
if [ -d "$TMPDIR/quant-buddy-skill" ]; then
  cp -rf "$TMPDIR/quant-buddy-skill/"* ~/.openclaw/workspace/skills/quant-buddy-skill/
else
  cp -rf "$TMPDIR/"* ~/.openclaw/workspace/skills/quant-buddy-skill/
fi
rm -rf "$TMPDIR"
```

### 部署后检查

1. 确认 `~/.openclaw/workspace/skills/` 下只有 `quant-buddy-skill/` 一个与本 skill 相关的目录
2. 读取 `SKILL.md` 确认版本号
3. 保留 `config.json` 中已有的 `api_key`（若用户之前已认证过）