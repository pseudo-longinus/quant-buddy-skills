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

目标运行角色至少声明 `role_id + kind(package|grant)`。Compose引用已注册数据时还需相应 `package_id/grant_id`、`contract_fingerprint`、`validation_receipt_file`；收据必须属于同任务且completed/success。先完成合同验证和注册，再填写引用；不能把signature或API Key写进执行计划。

同任务已选择Compose时，`fork_prepare`（含force_rebuild）不得全量继承来源运行时。需要改变业务范围时明确修订计划；不允许把fork改判unmatched，不新建task/page绕过。

## 进度不是交付

`update_progress`使用 `page_status/current_step`，不接受`status/step`；更新必须指定阶段，不能回退到初始化默认plan。未知阶段需在steps中显式登记，内置兼容publication_validation。

- `waiting_input`必须有 `required_input:{id,prompt,resume_step}`，仅用于真实业务决策或授权缺口。内部构建模式选择由Agent处理。
- 技术失败记录错误阶段与可执行恢复动作，例如 `error_code:"BUILD_FAILED", next_action:{command:"compose_page"}`。
- 计划任务的完成状态由发布验收产生，不通过`page_status:"done"`设置。
- 若已存在可读内容或旧页面状态未知，进度只写任务状态，返回`public_page_updated:false`，不得称“页面已更新”。对话/宿主显示进度，公开正文保留。首链确认为placeholder时才允许更新进度HTML。

## 恢复

```bash
python scripts/static_page.py delivery_status '{"task_id":"task_xxx","refresh_remote":true}'
```

- PLAN_REVISION_CONFLICT：读取当前计划，重新生成对应候选，不篡改旧receipt/hash。
- COMPOSE_PREPARE_FORBIDDEN：继续compose_page，不重新fork_prepare。
- GRANT_SET_INVALID：一次处理errors中的全部角色；确定性错误同输入不盲重试。
- PUBLISH_OUTCOME_UNKNOWN：先核对已保存的发布收据及当前页面版本/hash。远端仍显示旧版本不等于已证明请求不会迟到，不能直接重发。
- PUBLISH_VERSION_CONFLICT：检测到其他更新，停止覆盖，重新对齐。
- 若上次写入已确认且当前远端版本/hash一致，重试可复用该版本再做公开验收，不重复写入。

公开HTTP成功不是终态：仍需同page_id、版本、数据绑定、浏览器与回复契约证据。静态或部分结果需如实说明范围，不能冒充用户明确要求的实时/完整研究。

## 宿主与部署边界

宿主可设置绝对路径 `QBV_STATE_ROOT`，将任务路由/计划/Compose/manifest/收据放到各worker可访问的位置；设置 `QBV_SHARED_STATE_REQUIRED=1` 后缺少该根目录会明确失败。宿主仍须验证真实挂载及worker版本一致性，不能仅设置变量就宣称跨worker可靠。

计划/交付状态不再由终态回复清理或临时TTL扫描删除；保留策略由宿主另行管理。Grant/Formula Package新登记使用任务凭据目录；旧版全局凭据的证据恢复仍需独立验证。

本次为 **Skill-only 修复**，使用现有 `getPageDetail` / `updateStaticPage` 接口，不要求后端新增接口、能力开关或版本升级。

写前读取目标页版本/哈希，写后保存现有接口返回的版本，再核对公开浏览器实际内容和当前版本。响应已确认且同一候选/远端版本未变时，复用收据重新验收，不重复写入。响应丢失或结果不确定时，记录失败并停止自动重发；不能仅凭远端仍是旧版本或恰好匹配候选哈希，就假定前一次请求已经结束。

这些是客户端日志与写前检查，不是服务端原子条件更新或幂等保证。工具返回 `local_lock_and_read_before_write_no_server_cas` 如实表示边界。本次不承担服务端锁过期、并发覆盖或跨 Mongo/对象存储事务的修复，不因此阻塞正常 Skill 发布。

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

内联结果直接复用，不重复查数。CSV结果在普通live验证时不增加隐藏下载；物化命令才下载已返回的CSV，不重新执行原查询。若旧验证没有完整数据，可传`resource:"grant"|"package"`、对应已注册ID和contract_fingerprint，验证本任务登记身份后取数冻结。

materialize返回snapshot_receipt_file及snapshot_receipt_sha256。把这两项与role_id加入执行计划的snapshot_roles（已准备计划需要expected_revision/revision_reason）；panels引用snapshot_receipt_file，公式快照另指定snapshot_output或snapshot_outputs。必需输出不能只验证不展示。

- 页面只有快照：发布参数自动使用`live_data_mode:"verified_snapshot"`，不依赖原Grant/Package持续可用；声明“已验证静态快照，不会自动更新”。
- 既有动态角色又有快照：使用`mixed`，动态部分仍需完整路由/验证收据，并明确“部分实时、部分静态快照”。
- 用户要求实时：在计划中保留`require_live_data:true`，不能用技术性计划修订将其改为false。快照不能满足这一完整交付条件；不得冒充终态成品。
- captured_at是快照生成时间，不是行情交易日。保留数据本身的日期/报告期，不能自动把生成时间当成数据时点。

快照和mixed的终态回复链接分别使用“可分享静态研究页”和“可分享活页（部分实时、部分静态）”；validator按合同检查，不再强制把快照称作实时活页。

## 可编辑草稿与恢复诊断

宿主设置 `QBV_OUTPUT_ROOT` 时，草稿必须在 `SESSION_WORKSPACE` 内；否则使用当前会话工作目录的 `output/qbv/<task_id>/`。路径穿越、符号链接越界和写入Skill安装目录均失败关闭。`next_action.params_file` 才是Agent编辑入口，内部计划、凭据和验证收据不是编辑目标。

草稿按 revision/内容摘要命名，不覆盖旧研究文件。`unassigned_panels` 表示因模块删除而待迁移的内容，需搬到有效模块后明确移除迁移项，不能忽略它继续发布。

`runtime_roles[*].compose_module` 可指定数据面板位置；省略时放入首个模块，并按验证合同中的资产命名。`panels[*].runtime_role_id` 引用当前角色；与显式 grant_id/package_id 冲突时拒绝。text/image 不算运行角色消费，修正草稿保留文字并补独立table。`issues` 和 `draft_diagnostics` 汇总未解决项，不要原样重复调用或删除实时要求。

运行角色齐备后优先复用唯一、同任务、合同匹配的已有路由；存在多个匹配候选时显式提供 route_receipt_file。多资产路由逐项核验原子路由及收据，不制造新验证结果。未通过发布证据预检不会返回 publish_verified 下一步。

失败回复可保留 `progress_link`，使用返回的“任务进度（构建失败）/（未完成）”标签，明确 terminal=false。这里并未修改宿主卡片识别逻辑，不以“已完成”徽标或提取到的URL判断业务成功。
