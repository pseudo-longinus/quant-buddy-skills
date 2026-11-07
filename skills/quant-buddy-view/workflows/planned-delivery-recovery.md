# 计划驱动的研究页交付与恢复

用于普通研究页的继承、Compose、同页发布和失败恢复。已有文件转页继续走 existing-file-static-first，不要求先查研究范式。

## 最短路线

1. 按现有 Trace/ownership/范式路由创建或恢复一个目标 page_id。`new_page` 成功后保存执行计划和首链状态。
2. **单资产且确需继承数据合同**才走 `fork_prepare → fork_review_update → publish_workflow`。来源名称与代码必须对应真实资产；研究ID、篮子名不是证券代码。
3. **多主题/多资产或只借布局**走 `intent_profile → research_templates → fork_compose`。资产范围可用 `asset_scope.kind:"basket"`；不要为了满足单资产参数拼造source_asset。
4. `fork_compose` 返回 `execution_plan.plan_hash` 与 `next_action.params_file`。文件位于会话可写输出目录；填写title、研究文字及需要调整的compose_module，保留自动绑定的数据面板，用当前plan_hash运行 `static_page.py compose_page @文件`。
5. `compose_page`生成完整候选页和发布参数文件；按next_action运行 `publish_verified`，完成本地浏览器、同页发布和公开验收，再按终态回复契约收口。完整候选不是已发布成品，panel_block也不是完整页面。

当前Compose组装器支持layout、layout+style及original，复用被选section的外层布局类和受限样式，替换旧内容；不自动执行来源脚本或继承来源数据。其他借鉴级别返回需要适配的结构化错误，不得伪装成布局借鉴绕过。

## 执行计划

```bash
python scripts/static_page.py execution_plan '{"task_id":"task_xxx","view":true}'
python scripts/static_page.py execution_plan @plan-revision.json
```

修订输入必须包含 `expected_revision + revision_reason`，按需提供 `target_scope` 与 `runtime_roles`。task/page/source身份不能改变；初始化路由计划可在首次准备时补全，已准备的计划变化必须显式修订。旧plan_hash的候选和发布参数失效。每次成功修订返回新的next_action.params_file；旧稿保留，研究文字自动迁移，不编辑内部收据或手工修补旧hash。

本轮明确要求实时而旧计划未记录该要求时，发布返回 `CURRENT_LIVE_PLAN_REQUIRED`，先修订计划并绑定当前研究需要的数据角色。集合范围必须是 `basket/sector/market` 等明确范围；`market/sector` 或未列成员的 `basket` 还要有当前研究合同及 `selection_output`。把 `selection_output` 写进某个 `runtime_roles[*].required_outputs`，并绑定动态 package/handoff 角色；普通行情 Grant 不能覆盖名单或派生指标重算。合同还必须带同一范围的完整覆盖、逐行数量和实际观察日期。少量观察股价格自动刷新不能代替用户要求的全市场名单或计算指标自动更新；核心角色未覆盖时保留原页和未完成状态，不把混合页说成实时任务已完成。已验收页面的宿主收尾会按封存合同校验实际最终答复，缺失必填章节或最终链接格式时仍不能标记交付成功。

目标运行角色至少声明 `role_id + kind(package|grant)`。Compose引用已注册数据时还需相应 `package_id/grant_id`、`contract_fingerprint`、`validation_receipt_file`；收据必须属于同任务且completed/success。先完成合同验证和注册，再填写引用；不能把signature或API Key写进执行计划。

同任务已选择Compose时，`fork_prepare`（含force_rebuild）不得全量继承来源运行时。需要改变业务范围时明确修订计划；不允许把fork改判unmatched，不新建task/page绕过。

## 进度不是交付

金融快照使用当前任务的真实验证收据，经 `materialize_snapshot` 物化并绑定 `snapshot_roles` 后以 `verified_snapshot` 发布；纯静态内容模式不能替代金融数据证据。按本轮范围选择回复模板，不把单字段快照扩成完整个股研究。

`verify_published`、`delivery_status` 和恢复流程对已验收页面返回回复校验的 `next_action`：读取封存合同及模板，填写返回参数中的 `draft_file`，执行 `python scripts/validate_agent_reply.py @参数文件`。只有 `valid=true` 才按原文交付；缺数据证据时补原合同证据，不清空合同、不覆盖已发布页。重复核验或恢复不能替代回复校验。

`update_progress`使用 `page_status/current_step`，不接受`status/step`；更新必须指定阶段，不能回退到初始化默认plan。未知阶段需在steps中显式登记，内置兼容publication_validation。

- `waiting_input`必须有 `required_input:{id,prompt,resume_step}`，仅用于真实业务决策或授权缺口。内部构建模式选择由Agent处理。
- 技术失败记录错误阶段与可执行恢复动作，例如 `error_code:"BUILD_FAILED", next_action:{command:"compose_page"}`。
- 计划任务的完成状态由发布验收产生，不通过`page_status:"done"`设置。
- 若已存在可读内容或旧页面状态未知，进度只写任务状态，返回`public_page_updated:false`，不得称“页面已更新”。对话/宿主显示进度，公开正文保留。首链确认为placeholder时才允许更新进度HTML。

## 恢复

本轮宿主原始问题优先于历史计划。已有页追问先 `interpret` 当前页，再按新要求显式修订计划；不继续沿用旧的“方法页、无需实时”判断。

恢复顺序统一为：核对 pending/unknown 写入 → 只读核验已确认发布 → 复用 Capsule/Handoff/验证收据 → 确实没有可用数据才考虑方法页。内部 Compose 文件缺失只表示记录不完整，不能推断线上没有数据。聊天恢复 V1 走 [版本恢复](page-version-restore.md)，不进入此降级流程。

快照读取属于内部操作，传给QBS的用户问题与轮次仍沿用当前宿主上下文，不用“物化快照”等操作说明替代。交接失败须保留原验证合同并检查具体原因，不手工补造验证收据。静态升级为实时只改变取数方式，已有公式、日期定义、单位与股票范围保持原合同；需改变时明确修订，不能把不同算法假定为等价。

```bash
python scripts/static_page.py delivery_status '{"task_id":"task_xxx","refresh_remote":true}'
```

```bash
python scripts/static_page.py reconcile_delivery @reconcile-params.json
```

`reconcile-params.json` 包含 `task_id`、可选 `page_id/plan_hash`，以及旧 journal 未保存 trace 时必填的准确 `trace_id`。核销要求服务端确认同 task/page/trace/error 的 `outcome=rejected` 且 `write_applied=false`；新合同错误还必须 `retry_safe=true`，历史 `BAD_CHANGE_ASPECT/SCENE_TAG_NOT_FOUND` 日志可按已核实无写入事实兼容核销。核销在 `last_write.reconciliations` 留痕，不删除或重写原请求摘要。其他错误、查不到日志、身份不匹配或写入结果 unknown 均保持防重放保护。

发布更新前会本地预校验 `change_aspect` 与场景标签，标签预检失败不写 journal、不发起页面更新。直接 `upload` 创建完整研究页且返回成功后，工具会登记同 task 的 `unmatched/result` 计划与 confirmed journal；宿主收尾只调用 `verify_published` 复验原 page_id。任何恢复流程都不得把已确认的完整页降级为“研究方法说明，数据待补”，也不得以同 task 新建替代页面来覆盖原 page_id。

- PLAN_REVISION_CONFLICT：读取当前计划，重新生成对应候选，不篡改旧receipt/hash。
- COMPOSE_PREPARE_FORBIDDEN：继续compose_page，不重新fork_prepare。
- GRANT_SET_INVALID：一次处理errors中的全部角色；确定性错误同输入不盲重试。
- PUBLISH_OUTCOME_UNKNOWN：先核对已保存的发布收据及当前页面版本/hash。远端仍显示旧版本不等于已证明请求不会迟到，不能直接重发。若 `last_write.error_code=BAD_CHANGE_ASPECT/SCENE_TAG_NOT_FOUND` 或服务端合同确认 `write_applied=false`，用 `reconcile_delivery` 调只读结果接口核销；证据不全时保持 unknown。
- PUBLISH_VERSION_CONFLICT：检测到其他更新，停止覆盖，重新对齐。
- 若上次写入已确认且当前远端版本/hash一致，重试可复用该版本再做公开验收，不重复写入。

公开HTTP成功不是终态：仍需同page_id、版本、数据绑定、浏览器与回复契约证据。静态或部分结果需如实说明范围，不能冒充用户明确要求的实时/完整研究。

## 宿主与部署边界

宿主可设置绝对路径 `QBV_STATE_ROOT`，将任务路由/计划/Compose/manifest/收据放到各worker可访问的位置；设置 `QBV_SHARED_STATE_REQUIRED=1` 后缺少该根目录会明确失败。宿主仍须验证真实挂载及worker版本一致性，不能仅设置变量就宣称跨worker可靠。

计划/交付状态不再由终态回复清理或临时TTL扫描删除；保留策略由宿主另行管理。Grant/Formula Package新登记使用任务凭据目录；旧版全局凭据的证据恢复仍需独立验证。

计划发布使用 `getPageDetail` / `updateStaticPage`；确定性拒绝的存量恢复另使用只读 `publicationOutcome`。新 QBV 遇到尚未提供该接口的旧服务端时失败关闭，不执行写入。

写前读取目标页版本/哈希，写后保存现有接口返回的版本，再核对公开浏览器实际内容和当前版本。响应已确认且同一候选/远端版本未变时，复用收据重新验收，不重复写入。响应丢失或结果不确定时，记录失败并停止自动重发；不能仅凭远端仍是旧版本或恰好匹配候选哈希，就假定前一次请求已经结束。

下载/解读记录的编辑版本会沿 Compose、更新和恢复传递为 `expected_current_version_id`。服务端原子检查该前置条件，工具返回 `local_journal_and_server_cas`。版本变化即停止，不取一个新版本号继续覆盖。该保护不等于服务端全局幂等或跨 Mongo/对象存储事务；未知写入仍按原 journal 核对，不能盲重发。

已有可读页面失败时保留正文；尚未完成的任务只给出非终态状态和具体错误，不把技术失败伪装成用户待确认或成功交付。


## 注册身份与验证合同绑定

计划任务调用data_grant/formula_package的register时必须传同任务、completed/success且fingerprint匹配的`validation_receipt_file`。publish_workflow自动传递对应角色收据；不要把验证收据放进HTTP业务payload。

注册成功返回`registration_receipt_file`和`contract_fingerprint`。任务凭据落在任务根目录的`credentials/grant|package`，公开注册收据不含signature/API Key。Compose既核对验证收据，也核对**该grant_id/package_id的注册合同**，不能拿一份收据搭配另一授权。

同任务/身份/endpoint/合同的有效注册可复用，不重复注册。已过期或撤销、身份变化、文件hash冲突及注册/签名轮换结果不确定时失败关闭。`registration_status`只读本地证据，不能证明远端请求未执行；不确定时不能盲重发。

```bash
python scripts/data_grant.py registration_status '{"task_id":"task_xxx","grant_id":"dg_xxx"}'
python scripts/formula_package.py registration_status '{"task_id":"task_xxx","package_id":"pkg_xxx"}'
```

显式refresh/revoke使用同一任务存储并更新登记收据。轮换后旧Compose候选失效，必须重新构建；不会自动改写已发布页。旧版无登记证据的凭据不自动认领到计划任务。

## 已验证数据的静态研究页

静态金融数据不能靠手填JSON或`market_data_required:false`绕过证据要求。成功的QBS Grant验证会保存不可变结果引用；正文快照只通过受控materialize入口取得：

```bash
python scripts/static_page.py materialize_snapshot '{"task_id":"task_xxx","validation_receipt_file":"已完成的验证收据路径"}'
```

内联结果直接复用，不重复查数。日频 window/series CSV 在 validate_grant_set 中下载并逐资产、字段、日期校验，成功收据已包含物化结果；后续 materialize_snapshot 不重复下载或查询。其他引用型旧收据由物化命令下载已返回的 CSV。下载链接过期时，日频验证最多重做一次同合同只读查询，不改变日期/资产。若旧验证没有完整数据，可传`resource:"grant"|"package"`、对应已注册ID和contract_fingerprint，验证本任务登记身份后取数冻结。

materialize返回snapshot_receipt_file及snapshot_receipt_sha256。把这两项与role_id加入执行计划的snapshot_roles（已准备计划需要expected_revision/revision_reason）；panels引用snapshot_receipt_file，公式快照另指定snapshot_output或snapshot_outputs。必需输出不能只验证不展示。

- 页面只有快照：发布参数自动使用`live_data_mode:"verified_snapshot"`，不依赖原Grant/Package持续可用；声明“已验证静态快照，不会自动更新”。
- 既有动态角色又有快照：使用`mixed`，动态部分仍需完整路由/验证收据，并明确“部分实时、部分静态快照”。
- 用户要求实时：在计划中保留`require_live_data:true`，不能用技术性计划修订将其改为false。快照可作为本地研究证据，但不能替代本轮自动更新交付。发布前统一核对本轮范围、结果合同、`required_outputs`、动态 package/handoff 角色、完整覆盖行数和观察时点；任一缺失时保留原页并返回结构化未完成错误，不得覆盖为方法页或报告完成。
- captured_at是快照生成时间，不是行情交易日。保留数据本身的日期/报告期，不能自动把生成时间当成数据时点。

快照和mixed的终态回复链接分别使用“可分享静态研究页”和“可分享活页（部分实时、部分静态）”；validator按合同检查，不再强制把快照称作实时活页。

## QBS Handoff快照桥

`recover_delivery` 在降级前会查找同task/turn的 `.handoff.json`，并用 `handoff_snapshot_bridge.py` 物化 `validated_outputs[].data_reference.data_id`。Bridge只接受 `read_tool=readData`，读取 `last_column_full` 共同完整截面，校验data reference fingerprint、行数与内容hash后写入现有 `qbv_verified_snapshot_v1` receipt。输出合同为 `qbs_handoff_snapshot_bundle_v1`。

- 有可用输出：绑定`snapshot_roles`并按Handoff保留的`partial_research/partial`或更强已验证状态恢复；不得改写为`methodology/unavailable`。
- 只有部分角色：继续展示covered roles，页面列出missing roles；缺失角色不是零命中。
- 完全没有可用输出才进入方法页；Handoff hash、行数或数据ID校验失败时必须返回结构化错误，不能静默降级。

运行角色齐备但继承来源模板证据不完整时，`fork_compose`返回`COMPOSE_ROLE_EVIDENCE_INCOMPLETE`并停止生成候选页。Compose布局借鉴不继承来源模板package role；目标数据角色必须来自当前任务Handoff、显式注册角色或快照角色。

## 可编辑草稿与恢复诊断

宿主设置 `QBV_OUTPUT_ROOT` 时，草稿必须在 `SESSION_WORKSPACE` 内；否则使用当前会话工作目录的 `output/qbv/<task_id>/`。路径穿越、符号链接越界和写入Skill安装目录均失败关闭。`next_action.params_file` 才是Agent编辑入口，内部计划、凭据和验证收据不是编辑目标。

草稿按 revision/内容摘要命名，不覆盖旧研究文件。`unassigned_panels` 表示因模块删除而待迁移的内容，需搬到有效模块后明确移除迁移项，不能忽略它继续发布。

`runtime_roles[*].compose_module` 可指定数据面板位置；省略时放入首个模块，并按验证合同中的资产命名。`panels[*].runtime_role_id` 引用当前角色；与显式 grant_id/package_id 冲突时拒绝。text/image 不算运行角色消费，修正草稿保留文字并补独立table。`issues` 和 `draft_diagnostics` 汇总未解决项，不要原样重复调用或删除实时要求。

运行角色齐备后优先复用唯一、同任务、合同匹配的已有路由；存在多个匹配候选时显式提供 route_receipt_file。多资产路由逐项核验原子路由及收据，不制造新验证结果。未通过发布证据预检不会返回 publish_verified 下一步。

失败回复可保留 `progress_link`，使用返回的“任务进度（构建失败）/（未完成）”标签，明确 terminal=false。这里并未修改宿主卡片识别逻辑，不以“已完成”徽标或提取到的URL判断业务成功。

## 同页恢复而非停留在失败页

以下是本轮已授权页面任务的内部恢复，直接继续工具调用，保留已发完整业务答案。一次工具失败不等于任务结束；不发占位页作为成品。

1. `validate_grant_set` 的 `success/required_roles_complete` 表示全部合同是否通过；`status:partial` 保留成功项但不代表完整研究可发布。按 failed_grants 修正并只重验失败合同，零成功不注册。不用最新单值代替完整历史，不把缺失数据补零。
2. `SOURCE_CREDENTIAL_UNPAIRED/RESEARCH_DIGEST_EMPTY`：按 next_action 对同来源仅提取 layout/style，继续 fork_compose。只借布局不继承数据凭证，保持原 page_id 和来源。
3. `REGISTRATION_REJECTED` 保留明确拒绝码；`REGISTRATION_OUTCOME_UNKNOWN` 不重发注册。两者不意味着研究数据作废。执行返回的 recover_snapshot；单独注册工具返回 materialize_snapshot 时，物化后继续同页恢复。

明确实时要求时，不走静态降级。注册返回 `unresolved_data_names` 表示新执行环境找不到所引用的数据序列；从原 QBS 计算及验证记录取回全部上游公式，保留字面和依赖顺序，补齐同一包的完整合同后重新验证，再用新收据注册。当前会话能读到命名序列，不证明独立公式包能重算；不能只带最后几条排序公式或删除失败产出来通过。

恢复过程生成的说明、覆盖缺口和数据面板都补齐唯一编号及对应挂载点，保留已有编号。Presentation 主体占满宿主网格可用宽度；仍需真实浏览器验收，不以参数准备成功当作发布成功。

```bash
python scripts/static_page.py recover_snapshot @recovery-params.json
```

参数：task_id、当前 plan_hash、`roles:[{role_id,validation_receipt_file}]`。可传 title、description、panels 等研究内容，未指定时保留当前 Compose 草稿。角色须对应当前计划，不会删除未转换角色。初次 unmatched 计划尚未明确研究范围时，同时传真实 target_scope。

- Grant 复用已验证结果；公式从验证收据绑定的 QBS data_id 按原 reads 读取，既不注册新包也不改公式。旧公式收据缺产出映射时，执行返回的 qbs_bridge.py validate_package_set 重验原合同，再用新收据恢复，不循环调用同一失败的物化命令。
- 工具转换数据面板绑定、保留正文/标题/原草稿，修订同页计划并返回 compose_page 参数。继承页只借原来源布局；unmatched 保持原创路由，用 original 模块组装，不伪装 fork。
- **继续整理研究草稿**：自动表格只是数据绑定起点。将已有本地研究的结论、回测表、图表、栏目和口径迁移到返回的参数文件；处理未分配面板和必需产出，不能把三股50策略缩水成行情快照。原始数据验证不等于回测计算验证；保留数据、脚本、参数与结果的对应关系并核对派生结果。
- **优先恢复为 Presentation Mode**：找到可验证 handoff 时，先绑定 snapshot role，并生成/补齐 `presentation.html` 挂载点；保留既有高质量候选。普通 QBS 公式收据缺 `snapshot_receipt_file` 会返回 `QBS_RECEIPT_NEEDS_BRIDGE`，应走同任务恢复/handoff桥，不得重复提交同一收据或降级为无数据方法页。
- **质量 warning**：`composeQuality.warnings` 记录首屏结论缺失、长表前置、交互要求降级等问题；本阶段不阻断发布，但不能用搬长表、假指标或删除数据角色来消除。
- 按 next_action 执行 `compose_page → publish_verified → reply_validation_command`，真实验收成功后补链接。恢复成功只表示候选参数已准备，不是发布成功。
- snapshot 标注实际数据时点和不会自动更新；有效动态角色保留时为 mixed。`require_live_data:true` 不被技术恢复取消，静态部分不能冒充完整实时交付。
- 相同确定性错误和参数不循环重试。注册未知不重发，公开写入未知按 delivery_status 核对。恢复路径仍缺必要数据/权限或服务持续不可用时，保留原可读页面及研究产物，如实说明缺口，不绕过门禁显示成功。


有界恢复、方法页与新增研究状态见 [研究合同与恢复](research-contract-delivery.md)。优先执行 recover_delivery，最多两轮修复后同页交付可读成果。
