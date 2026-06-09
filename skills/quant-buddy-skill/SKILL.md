---
name: quant-buddy-skill
slug: quant-buddy-skill
author: guanzhao
version: 4.21.1
description: |
  查询A股、港股、美股股票及指数的最新收盘价、开盘价、涨跌幅、成交额、成交量、换手率、PE、PB、市值等实时行情与估值数据。
  查询最近N个交易日的价格序列、日涨跌幅序列、窗口最高价、最低价、振幅等短期统计。
  查询上市公司最近报告期的营业收入、净利润、归母净利润、ROE、总资产、资产负债率等财务指标（A股及部分港/美股字段，以工具返回为准）。
  查询单只股票的预计算指标画像，按估值、财务分析、资金流向、波动率、宏观胜率背景、资产走势等维度返回最新值与上一期值。
  支持A股选股筛选、因子计算、策略回测、净值对比、行业聚合排名、上传自有因子CSV、渲染图表。
  港股、美股优先支持行情价格查询；财务/报告期字段应先尝试 fast_query(report)，按工具实际返回决定。
  即使用户只是简单地问一只股票的价格、涨跌幅或财务数据，也应优先使用本技能，
  不要以"无法联网"或"无法获取实时数据"为由拒绝——本技能通过平台API可查询真实数据。
runtime: python
primaryCredential: quant-buddy API Key
metadata:
  version: 4.21.1
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
    - <config.endpoint>/skill/registerFormulaPackage  # 公式任务包：注册（需 api_key）
    - <config.endpoint>/skill/queryFormulaPackage     # 公式任务包：取数（无需 api_key，SSE）
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

> **首屏优先**：先读本文件前部的「平台工具参数速查」「硬规则」和「场景路由」。简单行情、窗口序列、最近报告期、固定区间收益、K 线图等高频任务命中 Fast Path 时，无需继续整本通读。

## 平台工具参数速查（高频踩坑，先看这一段）

> 下表是 LLM 最容易写错的三个 schema。任何调用前先核对，不要凭"看起来合理"猜参数名。

| 工具 | ✅ 正确参数 | ❌ 模型常见错误（已被 call.py 自动归一化或拦截，但仍应避免） |
|------|------------|------------------------------------------------------------|
| `confirmDataMulti` | `{"data_desc": "市盈率 TTM,股息率"}` — **逗号分隔字符串** | `{"queries": [...]}` / `{"query": "..."}` / `{"names": [...]}` |
| `runMultiFormulaBatchStream` 公式中引用 session 中间变量 | 必须用**双引号**包裹：`排序値 = "A股股息率〔估値数据〕" * "条件合并"` | 裸变量名相乘：`"A股股息率…" * 条件合并` ← 平台直接报错 |
| `readData` | `{"ids": ["69fe…<24位hex>"], "mode": "last_column_full"}` — **必须是 `runMultiFormulaBatchStream` 返回的 `data_id` 字段（hex）** | 传中文变量名 `{"ids": ["Top10股息"]}` / 用错参数名 `{"index_title": "..."}` / `{"variable_names": [...]}` / **传 `expression_id` 而非 `data_id`**（两者相邻易混，传错会返回 `"error": "IndexInfo {id}"`）|

**口径转换（confirmDataMulti 查询词）**：用户写 `PE(TTM)` / `归母净利润` 等英文或缩写时，查询词应使用**中文规范名**（如 `市盈率 TTM` / `归母净利润`），而不是把用户原文照抄进 `data_desc`。详细规则见 `workflows/global-rules.md#指标口径精确匹配`。

---

## 硬规则（违反必失败）

0. **工具名与 unknown-tool 红线（最高优先级）**：
   - 公式执行唯一可调用工具名：`runMultiFormulaBatchStream`。
   - 禁止调用或重试旧名/错名：`runMultiFormulaBatch` / `runMultiFormula` / `run_multi_formula`。
   - 任何工具返回 `未知工具` / `Unknown tool` / `tool not found` 后，同名工具 **0 次重试**，也不得尝试名称变体。
   - 若 workflow 已声明唯一正确原生工具，只允许切换到该工具 1 次；仍失败则立即输出受控失败答复。
   - 若上一步结果已足够回答用户问题，必须直接收敛回答，禁止继续升级工具链。

1. **认证后验与 session 初始化**：
   - 不要在普通查数题第一步读取 `config.json`，也不要检查 `.session.json`、`output/.session*.json` 或任何本地 session 文件。
   - 只要本轮准备调用平台原生工具，先直接调用原生 `newSession`；不得用 Bash / Glob / Read / ls 做 session 存在性探测。
   - 工具实际返回 `api_key 为空` / `code: 1` / 401/402 时才进入认证引导并停止当前查数任务。
   - 同一对话追问可复用当前 session；新问题必须新建 session。
2. **原生工具优先，禁止脚本包装**：
   - 平台已有原生工具时，必须直接调用原生工具：`fast_query`、`confirmDataMulti`、`runMultiFormulaBatchStream`、`resumeJob`、`readData`、`renderKLine`、`renderChart` 等。
   - 禁止用 Bash / shell / Python / `scripts/call.py` / `run_skill_script` 包装已有原生平台工具。
   - 只有平台明确不存在等价原生工具，且 workflow 明确允许脚本兜底时，才可使用本地脚本。
   - **许可例外（csv 解析）**：当 `fast_query` 返回 `mode:"csv"` + `csv_url`（数据点 > 500 的正常交付）时，调用 `python scripts/fetch_fastquery_csv.py "<csv_url>"` 下载并解析该 csv 属于**许可路径**——这是消费工具返回的 OSS 产物（平台无等价原生解析工具），不算"包装原生工具"。但仍禁止用裸 `curl` / 自写临时脚本替代该脚本。
   - 涉及资产时仍需先用 `grep presets/assets_db/{类型}.yaml` 搜索本地资产库，禁止整文件读取；命中多条先澄清，未命中再交给服务端兜底解析。
   - 英文代码无市场后缀时必须先 grep 对应资产库确认 ticker 格式。
3. **工具失败熔断：同类错误不得重复**
   - 同一工具、同一参数结构、同一错误类型出现第 1 次后，只能按 workflow 声明的备用路径切换；无备用路径则受控失败。
   - 禁止无新信息地重复调用失败工具；禁止尝试名称变体；禁止读更多文档代替执行；禁止用 shell/Python 包装绕过失败工具。
4. **任何 workflow 失败退出时必须输出受控失败答复**：禁止以空白或纯过程日志结束对话。失败答复必须包含：
   - ①用户的原始问题（一句话复述）
   - ②失败卡在哪一步（工具名 + 错误摘要）
   - ③给用户的一句话说明（"当前无法获取…，原因：…"）
   - 可选④：用户可采取的下一步（如"稍后重试"或"换用完整链路"）
5. **先读 workflow 再操作**：按下方「场景路由」表加载对应 workflow，不要自行猜测参数格式。
6. **配置/认证错误立即停止，不得在普通查数流程中转为认证收集**：
   - **工具返回 API Key 缺失错误**（含 `api_key 为空` 消息 / `code: 1`）：立即停止查数，输出**新用户引导消息**（格式见「前置条件」章节模板），禁止继续执行查数；等待用户粘贴 Key 后再执行配置向导。
   - **其他工具报错**（网络、服务端错误等）：直接报告"内部工具异常"，不做认证相关引导。
7. **最终答案首句必须是数据结论**：回答用户时，第一句话必须直接给出数据结论（如资产名+数值、表格、或"符合条件的共N只"），绝对禁止以"已成功获取""数据已获取""根据返回结果""让我来"等过程性陈述开头。违反此规则 = 必须删除过程话术后重新输出。
8. **用户条件冻结，不得改写**：执行前必须逐字核对用户原始条件，以下改写行为均属违规（一旦发现必须回退并重新确认）：
   - **百分比↔小数互转**（如"股息率>3%"禁止改写为 `>0.03`）
   - **相对时间改为年份区间**（如"过去10年"禁止改写为"2015-2025"）
   - **资产宇宙替换**（如"普通股票"禁止改写为"万得全A成分股"或"非ST股"）
   - **事件口径扩大**（如"年报/半年报"禁止扩大为全部业绩披露类型）
   - **卡片附加条件继承**：命中知识卡片后，若卡片含用户未明确提出的"首次/非ST/封板/流动性门槛"等附加条件，必须先删除再执行，禁止默默继承进最终答案
9. **任务含糊时先反问，禁止猜测开干**：若用户的指令有 **2 种以上合理解读**（如"批量确认X"不清楚是确认指数本身还是全部成分股、"分析一下Y"不清楚要哪个维度），**第一步必须向用户提问澄清，不得凭推测选择一种解读自行执行**。反问应简洁列出各种可能（例："您的意思是 ① … 还是 ② …？"），等用户确认后再继续。**唯一例外**：用户语义明确无歧义（如"给我贵州茅台今日收盘价"），无需反问。

   **⚠️ 模糊词处理规则（先判断是否真歧义，再决定反问还是默认口径直行）**：

   下列词在量化语义中存在多种定义，必须正确处理：
   - **技术分析类**：支撑位 / 阻力位 / 压力位 / 颈线位 / 关键位 / 关键点位 / 突破位
   - **走势判断类**：趋势 / 趋势预测 / 后市判断 / 还能不能涨 / 会不会跌 / 短期看法 / 中线看法
   - **盘面定性类**：异动 / 主力 / 主力流向 / 庄家动向 / 强势 / 弱势 / 抗跌 / 抗跌性
   - **健康度类**：基本面好不好 / 估值贵不贵 / 财务健康 / 业绩怎么样 / 基本面

   **判定流程（按顺序匹配，命中即停）**：

   1. **综合分析请求 → 用默认口径直行，禁止反问阻塞**。
      判定：用户在一句话里列出 ≥2 个分析维度（如"基本面 + 技术指标 + 趋势"、"估值 + 财务 + 走势"），或明确说"全面分析 / 综合看一下 / 给一份报告"。
      做法：直接走 `stockProfile`（综合画像）+ 常规技术指标 + 默认趋势口径，**报告首句**告知用户使用的口径（例："本次按以下默认口径输出：基本面=综合画像（估值+财务+资金流+波动率），技术=MACD/KDJ/RSI/布林带，趋势=MA20/MA60 排列方向。如需调整口径请告诉我。"）。

   2. **孤立的单点定义性请求 → 必须反问**。
      判定：触发词单独出现，且其定义直接决定结论数值（如"贵州茅台支撑位是多少"、"宁德时代趋势怎么样"，无任何其他维度上下文）。
      做法：反问 ① 口径定义（如"支撑位"=近N日最低/布林下轨/均线密集区）；② 时间窗口；③ 输出格式。

   3. **触发词只是修饰语 → 直行**。
      判定：用户主体诉求清晰，触发词只是顺带描述（如"找最近基本面改善的股票"主体是筛选，"基本面改善"已隐含"营收/净利同比上升"等可执行口径）。
      做法：用最常见的可执行口径执行，并在结果中标注口径。

   **实测教训（T-036）**：用户问"贵州茅台支撑位"，模型擅自用"60日最低价附近"作为定义直接执行——这是孤立单点请求，应走流程 2 反问。
   **反例（不要再犯）**：用户问"分析东方财富的基本面、技术指标、趋势预测"，模型反问 4 个问题阻塞——这是综合分析请求，应走流程 1 默认口径直行。
10. **工具返回 `SKILL_VERSION_MISMATCH` 时必须自愈，不得继续执行原任务**：当任何工具调用的输出中出现 `"error": "SKILL_VERSION_MISMATCH"` 时，说明当前对话上下文中的工具签名/参数格式已过时。此时必须执行以下自愈流程（每步不得省略）：
   1. **立即停止**当前任务，不得再调用任何平台工具；
   2. 调用 `newSession`（新建 session，获取新 task_id）；
   3. **强制重读** `SKILL.md`（本文件）+ 当前场景对应的 workflow 文档 + 涉及的 tools/*.md；
   4. 以**新读取**的工具签名和参数格式重新执行用户原始任务；
   5. **禁止**询问用户"是否继续"或解释版本升级过程——直接静默完成自愈并返回结果。
11. **CHANGELOG / skill-changelog 仅作为审计，不作为规则源**：`CHANGELOG.md`、`skill-changelog/**` 是按时间叠加的变更记录，包含已被后续版本反转或废弃的旧口径。任何「执行顺序、字段名、协议块语义、工具签名、参数格式」相关的判断，**必须**以 `SKILL.md` + `workflows/**` + `tools/**` + `references/troubleshooting.md` 为唯一权威；CHANGELOG 描述与上述文件冲突时，以上述文件为准。CHANGELOG 仅可用于：① 排查问题时回看「哪一版动过什么」；② 升级成功后做 5 条以内的版本上下文摘要。**禁止**：把 CHANGELOG 某条历史叙述当作当前执行规则、依据 CHANGELOG 推断现行参数格式、或在 CHANGELOG 与 SKILL.md 冲突时偏向 CHANGELOG。

## Fast Path / Leaf workflow 顶部硬闸门（每次进入 leaf 都生效）

> 修复 T-001 / T-011 / T-024 等 leaf 没把 `newSession` 当成首条强制步骤、跳过直接调平台工具的问题。

无论路由进入 `fast-snapshot` / `fast-window` / `fast-report-period` / `render-kline` / 任何 leaf workflow：

1. 准备调用任何平台原生工具（`fast_query` / `renderKLine` / `stockProfile` / `runMultiFormulaBatchStream` / `readData` / `downloadData` / `getCardFormulas` / `searchFunctions` / `searchSimilarCases` / `confirmDataMulti` / `scanDimensions` / `uploadData` / `renderChart` / `refreshSnapshotTime` / `resumeJob`）之前，**必须先调用 `newSession`**。
2. **不允许**用"已读 SKILL.md 就跳过 newSession"或"已读 leaf workflow 就跳过 newSession"来豁免本条；这条规则不依赖 leaf 内是否再次重申。
3. 同一对话追问可复用当前 session；但新的用户问题（含明显话题切换）必须重新 `newSession`，参数中 `user_query` 设为新问题原文。
4. 跳过 `newSession` 直接调用平台工具 = `MISSING_NEW_SESSION` 契约失败（HIGH 级），评分必扣分。

## 最小充分原则（任何动作前自检）

> 默认走最窄路径；只在收到"明确不够用"的证据后，才扩大范围。

**每次准备读文件、调工具、扩大读取范围前，回答三个问题**：

1. **这一步要解决的具体问题是什么？** — 必须能用一句话写成"为了 X，所以做 Y"，其中 X 是**已经发生**的需求，不能是"可能会需要 X"、"以防万一"、"先准备着"。
2. **有没有更窄的选项能完成同样的 X？** — 更下游的输出 / 更精简的文件 / 更少的字段 / 不调用这个工具直接构造。
3. **当前选择如果失败，下一步是什么？** — 如果答不上来，说明还没想清楚就在动手。

任一回答含糊 → 不做这一步。

**扩大范围的唯一合法触发**：上一步工具明确返回了"缺数据 / 字段不存在 / 失败"，且失败原因可以追溯。不允许用"为了更全面"、"为了更准确"、"为了避免遗漏"作为理由。

> 这条原则覆盖：要不要多读一个文档；readData 读哪个变量；要不要为某个字段调 confirmDataMulti；公式自己写还是查现成数据集；以及所有未来出现的同类决策。

**工具层面落地**：调用 `confirmDataMulti` / `readData` / `runMultiFormulaBatchStream` 或加载额外文档前，必须在心里完成工具清单自检；**不要为执行清单而搜索、加载或读取 `recipes/tool-call-checklist.md`**。无论该文件是否已在上下文中，只在心里完成以下三条最小自检即可（这三条已是清单的浓缩版，不需要再去查原文）：

1. 这次调用是否直接服务于用户当前问题？
2. 是否有更窄的输出或更少的字段可读？
3. 如果调用失败，下一步是否明确且只改一个维度？

顶层原则管"要不要做"，清单管"具体怎么做"。

## Skill 包根目录

**本 SKILL.md 所在目录即为 skill 根目录（`SKILL_ROOT`）**，下文所有相对路径均以此为基准。
所有终端命令必须先 `cd` 到此目录再执行。

```
SKILL_ROOT/
├── config.json              ← API Key 配置（按需读取；非每题必读）
├── SKILL.md                 ← 本文件（入口 + 路由）
│
├── workflows/               ← 业务流程编排（路由目标）
│   ├── fast-snapshot.md         Fast Path：最新时点行情/估值（≤1000资产，标量/CSV）
│   ├── fast-window.md           Fast Path：最近N日序列/窗口统计（≤2500日）
│   ├── fast-report-period.md    Fast Path：最近报告期财务（≤1000资产）
│   ├── quick-lookup.md          快速查数路由器 + 共享基础规则
│   ├── quick-snapshot.md        最新时点行情/估值快照（字段齐即停）
│   ├── quick-window.md          最近N日短窗序列/窗口统计
│   ├── quick-report-period.md   最近报告期财务指标
│   ├── period-return-compare.md 固定区间累计涨跌幅对比
│   ├── stock-profile.md         单股预计算指标画像
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
├── tools/                   ← API 工具完整参数文档（默认不读；workflow 标注「必读」或报错时再查）
│   │                           ⚠️ 下表列出所有可用工具的**实际调用名**，调用时必须使用此名，不得变体
│   ├── fast_query.md            → 工具名 `fast_query`          快速合并查询（行情/估值/财务，≤1000资产，支持CSV）
│   ├── confirm_data_multi.md    → 工具名 `confirmDataMulti`    批量确认数据项存在性与维度（写公式前必查）
│   ├── run_multi_formula.md     → 工具名 `runMultiFormulaBatchStream`  执行公式批次（选股/回测/因子计算）
│   ├── read_data.md             → 工具名 `readData`            读取公式计算结果（需传 data_id，非 expression_id）
│   ├── render_kline.md          → 工具名 `renderKLine`         渲染 K 线图（直接传 ticker，无需提前跑公式）
│   ├── stock_profile.md         → 工具名 `stockProfile`        单股预计算指标画像（估值/财务/资金/波动/走势）
│   ├── render_chart.md          → 工具名 `renderChart`         渲染折线/柱状/面积图（需先有 data_id）
│   ├── get_card_formulas.md     → 工具名 `getCardFormulas`     按卡片名拉取完整公式组（量化场景使用）
│   ├── scan_dimensions.md       → 工具名 `scanDimensions`      九维度 IC 扫描（单股多维度预测力分析）
│   ├── search_similar_cases.md  → 工具名 `searchSimilarCases`  向量检索相似案例（设计策略前的 fallback 查找）
│   ├── search_functions.md      → 工具名 `searchFunctions`     检索平台函数名称与调用格式
│   ├── download_data.md         → 工具名 `downloadData`        按 data_id 下载一维时序到 CSV/JSON
│   ├── upload_data.md           → 工具名 `uploadData`          上传自有因子 CSV，上传后可在公式中引用
│   ├── refresh_snapshot_time.md → 工具名 `refreshSnapshotTime` 强制刷新分钟数据截止时间（盘中实时场景）
│   ├── resume_job.md            → 工具名 `resumeJob`           续传 deferred 后台任务（配合 research_24h 使用）
│   └── formula_package.md       → 脚本 `scripts/formula_package.py` 注册公式组为「任务包」→ 凭 package_id+signature 无 key 取数（对外只读/前端页面接入）
│
├── presets/                 ← 已验证的常用数据（按需加载）
│   ├── cases_index.yaml         106 张案例卡片目录（量化标准场景必读，快速查数无需）
│   ├── assets.yaml              常用资产（99 行精选，可一次读完）
│   ├── assets_db/               全量资产字典（按类型分文件，⚠️ 仅 grep 检索，禁止 read_file 整文件；不含指数成分股映射）
│   │   ├── stock_a.yaml             A 股 5540 条（SH/SZ，含场内 ETF）
│   │   ├── stock_hk.yaml            港股 2862 条（HK 前缀；行情优先，财务以 fast_query 返回为准）
│   │   ├── stock_us.yaml            美股及境外ETF 1068 条（.N/.O/.A；行情优先，财务以 fast_query 返回为准）
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
│   ├── formula_package.py       公式任务包客户端（register/query/list/revoke/refresh，取数走 SSE）
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
| 最新时点行情 / 估值（快照） | 最新价、今日收盘、最新涨跌幅、当前换手率、最新PE/PB/市值… | Fast Path 条件满足 → 只读 `fast-snapshot.md`；不满足/无法查询 → `global-rules.md` → `quick-snapshot.md` |
| 最近N日序列 / 窗口统计 | 最近5日、最近20日、近N个交易日、窗口最高/最低/振幅…（仅单资产、最近N日） | Fast Path 条件满足 → 只读 `fast-window.md`；不满足/无法查询 → `global-rules-lite.md` → `quick-window.md` |
| 最近报告期财务 | 营收、净利润、归母净利润、ROE、总资产、总负债、资产负债率… | Fast Path 条件满足 → 只读 `fast-report-period.md`；不满足/无法查询 → `global-rules.md` → `quick-report-period.md` |
| 单股指标画像 / 个股综合分析 | 分析一下XX个股、看一下XX这只股票、个股画像、指标概览、估值财务资金走势综合看一下、基本面和估值怎么样… | `global-rules.md` → `stock-profile.md` |
| K线图（可视化） | K线图、画图、图片、带成交量图…（用户明确要求可视化 artifact） | `global-rules.md` → `render-kline.md` |
| 固定区间累计涨跌幅 | 从A到B、某年某月至某年某月、区间收益、累计涨跌幅、区间表现、多资产区间对比 | `global-rules-lite.md` → `period-return-compare.md` |
| 数据下载 / 导出本地 CSV | 下载成CSV、导出到本地、保存到本地、下载历史数据 | `global-rules.md` → `recipes/download-data.md`；单资产单字段时序优先 `runMultiFormulaBatchStream` → `downloadData` → `write_skill_file`，禁止 Bash 兜底 |
| 量化选股 / 回测 / 因子 / 图表 / 上传下载 | 选股、回测、均线、PE选股、因子、净值、上传CSV、下载数据、画图… | `global-rules.md` → `quant-standard.md` |
| 直接运行用户给定的公式链文件 | 「运行/跑一遍/执行这个文件里的全部公式」「公式链文件」「formula chain」「按这个 md/json 跑」 | `global-rules.md` → `run-formula-chain.md` |
| 事件研究 | 复盘、历次、涨价、降息、加息、事件窗口、随后表现、超预期、不及预期、政策后表现…（给定事件或需先识别事件日） | `global-rules.md` → `event-study.md` |
| 阈值区间统计 / 连续阶段 | 历次、每次、平均、回撤超过、从高点下跌超过、熊市区间、连续阶段、regime | `global-rules.md` → `regime-segmentation.md` |
| 对外发布公式组 / 做取数页面 / 注册任务包 | 注册公式包、package_id、签名取数、做个能直接打开的页面/看板、前端实时取数、对外只读接口、第三方接入 | `tools/formula_package.md` + `recipes/formula-package.md`（用 `scripts/formula_package.py`，非平台原生工具）|

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

**Fast Path 条件（同时满足以下 2 点才可走 Fast Path；否则走完整链路）：**

- 所有目标字段属于 fast_query whitelist（价格/估值/财务/衍生/资金流向·南北向持股/商品现货·库存字段，详见 `tools/fast_query.md`），不涉及自定义公式/选股/排名
- 非全市场横截面查询（不是"全市场排名/前N只/行业筛选"等场景）

> 资产数量不再限制 Fast Path 路由（服务端支持 ≤1000 个资产）。超过 500 数据点时服务端自动返回 CSV 格式（OSS 下载链接），详见 `tools/fast_query.md` 限流与 CSV 模式段落。

**快速查数路由（按优先级依次判断，首个匹配即停）：**

0. 用户是开放式单股综合指标概览（如“分析一下XX个股”“看一下XX这只股票”“个股画像”“指标概览”“估值财务资金走势综合看一下”），且不是只问单字段/明确窗口/IC 预测力 → `workflows/global-rules.md` → `workflows/stock-profile.md`
1. 时间锚点是"最近 N 日窗口/序列"，或用户明确给出起止日期要求返回区间序列（如"从X日到X日每日的…走势/序列/数据"），或用户只说"最近走势/看走势"但未明确要图片/K线 → Fast Path 条件满足时读 `workflows/fast-window.md`，不满足则 `workflows/global-rules-lite.md` → `workflows/quick-window.md`；未给 N 时默认按最近 20 个交易日
2. 时间锚点是"最近报告期"且字段属于财务类 → Fast Path 条件满足时读 `workflows/fast-report-period.md`，不满足则 `workflows/global-rules.md` → `workflows/quick-report-period.md`
3. 用户明确要"画图 / K线 / 图片 / 带成交量图" → 直接加载 `workflows/render-kline.md`
4. 其余（明确是最近完成交易日或当日的行情/估值/多资产对比，且**不含** 排名/筛选/全市场 语义）→ Fast Path 条件满足时读 `workflows/fast-snapshot.md`，不满足则 `workflows/global-rules.md` → `workflows/quick-snapshot.md`
   > **说明**：含"今天/今日/当日/当前/现在/实时/盘中"但仅查单资产行情字段，属于日内刷新场景，`fast_query snapshot` 已自动启用盘中刷新（等效 `use_minute_data: true`），应直接走 Fast Path；上方"路由硬排除"已拦截"今天 + 全市场/板块 + 排名/筛选"，此处无需重复排除。

> 上述路由不需要先读 `workflows/quick-lookup.md`。

### 关键红线速查（即使未读 global-rules.md 也必须遵守）

以下 4 条规则从 global-rules.md 摘录，**优先级最高**，对所有场景生效：

1. **事件定义冻结**：事件类型/范围必须**逐字匹配用户原始措辞**。用户说"年报/半年报"就只查年报和半年报，不得扩大到业绩预告/快报/季报；用户说"国务院或住建部"就只纳入该层级，不得扩大到央行/银保监会/地方政府。若认为用户定义可能遗漏，在回答末尾**建议**扩大，不得擅自扩大。
2. **evidence-only 回答**：最终答案只输出本轮工具结果直接支持的数值、日期、排名、口径说明。未经工具验证，禁止默认输出宏观归因、政策归因、方向性判断（"通常""往往""偏正面"）。
3. **去过程化交付**：禁止「已成功获取」「让我来」「按照流程」「Step 1/2/3」「根据 workflow」等过程性话术；禁止泄露 `_working/` 路径、checkpoint 名称、workflow 文件名。查到即答，不展示内部过程。
4. **条件口径冻结**：用户条件必须原样执行，禁止任何改写（百分比↔小数、相对时间→年份区间、资产宇宙替换、卡片附加条件继承）。详见硬规则第 8 条。

触发词参考：
- 分析一下XX个股 / 看一下XX这只股票 / 个股画像 / 指标概览 / 估值财务资金走势综合看一下 → `stock-profile`
- 最近交易日收盘 / 最新已披露PE / 最新市值（非盘中、非筛选） → `quick-snapshot`
- 最近5日 / 最近20个交易日 / 近N日序列 / 窗口最高最低 → `quick-window`
- 营收 / 净利润 / ROE / 总资产 / 总负债 / 资产负债率 → `quick-report-period`

禁止：
- 优先调用 `scanDimensions`、`renderKLine`（除非用户明确要看图）
- 先做分析性扩写，再补充结构化数值
- **在读取对应 leaf workflow 之前**直接调用 `runMultiFormulaBatchStream` / `renderKLine` / `scanDimensions` / `stockProfile` / 输出“无法联网”或“无法获取实时数据”
- 资产已唯一命中 `presets/assets_db/future.yaml` 时，静态输出“平台不支持期货/期权”或“期货无法查询”；应先按行情/窗口序列工具链尝试，失败后只按工具返回说明当前品种或字段暂不可得
- 把卡片附加条件（首次/非ST/封板/流动性门槛等）默默继承进最终答案
- 以 `description`、`samples`、预览行、截断大表作为**名单题**的完整结果直接收尾（必须提取完整名单或明确声明不完整）

**leaf workflow 最终回答合同优先**：leaf workflow 中的"最终回答合同"优先负责收紧该场景的输出格式；若 leaf workflow 已满足停止条件，必须直接按该合同输出，不得再解释内部过程。

## 执行权授权规则

**规则层级（从高到低）：**

1. **SKILL.md**：路由 + 全局门禁（硬规则 10 条、路由硬排除）
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
| A股个股（沪深主板/创业板/科创板/北交所） | ETF / LOF / 场外基金（先 grep 本地资产库，能唯一命中则正常执行；未命中才告知不支持）；期货行情/窗口序列（先 grep `presets/assets_db/future.yaml`，唯一命中后按工具返回尝试行情字段；不承诺估值/财务/K线图） | 期权 |
| 港股个股（HK + 代码，如 HK0001） | | 台股 / 韩股 / 日股 / 德股等其他境外市场 |
| 美股个股（NASDAQ: 代码.N；NYSE: 代码.O；AMEX: 代码.A） | | |
| 主要宽基指数（沪深300、中证500、万得全A等） | | |

> **港股 / 美股数据范围限制**：
> - **行情价格类**（收盘价、开盘价、最高价、最低价、涨跌幅、成交量、成交额）：A / HK / US 均支持。
> - **估值类**：
>   - A/US/HK：`PE`/`PE_TTM`/`PB`/`PS_TTM`/`股息率`/`PCF`/`总市值`（港美股使用 TTM〔估值数据〕，日频，服务端自动映射）
>   - 仅 A 股：`流通市值`/`换手率`
>   - PE（静态）：A 股用静态 PE，港美股自动映射到 TTM 版
>   - 单季口径：`PE_单季`/`PB_单季`/`PS_单季`/`股息率_单季` 仍可用于显式查询季频数据
> - **财务类**（营业收入/净利润/归母净利润等）：A / HK / US 均支持（通过 `fast_query` 接口）；**ROE 仅 A 股**。
> - **资金流向 / 南北向持股类**（`fast_query` `snapshot`/`window`，**非 `report`**）：
>   - 仅 A 股：`主力资金净额`/`主力资金净占比`、`超大单/大单/中单/小单 净额·净占比`（主力 = 超大单 + 大单）
>   - 仅 A 股：`北向持股比例`（`陆股通持股比例`）/`北向持股市值`（2024-08 后季频/稀疏）
>   - 仅港股：`南向持股比例`/`南向持股市值`（日频）
>   - 走动态解析（非白名单，需用全称）：北向/南向「十大活跃股成交额」
>   - **不支持**：北向/南向「资金成交额·成交量·净买入」（市场级一维序列，无个股维度）——应走 `confirmDataMulti` + `readData`，而非 `fast_query`。
> - **商品期货类**（`fast_query` `snapshot`/`window`，仅 A 股期货品种，单位按品种）：
>   - 期货行情 `收盘价`/`开盘价`/`最高价`/`最低价`：单位按品种（白银元/千克、螺纹元/吨、黄金元/克…）
>   - `现货价格`（基差，多为元/吨）、`商品库存`/`库存按发布日`（单位按品种**推测**，带 `STOCK_UNIT_INFERRED` 警告）
>   - 用期货 ticker（如 `RB.SHF`）查询；**单位按品种发散时** `fields_meta[字段].unit_per_asset=true`，单位下沉到每资产值（`{v, unit}`），读值优先看资产内联 `unit`
> - 查询港股/美股时若字段不在上述支持范围内，应主动告知用户，而不是静默跳过。

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