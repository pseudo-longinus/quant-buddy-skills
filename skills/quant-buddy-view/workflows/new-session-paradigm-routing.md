# Workflow · 新会话：单股快速返回 / 查范式卡后三分支

新会话被判定为可分享活页任务后先判断是否命中“简单单一 A 股分析”快速通道；未命中才查范式卡（`templates` 活页列表），再决定 direct / fork / 自建。范式卡 = 后台 `recommend:官方精选` 或 `recommend:社区` 标签的现成活页列表。若 `config.json._channel=feishu-group`，所有非终态 hint 都按 `delivery_policy.emit_intermediate_url=false` 处理：内部流程照常创建/维护页面，但用户只在终态收到 playground 链接。

> 场景：用户说「宁德时代现在估值贵不贵，帮我做个能发出去的页」/「沪深300今天哪些成分股异动」。

## -1. 建立 Trace Context

在任何模板、公式、数据或发布请求前，先记录用户原始问题。这一步会真的写后端审计记录，所以必须带上本次任务的身份，且与后续所有命令保持同一个 key：

```bash
# key 走环境变量：exec 日志里 env 会脱敏，命令串是原样记录的，不要拼进命令
QBV_API_KEY=<本次任务的 key> python scripts/trace_context.py begin '{"user_query":"用户原始问题"}'
```

保存返回的 `task_id`。本工作流后续每个 `static_page.py`、`formula_package.py`、`data_grant.py` 命令都必须在参数中复用它；调用 quant-buddy-skill 验证公式时，使用 `qbs_bridge.py` 并显式传该 `task_id + user_query`，由 task-scoped session 防止并发拆链。

## -0.5. 快速通道：简单单一 A 股分析

同时满足以下条件时直接走快速通道：

- 用户只指定一只 A 股名称或代码；
- 诉求是简单综合分析、个股画像、估值/财务/行情概览并返回可分享页面；
- 没有定制栏目或版式、指定额外指标/公式/图表、对比、多标的、指数、港股、美股、选股或回测要求。

```bash
python scripts/static_page.py new_asset_page '{"task_id":"task_xxx","asset":"贵州茅台","user_query":"分析贵州茅台"}'
```

该命令直接调用 `POST /skill/newAssetPage`，由服务端完成资产解析、固定来源页实例替换和三份固定 Data Grant 注册。Agent 不查 `templates`、不运行 `new_page/fork_prepare`、不另跑 QBS 预验证、不自行注册 Grant。成功条件是 `agent_reply_contract.terminal=true` 且 `operation=new_asset_page`；最终只返回 contract 的 `public_url`，不生成七节 Markdown 分析，也不运行 `validate_agent_reply.py`。同一 task/资产重试由服务端幂等返回已有页面。

任一条件不满足就进入第 0 步，不要把定制单股页或多资产请求塞进快速通道。快速通道创建的是调用者自己的页面；后续内容修改复用现有 `update(page_id)`。

## 0. 查范式卡判命中

```bash
# 查官方精选 + 社区的范式卡列表（命中池，官方优先）
python scripts/static_page.py templates '{"task_id":"task_xxx","recommend":"all","page":1,"page_size":20}'
```

调用返回后，先做一次一致性核对，再进入分支判断：

- `item_count == len(items_summary)` 且存在 `full_result_file`/`full_result_sha256`（说明完整候选已成功落盘）——满足才能继续往下判断 ①/②/③；
- 任一条件不满足，或返回 `error` 为 `TEMPLATES_PERSIST_FAILED` / `TEMPLATES_RESPONSE_SHAPE_UNEXPECTED`，必须停下来告诉用户「范式候选核对失败，暂无法确认是否命中」，**禁止**据此判定为③未命中直接自建，也**不允许**重复调用 `templates` 来重试（每个任务只能调用一次）。

按用户请求判断落到哪个分支：

- **范式匹配 + 标的/股票池一致** → ① 直接命中
- **范式匹配但标的不符 / 用户要改内容** → ② fork
- **无匹配范式** → ③ 自建

> 判据边界：单标的范式要求标的一致；固定指数/股票池范式要求指数或股票池一致；资产无关的全市场范式要求市场范围与分析场景一致。范式相同但具体范围不同一律 fork。

fork/unmatched 都必须由 Agent 在 `new_page.routing_decision` 中显式记录判断；脚本校验候选确实来自本次 `items_summary`、补齐候选快照并与新 `page_id` 绑定，但不替 Agent 做语义匹配。常用 fork reason 为 `same_paradigm_different_asset` / `same_paradigm_different_scope` / `user_requests_template_changes`；unmatched reason 为 `no_relevant_candidate` / `paradigm_mismatch` / `page_shape_mismatch` / `required_capability_missing` / `user_requires_bespoke`。

## ① 直接命中：返回现成链接（不建页、不注册）

1. `templates` 一旦精确命中：普通渠道的下一条用户可见消息立即返回列表项的 `download_url/public_url`，且**命中与这条消息之间禁止任何工具调用**；`feishu-group` 禁止发送该链接，直接进入下一步。不 `new_page`、不注册、不 fork。
2. 普通渠道发出链接后、`feishu-group` 不发链接而是立即运行一次 `direct_deliver`；不要单独读取模板详情、解析 HTML、查询数据或调用 finalize：
   ```bash
   python scripts/static_page.py direct_deliver '{"task_id":"task_xxx","page_id":"page_xxx","template_revision":"sha256"}'
   ```
3. `direct_deliver` 内部读取一次模板、下载一次 HTML、按当前 package/grant 各查询一次并调用一次 finalize；公式结果固定为 summary，grant 完整结果只写系统临时目录。失败时不 finalize。
4. 只有 `agent_reply_contract.terminal=true` 且 `operation=direct_finalize` 才允许收口。回复模板和 `page_context` 沿用原页。
5. `direct_deliver` 返回 `agent_reply_contract_file`、`reply_draft_file`、`reply_validation_params_file` 和 `reply_validation_command`。按 contract 的 `reply_render_policy` 与 `reply_data_availability` 删除结构性不存在的字段、整列、整行和空可选章节，再把 Markdown 草稿写入返回的 draft 路径，只执行返回的校验命令一次；成功会清理本任务 contract、draft、params 和 grant 临时结果。
6. 用户之后说「要改这个页面内容」→ 转 ② fork。

## ② fork：范式命中但要改 → 换标的注册自己的公式包

1. 运行 `new_page` 创建进度页并取得 `page_id + url`，同时引用本次候选并记录 fork 决定：
   ```bash
   python scripts/static_page.py new_page '{"task_id":"task_xxx","user_query":"分析下彩虹股份","title":"彩虹股份分析活页","routing_decision":{"mode":"fork","source_template_id":"page_template_xxx","reason_code":"same_paradigm_different_asset"}}'
   ```
   普通渠道立刻把首链发给用户/承接方；`feishu-group` 只内部保留 `page_id/url`，不得向用户发送。
2. 用同一 `task_id` 调 `fork_prepare`，同时传 `source_template_id + target_page_id`，**并且必须传 `target_asset`**，推荐给全 `{"name":"中国中车","code":"601766"}`（只给代码时脚本会先反查资产库补名字，反查不到才报 `TARGET_ASSET_NAME_REQUIRED`）。

   **职责分工**：Agent 负责说清楚"换成哪只标的"，脚本负责"这只标的在页面里写成什么样"。来源模板的主资产由脚本从模板公式（`取出(...)`/`收盘价(...)` 等）词频 + 标题自动推导，代码的实际书写形态（`SH600900` / `600900.SH` / 裸 `600900`）由脚本扫描来源 HTML 得出，**只替换页面里真实存在的写法**。不要去猜来源 HTML 里代码写成什么样——你看不到那个文件，猜错会直接让 fork 失败。

   - **多资产/指数类范式**（没有唯一主资产）推导会失败并返回 `FORK_SOURCE_ASSET_AMBIGUOUS`，报错里带 `detected_source_asset.candidates`（候选资产名）和 `example_params`（可照抄的调用）。此时用 `source_asset` 显式指明来源模板主资产再重试。为避免这一轮往返，这类范式建议一开始就传 `source_asset`。
   - `asset_replacements` 现在是**可选覆盖**：只在需要额外文案替换、或要覆盖脚本推导结果时才传，同名 key 以你传的为准。
   - 替换完成后、写出工作 HTML **之前**，脚本会做残留检查：主资产名或其代码写法若仍留在页面里，直接返回 `FORK_SOURCE_ASSET_RESIDUAL`，不会等到发布成功后才发现文案还是源模板原样。

   脚本生成 `fork_manifest_v2`、脱敏 `*.fork.html`、credential-free `*.fork-review.json`、`*.publish-plan.json` 和任务绑定；原始来源 HTML 仅供内部 SHA/凭证校验。
3. Agent只编辑脱敏 HTML 和 review。来源 package/grant 通道、Grant kind/query_type/fields/dimensions/window/result mode及CSV/inline合同默认继承；主资产的公式/文案替换已由上一步的 `target_asset` 推导完成，同业矩阵填写 `target_slots`，复杂跨资产公式填写完整 `target_formulas`。**同业资产不在主资产替换范围内**（残留检查也会跳过它们），必须由你在 review 阶段选定目标同业——系统不替 Agent 选。
4. 运行 `fork_prepare` 返回的 `publish_command`，不要手写 package/grant、Marker、reads、Grant payload 或完整 workflow JSON。
5. 发布器在第一次网络写入前依次检查 review完整性、来源凭证残留、Marker唯一性、required outputs/公式左值/reads、PE/PB 水位公式的明确算法与正整数窗口、Grant合同差异和Card Runtime假凭证结构；fork 默认继承来源模板已验证的水位口径。
6. Package验证和注册从同一 `{formulas,reads,begin_date}` 合同派生；Grant验证和注册使用同一 `kind + payload` fingerprint。`validate_grant_set`支持 `fast_query`、`stockProfile` 和 `selectByComposition`。
7. 每个runtime role只注册一次；正文与Card共享合同由发布器自动向全部Marker扇出替换，然后上传图片、写prepared HTML并单次调用`publish_verified`。
8. `fork_manifest_v2` 手工传runtime bindings返回 `MANUAL_RUNTIME_BINDINGS_FORBIDDEN`。已准备的v1任务仍可按旧接口发布；不要混搭v1/v2。
9. 发布器返回SHA256绑定的完整contract、draft路径和唯一校验命令；禁止手工重建精简contract。校验成功后，回复=回复模板格式+contract的`public_url`；`feishu-group`只发送该playground链接。

## ③ 未命中：自建

无匹配范式时，由 Agent 指出最接近候选及实质能力缺口，再走 [dashboard-end-to-end.md](dashboard-end-to-end.md)：

```bash
python scripts/static_page.py new_page '{"task_id":"task_xxx","user_query":"制作事件时间线页面","title":"事件分析活页","routing_decision":{"mode":"unmatched","closest_template_id":"page_template_xxx","reason_code":"required_capability_missing","reason":"候选模板缺少用户要求的事件时间线与情景推演能力"}}'
```

记录成功后继续 `build_dashboard` / bespoke 自建 → 验证 → 注册 → 生成 → verify → `publish_final`。普通渠道发送首链，`feishu-group` 不发送；其余收口同 ②。`build_dashboard` 不读取也不限制 routing；只有最终发布与已记录决定矛盾时才要求复核。

若 `new_page` 已记录 fork，但在 `fork_prepare` 前确认模板确有实质能力缺口，直接 `publish_final` 会在网络写入前返回 `ROUTING_RECONFIRM_REQUIRED`。此时要么继续返回的 fork 路径，要么在同次发布参数中显式改判：

```json
{
  "routing_override": {
    "from_mode": "fork",
    "to_mode": "unmatched",
    "reason_code": "required_capability_missing",
    "reason": "审核后确认模板缺少用户要求的核心能力"
  }
}
```

已经执行 `fork_prepare` 后不得在 `publish_final` 改判；此时继续标准 fork 工作流。

## 后续追问

- 自己的链接 → `update` 同 `page_id`（内容变、URL 不变）。
- 命中的官方/社区链接要改 → 只能转 ② fork 成自己的链接后再改。

## 必要消歧：首链等待并同页恢复

fork/unmatched 创建首链后，如果资产库证明存在 A/H、同名代码或其他不能安全默认的口径：

1. 先用原 `task_id/page_id` 调 `update_progress`，传 `page_status:"waiting_input"` 与 `required_input:{id,prompt,options?,resume_step}`。
2. 只有响应含 `agent_reply_hint.interaction_required:true` 才允许在对话中询问用户；此轮不得声称页面完成。`feishu-group` 只提出问题，不附带进度链接。
3. 用户回复后禁止重新建 Trace 或首链；用相同 `task_id/page_id` 调 `update_progress(page_status:"running", current_step:<resume_step>)`，随后继续原分支。
4. 最终仍必须 `publish_final` 并取得 `agent_reply_contract.terminal:true`。

## 运行质量门禁

- 没有 terminal contract 禁止完成业务任务；唯一可暂停例外是成功的 `waiting_input` checkpoint，且用户回复后必须同任务续跑。
- 每个 package/grant 最多查询一次，仅明确瞬时网络失败允许重试一次。
- direct 命中后禁止研究脚本实现、运行子命令 `--help` 或重复调用 `template/query/finalize`；使用 `direct_deliver` 的紧凑结果继续生成回复。
- `new_asset_page` 成功后直接返回 terminal contract 的公开 URL，不进入 validator；其余分支在 validator 返回 `valid=true` 后立即最终回复，禁止再次校验、运行 `--help`、扫描临时目录或继续 memory 搜索。
- 性能门槛：普通渠道模板命中到首链 ≤5 秒；所有渠道 terminal 到最终回复 ≤45 秒、端到端 ≤120 秒、用户可见消息间隔 ≤60 秒。
- 未跑浏览器验收时，只能声明公开 URL 和实时接口可访问。
