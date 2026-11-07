# researched_static 联网研究静态页（降级兜底写作指南）

QBS 无可恢复证据、恢复链落到最低档时读取本指南。目标：**兜底页也要回答用户的问题**——用可溯源的公开来源做出可交付、好看、诚实标注的静态研究页，而不是无数据方法页。

## 何时进入本档

- 仅由 `recover_delivery` 降级触发（`recovery_phase=researched_static`，计划为 `partial_research + partial + live_data_mode=researched_static`）；恢复状态绑定了 plan_hash，发布门禁校验，Agent 不得主动选择此档绕过 QBS 验证。
- 宿主预算收尾（`finish_research_delivery`）没有 Agent 可联网检索，走原 methodology 方法页。
- 恢复自带机器保底骨架（`presentation_origin=machine`）：它让 draft 结构完整、compose 可构建、发布数据门禁可过，但**首屏没有真实关键值，通不过 self-built 浏览器验收**——这是设计而非缺陷，强制交付前完成联网检索并手写 presentation 替换。

## 写作流程（按 next_action 指令）

1. **先联网检索再动笔**：围绕用户原始问题找公开来源；关键数字尽量双源交叉；查无实据写明证据缺口，不得臆测或填占位数字。
2. **手写 presentation.html 替换机器骨架**（`compose-bespoke-v1` 白名单语法）：
   - 首屏 = 结论 + 3–4 个关键数字 + 每个数字的来源日期；大字号高亮，先答问题再给证据。
   - 图表用 CSS 柱图 / 表格 / 排版层级表达（白名单无 script/svg，不要内联 ECharts）。
   - 正文保留 `data-qb-sources` 公开来源汇总区：逐条「来源标题 · 发布方 · 发布日期 · 支撑内容」，这是发布硬门禁。
   - 保留两个面板挂载点（`web_research_answer` 公开来源研究、`methodology_note` 研究方法与边界），替换后把草稿 `presentation_origin` 改为 `authored`。
3. **填写 `sources_manifest_file`**（`researched_sources_v1`）：`sources` 数组 1–12 条，每条 `title / url(https) / publisher / published_at(YYYY-MM-DD，不晚于今天) / supports`；清单放在任务输出目录，发布时校验并落 sha256 收据。
4. **查无可信来源不要编造**：用 `execution_plan`（带 `expected_revision + revision_reason`）修订 `research_status=unavailable`、`delivery_kind=methodology`，草稿 `live_data_mode` 改 `static_content_only`，交付原方法页。

## 红线（发布门禁强制）

| 红线 | 机制 |
|---|---|
| 不得主动选择此档 | `RESEARCHED_RECOVERY_ORIGIN_REQUIRED`：恢复状态未登记该 plan_hash 即拒绝 |
| 不冒充实时 | 不绑 asset/行情合同、不混实时收据；`market_data_required:false` |
| 来源可追溯 | `RESEARCHED_SOURCES_*`：清单缺失/坏条目/越界路径全部拒绝 |
| 页面可见来源区 | `RESEARCHED_SOURCES_SECTION_REQUIRED`：HTML 无 `data-qb-sources` 即拒绝 |
| 视觉门禁不降 | 仍走 self-built 五视口浏览器验收（320px 无横向滚动、首屏可读）；机器骨架通不过首屏证据检查，必须手写替换 |

## 逃生口（按代价从小到大）

1. 手写 presentation 替换机器骨架（正常路径）。
2. partial 降级稿确实无法手写时：删除草稿 `presentation` 字段回退标准模块渲染（表格即证据）。
3. researched_static 查无可信来源：`execution_plan` 修订 `unavailable/methodology` + 草稿 `live_data_mode` 改 `static_content_only`，交付方法页。

## 交付措辞

- 链接标签固定：**可分享研究静态页（公开来源）**；回复不写“打开时实时结果”，明说“数据来自公开来源、未能实时验证、关键数字已带来源与日期”。
- 与 QBS 已验证数据同页时分区展示、不混写；本档默认不与 QBS 数据同页（无可用 QBS 证据才进入本档）。
