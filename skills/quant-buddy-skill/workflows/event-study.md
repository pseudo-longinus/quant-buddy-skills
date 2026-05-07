# 事件研究

> **适用范围**：给定或可搜索到的历史事件日期，研究事件发生后资产在各时间窗口的表现。  
> 本流程定义本场景的专用执行步骤；全局执行合同、证据分级、禁语与回答边界仍以 `workflows/global-rules.md` 为准。

> ⛔ **硬前置条件**：进入本流程前 **必须** 已读取 `workflows/global-rules.md`。
> 未读取 = 本流程所有步骤无效，不得继续。

### 内联核心红线（来自 global-rules，无需额外读取即刻生效）

1. **evidence-only**：最终答案只输出工具结果支持的数值/日期/排名/口径说明；**禁止**输出"新冠疫情冲击""市场环境""利好出尽""政策宽松预期""OPEC+减产谈判"等无工具证据的归因——即使你认为这些是"常识"也不行
2. **去过程化**：禁止「已成功获取」「让我来」「按照流程」「Step 1/2/3」「数据已获取」等过程性话术；禁止泄露 `_working/` 路径/checkpoint/workflow 名
3. **事件定义逐字冻结**：用户说"2015年12月、2022年3月、2022年5月三次"就只查这三次，不得泛化为"2015-2022年区间内所有加息"；用户说"过去10年"就严格按10年筛选，不得扩大到更早
4. **资产口径冻结**：`assets_db` 本地资产库 返回与用户原口径不一致时，禁止静默替代
5. **输出前自检**：输出最终答案前，必须执行 global-rules 的 ⛔ 最终答案自检清单（删过程话术 → 删无证据归因 → 校验汇总数值 → 核对 Working State）

### 最小执行链（强制，不得跳过任何一步）

```
1. read_skill_file("workflows/global-rules.md")        ← 未完成则停止
2. 冻结 event_definition  → write event_definition.json ← 未完成则停止
3. grep presets/assets_db/{类型}.yaml 确认资产                        ← 未完成则停止
4. 确定事件日期 → write event_candidates.json            ← 未完成则停止
5. read event_candidates.json 读回确认
6. buildEventStudy
7. runMultiFormulaBatch
8. readData
9. 按 evidence-only 模板输出（禁止无证据归因）
```

> 跳过步骤 1-4 中的任何一步即为执行违规。即使最终数值恰好正确，流程不合规 = 不可接受。

---

## 执行协议：Abstract Target + Checkpoints + Backward Recovery

### Abstract Target
> 交付对象：给定事件日期集合，计算目标资产在每个事件日之后的各时间窗口累计收益，以结构化表格输出。

### Checkpoints

| CP | 名称 | 已验证状态 | Acceptance Test |
|----|------|-----------|-----------------|
| E0 | 场景+模式冻结 | 模式(single/compare/threshold)、资产、窗口已确定 | 模式为三者之一；资产已通过 presets/assets_db 唯一命中；窗口在映射表内 |
| E1 | 事件日期冻结 | 事件日期列表已确定 | 至少 1 个有效 YYYYMMDD 日期；跨时区口径已校正 |
| E2 | 公式生成冻结 | buildEventStudy 已返回 formulas | formulas 数组非空；warnings 已记录 |
| E3 | 数据已取 | runMultiFormulaBatch + readData 完成 | 每个窗口至少有 1 个有效数值；无全 NaN 列 |
| E4 | 交付完成 | 格式化输出 + Acceptance Test 通过 | 见下方 Acceptance Test 节 |

### Backward Recovery（失败时）

| 失败位置 | 回退到 | 允许修改的唯一 slot | 禁止 |
|---------|--------|-------------------|------|
| E1 搜索无果 | E0 | 搜索关键词（换措辞重搜） | 凭记忆编造日期 |
| E2 buildEventStudy 失败 | E1 | 日期格式或窗口参数 | 同时改资产和日期 |
| E3 runMultiFormulaBatch 失败 | E2 | 公式（换 prefix 或简化窗口） | 同时改日期和公式 |
| E3 readData 失败/全 NaN | E2 | 读取模式（换 mode） | 切换到其他 workflow |
| E4 数值不合理 | E3 | 重新 readData 验证 | 引入窗口外数据补救 |

### Retry Budget
- 同一 slot 最多改 1 次，总回退上限 2 次
- 超出后进入安全失败：输出已取到的部分数据 + 说明失败原因

> ⚠️ 429 错误不受本节 Retry Budget 约束——按 global-rules.md 第 12 条「429 前置拦截」规则处理。

### ⛔ 恢复禁区（公式失败时绝对禁止的路径）
- **禁止**直接跳 `run_skill_script` 手工计算核心数值
- **禁止**用 `webSearch` 搜索来补充核心结论（如事件次数、收益率）
- **禁止**在脚本 stdout 为空时手写 event_candidates
- 正确路径：检查语法 → `searchFunctions` 确认函数签名 → 仅重试失败公式

### Acceptance Test（E4 必检）
- [ ] 每个事件日都有对应的窗口收益行（缺失的标注"数据不足"）
- [ ] 收益值保留 2 位小数，百分比格式，不补伪精度
- [ ] 样本数 < 5 时，均值行标注"有限样本参考"
- [ ] 若有 warnings（窗口重叠），在表格前展示
- [ ] 阈值触发模式：明确列出阈值条件和识别到的事件日来源

---

## 触发条件

触发词命中以下任一：复盘、历次、涨价、降息、加息、事件窗口、随后表现、超预期、不及预期、政策后表现、事件研究。

### 排除条件（不进入本流程）

即使包含上述触发词，若用户意图属于以下情形，**不应**进入事件研究流程：

- **固定区间涨跌幅查询**：用户给出明确的起止日期，只问该区间内某资产的累计涨跌幅或价格变化（如"2019年7月至2020年3月降息周期内沪深300涨了多少"）→ 应走 `quant-standard.md`，直接用 `收盘价()` + `readData` 算区间收益
- **单纯行情走势描述**：用户只想知道某段时间的价格走势、最高最低点 → 应走 `quick-window.md` 或 `quant-standard.md`

**判断口诀**：
- 有明确起止日 + 只问区间数值 → `quant-standard`（区间查询）
- 有事件 + 问"随后N天/月表现" → 本流程（因果窗口）
- 有阈值条件 + 问"每次发生后表现" → 本流程（阈值触发模式）

## 场景识别

### 单组事件（single）

用户表达类似：

- 历次茅台提价后股价表现
- 美联储加息后沪深300怎么走
- 某政策出台后某股票 1周/1月/3月 表现

→ 走 `single` 模式。

### 分组对比（compare）

用户表达类似：

- 超预期 vs 不及预期
- 宽松政策 vs 收紧政策
- 利好公告 vs 利空公告

→ 走 `compare` 模式。

### 阈值触发（threshold）

用户表达类似：

- 国际油价单月跌幅超过20%共发生几次？每次后中国石油表现如何
- A股历次熊市（沪深300从高点下跌超30%）区间内消费行业超额收益
- 某指标突破某阈值后的市场表现

→ 走 `threshold` 模式。

**threshold 模式的关键区别**：事件日期不由用户直接提供，也不通过搜索获取，而是需要**先识别满足阈值条件的历史区间/日期**，再对这些日期做标准事件窗口分析。

threshold 模式执行流程：
```
Step 0  阈值事件日识别（本模式独有）
→ Step 1  确认事件日期（= Step 0 的输出）
→ Step 2~4  同 single 模式
```

**Step 0：阈值事件日识别**

首先判断阈值条件是否**可量化**（即能用平台数据计算）：

| 条件类型 | 示例 | 日期来源 |
|---------|------|---------|
| **可量化阈值** | 沪深300回撤>30%、油价月跌幅>20%、PE<10 | **必须**数据驱动（runMultiFormulaBatch + readData） |
| **不可量化阈值** | 历次大规模财政刺激、贸易战升级 | LLM 知识 + webSearch 交叉验证 |

#### A. 可量化阈值（数据驱动，不得跳过）

当阈值条件涉及可计算的数值指标（价格、指数点位、收益率、估值倍数等）时：

1. **用 grep presets/assets_db/{类型}.yaml 确认资产**
2. **用 confirmDataMulti 确认度量指标**（如 `收盘价()`、`PE(TTM)` 等）
3. **用 runMultiFormulaBatch 在公式层完成阈值筛选**（begin_date 需覆盖足够历史区间）——必须在公式中直接生成布尔掩码（如 `HIT=("月收益率"<-0.20)`），而不是取回完整序列后在回答层人工扫描
4. **用 readData (`last_column_full`) 读取筛选结果（布尔掩码 / 命中月份）**——因为只有少数命中点为 1，输出不会被截断
5. **从 readData 返回的非零点直接提取事件日期**

**⛔ 禁止取回完整连续序列后在回答层人工逐行扫描**：
- `last_column_full` 返回的月度/日度序列可能超过数千点，会被上下文截断，导致遗漏事件
- 必须让 runMultiFormulaBatch 在公式层完成 `<` / `>` 阈值判断，只把 0/1 结果传给 readData
- 实测反例（T-021, iter-013）：模型对 134 个月的月度收益率用 `last_column_full` 全量读取，返回被截断只剩 25 个月，导致 2018-11（-20.81%）被遗漏，最终只报 1 次事件而非 2 次

**⛔ 月度/季度/年度阈值采样标准配方（硬规则，不得自由换口径）**：

当阈值条件以"月/季/年"为单位时（如"单月跌幅超过20%"），**必须**使用以下标准配方：

```
Step A: 取日频收盘价序列  — BRENT_CLOSE=收盘价(IPE-布伦特原油)
Step B: 用 周期采样("收盘价序列", "月末基准日期") 提取每月最后一个交易日的收盘价  — BRENT_M=周期采样("BRENT_CLOSE","月末基准日期")
Step C: 用 ("月末价"/延迟("月末价",1))-1 计算相邻月末的环比收益  — BRENT_RET=("BRENT_M"/延迟("BRENT_M",1))-1
Step D: 在公式层生成布尔掩码  — HIT=("BRENT_RET"<-0.20)
Step E: readData(HIT, mode=last_column_full) 只读命中点，从非零日期提取事件月
```

> **Step D 是关键**：必须在 runMultiFormulaBatch 中完成阈值判断，生成 0/1 掩码。禁止跳过 Step D 直接对 Step C 的连续序列做 readData 全量扫描——序列过长会被截断导致遗漏。

**禁止**：
- 使用 `月度变频(价格序列, 中间值)` — 该函数可能导致采样点不在月末，口径不稳定
- 使用月内任意点（如月初第一个交易日）作为月度采样基准
- 使用 `MONTHLY_CLOSE()` / `MONTHLY_RETURN()` 等未经 `searchFunctions` 确认存在的函数
- 在未确认函数签名的情况下臆造函数名 → 必须先 `searchFunctions` 确认

**季度/年度同理**：`周期采样(序列, "季末基准日期")` / `周期采样(序列, "年末基准日期")`

**禁止**：
- 对可量化阈值使用 LLM 记忆或 webSearch 共识日期替代数据计算
- 仅凭"公开共识"跳过数据验证（如"A股历史上共有N次熊市"不是数据证据）
- 手工估算阈值触发点而非从序列中精确识别

#### B. 不可量化阈值（知识驱动）

当阈值条件无法用单一数值指标表达时（如政策事件、地缘变化）：

1. **LLM 领域知识**：对公开的、有确定性共识的事件，可直接给出日期，但必须逐一标注来源依据
2. **搜索验证**：用 webSearch 搜索"XX历次发生时间"进行交叉验证
3. **用户补充**：若无法从公开知识确定，告知用户"需要您提供满足条件的日期列表"

---

## 执行流程

```
Step 0.5  事件定义冻结（⛔ 硬门禁，不得跳过）
Step 1    确定事件日期
→ Step 2  buildEventStudy 生成公式
→ Step 3  runMultiFormulaBatch 执行公式
→ Step 4  格式化输出
```

### ⛔ Step 0.5：事件定义冻结（进入 Step 1 前必须完成）

在开始搜索或回忆事件日期**之前**，必须先完成以下 checklist：

- [ ] **用户原始事件定义**：逐字抄录用户对事件的描述（如"年报/半年报发布后"、"国务院或住建部出台重大房地产宽松政策"）
- [ ] **in-scope 事件类型**：仅限用户措辞覆盖的事件（如：年报、半年报）
- [ ] **out-of-scope 事件类型**：明确排除哪些相关但不同的事件（如：业绩预告、业绩快报、三季报、季报）
- [ ] **发布主体边界**（若适用）：用户指定"国务院或住建部"时，排除央行、银保监会、地方政府、交易商协会等其他主体

**冻结后不得修改**：后续 Step 1~4 的所有筛选、搜索、归类必须严格以此定义为唯一入样标准。若模型认为用户定义可能遗漏重要事件，在最终回答末尾**建议**扩大范围，不得擅自扩大。

## 事件锚点优先级（硬规则）

对于提价/公告/政策/财报/回购/分红等离散事件：
1. 默认 anchor_basis = announcement_date（首次公开披露日/公告日）
2. effective_date 仅记录，不自动替代公告日
3. 只有当用户明确要求按生效日统计时，才允许 anchor_basis = effective_date
4. 若最终锚点不是公告日，必须写明：
   - anchor_basis
   - anchor_override_reason
否则不得进入 buildEventStudy

## accepted candidate 最低证据要求（硬规则）

若 `final_decision = accepted`，以下字段不得为空、不得为 "-"：
- `label_evidence_quote`（支持该事件被接纳的具体证据引用）
- `evidence_event_type`（事件被归类的具体类型）
- `evidence_event_date`（事件发生的具体日期）
- `label_confidence`（对该事件分类的置信度）

缺少任一字段的 accepted candidate 视为无效，不得进入 buildEventStudy。

## 锚点一致性校验（硬规则）

- 若 `anchor_basis = announcement_date` 且 `announcement_date` 是交易日，则 `trading_anchor_date` 必须等于 `announcement_date`
- 若 `announcement_date` 非交易日，`trading_anchor_date` 才允许顺延至下一交易日
- 若 `anchor_basis` 与 `trading_anchor_date` 不一致且无合法顺延理由，不得进入 buildEventStudy

## 写后必读（强制步骤）

在写入以下文件后，必须立即 `read_skill_file` 回读并校验：
- `event_definition.json`
- `event_candidates.json`
- `event_selection.json`

校验项：
- 写入的内容与预期一致
- accepted candidates 满足上述最低证据要求
- 锚点一致性校验通过

校验不通过 = 不得进入 buildEventStudy / final answer

#### 发布主体 vs 发布场合（硬规则）

当用户限定了发布主体（如"国务院""住建部"）时：
- **发布主体** = 实际出台/签署政策的机构
- **发布场合** = 政策公开/宣布的会议/发布会地点
- **"国务院新闻办公室发布会"只是场合，不等于国务院出台了政策**
- **"国务院政策例行吹风会"只是场合，不等于国务院出台了政策**
- 必须识别**真正的政策制定方**：若政策由央行/金融监管总局/银保监会制定，只是在国务院系统的发布会上宣布 → 该事件的发布主体是央行等，不是国务院
- 筛选时以发布主体为准，不以发布场合为准

#### 政策事件主体边界细化（single / compare 模式常用）

适用范围：用户询问"某行业历次重大政策出台后，相关标的随后 N 日表现如何"，且明确限定了政策发布主体（如国务院、住建部、证监会、发改委）。

**仅当以下条件同时满足时启用本小节**：
- 事件类型是政策/监管/产业扶持类离散事件
- 用户对发布主体有明确限定
- 当前问题走事件研究，而不是固定区间复盘

**主体边界判断表**：

| 情形 | 正确认定 | 处理 |
|------|----------|------|
| 住建部印发正式通知/意见 | 主体 = 住建部 | 若 `subject_boundary` 包含住建部，可入候选 |
| 国务院或国务院办公厅正式印发政策文件 | 主体 = 国务院 | 若 `subject_boundary` 包含国务院，可入候选 |
| 国务院常务会议审议通过并形成正式政策文件 | 主体 = 国务院 | 以正式文件/会议决定为准，不以新闻标题缩写代替 |
| 国务院新闻办发布会、国务院政策例行吹风会 | 仅是发布场合 | 必须继续识别真正签发机构，不得直接记为国务院 |
| 央行/金融监管总局/银保监会发文，只是引用"落实国务院部署" | 主体 = 央行/金融监管总局/银保监会 | 若用户限定国务院/住建部，则 `in_scope=false` |
| 地方政府取消限购、下调首付 | 主体 = 地方政府 | 若用户限定中央部委，则 `in_scope=false` |

**政策性质判断表（以房地产宽松政策为例）**：

| 类型 | 是否可视为宽松政策 | 典型抓手 |
|------|--------------------|----------|
| 需求端放松 | 是 | 降首付、降利率、认房不认贷、限购松绑、购房补贴 |
| 供给端融资支持 | 是 | 白名单、支持房企融资、专项贷款、三支箭 |
| 去库存政策 | 是 | 收购存量商品房、棚改货币化、PSL 扩容 |
| 一般性表态 | 否 | 稳楼市、促进平稳健康发展、止跌回稳 |
| 宏观会议部署/听取汇报 | 否 | 研究部署、听取汇报、政策吹风、原则性定调 |

**`direct_policy_terms_hit` 预筛规则（硬规则）**：
- 若用户在问题中用括号或并列举例给出抓手（如"降首付、限购松绑"），应在 `event_definition.json` 中同步记录这些 `policy_terms`
- 候选事件只有在 `actual_subject` 合规且 `direct_policy_terms_hit = true` 时，才可进入 accepted 样本
- 若候选事件只体现泛宽松表态、会议部署或原则性定调，而未命中用户给出的直接抓手，必须 `in_scope=false`，`reason` 标注"未命中直接政策抓手"

**日期精度补充（硬规则）**：
- 政策事件若当前只能确认到年/月粒度，`date_precision` 只能写 `month` 或 `year`，不得补成该月 1 日
- 进入 `buildEventStudy` 前必须进一步细化到 `day`；若最终仍无法精确到日，该候选不得 accepted

将冻结结果写入 Working State 文件：

```json
write_skill_file({
  "path": "output/_working/{task_id}/event_definition.json",
  "content": "{\"event_definition\": \"用户原始措辞，逐字\", \"in_scope\": [\"事件类型1\", \"事件类型2\"], \"out_of_scope\": [\"排除类型1\", \"排除类型2\"], \"subject_boundary\": \"发布主体边界，若适用\", \"time_scope\": {\"raw\": \"用户原始时间表达，如过去10年\", \"type\": \"relative|absolute\", \"begin_date\": \"YYYYMMDD\", \"end_date\": \"YYYYMMDD\"}, \"sample_count_constraint\": \"用户要求的样本数，如各取2-3次；若用户未限定则为 null\"}"
})
```

**`time_scope` 字段（必填）**：
- `raw`：用户原始时间表达，逐字抄录（如"过去10年"、"2015年至今"、"最近5次"）
- `type`：`relative`（相对，如"过去10年"）或 `absolute`（绝对，如"2015-2023"）
- `begin_date` / `end_date`：转化为 YYYYMMDD；相对时间以当前日期为锚点计算
- 后续 Step 1 搜索到的候选事件，**必须过滤掉 time_scope 范围外的样本**；范围外的事件在 `event_candidates.json` 中标记 `in_scope: false, reason: "out of time_scope"`

**`in_scope` 字段（收敛原则，硬规则）**：
- `in_scope` 必须是用户措辞中**最严格的核心收敛解释**，不得为扩大样本量而纳入边缘类型
- 用户问"历次涨价"→ only include 正式出厂价/官方售价上调公告；不得扩展到"零售价指导价建议""市场自发调价"
- 若用户措辞有歧义，选择**最窄的合理解释**写入 in_scope，其余分类写入 out_of_scope 并说明
- 禁止事后修改已冻结的 in_scope 以纳入更多样本

**`sample_count_constraint` 字段**：
- 若用户明确限定了样本数（如"各取2-3次"），必须逐字记录
- 后续 accepted 样本数**不得超过**用户限定的上界
- 若实际可用样本少于用户下界，如实说明"仅找到N个满足条件的样本"，不得用低质量样本硬补

### Step 1：确定事件日期

**事件日期获取优先级（硬规则）**

当用户已显式给出有限个事件月份/日期、明确事件类型、明确样本数范围时，必须优先：
1. 冻结 `event_definition.json`
2. 写 `event_candidates.json`
3. 在 skill 内完成候选枚举与筛选

不得先用 `webSearch` 去"确认日期"。只有当用户时间锚点不足以形成唯一候选、或 skill 内无法完成确定性枚举时，才允许外搜。

**日期来源优先级（严格按序，首个命中即停）**：

> 对"过去N年/历次X事件"类问题，若平台数据可直接识别阈值事件（如通过 runMultiFormulaBatch 计算阈值触发日），不得优先使用 webSearch 生成事件池；webSearch 仅作兜底或证据补强。

1. **用户已提供**：用户消息中明确给出了日期列表 → 直接使用
2. **平台案例库**：`searchSimilarCases` / `getCardFormulas` 可获取结构化事件数据 → 使用案例中的日期
3. **Agent 自带搜索工具**：如果当前 Agent 有 web search 能力 → 优先用 Agent 搜索
4. **博查兜底**：以上全不可用时，调用本地 `webSearch` 工具搜索事件日期

#### 使用 webSearch 搜索日期

直接调用 `webSearch` 工具（无需通过 `run_skill_script`）：

```json
webSearch({"query": "茅台历次提价时间 日期", "count": 8})
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| query | string | 是 | 搜索关键词，应包含"日期""时间"等词以提高命中率 |
| count | int | 否 | 返回条数，默认 8 |
| freshness_months | int | 否 | 搜索时间范围（月），默认 36 |

从搜索结果的 snippet 中提取 YYYYMMDD 格式日期。

**日期规则**：
- 用户已明确给出精确日期 → 直接使用
- 用户给出月份/年份等近似范围（如"2015年12月加息"）→ 可用 LLM 知识将公开确定性事件（如 FOMC 会议日）精确到 YYYYMMDD
- 用户完全未提供、需要自行查找的日期 → **必须**通过搜索或案例库获取，禁止凭记忆编造
- 搜索无果时，告知用户"需要提供事件日期清单才能继续"

**⛔ 日期精度禁止伪装（硬规则）**：
- 当信息源（搜索结果 / LLM 知识）只提供到"年-月"粒度时（如"2006年2月"），**禁止**默认补充为该月1日（20060201）
- 必须通过进一步搜索或案例库精确到日，或标注 `date_precision: "month"` 并在候选表中说明
- 仅当有多个独立信源交叉确认具体日期时，才可将月级信息精确到日级
- **宁可少纳入一个事件，不可用伪精度日期污染事件研究**

**⛔ webSearch 不免除 Working State 义务**：
- 无论日期来自哪个渠道（用户提供 / LLM 知识 / webSearch / 案例库），都 **必须** 先完成 Step 0.5 的 `event_definition.json` 写入，再完成 Step 1.7 的 `event_candidates.json` 写入
- webSearch 是日期获取手段，不是结构化决策冻结的替代品
- 直接从 webSearch 结果跳到 buildEventStudy = 执行违规

**事件定义冻结规则（E1 硬规则 — 详见 Step 0.5）**：
- 所有搜索结果必须对照 Step 0.5 冻结的 `in_scope` / `out_of_scope` 逐条过滤（通过 `read_skill_file("output/_working/{task_id}/event_definition.json")` 读回）
- 搜索结果中出现 out-of-scope 事件时，必须**丢弃**，不得纳入日期列表
- 最终 `event_candidates.json` 中的日期仅包含通过 in_scope 校验的日期

**跨时区事件日期口径（硬规则）**：
- `某天后累加` 从事件日的**下一个交易日**开始计数，因此事件日应定义为"消息公布时 A 股尚未开盘的最后一个交易日"
- 对于北美/欧洲盘后公布的事件（如 FOMC 声明美东 14:00 = 北京时间次日凌晨），事件日取**美东公布当天的日历日**，而非 A 股首个反应日
  - 示例：FOMC 于美东 2015-12-16 宣布加息 → 事件日 = **20151216**（非 20151217）
  - 这样 `某天后累加` 自然从 12-17（A 股首个反应日）开始累加，完整捕获首日反应
- **禁止**将"A 股首个反应日"作为事件日——这会导致 `某天后累加` 从 T+2 开始，系统性丢失事件首日信息
### Step 1.5：事件日口径决策（强制执行）

当事件存在多个候选日期（公告日/执行日/生效日/首个交易日）时，必须先列候选日期，再选主口径。

**默认规则**：
- 用户问"股价/市场表现"（如"涨价后股价表现""分红后市场反应""扩产后走势"等）→ **必须用公告日**（announcement_date），不得改为生效日——股价在公告日即充分定价，生效日是执行层概念，非市场信息层
- 用户明确问"公告后市场反应" → 默认用公告日
- 用户明确问"实施/生效后市场表现" → 才允许用生效日，且须写明 anchor_override_reason
- 若公告时点不明确，且需区分盘中/盘后 → 不得自行脑补，必须说明不确定性

⚠️ **T-019 教训**：问"茅台历次涨价后一周/一个月/一年股价表现"时，trace 选用了生效日（顺延交易日）而非公告日，导致锚点偏移；正确做法是锁定公告日作为事件日。

**最终回答必须说明**：
- 采用哪一口径
- 未采用哪一口径
- 采用理由

### Step 1.6：事件样本准入闸门（财报/政策/阈值类必须执行）

若问题涉及人工归类或人工筛样（如超预期/不及预期、政策宽松/收紧、年报/半年报）：

**在调用 buildEventStudy 前**，必须先形成候选样本表：

| 事件类型 | 实际主体 | 原始披露日期 | 采用事件日 | 归类 | 证据原文 | 证据所属事件 | 证据置信度 | in_scope |
|---------|---------|------------|----------|------|---------|------------|-----------|----------|
| 年报 | 贵州茅台 | 2021-03-30 | 20210330 | 超预期 | "净利润同比+25%，一致预期+18%" | 2020年报 | explicit | true |

**准入规则（硬规则）**：
- 只有 `in_scope = true` 的样本可进入 buildEventStudy
- 用户限定"年报/半年报"时，不得纳入业绩预告、业绩快报、季报等题外事件
- 用户限定某一级别政策（如"国务院或住建部"）时，不得纳入地方执行、央行操作、政治局表态等题外事件
- 证据不足的样本宁缺毋滥，不得为凑样本数强行纳入
- 高度重叠的事件（间隔 < 5 个交易日）应合并为一个事件簇，取首日
- **time_scope 过滤**：不在 `event_definition.json` 中 `time_scope` 范围内的样本，`in_scope` 必须为 `false`
- **sample_count_constraint 遵守**：若用户限定"各取2-3次"，accepted 样本数不得超过 3

**compare 模式证据标签准入（硬规则）**：

当需要对事件进行分组标签（如超预期/不及预期、宽松/收紧）时：
- 每个标签必须有**具体、可复核的证据**支撑，不得使用笼统描述作为分类依据
- **可接受的证据**：研报标题明确含"超预期/不及预期"、财务数据 vs 一致预期的数值比较、政策文件原文中的明确表述
- **不可接受的证据**："业绩稳健增长""市场反应平淡""疫情下业绩韧性强"等模糊描述 → 不得作为超预期/不及预期的分类依据
- 若无法为某个事件找到满足上述标准的证据，该事件 `in_scope` 设为 `false`，`reason` 标注"证据不足以支撑标签判定"
- **宁可因证据不足减少样本，不可用弱证据硬贴标签**

#### 财报业绩超预期分类细则（compare 模式常用）

适用范围：用户询问"历次年报/半年报发布后，超预期 vs 不及预期随后表现如何"之类问题。

**仅当以下条件同时满足时启用本小节**：
- 事件限定为正式年报/半年报披露，不含业绩预告、业绩快报、季报
- 需要按"超预期/不及预期/符合预期"分组
- 当前问题走 compare 模式

**推荐执行顺序**：
1. 先确定正式披露日。优先用 `报告期转发布日(...)` 获取候选披露日；必要时再用交易所公告页、东财年报季报页做交叉验证
2. 对每个披露日逐期搜索：`{股票简称} {报告类型} {yyyymmdd} 超预期 OR 不及预期`
3. 将搜索结果写回 candidate，再按下表决定 `label` 与 `label_confidence`

| 分类结果 | 最低证据门槛 | `label_confidence` | 处理 |
|----------|--------------|--------------------|------|
| 超预期 | 至少 2 篇主流财经媒体/券商研报标题**明确**含"超预期""大超预期""显著好于预期"等同义表述 | `explicit` | 可入样 |
| 不及预期 | 至少 2 篇主流财经媒体/券商研报标题**明确**含"不及预期""低于预期""弱于预期"等同义表述 | `explicit` | 可入样 |
| 符合预期 | 标题原文**明确**含"符合预期""中规中矩""大致在预期内"等表述 | `explicit` | 仅当用户明确要求比较"符合预期"时入样；否则可记录为 rejected 候选 |
| 证据不足 | 无结果、只有 1 篇明确证据、或标题过于模糊无法落到具体标签 | `insufficient` | `in_scope=false` |
| 间接推断 | 仅凭股价反应、增速放缓、低于历史高位、市场情绪等间接线索推断 | `inferred` | `in_scope=false` |

**T22 类题的额外约束**：
- `label_evidence_quote` 必须直接引用标题原文，不得把搜索结论改写成自己的判断
- 可接受字眼包括："超预期"、"大超预期"、"显著好于预期"、"低于预期"、"弱于预期"
- 不可接受字眼包括："业绩稳健增长"、"增速放缓"、"韧性仍强"、"市场反应平淡"
- 若搜索结果没有明确超/不及预期字眼，**不得默认视为符合预期**；除非标题原文明确写出"符合预期"等表述，否则按 `insufficient` 处理
- 若某一组因证据不足被大量剔除，必须保留"样本不足"，不得通过放宽定义来凑满 2-3 次

**`label_confidence` 自动准入规则（硬规则）**：
- 每个候选样本必须填写 `label_confidence` 字段，取值仅限 `"explicit"` / `"inferred"` / `"insufficient"`
  - `explicit`：有数值比较、研报明确定性、政策原文等可复核证据
  - `inferred`：基于间接信息（如市场反应、新闻标题）推断，证据不够硬
  - `insufficient`：无法找到任何支撑标签的证据
- **`label_confidence = "insufficient"` → 强制 `in_scope = false`**，`reason` 标注"证据不足以支撑标签判定"
- **`label_confidence = "inferred"` → 强制 `in_scope = false`**，无任何例外。`reason` 标注"inferred 证据不满足准入标准"。若某组全部样本均为 inferred，在最终答案中说明"未找到满足证据标准的{组名}样本，该组为空"

**证据-事件交叉校验规则（硬规则）**：
- 每个候选样本必须填写 `evidence_event_type`（证据实际描述的报告类型，如"2022年报""2023H1半年报"）和 `evidence_event_date`（证据实际描述的报告期，如"2022年度""2023年上半年"）
- **`evidence_event_type` 必须与当前候选的 `event_type` 一致**：年报证据只能用于年报候选，半年报证据只能用于半年报候选
- **`evidence_event_date` 必须能唯一映射到当前候选事件的报告期**：不得用2023H1证据给2022年报贴标签
- 任一不匹配 → **强制 `in_scope = false`**，`reason` 标注"证据错配: 证据属于{evidence_event_type}({evidence_event_date})，当前候选为{event_type}"

**`actual_subject` 主体校验规则（硬规则）**：
- 每个候选样本必须填写 `actual_subject` 字段（真正的政策制定方/事件发布主体）
- 若 `event_definition.json` 中有 `subject_boundary`，则 `actual_subject` 必须落在 `subject_boundary` 范围内
- **`actual_subject` 不在 `subject_boundary` 内 → 强制 `in_scope = false`**，`reason` 标注"主体越界: {actual_subject} ∉ {subject_boundary}"

**未形成候选样本表，不得直接调用 buildEventStudy**。

### Step 1.7：写入 EventCandidateTable（强制执行）

完成候选样本表后，**必须**通过 `write_skill_file` 将其持久化为 `event_candidates.json`。

**每个 candidate 必须包含以下字段**：
- `candidate_id`
- `event_type`
- `actual_subject`
- `raw_date`
- `date_precision`: `day` | `month` | `year`
- `announcement_date`（首次公开披露日）
- `effective_event_date`
- `trading_anchor_date`
- `anchor_basis`: `announcement_date` | `effective_date`（默认 announcement_date）
- `anchor_rule`
- `subject_match`: `exact` | `approximate` | `out_of_boundary`
- `direct_policy_terms_hit`（用户括号中给出的示例关键词是否命中，布尔值或 null）
- `label`（compare 模式必填）
- `label_evidence_quote`
- `evidence_event_type`
- `evidence_event_date`
- `label_confidence`: `explicit` | `inferred` | `insufficient`
- `in_scope`
- `reason`
- `subject_evidence_quote`（政策/主体类事件时，记录主体判定的原文依据；非政策题可填 null）
- `policy_evidence_quote`（政策类事件时，记录政策性质判定的原文依据；非政策题可填 null）
- `evidence_consistency_check`（简述证据与当前 candidate 事件类型/日期/主体的一致性检查结论）
- `final_decision`: `accepted` | `rejected`（最终决定，与 `in_scope` 同步；校验规则：若 `subject_evidence_quote` 或 `policy_evidence_quote` 为空且该事件类型需要该证据，则 `final_decision` 不得为 `accepted`）

示例：

```json
write_skill_file({
  "path": "output/_working/{task_id}/event_candidates.json",
  "content": "{\"input_count\": 9, \"candidates\": [{\"candidate_id\": 1, \"event_type\": \"年报\", \"actual_subject\": \"贵州茅台\", \"raw_date\": \"2021-03-30\", \"effective_event_date\": \"20210330\", \"trading_anchor_date\": \"20210330\", \"anchor_rule\": \"生效日即交易日，直接使用\", \"label\": \"超预期\", \"label_evidence_quote\": \"净利润同比+25%，一致预期+18%\", \"evidence_event_type\": \"年报\", \"evidence_event_date\": \"2020年度\", \"label_confidence\": \"explicit\", \"in_scope\": true, \"reason\": \"数值证据明确支撑超预期判定\"}, {\"candidate_id\": 2, \"event_type\": \"业绩预告\", \"actual_subject\": \"贵州茅台\", \"raw_date\": \"2021-01-15\", \"effective_event_date\": \"20210115\", \"trading_anchor_date\": null, \"anchor_rule\": null, \"label\": \"-\", \"label_evidence_quote\": \"-\", \"evidence_event_type\": \"-\", \"evidence_event_date\": \"-\", \"label_confidence\": \"-\", \"in_scope\": false, \"reason\": \"out_of_scope: 用户限定年报/半年报\"}, {\"candidate_id\": 3, \"event_type\": \"半年报\", \"actual_subject\": \"贵州茅台\", \"raw_date\": \"2022-08-03\", \"effective_event_date\": \"20220803\", \"trading_anchor_date\": \"20220803\", \"anchor_rule\": \"公告日即交易日\", \"label\": \"不及预期\", \"label_evidence_quote\": \"股价下跌,市场反应负面,部分研报提及增速放缓\", \"evidence_event_type\": \"半年报\", \"evidence_event_date\": \"2022H1\", \"label_confidence\": \"inferred\", \"in_scope\": false, \"reason\": \"inferred 证据不满足准入标准\"}]}"
})
```

**⛔ 双日期字段（硬规则）**：
- `effective_event_date`：事件实际发生/生效/公告的日历日（可能非交易日）
- `trading_anchor_date`：buildEventStudy 传入的计算锚点（必须为交易日）
- `anchor_rule`：如何从 effective_event_date 推导 trading_anchor_date（如"非交易日取下一交易日"）
- **最终表格默认展示 `effective_event_date`，不得将 `trading_anchor_date` 冒充事件日期**
- 若两者不同，必须在口径说明中注明

**Cardinality Contract（硬规则）**：
- `input_count` == `candidates` 数组长度
- `accepted_count`（in_scope=true 的数量）+ `rejected_count`（in_scope=false 的数量）== `input_count`
- 后续 buildEventStudy 传入的 dates 数量必须 == `accepted_count`

**样本数约束校验（硬规则）**：
- 若 `event_definition.json` 中 `sample_count_constraint` 非 null（如"各取2-3次"），则：
  - compare 模式下，每组 `in_scope=true` 的数量**不得超过**约束上限（如 3）
  - 若某组超过上限 → 按 `label_confidence` 优先级（explicit > inferred）+ 证据质量裁剪至上限，被裁剪样本 `in_scope` 改为 `false`，`reason` 标注"裁剪: 超出样本数约束上限"
  - 若某组不足约束下限（如 < 2）→ **不得用弱证据补齐**；在最终答案中明确说明"目标样本数 X-Y 次，实际仅找到 Z 个满足证据标准的样本"

**写入后**，必须 `read_skill_file("output/_working/{task_id}/event_candidates.json")` 读回，确认 in_scope=true 的日期列表，再传入 buildEventStudy。

### Step 1.8：生成 EventSelection（强制执行）

在调用 `buildEventStudy` 前，必须基于 `event_candidates.json` 生成：
`output/_working/{task_id}/event_selection.json`

结构至少包含：
```json
{
  "accepted_dates": [20210330, 20220803],
  "accepted_count": 2,
  "rejected_dates": [20210115],
  "accepted_events": [{"candidate_id": 1, "trading_anchor_date": "20210330"}, ...],
  "rejected_events": [{"candidate_id": 2, "reason": "out_of_scope"}]
}
```

规则：
- `buildEventStudy.dates` **只能**来自 `event_selection.accepted_dates`
- 不允许模型绕过 `event_selection.json` 手工填写 dates
- 若 accepted 样本不足，必须如实回答"样本不足"，不得放宽准入补齐
- 若题目要求输出均值/分布，且最长统计窗口 **大于或等于** 相邻 accepted 事件的最小间距，必须先在 `event_selection.json` 中裁剪重叠样本，或缩短到不重叠窗口后再统计；**不得仅在答案中提示重叠后继续输出原分布**

### 事件锚点一致性合同（硬规则）

执行 `buildEventStudy` 时：
- `dates` 参数必须逐项等于对应候选的 `trading_anchor_date`
- 不允许模型为了"交易日方便"把公告日改成首个交易日，除非 `anchor_basis` 本身就是 `trading_anchor_date` 且 `anchor_rule` 已说明顺延
- 最终口径说明必须与 `event_candidates.json` 中的 `anchor_basis` / `anchor_rule` 一致
- 最终表格展示日期默认为 `effective_event_date`，计算锚点为 `trading_anchor_date`，两者不同时必须注明

### ⛔ buildEventStudy 前置检查（Step 2 前必须全部通过）

1. `read_skill_file("output/_working/{task_id}/event_candidates.json")` **已执行**（不是写完就算，必须读回）
2. `in_scope=true` 的样本数 ≥ 1
3. 每个 `in_scope=true` 的样本：`event_type` ∈ `event_definition.in_scope`
4. 每个 `in_scope=true` 的样本：`effective_event_date` 在 `time_scope` 范围内
5. 每个 `in_scope=true` 的样本：`actual_subject` 落在 `event_definition.subject_boundary` 范围内（若有 subject_boundary）
6. 每个 `in_scope=true` 的样本：`label_confidence` ≠ `"insufficient"` 且 ≠ `"inferred"`（无例外）
7. 每个 `in_scope=true` 的样本：`evidence_event_type` 与 `event_type` 一致，`evidence_event_date` 能映射到当前候选的报告期
8. compare 模式下，每组 `in_scope=true` 数量 ≤ `sample_count_constraint` 上限（若有约束）
9. `date_precision` 必须为 `day`；若为 month/year，则不得进入 buildEventStudy
10. `buildEventStudy.dates` 必须逐项等于 `trading_anchor_date`
11. 对 A股事件，若 `effective_event_date` 非交易日，则 `trading_anchor_date` 必须顺延到下一交易日
12. 若 `actual_subject` 不在 `subject_boundary` 内，则强制 `in_scope=false`
13. 若用户括号中给出示例抓手（如"降首付""限购松绑"），必须命中 `direct_policy_terms_hit` 才可入池
14. `buildEventStudy.dates` 必须严格等于 `event_selection.json.accepted_dates`（逐项对应）
15. 任一命中 `out_of_scope` 的候选若仍进入 accepted_dates，则视为 workflow 失败，必须重建候选表
16. 若 `effective_event_date` 非交易日且本题统计口径要求交易锚点，则 `buildEventStudy.dates` 实际传入日期必须来自 `trading_anchor_date`，不得直接使用自然日
17. **锚点最终确认（强制）**：在通过上述 1-16 项检查后、实际调用 `buildEventStudy` 前，必须执行 `read_skill_file("output/_working/{task_id}/event_selection.json")` 读回 accepted 列表，逐条核对：(a) 每个 accepted 候选的 `anchor_basis` 与 `trading_anchor_date` 是否自洽（即 `anchor_basis=announcement_date` 时 `trading_anchor_date` 确实等于公告日或其合法顺延）；(b) `buildEventStudy.dates` 数组与 `accepted_dates` 逐位相等。任一不自洽 → 修正 `event_selection.json` 后重读，禁止直接调用 `buildEventStudy`

→ **任一项不通过 = 修正 event_candidates.json 后重新读回，禁止调用 buildEventStudy**

### Step 2：buildEventStudy 生成公式

直接调用 `buildEventStudy` 工具（无需通过 `run_skill_script`）：

#### single 模式

```json
buildEventStudy({
  "dates": [20170911, 20180111],
  "asset": "贵州茅台",
  "windows": ["1周", "1月", "1年"],
  "prefix": "MT"
})
```

#### compare 模式

```json
buildEventStudy({
  "mode": "compare",
  "asset": "贵州茅台",
  "group_a_name": "超预期",
  "group_a_dates": [20210831, 20220330, 20230829],
  "group_b_name": "不及预期",
  "group_b_dates": [20220831, 20240829],
  "windows": ["1周", "1月"],
  "prefix": "MT"
})
```

#### 参数说明

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| mode | string | 否 | `single`（默认）或 `compare` |
| dates | int[] | single 必填 | 事件日期列表，YYYYMMDD |
| asset | string | 是 | 资产名称（如"贵州茅台""沪深300"） |
| windows | string[] 或 int[] | 否 | 时间窗口，默认 `[5, 21]`。支持：1周/2周/1月/3月/半年/1年 |
| prefix | string | 否 | 公式前缀，默认 "ES" |
| group_a_name | string | compare 必填 | A 组名称 |
| group_a_dates | int[] | compare 必填 | A 组日期列表 |
| group_b_name | string | compare 必填 | B 组名称 |
| group_b_dates | int[] | compare 必填 | B 组日期列表 |

#### 窗口映射

| 说法 | 交易日 N |
|------|----------|
| 1周 | 5 |
| 2周 | 10 |
| 1月 | 21 |
| 3月 | 63 |
| 半年 | 126 |
| 1年 | 252 |

返回值包含 `formulas` 数组和可能的 `warnings`（窗口重叠警告）。

### Step 3：runMultiFormulaBatch 执行公式

将 Step 2 返回的 `formulas` 数组直接传入 `runMultiFormulaBatch`：

```json
runMultiFormulaBatch({"formulas": [...Step 2 返回的 formulas...]})
```

### Step 3.5：readData 验证（可选）

如需读取事件收益的具体数值，使用 `readData` 工具：

- 事件研究产出的收益数据为**一维**序列，使用 `mode: "last_column_full"` 读取
- **不要使用** `table_data` 模式（不支持一维采样数据）

### Step 3.6：执行后映射一致性校验（强制执行）

回答前必须检查：
1. 本次 buildEventStudy 传入的事件日期列表（记录总数）
2. 本次 readData 读取的结果条数
3. 两者是否一一对应

若 `事件数 ≠ 有效结果数`：
- **不得直接输出逐事件收益表**
- 必须执行以下之一：
  1. 合并高时间重叠的事件簇，重新调用 buildEventStudy
  2. 改为按事件簇输出（标注合并原因）
  3. 仅输出可确认一一映射的事件，明确标注"以下 N 个事件因窗口重叠被排除"
- 必须写明原始候选事件数、最终有效样本数、差异原因
- **禁止**：保留全部事件日但强行对齐不等长的结果列表

### Step 4：格式化输出

#### 前置校验（进入 E4 前必检）

- 逐事件日检查：是否每个日期都有至少一个窗口的有效数值？缺失的标注"数据不足（可能停牌/未上市）"
- 样本数检查：总有效事件日数记录在手，< 5 时后续均值行必须标注

#### 解释原则

1. **先逐次事件，再给均值** — 列出每个事件日期对应的各窗口收益，最后汇总均值
2. **样本数 < 5 时，不把均值说成统计规律** — 改用"参考""有限样本下"等措辞
3. **compare 模式两组分别列出** — 先各组逐次，再各组均值对比
4. **threshold 模式额外输出** — 在表格前说明阈值条件和识别到的事件日列表及来源
5. **不补精度** — 工具返回几位小数就展示几位，不追加推理修饰
6. **compare 样本不足不静默降级** — 若某一组有效样本数为 0 或低于用户目标样本数，仍优先保留 compare 框架，明确写出"目标样本数 / 有效样本数"，不得静默降级为 single

#### 输出格式

| 事件日期 | 后 5 日收益 | 后 21 日收益 | ... |
|----------|------------|-------------|-----|
| 2017-09-11 | +x.xx% | +x.xx% | ... |
| 2018-01-11 | +x.xx% | +x.xx% | ... |
| **均值** | **+x.xx%** | **+x.xx%** | ... |

#### warnings 处理

如果 Step 2 返回了 warnings（窗口重叠），在输出表格前展示警告。

#### 输出规则（合并：方法限制 + 输出边界 + 输出纪律）

**必须保留的方法限制**：
- 样本数 ≤ 3：注明"样本极少，均值仅供参考，不构成统计规律"
- 搜索获取的日期不完整：注明"仅包含已搜索到的 N 次"
- 窗口重叠（buildEventStudy 返回 warnings）：在表格前展示警告，注明受影响窗口对
- 样本数 < 5 时，不得把描述性结果包装为统计规律；若输出均值，标注"仅描述性汇总"

**禁止出现**：
- 过程性话术（「让我」「按照流程」「Step 1 完成」「根据 workflow」等）
- 总结性段落（「综上所述」「整体来看」）——数据表格本身就是结论
- 未经本轮证据支持的宏观/政策/行业因果归因
- "偏正面""通常""往往"类方向性判断
- "可能存在 ±1 个交易日偏差"类未被本轮验证的不确定性声明
- checkpoint 名、workflow 名、内部校验表、`_working/` 路径
- 未被请求的投资建议、风险提示

**归因规则（强制）**：
- 默认不输出任何归因。事件研究的交付物是**数值表格 + 口径说明**，不是因果解释
- 禁止输出"主要受…影响""可能与…有关""这与当时…背景相呼应"等归因表述
- 禁止输出未经工具计算的概念（如"熔断机制""政策宽松预期""市场恐慌情绪"），除非本轮有对应工具证据
- 仅当用户**明确要求解释原因**时，才可输出归因段落，且必须标注"以下为可能解释，非本轮数据的因果证明"

---

## 公式模板参考

详见 `recipes/event-study-formulas.md`。

### T22 / T23 专题入口

- 财报超预期 / 不及预期类 compare 问题：回看 Step 1.6 的**财报业绩超预期分类细则**
- 主体受限的政策事件类 single / compare 问题：回看 Step 0.5 的**政策事件主体边界细化**
- 需要先搜索打标再组装 compare 公式时：加载 `recipes/event-study-formulas.md` 的**模板 D**

### 偏移区间识别（模板 C 路由）

当用户表述包含以下模式时，应使用 **模板 C**（偏移区间回报）而非默认的模板 A：

**触发表述**：
- "排除事件当天" / "不含事件日"
- "第 N 天到第 M 天" / "T+N 到 T+M"
- "事件消化期之后" / "去掉前几天"
- "从第 2 个交易日开始" / "跳过事件首日"

**路由规则**：
1. 识别到偏移区间意图后，从 `recipes/event-study-formulas.md` 加载模板 C
2. 根据用户表述确定 N（起始边界 = 用户起始天数 - 1）和 M（终止天数）
3. 模板 C 使用 **收盘价比值法**，不需要事件信号、日收益率、某天后累加或分段最终值
4. 输出表格标题应体现偏移区间（如"T+2 到 T+20 涨幅"），而非标准窗口名

**N 值推导示例**：
| 用户说法 | N | M | 实际持仓区间 |
|---------|---|---|-------------|
| "第 2 天到第 20 天" | 1 | 20 | T+1 收盘 → T+20 收盘 |
| "排除事件当天，后 1 个月" | 1 | 21 | T+1 收盘 → T+21 收盘 |
| "第 3 天到第 60 天" | 2 | 60 | T+2 收盘 → T+60 收盘 |
| "跳过前 5 天，后 3 个月" | 5 | 63 | T+5 收盘 → T+63 收盘 |

> **注意**：模板 C 不走 buildEventStudy 工具，也不需要选取日期生成事件信号。直接用 `取某天` 嵌套 `交易日位移` 提取两个价格点，再做价格比值即可。多个历史事件需为每次事件单独建立前缀变量（`取某天` 每次只能绑定一个日期）。
