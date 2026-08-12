# CHANGELOG — quant-buddy-view

版本记录按**从新到旧**排列。

> ⚠️ **本文件不是规则源**。
> 这里只用于版本审计和历史问题回溯，可能包含已被后续版本反转或废弃的旧口径。
> 当前执行规则一律以 `SKILL.md` + `workflows/**` + `tools/**` + `guides/**` 为准；发生冲突时，以这些当前规则文件为准。
> Agent 在维护、升级或排查版本差异时，应阅读最新版本和与问题相关的历史条目；普通建页任务不需要默认加载全部历史。

---

## [0.6.39] — 2026-08-12

- 增加 QBS companion 托管安装协调：检测到 `.managed-install.json` 且 manager/channel 为 `quant-buddy-skill/companion` 时，QBV 不再触发独立 GitHub tag 自更新，由 QBS 在 `newSession` 阶段统一管理。
- standalone updater 与 QBS Companion Manager 共享 skills 根目录的 `.quant-buddy-view.update.lock`，并在锁内重新检查版本，避免并发覆盖和降级；托管安装调用 standalone updater 时返回 soft skip。
- 自更新继续保留用户配置、输出和日志，并将 managed marker 纳入保护范围；新增 managed/standalone、共享锁与更新保留行为测试。

## [0.6.38] — 2026-08-12

### Turn 追踪失败不再阻断活页流程

- `trace_context.py begin/beginTurn` 在服务端 Turn 写入失败、响应异常或 task_id 不一致时，仍持久化本地 Task/Turn 上下文并返回 `code:0`。
- 返回值新增 `tracking_recorded` 与 `tracking_error` 供诊断；QBV/QBS 后续建页、更新、取数和发布继续执行。
- 本地 Trace Context 无法持久化仍保持硬失败，因为独立进程无法安全恢复后续业务上下文。

## [0.6.37] — 2026-08-11

### 官网托管活页页头与 WebAgent Preview 隐藏

- Share Shell 保持 `share-shell-v2`，revision 升至 `3`，新增 `official_header_iframe` 能力；整个可见页头改由官网 `/embed/live-page-header` iframe 托管，活页 Parent Bridge 继续执行刷新、收藏、分享、认证与移动 WebAgent 动作。
- 新增 `qb-live-page-header-v1` 双向协议，严格校验官方 origin、精确 iframe source、channel、version 和 `page_id`；页头 4 秒未 ready 时显示轻量 fallback，resize 仅接受 44–120px。
- 官网 WebAgent Preview 上下文不加载页头或预加载收藏 iframe；旧页头和 revision 3 Header Host 均可通过代理注入的 meta/style 从文档流中隐藏。
- revision 3 canonical artifact hash：`8d3463e9e96b6830958a04820da56f95352e99980cadb2010f0c6722ac507e88`。正文、Data Kernel、实时取数、Card Runtime、`page_id` 与公开 URL 仍不属于 Shell-only 刷新范围。
- 新版读取链统一为服务端 `listPages/getPageDetail`：`list/download` 固定 `mode=mine`，`templates/template` 固定 `mode=public`；旧服务端静态页/模板读取接口继续仅供旧 Skill 版本兼容。
- 公共范式池由服务端一次完成官方精选与社区的联合分页；新版不再客户端双请求合并。
- 公开详情统一提供下载链接、revision、公式包定义和安全 Data Grant 合同，供 direct/fork 使用。

---

## [0.6.36] — 2026-08-06

### 多轮追问 Turn 追踪

- `trace_context.py` 新增 `beginTurn`；当前 `turn_id/user_query` 按 `task_id` 持久化，独立 Python 进程可恢复。
- 公共请求自动发送 `x-turn-id`；`qbs_bridge` 复用同一 Task/Turn，并在追问切换后先同步 QBS `beginTurn`。
- 同一 Session 的后续用户消息先创建 Turn；更新既有活页继续复用原 `page_id` 与公开 URL。

## [0.6.35] — 2026-08-05

将活页页头升级为 Share Shell v2 能力契约：统一 Logo 鉴权后进入个人中心投研仓、投研仓收藏、移动端 75dvh“问一问” Web Agent、桌面端 Playground 跳转及 Agent 回答后的刷新/重载协议。新增 `assets/share-shell/contract.json`、revision 注入和六 Marker 标准化 SHA-256 工具；显式 `refresh_share_shell:true` 仍只替换 Share Shell 区块并保留正文、Data Kernel、实时取数与 Card Runtime。以后页头视觉或交互调整必须提升 revision、更新能力契约并通过刷新与通信回归测试。

---

## [0.6.34] — 2026-08-04

新增 `agent_model` 柔性采集与任务级贯穿：Agent 明确知道真实运行模型时可在 `trace_context begin` 显式传入，宿主也可通过可选环境变量 `QBV_AGENT_MODEL` 注入；两者都缺失或只有空白时保持为空，禁止猜测、询问用户或阻断活页流程。非空模型名会 best-effort 保存到 task-scoped Trace Context，后续独立 QBV 命令自动恢复并通过 `x-agent-model` 发送，QBS bridge 创建继承会话时也同步透传。上下文文件缺失、损坏或不可写均静默降级，不改变现有命令退出码。配套服务端审计在当前请求未携带模型名时，可从同 `task_id`、同认证用户的成功 `newSession` 记录柔性回填；反查发生在响应后的日志阶段，失败仍写入 `null`，不影响用户请求。

---

## [0.6.33] — 2026-08-04

提升活页进度版本的可追踪性：`update_progress` 未显式传 `change_note` 时，自动按页面状态、中文阶段标题和用户可见 `message` 生成不超过 200 字的修改描述，区分“进度更新 / 等待输入 / 进度完成 / 进度失败”；`final_publish` 阶段进一步区分“开始发布 / 完成发布 / 发布失败”。调用方显式提供的 `change_note` 仍具有最高优先级，正式 `publish_final` 未提供说明时默认记录“完成发布：正式活页内容已发布”，避免版本历史连续出现无法定位的“更新页面内容”。同时让 `publish_final` 的内部发布进度快照继承 `live_data_mode`、市场数据要求、资产与路由/公式/Grant 收据等结构化证据，避免正式发布成功但“开始发布”版本因证据参数丢失而写入失败。

---

## [0.6.32] — 2026-08-03

修复具体资产实时取数探测链：`fast_query` 改用接口支持的 `result_mode:"value"`，正确解包 `{code, data:{...}}` 响应中的 `results`、`asset_errors` 与 `field_errors`，资产名称归一化保留中日韩统一表意文字，避免中文资产被误判为 `TARGET_ASSET_MISSING`。统一 direct 与 fork 的运行时凭证发现逻辑，支持 `PACKAGE_ID/SIGNATURE`、`ROSTER_PACKAGE_ID/ROSTER_SIGNATURE`、`FUND_GRANT_ID/FUND_GRANT_SIGNATURE` 等带角色前缀的 JS 常量；模板声明但来源 HTML 未发现的凭证必须显式说明缩减原因，禁止把元数据残留静默带入发布合同。

公式包注册合同继续按平台能力接受最多 100 条公式，QBS 验证在同一包内按每批最多 20 条自动拆分，前批输出通过 `force_reusable_array` 保活。多批验证完成后生成绑定完整合同指纹、子收据路径及 SHA256 的包级聚合收据；发布门禁兼容旧单批收据，并严格校验聚合输出摘要、子收据唯一性、内容哈希及任务归属。版本测试改为校验 `SKILL.md` 顶层版本、metadata 版本与运行时解析结果动态一致，避免每次发版维护硬编码断言。

---

## [0.6.31] — 2026-08-03

新增具体资产证据闸门：点名资产时必须先通过 `resolve_asset_data` 验证平台 ticker 映射和用户所需数据角色，禁止依据上市状态、所有权、名称或市场惯例先验推断平台能力、代理资产、静态回退或页面结构；验证结果必须区分资产未映射、接口不支持、字段缺失和额度限制。建立正式的 `CHANGELOG.md` 治理与 Agent 阅读边界：维护、升级或排查版本差异时读取最新版本及相关历史，普通建页任务不默认加载全部历史；当前规则仍以 `SKILL.md`、`workflows/**`、`tools/**`、`guides/**` 为准。将历史版本说明从 `SKILL.md` 移入 changelog，同时保留仍有效的 Fork 数据通道继承硬规则。发布包和自更新流程现在强制包含 changelog，并新增对应测试；根目录打包脚本补充 `skillhub` channel 用法示例。

## [0.6.30] — 2026-08-01

资产实时页面统一先调用 `scripts/qbs_bridge.py resolve_asset_data`，按 `stockProfile → fast_query(snapshot) → fast_query(report) → 必需公式` 探测。`ASSET_NOT_FOUND` 等数据级失败不得直接静态回退；只有 `live_data_route_receipt_v1` 证明全部核心角色都已探测且均为数据级失败时，才能使用 `static_after_live_probe`。鉴权、配额、网络、协议或服务错误返回 `blocked`，禁止用静态页面掩盖。Grant-only、formula-only 和混合页面统一携带 route/grant/formula 结构化收据发布，禁止自由文本 waiver。

---

## [0.6.29] — 2026-07-31

同步 `SKILL.md` 顶层 `version` 与 `metadata.version` 至 0.6.29，并更新图片相关测试中的版本预期；该版本没有新增运行时规则。

---

## [0.6.28] — 2026-07-31

新增单一 A 股简单综合分析快速通道。完成 `trace_context.py begin` 后可直接调用 `static_page.py new_asset_page`，由 `skill_server /newAssetPage` 使用固定来源页和三份固定 Data Grant 合同生成调用者自己的实时个股页，并返回终态公开 URL；该分支跳过 `templates/new_page/fork`，也不要求 Agent 另跑 QBS 验证或自行注册 Grant。快速通道仅覆盖无定制栏目/版式、无额外指标/公式/图表、无对比/多标的要求的单一 A 股；其他请求继续原 direct/fork/unmatched 路由。

---

## [0.6.27] — 2026-07-30

`new_page` 在完整执行 `templates(recommend:"all")` 后还必须由 Agent 显式提交 `routing_decision`：fork 传本次 `items_summary` 中的 `source_template_id + reason_code`，unmatched 传最接近候选、实质能力缺口及原因。脚本核验候选属于当前 task、补齐候选标签快照并把决定与 `page_id` 写入既有 `routing-credential.json`。`publish_final` 在任何网络写入前复核该决定：已选 fork 但未执行 `fork_prepare` 时返回可恢复的 `ROUTING_RECONFIRM_REQUIRED`；确认模板确实不适用时可用显式 `routing_override` 改判 unmatched。`build_dashboard` 不受限制，旧任务无路由记录时保持兼容。

---

## [0.6.26] — 2026-07-28

修复 `emit:"panel_block"` 嵌入 bespoke 页面时的两处真实崩溃/误判（真实任务实测复现并核实过）：① `_RENDER_JS_TEMPLATE` 整体包一层 IIFE，`fmt`/`esc`/`normalize`/`colIdx` 等不再泄漏到全局作用域，不会再跟宿主 bespoke 页面自己的同名变量（如 `const fmt=...`）撞名报 `SyntaxError`——宿主页面不需要手工包 IIFE 就能安全共存；`_BOOTSTRAP_BLOCK_RE`/`_EMBEDDED_BOOTSTRAP` 同步补上外层 IIFE 的收尾。② `cmd_panel_block` 新增可选 `host_html_file`/`include_data_kernel` 参数：给了宿主页面路径会自动探测是否已有取数内核（marker 版或历史手写等价版，复用 `data_kernel_retrofit.py` 现成判断逻辑），检测到则跳过重复内联 `data-kernel.js`，避免同页两份内核顶层变量重复声明崩溃。③ `chart_edit.py::_extract_boot` 改用 `json.JSONDecoder().raw_decode` 定位 `BOOT` 边界，不再要求 `const BOOT = {...};` 后面严格紧跟 `let LAST_OUTPUTS`，marker 区块内部多出的空白/注释不会再让 `inspect` 误判 `legacy:true`。④ 修复 fork 流程 `decisions` 契约不一致（两次真实任务复现）：`fork_prepare` 之前只在 `review_update_params_file` 里写一个空 `"decisions": {}`，而 `required_decisions` 给出的 `decision_id` 又是扁平点号字符串（如 `roles.package.package_001.target_formulas`），导致 Agent 把它当提交用的 key 直接写，被 `apply_review_decisions` 以 `FORK_REVIEW_DECISIONS_INVALID` 拒绝。现在 `fork_prepare`/`fork_review_update` 改为写入 `build_decisions_skeleton()` 生成的嵌套占位骨架（`{"roles":{"<role_id>":{...}}}`），Agent 只需要在骨架里填空；同时修掉一个连带 bug——`fork_review_update` 原来每轮无条件把 `decisions` 重置成 `{}`，多角色分轮填写时会丢掉已经确认的同业映射，现在改成按最新 review 重新生成骨架，已填值会被保留。⑤ **fork 资产替换改为由 `target_asset` 驱动**（真实任务复现：Agent 连撞三次 `未在来源 HTML 找到替换项` 后放弃 fork、退回自建）。病根是职责分配——`fork_prepare` 本来就收到了 `target_asset`，却只把它记进 manifest，反过来要求 Agent 手写 `asset_replacements`，即让 Agent 去猜一个它从没见过、且流程明令禁止读取的 HTML 里代码究竟写成 `SH600900` 还是 `600900.SH`。现在改为：Agent 负责说"换成哪只标的"，脚本负责推导来源主资产（模板公式词频 + 标题）并扫描来源 HTML 得出代码的实际书写形态，**只替换页面里真实存在的写法**，这类报错结构上不再可能发生；只给代码时先反查同级 quant-buddy-skill 资产库补名字。多资产/指数类范式推不出主资产时 fail-closed 返回 `FORK_SOURCE_ASSET_AMBIGUOUS`，报错自带候选资产名、来源 HTML 中真实存在的代码写法和可照抄的调用示例，由 Agent 传 `source_asset` 指定。替换后主资产若仍残留，在写出工作 HTML **之前**就返回 `FORK_SOURCE_ASSET_RESIDUAL`（同业资产不在检查范围内，它们本就该由 `target_slots` 决策替换），不再等到发布成功后才发现文案还是源模板原样。`asset_replacements` 降级为可选覆盖，老调用零改动。

---

## [0.6.25] — 2026-07-28

`build_dashboard.py` 新增 `emit:"panel_block"` 局部产出模式——只生成带 `QBV_RENDER_JS_START/END` marker 的图表 `<script>` 片段（不生成整页 HTML），供 bespoke（手写）页面把折线/柱状/双轴/雷达图这类图表交给标准声明式引擎画：panel 加 `target_selector` 指向 bespoke 布局里已有的容器，渲染进去不包卡片外壳。`renderChart` 新增双轴（`dual_axis`+`right_series`）与迷你走势图（`sparkline`），新增 `renderRadarChart`（`type:"radar"`）。`_render_js_for_boot()` 统一了「整页启动 / 嵌入式启动」的选择逻辑，`_render_html` 与 `chart_edit.py::_patch_page` 共用，避免嵌入式图表被编辑后误换成会二次初始化 `QBShareShell` 的整页启动代码。`chart_edit.py::add_series` 新增 `axis:"right"` 参数。目的：终结「bespoke 页面里的图表只能整页手工补丁」——用这套局部产出模式重建模板后，图表可直接用 `chart_edit.py` 现成的定点编辑操作维护，不需要为 bespoke 页面另造一套编辑机制。`compile_bespoke_page.py` 新增非阻塞 lint，检测把行数据硬编码进 JS 调用参数（如 `setBar($("..."),[...])`）的写法，提示改用 `data-qb-bar-row` 属性驱动。详见 `guides/bespoke-page.md`「统一原则」一节。

---

## [0.6.24] — 2026-07-24

`single_stock_deep_dive_v1` 启用数据驱动柔性回复：公式验证成功后复用 `data_id`，按兼容 `readData` 模式每批最多10个补读模板所需值；Grant直接复用验证响应。整个过程不重算公式、不重查已注册 package/grant。终态 contract 绑定 `reply_data_evidence_v1` 文件与 SHA256；七节标题必须完整保留，有数据的模板字段必须输出，无数据整节使用标准说明。`feishu-group` 终态 contract 同时声明最多 5 张 Markdown 表格，模板用列表或行内文本承载其余数据；validator 成功后必须原样发送 `validated_markdown`。

---

## [0.6.23] — 2026-07-23

所有正式任务产物统一进入 `trace_context begin` 返回的跨平台 `task_temp_dir`；新 fork 固定执行 `fork_prepare → fork_review_update → publish_workflow`。Agent 只填写生成的 review-update 参数文件中声明的业务决策，不直接编辑标准 fork HTML/review，也不创建一次性辅助脚本。`fork_review_update` 生成绑定 task/page/manifest/review/HTML 哈希的 receipt；缺失、不完整或过期时，发布器在首次网络调用前 fail-closed。所有返回命令使用当前 `sys.executable`，不硬编码 `python`/`python3`。

---

## [0.6.22] — 2026-07-23

补强 Card Runtime retrofit 的日期与视觉保真：模板不再内置历史日期，hydrate 从嵌套输出中选择最新可用日期；已识别页面继续生成与内容语义匹配的专属视觉，不回退为通用三指标布局。详细契约见 `guides/essence-cover-card.md`。

---

## [0.6.21] — 2026-07-23

新增活页 UI/UX 系统指南，以“稳定体验骨架 + 可变内容表达”组织字体、主题 token、页面原型、模式库、响应式转换、实时状态和验收矩阵；`SKILL.md` 只保留按需路由，浏览器批注细节继续由 `ui-refinement` profile 与维护指南承载。

---

## [0.6.20] — 2026-07-23

分享海报预览新增 `data-qb-runtime-src` 合同，允许用户点击分享前保持空 `src`；静态预检与浏览器图片门禁只豁免显式声明且尚未赋值的运行时图片，普通正文图片仍必须提供非空 `src`。`fork_prepare` 会为旧版 `sharePosterImage` 自动补充该合同，不再要求任务临时塞透明占位图。fork 的 PE/PB 水位输出允许继承来源模板的明确算法与正整数窗口（如 `排序水位(...,250)` 或 `数值水位(...,750)`），不再强制统一改成250日，但仍必须通过 QBS 验证且禁止直接别名原始指标。Card Runtime 完整重建同时改为显式视觉合同并 fail-closed：未命中页面专属视觉、也未传 `visual_contract` 时返回 `CARD_VISUAL_REQUIRED`，不再自动挑前三个 outputs 生成三行指标卡；新建 artifact 必须声明 `data-qb-card-visual-kind` / manifest `visual_kind` 并通过 `--require-card-visual-contract`。`numeric-focus` 只在显式选择时可用，且必须是“一个主数字 + 最多两个解释项”，不能退化为三个等权矩形；新增 `basis-structure` 基差轴视觉作为首个合同化示例。

---

## [0.6.19] — 2026-07-22

新 fork 默认由 `fork_prepare` 生成 `fork_manifest_v2`、脱敏 HTML、credential-free review 和 publish plan；自动识别页面/Card Runtime 凭证、聚合相同合同并生成唯一 Marker。package role 明确区分模板接口原始 `source_contract.formulas/nodes` 与新包请求 `target_registration_contract.formulas/reads/begin_date`，来源 `nodes[].data_id` 不进入目标注册合同。Agent 只填写目标同业槽位、复杂跨资产公式及业务文案，`publish_workflow.py` 从目标注册合同派生验证与注册，并在第一次网络写入前检查 review、required outputs/reads、估值分位语义、Grant 合同差异和 Card Runtime 结构；v1 任务继续兼容，本版不修改图片门禁，不实现注册幂等。已发布范式卡的 Card Runtime 协议同时新增 `preserve_visual` 路径，只更新 manifest/runtime 与 ready 契约，逐字节保留原 template/style；`retrofit_card_runtime` 的独立验收固定使用 `--card-runtime-only`。禁止用通用三指标重建路径覆盖已有视觉 artifact；只有 artifact 缺失且明确选择 `numeric-focus` 时才允许生成数字主导卡片。

---

## [0.6.18] — 2026-07-22

`publish_workflow.py` 在 QBS 验证、注册和上传等网络写入前，先以假凭证运行 Card Runtime 结构预检，提前拦截空 manifest 凭证、缺少/空 `src` 的图片等结构错误；package/grant 的 `markers.package_id`、`markers.grant_id`、`markers.signature` 现在兼容单个字符串或非空字符串数组，同一次注册可扇出替换页面正文与 Card Runtime 中的多个唯一 marker，避免为同一数据合同重复注册公式包。

---

## [0.6.17] — 2026-07-21

`templates` 不再把完整候选池原样打到 stdout——响应改为 `item_count` + 覆盖全部候选的 `items_summary`（不是 top-N）+ 完整结果落盘产生的 `full_result_file`/`full_result_sha256`；完整候选（含 `agent_reply_hint`/`page_context`）落盘到系统临时目录，交由既有 `cleanup_task_temp_files` 自动回收。落盘失败（`TEMPLATES_PERSIST_FAILED`）或响应结构异常（`TEMPLATES_RESPONSE_SHAPE_UNEXPECTED`）时直接返回错误，不再退化为把完整结果打印到 stdout——这是为了修复"候选池被外层工具输出预算截断、又没有另存一份，导致误判 unmatched 走自建"的事故根因。`templates` 现在也需要 Trace Context（task_id）。

---

## [0.6.16] — 2026-07-21

模板接口开始返回来源公式原文。0.6.19 起这些语义只投影到 credential-free `fork-review.json`：主资产自动替换、同业矩阵生成槽位、复杂跨资产公式要求完整审核；Agent不再读取带来源 ID/Marker 的底层 runtime contract。

### 同期补充：Fork 数据通道继承

fork 的目标是替换标的并保持来源范式运行合同，不是重新设计数据层。来源模板某一角色使用公式包，目标页同一角色继续使用公式包；来源使用 `fast_query` / `stock_profile` / `composition_select` 数据授权，目标页继续使用同 kind、同 query_type、同响应形状的数据授权。禁止仅因“财务数据通常可走 fast_query(report)”就在 fork 中把来源财务公式包改成 grant，也禁止反向把来源 grant 改成公式包。只有 `unmatched` / 明确从零重建时才重新做通道选择；此时平台白名单报告期财务优先 `fast_query(query_type="report")`。

> 当前有效规则已保留在 `SKILL.md`「硬规则」中；本条仅记录其历史来源。

---

## [0.6.15] — 2026-07-20

新增活页正文图片上传/列表、可在当前页面点击放大的声明式 image panel、publish_workflow 图片 marker、fork 同页复制和浏览器图片门禁；PNG/JPEG/WebP 由服务端统一转为同域 WebP，发布必须保持图片与目标 `page_id` 同属。

---

## [0.6.14] — 2026-07-16

`data-kernel` 可在浏览器实时下载并解析 FastQuery `mode:"csv"`，自动 hydrate 为兼容的 `results[].fields[].series`；标准看板和构建期体检共用同口径，发布门禁等待 `QB_DATA_RUNTIME` 完成后再验收。
