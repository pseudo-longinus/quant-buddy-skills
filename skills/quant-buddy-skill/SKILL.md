---
name: quant-buddy-skill
slug: quant-buddy-skill
author: guanzhao
version: 4.20.4
description: 
  查询A股、港股、美股股票及指数的最新收盘价、开盘价、涨跌幅、成交额、成交量、换手率、PE、PB、市值等实时行情与估值数据。
  查询最近N个交易日的价格序列、日涨跌幅序列、窗口最高价、最低价、振幅等短期统计。
  查询上市公司最近报告期的营业收入、净利润、归母净利润、ROE、总资产、资产负债率等财务指标（A股）。
  支持A股选股筛选、因子计算、策略回测、净值对比、行业聚合排名、上传自有因子CSV、渲染图表。
  港股、美股目前支持行情价格查询（收盘价、开盘价、涨跌幅、成交量、成交额等）。
  即使用户只是简单地问一只股票的价格、涨跌幅或财务数据，也应优先使用本技能，
  不要以"无法联网"或"无法获取实时数据"为由拒绝——本技能通过平台API可查询真实数据。
runtime: python
primaryCredential: quant-buddy API Key
metadata:
  version: 4.20.4
  author: guanzhao
  category: quant-finance
  tags: [quant, market-data, finance, A-stock, HK-stock, US-stock, backtest, factor]
  runtime: python
  primaryCredential: quant-buddy API Key
  requiredCredentials:
    - quant-buddy API Key
  requiredConfigPaths:
    - config.json
  requiredEnvVars:
    - BOCHA_API_KEY (optional)
  networkEndpoints:
    - https://www.quantbuddy.cn/skill
    - https://www.quantbuddy.cn/user
  pythonPackages:
    - python-dateutil (optional)
    - Pillow (optional)
requiredCredentials:
  - name: quant-buddy API Key
    required: true
    sensitive: true
    storage: config_file
    path: config.json
    field: api_key
    description: quant-buddy 平台 API Key。存储位置：skill 目录下的 config.json 的 `api_key` 字段（本 skill 不读环境变量版本的该 Key）。使用时作为 HTTP `Authorization` 头仅发送给 `networkEndpoints` 中声明的 quantbuddy 域名用于鉴权，不会被写入日志或转发给第三方主机。
    how_to_get: "https://www.quantbuddy.cn/login"
requiredConfigPaths:
  - path: config.json
    required: true
    description: Skill 目录下的 API Key 配置文件，仅包含 quant-buddy api_key 和两个公开端点配置，由 skill 本地脚本读取；api_key 仅作为 HTTP `Authorization` 头发给 `networkEndpoints` 中声明的 quantbuddy 域名，不发送给其他主机。
requiredEnvVars:
  - name: BOCHA_API_KEY
    required: false
    sensitive: true
    description: 可选。仅 scripts/event_study_local.py 的事件新闻搜索功能读取；未配置时该可选功能自动禁用，其它功能不受影响。
    how_to_get: "https://open.bochaai.com"
networkAccess: true
networkEndpoints:
  - https://www.quantbuddy.cn/skill
  - https://www.quantbuddy.cn/user
runtimeRequirements:
  python: "3.8+"
  packages:
    - name: python-dateutil
      version: ">=2.8"
      required: false
      description: Used by scripts/event_study_local.py for the optional event-study / Bocha news feature. Not needed if BOCHA_API_KEY is not configured.
    - name: Pillow
      version: ">=9.0"
      required: false
      description: Used by scripts/call.py saveChart command to convert chart images to JPEG. Falls back gracefully (writes raw bytes) if not installed; no credential exposure risk.
---

# 观照量化投研

> **⚠️ 必读：本文件较长，必须完整读取，不要设置 limit 参数截断。前 50 行不包含操作规范。**

## 硬规则（8 条，违反必失败）

0. **开工第一步：先查 API Key，再做任何其他事**。收到新问题后的第一个动作必须是读 `config.json`（或等效检查 api_key 字段）：
   - 若 `api_key` 为空字符串 → **立即停止**，直接输出「前置条件」章节的**新用户引导消息**，**禁止** newSession、**禁止**读 workflow / quick-lookup / 任何业务文档、**禁止**调用 `scripts/call.py` 或任何平台工具。等用户贴入 `sk-` 开头的 Key 后再执行「配置向导」。
   - 若 `api_key` 非空 → 继续第 1 条。
   - **唯一例外**：用户本轮消息本身就是 `sk-` 开头的 Key（进入配置向导）或与查数无关的闲聊/元问题（如"你会做什么"）。
   - **为什么**：查数类工作流最终都会调 `scripts/call.py`，api_key 为空时必然失败。提前在入口拦截可以避免多次失败调用，给新用户直接、清晰的第一印象。

1. **每个新问题/新对话必须新建 session**：收到用户的新问题后，在调用任何平台工具之前，必须先新建 session（优先直接调用原生 `newSession` 工具；仅当当前环境没有原生 `newSession` 时，才使用 `GZQ_PARAMS='{"user_query":"<用户的问题>"}' python scripts/call.py newSession`）。newSession 是本地 UUID 生成，不可省略；`user_query` 仅用于本地 session 初始化标注，方便后续 trace 分析。
   - **为什么**：session 文件会自动注入到所有工具调用中。不新建 session = 复用上一轮对话的 task_id = 变量名冲突风险 + session 污染。
   - **多会话隔离（必须）**：当本对话有可能与其他对话/进程并行使用本 skill（多个 Claude 窗口、共享开发机、并行 trace）时，**在 chat 的第一条 bash 命令里**先执行：
     ```bash
     export QBS_SESSION_KEY=$(python -c "import uuid;print(uuid.uuid4().hex[:12])")
     ```
     之后**所有 `python scripts/call.py` 都必须在这同一个 terminal 会话里跑**（环境变量只在该会话内可见）。如此每个对话独占 `output/.session.<key>.json` 文件，互不覆盖。未设置时退化到默认 `.session.json`，仅适合单会话场景。
   - **唯一例外**：同一对话中的追问/续问（如"再画个图""换个时间段"），可复用当前 session（`QBS_SESSION_KEY` 也保持不变）。
2. **原生工具优先，脚本包装仅限无原生等价能力时**：平台已提供的原生工具（`fast_query`、`confirmMultipleAssets`、`confirmDataMulti`、`runMultiFormulaBatch`、`readData`、`renderKLine`、`renderChart` 等）必须优先直接调用；禁止用 `run_skill_script`、shell 命令、`GZQ_PARAMS=... python scripts/call.py ...` 等方式包装这些原生工具；`scripts/call.py` 仅用于：① `newSession` 等管理动作；② workflow 明确要求的本地脚本步骤；③ 平台不存在等价原生工具时的兜底。
   - **⛔ 典型违规反例（直接失败）**：`confirmMultipleAssets` 的 `intentions` 本身就是数组，设计意图是「一次传多个资产名同时确认」；**任何在 for 循环 / while 循环里对它重复调用的写法都是违规**，无论是通过原生工具还是 `scripts/call.py` 包装。需批量确认资产时，应单次调用并传完整数组；若数组过大，则按批传入（每批一次调用），而不是每个资产调用一次。
  - **确认资产也必须先查本地库**：用户明确说「确认资产 / 批量确认 / confirm / 找代码 / 找ticker」时，仍然先走本地资产路由：`presets/assets.yaml`（可读完）→ `grep presets/assets_db/{类型}.yaml`（禁止整文件读取）→ 仍未命中再调用 `confirmMultipleAssets`。不得因为用户使用了「确认」二字就直接调用工具。
  - **英文代码无市场后缀时必须 grep 确认格式**：用户直接输入英文股票代码（如 `GOOGL`、`AAPL`、`BIDU`）但未携带市场后缀（`.O`、`.N`、`.A`）时，**不得凭 user memory / 猜测 / 拼接后缀直接查数**，必须先 `grep presets/assets_db/stock_us.yaml` 找到正确 ticker 后再调用工具。
  - **⛔ 严禁用 inline 解释器 heredoc / `-c` 包装 `scripts/call.py`**：以下写法**全部违规**，无论参数有多复杂、批次有多少、依赖关系有多绕：
    - `python - <<'PY' ... subprocess.run(['python','scripts/call.py','<工具名>',...]) ... PY`
    - `python -c "import subprocess; subprocess.run(['python','scripts/call.py',...])"`
    - `node -e "...child_process.execSync('python scripts/call.py ...')..."`
    - 任何在 inline 脚本里 `for/while` 循环驱动多批 `runMultiFormulaBatch` 的写法
    - **理由**：这种「自写 driver 脚本」会绕过本 skill 的 session 注入、配额校验、错误协议；trace 中表现为 task_id 漂移、stdout 阻塞、`/tmp/gzq_out.txt` 在 Windows 上不存在等连锁失败。call.py 的兜底地位**只允许一层调用**（shell → call.py），不允许在它外面再套 python/node 解释器。
  - **多批 `runMultiFormulaBatch` 的合规模板**：当公式数超过单批硬上限（20 条）需切批时，切批与编排**必须由 LLM 自己在工具调用之间完成**，禁止写脚本自动化。每批一次独立调用；任何参数预处理（读 md、regex、依赖分析、生成 `force_reusable_array`）都在 LLM 推理中完成，必要的中间产物用 `create_file` 落盘到 `output/tmp_batches/batch_K.json`，然后逐批用：
    ```bash
    GZQ_PARAMS="$(cat output/tmp_batches/batch_K.json)" python scripts/call.py runMultiFormulaBatch
    ```
    **每批一条独立 shell 命令**，前一批返回后再发起下一批；**禁止**写一个 python 脚本一次跑完所有批。这是 hard rule，违反必失败。
3. **先读 workflow 再操作**：按下方「场景路由」表加载对应 workflow，不要自行猜测参数格式。
4. **配置/认证错误立即停止，不得在普通查数流程中转为认证收集**：
   - **工具返回 API Key 缺失错误**（含 `api_key 为空` 消息 / `code: 1`）：立即停止查数，输出**新用户引导消息**（格式见「前置条件」章节模板），禁止继续执行查数；等待用户粘贴 Key 后再执行配置向导。
   - **其他工具报错**（网络、服务端错误等）：直接报告"内部工具异常"，不做认证相关引导。
5. **最终答案首句必须是数据结论**：回答用户时，第一句话必须直接给出数据结论（如资产名+数值、表格、或"符合条件的共N只"），绝对禁止以"已成功获取""数据已获取""根据返回结果""让我来"等过程性陈述开头。违反此规则 = 必须删除过程话术后重新输出。
6. **用户条件冻结，不得改写**：执行前必须逐字核对用户原始条件，以下改写行为均属违规（一旦发现必须回退并重新确认）：
   - **百分比↔小数互转**（如"股息率>3%"禁止改写为 `>0.03`）
   - **相对时间改为年份区间**（如"过去10年"禁止改写为"2015-2025"）
   - **资产宇宙替换**（如"普通股票"禁止改写为"万得全A成分股"或"非ST股"）
   - **事件口径扩大**（如"年报/半年报"禁止扩大为全部业绩披露类型）
   - **卡片附加条件继承**：命中知识卡片后，若卡片含用户未明确提出的"首次/非ST/封板/流动性门槛"等附加条件，必须先删除再执行，禁止默默继承进最终答案
7. **任务含糊时先反问，禁止猜测开干**：若用户的指令有 **2 种以上合理解读**（如"批量确认X"不清楚是确认指数本身还是全部成分股、"分析一下Y"不清楚要哪个维度），**第一步必须向用户提问澄清，不得凭推测选择一种解读自行执行**。反问应简洁列出各种可能（例："您的意思是 ① … 还是 ② …？"），等用户确认后再继续。**唯一例外**：用户语义明确无歧义（如"给我贵州茅台今日收盘价"），无需反问。
8. **工具返回 `SKILL_VERSION_MISMATCH` 时必须自愈，不得继续执行原任务**：当任何工具调用的输出中出现 `"error": "SKILL_VERSION_MISMATCH"` 时，说明当前对话上下文中的工具签名/参数格式已过时。此时必须执行以下自愈流程（每步不得省略）：
   1. **立即停止**当前任务，不得再调用任何平台工具；
   2. 调用 `newSession`（新建 session，获取新 task_id）；
   3. **强制重读** `SKILL.md`（本文件）+ 当前场景对应的 workflow 文档 + 涉及的 tools/*.md；
   4. 以**新读取**的工具签名和参数格式重新执行用户原始任务；
   5. **禁止**询问用户"是否继续"或解释版本升级过程——直接静默完成自愈并返回结果。

## 最小充分原则（任何动作前自检）

> 默认走最窄路径；只在收到"明确不够用"的证据后，才扩大范围。

**每次准备读文件、调工具、扩大读取范围前，回答三个问题**：

1. **这一步要解决的具体问题是什么？** — 必须能用一句话写成"为了 X，所以做 Y"，其中 X 是**已经发生**的需求，不能是"可能会需要 X"、"以防万一"、"先准备着"。
2. **有没有更窄的选项能完成同样的 X？** — 更下游的输出 / 更精简的文件 / 更少的字段 / 不调用这个工具直接构造。
3. **当前选择如果失败，下一步是什么？** — 如果答不上来，说明还没想清楚就在动手。

任一回答含糊 → 不做这一步。

**扩大范围的唯一合法触发**：上一步工具明确返回了"缺数据 / 字段不存在 / 失败"，且失败原因可以追溯。不允许用"为了更全面"、"为了更准确"、"为了避免遗漏"作为理由。

> 这条原则覆盖：要不要多读一个文档；readData 读哪个变量；要不要为某个字段调 confirmDataMulti；公式自己写还是查现成数据集；以及所有未来出现的同类决策。

**工具层面落地**：调用 `confirmDataMulti` / `readData` / `runMultiFormulaBatch` 或加载额外文档前，必须先勾选 [`recipes/tool-call-checklist.md`](recipes/tool-call-checklist.md) 对应小节（每节 5–10 行）。顶层原则管"要不要做"，清单管"具体怎么做"。

## Skill 包根目录

**本 SKILL.md 所在目录即为 skill 根目录（`SKILL_ROOT`）**，下文所有相对路径均以此为基准。
所有终端命令必须先 `cd` 到此目录再执行。

```
SKILL_ROOT/
├── config.json              ← API Key 配置（按需读取；非每题必读）
├── SKILL.md                 ← 本文件（入口 + 路由）
│
├── workflows/               ← 业务流程编排（路由目标）
│   ├── fast-snapshot.md         Fast Path：最新时点行情/估值（≤3资产，标量）
│   ├── fast-window.md           Fast Path：最近N日序列/窗口统计
│   ├── fast-report-period.md    Fast Path：最近报告期财务（≤3资产）
│   ├── quick-lookup.md          快速查数路由器 + 共享基础规则
│   ├── quick-snapshot.md        最新时点行情/估值快照（字段齐即停）
│   ├── quick-window.md          最近N日短窗序列/窗口统计
│   ├── quick-report-period.md   最近报告期财务指标
│   ├── period-return-compare.md 固定区间累计涨跌幅对比
│   ├── global-rules-lite.md     精简全局规则（quick-window/period-return-compare 专用）
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
├── tools/                   ← API 工具的完整参数文档
│   ├── run_multi_formula.md
│   ├── read_data.md
│   └── ...（正常链路无需提前阅读，遇到参数问题时查）
│
├── presets/                 ← 已验证的常用数据（按需加载）
│   ├── cases_index.yaml         106 张案例卡片目录（量化标准场景必读，快速查数无需）
│   ├── assets.yaml              常用资产（99 行精选，可一次读完）
│   ├── assets_db/               全量资产字典（按类型分文件，⚠️ 仅 grep 检索，禁止 read_file 整文件；不含指数成分股映射）
│   │   ├── stock_a.yaml             A 股 5505 条（SH/SZ）
│   │   ├── stock_hk.yaml            港股 2862 条（HK 前缀，仅行情）
│   │   ├── stock_us.yaml            美股 1044 条（.N/.O/.A，仅行情）
│   │   ├── index.yaml               指数 503 条
│   │   └── future.yaml              期货 257 条
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
    ├── .session.<key>.json      当前 session task_id（按 QBS_SESSION_KEY 派生，多会话隔离）
    ├── ic_data/                 IC 扫描结果
    └── *.png / *.csv            图表和数据文件
```

---

**全局 429 处理（所有路径均适用）**：

| error.code | 处理 |
|---|---|
| `RATE_LIMIT_EXCEEDED` / `CONCURRENT_LIMIT` | 读 `retryAfter` 秒后**静默重试**，不向用户暴露 |
| `WINDOW_QUOTA_EXCEEDED` | **立即停止**，读 `references/troubleshooting.md` 配额限流段，输出提示 |
| `DAILY_QUOTA_EXCEEDED` / `DAILY_SCAN_EXCEEDED` | **立即停止**，输出：`⚠️ 今日额度已满，次日 00:00 重置。` |
| `SERVICE_OVERLOADED`（503） | `retryAfter` 秒后静默重试 1 次，仍失败则告知"系统繁忙，请稍后重试" |

---

## ⛔ 执行顺序（路由前必读，所有场景必须遵守）

**无论匹配到哪个 leaf workflow，执行顺序固定为：**

```
① read_skill_file(global-rules 版本，见下表)  →  ② read_skill_file(leaf workflow)  →  ③ 执行
```

**步骤 ① 全局规则文件选择（按目标 leaf workflow 确定）**：

| 目标 leaf workflow | 步骤 ① 读取的文件 |
|---|---|
| `fast-snapshot.md` | 无（Fast Path，跳过步骤 ①，直接执行） |
| `fast-window.md` | 无（Fast Path，跳过步骤 ①，直接执行） |
| `fast-report-period.md` | 无（Fast Path，跳过步骤 ①，直接执行） |
| `quick-window.md` | `workflows/global-rules-lite.md` |
| `period-return-compare.md` | `workflows/global-rules-lite.md` |
| 其他所有 workflow | `workflows/global-rules.md` |

- **步骤 ① 是硬前置条件**。确定目标 leaf 后，先按上表选择并读取对应 global-rules 版本，再读 leaf workflow，最后执行。
- Fast Path（fast-*.md）直接从步骤 ② 开始，无需步骤 ①。

---

## 场景路由

**先识别用户意图，确定目标 leaf workflow；然后按上方执行顺序加载**：

| 场景 | 触发词 | 目标 leaf workflow |
|------|--------|----------|
| 最新时点行情 / 估值（快照） | 最新价、今日收盘、最新涨跌幅、当前换手率、最新PE/PB/市值… | Fast Path → `fast-snapshot.md` / 完整链路 → `global-rules.md` → `quick-snapshot.md` |
| 最近N日序列 / 窗口统计 | 最近5日、最近20日、近N个交易日、窗口最高/最低/振幅…（仅单资产、最近N日） | Fast Path → `fast-window.md` / 完整链路 → `global-rules-lite.md` → `quick-window.md` |
| 最近报告期财务 | 营收、净利润、归母净利润、ROE、总资产、总负债、资产负债率… | Fast Path → `fast-report-period.md` / 完整链路 → `global-rules.md` → `quick-report-period.md` |
| K线图（可视化） | K线图、画图、展示走势… | `global-rules.md` → `render-kline.md` |
| 固定区间累计涨跌幅 | 从A到B、某年某月至某年某月、区间收益、累计涨跌幅、区间表现、多资产区间对比 | `global-rules-lite.md` → `period-return-compare.md` |
| 量化选股 / 回测 / 因子 / 图表 / 上传下载 | 选股、回测、均线、PE选股、因子、净值、上传CSV、下载数据、画图… | `global-rules.md` → `quant-standard.md` |
| 直接运行用户给定的公式链文件 | 「运行/跑一遍/执行这个文件里的全部公式」「公式链文件」「formula chain」「按这个 md/json 跑」 | `global-rules.md` → `run-formula-chain.md` |
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

**Fast Path 条件（同时满足以下 3 点才可走 Fast Path；否则走完整链路）：**

- 资产数 ≤ 3
- 所有目标字段属于 fast_query whitelist（价格/估值/财务/衍生字段，详见 `tools/fast_query.md`），不涉及自定义公式/选股/排名
- 非全市场横截面查询（不是"全市场排名/前N只"等场景）

**快速查数路由（按优先级依次判断，首个匹配即停）：**

1. 时间锚点是"最近 N 日窗口/序列" → Fast Path 条件满足时读 `workflows/fast-window.md`，不满足则 `workflows/global-rules-lite.md` → `workflows/quick-window.md`
2. 时间锚点是"最近报告期"且字段属于财务类 → Fast Path 条件满足时读 `workflows/fast-report-period.md`，不满足则 `workflows/global-rules.md` → `workflows/quick-report-period.md`
3. 用户明确要"画图 / K线 / 带成交量走势" → 直接加载 `workflows/render-kline.md`
4. 其余（明确是最近完成交易日的行情/估值/多资产对比，且**不含** 今天/今日/当日/当前/现在/实时/盘中/排名/筛选 语义）→ Fast Path 条件满足时读 `workflows/fast-snapshot.md`，不满足则 `workflows/global-rules.md` → `workflows/quick-snapshot.md`

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
- **在读取对应 leaf workflow 之前**直接调用 `runMultiFormulaBatch` / `renderKLine` / `scanDimensions` / 输出"无法联网"或"无法获取实时数据"
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

> **凭据存储说明**：本 skill 的 quant-buddy API Key **只存放在 skill 目录下的 `config.json` 的 `api_key` 字段**，不使用环境变量（`QUANT_BUDDY_API_KEY` 等环境变量不会被读取）。仅可选的 `BOCHA_API_KEY`（事件新闻搜索）走环境变量。

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
- 若 `api_key` **为空** → **立即停止**，禁止继续查数，输出以下**新用户引导消息**（原样输出，不得删减）：

  ---
  ⚠️ 尚未配置 API Key，当前无法查询数据。

  前往 https://www.quantbuddy.cn/login 登录/注册并获取 API Key，然后直接发给我：
  > 帮我配置 APIkey：sk-xxxxxxxx
  ---

---

### 配置向导（用户粘贴 Key）

当用户消息中包含 `sk-` 开头的字符串时：

1. 从用户消息中提取 `sk-` 开头的完整 Key 字符串
2. 将 Key 写入 `config.json` 的 `api_key` 字段（用 `replace_string_in_file` 直接写入）
3. **必须输出**：「✅ API Key 配置成功！」
4. **自动重试**：若本对话中有被 api_key 缺失错误中断的查询（如之前用户问过行情），**先调 `newSession`（以原始用户问题作为 `user_query`）新建 session**，再立即重新执行该查询并给出数据结论，不需要用户再次发起。

**运行时 401/402** → 立即停止，提示用户 API Key 无效/过期/配额耗尽，请重新前往官网获取新的 Key 并重新配置。

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