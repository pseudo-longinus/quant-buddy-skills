# CHANGELOG — quant-buddy-view

版本记录按**从新到旧**排列。

> ⚠️ **本文件不是规则源**。
> 这里只用于版本审计和历史问题回溯，可能包含已被后续版本反转或废弃的旧口径。
> 当前执行规则一律以 `SKILL.md` + `workflows/**` + `tools/**` + `guides/**` 为准；发生冲突时，以这些当前规则文件为准。
> Agent 在维护、升级或排查版本差异时，应阅读最新版本和与问题相关的历史条目；普通建页任务不需要默认加载全部历史。

---

## [0.6.50] — 2026-08-20

### TopN 回复合同纠偏与 validator 凭证收口

- TopN、选股、榜单、排名、全 A 与因子筛选页面优先使用 `generic_live_page_delivery_v1`，避免标题中的 PE、ROE、盈利或估值关键词误绑到单股七节回复模板。
- 默认 `config.json/config.local.json` 凭证改由 validator 子进程自行发现，`direct_deliver/publish_verified` 返回不再携带真实默认 key；仅显式本次调用覆盖保留进程内 `reply_validation_env` 合同。
- 新增 Top20/选股路由与默认配置、显式覆盖、命令串、参数文件凭证边界回归测试。

## [0.6.49] — 2026-08-20

### Direct 范式交付同步闭环 QBS→QBV Job

- `direct_deliver` 在取得字段一致的强终态 `direct_finalize` contract 后，从 QBS Handoff 的 task-scoped Trace Context 恢复真实 `turn_id`，自动写回 `target_skill_id + target_page_id + public_url` 并将匹配 Job 置为 `completed`。
- 没有 QBS Handoff 或显式 Job 身份的 QBV standalone 不查询、不修改 Job，返回合同保持不变；direct 数据查询失败也不会提前关闭 Job。
- 重复 direct 终态返回 `already_completed`，身份不完整、冲突或不唯一时继续失败关闭，避免网络重试重复创建或错误归档页面。

## [0.6.48] — 2026-08-20

### QBS→QBV Job 生命周期由确定性脚本自动闭环

- `qbs_handoff_adapter.py evaluate` 在发现匹配的 `qbs_qbv_job_v2` 时自动把 Job 从 `queued` 写为 `running`；没有 QBS Job 的 QBV standalone 保持无副作用。
- `publish_verified` 只有在页面已发布且公网验收通过后，才自动写回真实 `target_skill_id + target_page_id + public_url` 并置为 `completed`；重复回调幂等，Task 匹配不唯一时失败关闭。
- 新增显式 `fail-job` 终态入口和本地原子写入/锁，避免依赖 Agent 记忆手工调用 QBS 更新命令。

## [0.6.47] — 2026-08-20

### 薄适配器原样消费 QBS 已验证公式合同

- `qbs_handoff_adapter.py` 校验可选 `qbs_formula_runtime_contract_v1` 的公式左值、reads、执行参数和 fingerprint；有效时返回 `formula_runtime_action=register_exact`。
- QBV 页面 SOP 仍保持独立：只禁止重算 covered 公式；direct/fork/unmatched、ownership、Formula Package 注册、构建、发布与公网验收均不改变。
- 合同缺失时兼容旧 Handoff；合同被篡改时标记 unusable 并安全回退，不注册猜测或缩写后的公式。

## [0.6.46] — 2026-08-19

### 异资产 Fork 不再把目标页元数据覆盖回来源范式

- `fork_prepare` 在调用方未重复传 `title` 时，优先读取 `new_page` 已创建目标页的现有标题；目标页详情读取失败才使用完成资产替换后的来源标题，避免宁德时代页面被正式发布为“长江电力”元数据。
- 正式发布的 `description` 同步应用主资产替换，不再让进度页临时描述或来源资产文案残留；显式 `page_context` 也使用相同替换规则。
- 异资产 Fork 在生成 publish plan 前新增 `FORK_METADATA_SOURCE_ASSET_RESIDUAL` 门禁，标题、描述或显式页面上下文仍含来源主资产时拒绝发布。
- 新增真实故障回归测试，覆盖目标页标题保留、来源描述替换和 metadata 无来源资产残留。

## [0.6.45] — 2026-08-19

### 在 0.6.44 活页流水线上接入 QBS 已验证结果

- 新增薄适配器校验 `qbs_computation_capsule_v1` 与 `qbs_qbv_handoff_v1` 的 task/turn lineage、合同 fingerprint、artifact SHA256、receipt 和 role 覆盖度，输出 `covered/partial/unusable`。
- `covered` 直接复用 QBS 已物化结果，`partial` 只补缺失角色，`unusable` 无损回退 QBV 原有 QBS bridge；QBV 的 direct/fork/unmatched、ownership、构建、发布和公开验收职责保持独立。
- Handoff 恢复原 `task_id + turn_id`，避免同一用户问题重复创建 Turn；发布门禁继续验证实时查询结果，跨 Turn、缺失或篡改证据失败关闭。
- 完整保留 0.6.44 的本地 HTML 快照优先发布、同页 QBS 渐进增强、LIVE marker 与 Card Runtime 能力；合并不回退现有 preserve-HTML 流程。

## [0.6.44] — 2026-08-18

### 本地 HTML 活页化先发布渲染快照，再同页渐进增强 QBS

- `preserve_html_qbs_live` 改为两阶段写入：`upload` 先用来源页渲染快照创建稳定 `page_id`，`update` 先把快照写入原 `page_id`；随后才执行 QBS 路由、凭证、Runtime 和保真门禁，complete/partial 均通过 `updateStaticPage` 写回同一链接。
- 新增 `source_snapshot_html_file/source_snapshot_html_sha256` 合同和 `scripts/capture_rendered_html.mjs`。异步来源必须提供渲染完成且已冻结旧脚本的快照；捕获器保留当前 DOM/SVG/表格/表单状态并固化 canvas，避免托管后重新调用旧接口覆盖快照。
- partial 不再整页降级：已成功路线对应区域继续使用 QBS live，失败区域保持首次快照；全部失败或第二阶段更新失败时，活页仍显示完整快照，不再生成通用错误页或替代链接。
- 未转换 div 不再强制注入 `data-qb-live-mode="static"`；只有 QBS 成功区域需要 `data-qb-live-mode="live"` 和公式包/Data Grant tag，并显示低干扰 `● LIVE`。保真基线从未渲染 source 调整为渲染 snapshot，动态数值、表格和 SVG 不会因来源占位符而被误判为内容篡改。
- 响应新增 `snapshot_published_first`、`source_snapshot_published` 与 `publish_sequence`；保留 `transformation_status/source_html_fallback_published` 兼容字段，并增加快照哈希审计。普通 upload/update 和非 preserve 模式不受影响。
- preserve 入口不再预读 QBS 目标 HTML：即使目标文件尚未生成、缺失或不可读，也先完成快照 upload/update，再以 `PRESERVE_HTML_TARGET_READ_FAILED` 记录增强失败，确保链接仍展示原页面快照。

## [0.6.43] — 2026-08-18

### 本地 HTML QBS 活页增加可见 LIVE 徽标

- `preserve_html_qbs_live` 完整成功后由 `static_page.py` 自动注入标准可见徽标：默认仅在实时区域右上角显示低对比度 `● LIVE`，悬浮后再展开“QBS 实时计算/取数，刷新时更新”的说明；绝对定位且不进入文档流，避免挤压用户原页面布局。
- 徽标样式升级为 `<style data-qb-live-indicator-runtime="v2">`：颜色继承当前区域文字颜色，以低透明度背景/边框适配浅色和深色主题；同页重复 update 保持幂等，并可安全替换已知的 v1 标准样式。终态 `transformation_validation.visible_live_indicator` 返回版本、启用状态和两类 live div 数量。
- 保真 CSS 校验只忽略 marker 与内容都完全匹配的 QBV 标准样式；任意伪造 marker 或修改过的 CSS 仍按布局变化拒绝，不能绕过来源 CSS 合同。
- `partial` / `failed` 继续发布原页静态回退，但不会注入可见 LIVE 徽标，避免把静态内容冒充为实时区域。

## [0.6.42] — 2026-08-17

### 本地 HTML 活页化失败也保留原页，并声明 div 实时状态

- `preserve_html_qbs_live` 的目标 HTML 现在要求每个可渲染 `<div>` 声明 `data-qb-live-mode="static|live"`；公式包和 Data Grant 实时区域分别使用 `data-qb-live-tag="qbs-formula-package"` / `qbs-data-grant`，避免把静态内容误报为实时。
- 完全成功继续发布 QBS 实时版本；路由部分成功或转换/凭证门禁失败时，不再直接丢失交付，而是重新校验 `source_html_file` SHA256，把来源 HTML 的可渲染 div 标记为 static 后继续 upload，或更新原 `page_id`。来源文件缺失、不可读或哈希不一致仍拒绝覆盖。
- 静态回退只改 div 的运行时声明属性并移除错误 live tag，不改可见正文、CSS、布局、SVG、表格或脚本；`script/style/template/noscript` 与注释中的 `<div>` 文本不会被误写。
- 终态响应新增 `transformation_status: complete|partial|failed` 与 `source_html_fallback_published`；partial/failed 保留 `transformation_error`。专用回复模板按真实状态区分“QBS 实时版”和“原页静态回退版”。

## [0.6.41] — 2026-08-17

### 本地 HTML QBS 活页化使用专用终态交付合同

- `preserve_html_qbs_live` 无条件选用 `preserve_html_qbs_live_delivery_v1`，即使调用方显式传入通用模板，也不再把一次结构保真的数据链迁移扩写成行业研究报告。
- 新模板只交付结构/样式保真、非 QBS 数据链替换、QBS 实时刷新状态、`page_id` 与公开链接，不输出未绑定回复证据的业务数值、趋势、分位或投资判断。
- 该模式的终态 contract 新增 `require_page_id_in_reply:true`；validator 要求最终回复在公开 URL 之外单独包含准确 `page_id`，缺失时分别返回 `PAGE_ID_REQUIRED` / `PAGE_ID_MISSING`。
- `static_page.py update` 与 `upload/publish_final` 对齐：直接更新本地 HTML 时也会解析并返回专用回复模板合同，同时保持原 HTML、DOM、CSS 和可见正文不变。

## [0.6.40] — 2026-08-17

### 保持用户本地 HTML 不变的数据链 QBS 活页化

- `static_page.py upload/update` 新增显式 `transformation_mode:"preserve_html_qbs_live"`：用于用户已有本地 HTML 调用非 QBS 服务接口的场景，不走在线模板 fork，也不要求 QBS Handoff。
- 发布前校验来源 HTML 的文件 SHA256、非 QBS 接口已移除、非运行时 DOM/稳定属性、可见静态正文、内联 CSS 和标题文案未变，并复用实时路由、公式验证与 Grant 验证收据；直取数据使用 Data Grant，需要计算时要求已验证并注册公式包。
- 该模式自动禁用 Share Shell 注入/刷新，确保校验后的 HTML 就是最终上传 HTML；目标 HTML 必须包含可实际查询的 QBS package/grant 凭证、对应 Runtime 调用以及真实刷新绑定；失败在页面托管写请求前拒绝，成功响应附加不含 signature 的 `transformation_validation`。
- 测试覆盖本地 HTML 调用非 QBS 接口并动态刷新的最小场景；本版本暂不引入 Block Runtime 标记或 Block 持久化。
- `qbs_bridge.py validate_package_set` 在 QBS `summary` 输出只返回 `expression_id/data_id/status` 时，按同批公式顺序恢复 `variable_name` 并校验数量/名称冲突，避免成功公式被误判为 `REQUIRED_OUTPUT_MISSING` 而跳过注册与上传。
- QBV 验证切批与 QBS 工具合同统一为单批最多 **20 条公式**；21 条及以上必须拆批。

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
