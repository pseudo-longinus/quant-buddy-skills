# QBS → QBV 并行活页路由

> 本文只定义 **QBS 何时交接**、Handoff 合同和后台 Job 边界。页面范式、direct/fork/unmatched、页面归属、复制、发布、Card Runtime 与公网验收全部由 `quant-buddy-view` 的现有 SOP 决定。

## 1. 不阻塞原则

- QBS 必须先完成本轮查询、计算、校验并准备好正常答案；QBV 失败不得撤销、覆盖或延迟这些业务结果。
- `route=create|existing_page` 时，QBS 必须使用宿主提供的**内部子 Agent 委派工具**启动独立 QBV 子任务，优先使用 `spawn_agent`；仅当宿主实际提供其他等价内部委派工具时才使用该工具。
- 委派调用只等待“已接受/已创建子 Agent”的即时回执，**不得在 QBS 第一条回答前等待页面生成完成**。
- 只有拿到真实委派回执，第一条回答末尾才可写“正在生成活页，完成后补充链接”；委派能力不可用或调用失败时必须把 Job 写为失败，但仍正常返回 QBS 答案，不得假称已开始生成。
- 子 Agent 完成后，父 Agent 或宿主回调向原用户、原任务追加第二条消息；不得另开用户可见任务代替回推。

## 2. 强制执行闸门

凡用户要求任何图表 artifact，QBS 在业务数据/静态图验证完成后、发送第一条回答前，必须实际执行分类器。**读取本文、生成 PNG 或模型自行判断均不算完成路由。**

```powershell
python scripts/live_page_routing.py route --user-query "用户本轮原话"
```

Windows / PowerShell 优先使用上面的 `--user-query` 形式，避免内联 JSON 引号被宿主 Shell 改写；自动化场景也可继续使用 `@payload.json`。宿主 Bash 的 cwd 已是 Skill 根目录时，必须原样执行上述相对路径命令，**不要 `cd`、不要改写为宿主猜测的绝对路径、不要先运行 `python -c` 测试权限**。

强图表自然表达包括但不限于：

- “把股价、成交量和 PE **放在一张图里**”；
- “把这些指标**画成一张图**”；
- “放到**同一个图里比较**”；
- “把价格和估值放一起对比，**做成图**”；
- “将多个指标**绘制成图表**”。

`route` 输出的 JSON 必须保留在本轮执行证据中。分类器失败是旁路错误，记录后继续 QBS，不得阻断首答；但禁止无命令调用记录就宣称已判定路由。

## 3. 四种 QBS 路由

| route | 条件 | QBS 动作 |
|---|---|---|
| `none` | 一次性查数、普通分析、弱“看看走势”、用户只要 PNG/本地图片 | 直接回答，不交接 |
| `suggest` | 有持续复用价值但结构不稳定；或页面依赖未经确认的高风险状态 | 直接回答并询问/建议，确认前不入队 |
| `create` | 明确 K 线/分时/收益净值回撤曲线/多资产对比/指标曲线/排名图/热力图/动态看板；明确可刷新、可交互、可分享、持续跟踪；或命中“低PE高ROE选股 TopN”这类已确认高频且结构稳定的因子榜单 | 正常回答，同时准备并启动 QBV Job |
| `existing_page` | 用户给出 `page_id`、活页链接或明确修改已有活页 | 正常回答，把页面引用交给 QBV；QBS 不判断归属 |


### 3.1 高频稳定榜单例外

`A股低PE高ROE选股Top20` 虽然没有出现“活页/图表”等产品词，但它是已确认的高频复用场景，页面 schema 稳定：TopN 表格、PE、ROE、综合比值、排序/筛选/刷新。因此确定性路由为 `create`，原因码为 `structured_factor_screening_ranking`。

边界：

- 仅对同时出现“低PE/低市盈率/低估值”与“高ROE/高净资产收益率/高盈利”，并明确“选股/筛选/排名 + TopN/前N”的表达生效。
- 普通一次性条件选股仍为 `none`；不能因为结果是列表就自动建页。
- 用户明确“只要表格/不要网页/不需要活页”时优先 `none`。
- QBS 必须先完成 TopN 文本答案和验证；QBV 只复用结构化结果生成增值页面。

## 4. 高风险持久状态

以下状态可用于本轮临时计算，但未经用户确认不得写入活页：

- 持仓、仓位、成本价、买入价、股数；
- 止损、止盈、加减仓、调仓条件；
- 自动交易、自动化规则和触发条件。

若页面依赖这些状态：

1. 路由改为 `suggest`；
2. `requires_persistence_confirmation=true`；
3. 用户明确确认后再以 `persistence_confirmed=true` 重新分类并准备 Job。

## 5. Handoff 合同

QBS 只能生成 `create` 或 `existing_page` Handoff：

```json
{
  "schema_version": "qbs_qbv_handoff_v1",
  "task_id": "同一用户任务 ID",
  "turn_id": "触发页面的当前 Turn ID",
  "source_skill_id": null,
  "source_skill_id_status": "unavailable",
  "source_skill_name": "quant-buddy-skill",
  "source_skill_version": "当前 QBS 版本",
  "user_query": "当前用户原话",
  "route": "create | existing_page",
  "route_reason": ["visualization_required"],
  "page_reference": null,
  "validated_outputs": [],
  "validation_receipts": [],
  "computation_capsule": {
    "schema_version": "qbs_computation_capsule_v1",
    "page_intent": {},
    "asset_resolution": {},
    "validated_contracts": [],
    "validated_outputs": [],
    "validated_insights": [],
    "validation_receipts": []
  },
  "requires_persistence_confirmation": false,
  "persistence_confirmed": false
}
```

硬约束：

- `source_skill_id` 有真实运行值时必须原样记录并设 `source_skill_id_status=available`；拿不到时写 `null` 与 `source_skill_id_status=unavailable`，同时记录 `source_skill_name/source_skill_version`。`source_skill_id` 缺失不得阻止 Handoff、Job 或子 Agent 委派，且禁止猜测任一历史 `skill_*`。
- `task_id` 与 QBS 当前 Session 相同；`turn_id` 必须是当前用户消息对应的不可变 Turn。
- `validated_outputs` / `validation_receipts` 保留旧 Handoff 兼容；新链路优先传 `computation_capsule`。胶囊不能只传 PNG/文件路径，必须同时给出结果快照、可复现合同、字段映射、fingerprint/hash、核心问题和主图意图。
- QBV 使用 `qbs_handoff_adapter.py` 判断覆盖度：`covered → skip`、`partial → delta_only`、`unusable → normal`。只跳过资产识别、同字段取数、同公式和已验证结论；Grant/Package 注册、页面运行时首次查询、页面构建、发布和公网验收不得跳过。
- Handoff 不得出现 `update_owned`、`copy_to_owned`、`direct`、`fork` 或 `unmatched`。


### 5.1 计算胶囊（优先）

真实用户示例：

> 帮我把长鑫科技最近一年的股价、成交量和 PE 变化放在一张图里，我想看看估值和价格是不是同步。

QBS 完成资产识别、行情/估值查询和本轮分析后，把**已经验证过的部分**写成胶囊：

```powershell
python scripts/qbv_computation_capsule.py build '@capsule-input.json'
```

最小输入结构：

```json
{
  "task_id": "当前 QBS task_id",
  "turn_id": "当前用户 Turn",
  "user_query": "用户原话",
  "page_intent": {
    "question_to_answer": "估值和价格是否同步",
    "recommended_page_type": "price_volume_valuation",
    "primary_visualization": "price_volume_pe_timeseries",
    "required_roles": ["main_series"]
  },
  "asset_resolution": {
    "query": "长鑫科技",
    "canonical_name": "长鑫科技",
    "canonical_id": "平台已验证的资产 ID",
    "market": "CN"
  },
  "validated_contracts": [{
    "role": "main_series",
    "kind": "fast_query",
    "contract": {"kind": "fast_query", "payload": {}}
  }],
  "validated_outputs": [{
    "role": "main_series",
    "artifact_file": "QBS 本轮结果 JSON/CSV 的绝对路径",
    "row_count": 0,
    "field_mapping": {"date": "trade_date", "price": "close", "pe": "pe_ttm"}
  }],
  "validated_insights": [],
  "validation_receipts": []
}
```

脚本自动补齐合同 fingerprint、artifact SHA256 并验证文件存在。把返回的 `computation_capsule` 原样放入 Handoff；task/turn/query 不一致、hash 被篡改时禁止宣称可复用。没有足够结构化产物时可以省略胶囊，让 QBV 无损走原流程，但不得用低质量胶囊强行跳过 QBS 验证。

## 6. 一命令准备已验证页面

QBS 已经得到排名、对比、回测、热力图或其它结构化结果 artifact 时，不再让 Agent 手工拼装 Capsule、Handoff 和 Job。把最小业务输入写入 `skill/output` 下的 UTF-8 JSON：

```json
{
  "task_id": "当前 task_id",
  "turn_id": "当前 turn_id",
  "user_query": "用户本轮原话",
  "route": "create",
  "source_skill_id": null,
  "source_skill_version": "当前 QBS 版本",
  "page_intent": {
    "question_to_answer": "页面要回答的核心问题",
    "recommended_page_type": "industry_return_ranking",
    "primary_visualization": "horizontal_ranked_bar_chart",
    "required_roles": ["industry_ranking"]
  },
  "asset_resolution": {"universe": "申万一级行业"},
  "validated_roles": [{
    "role": "industry_ranking",
    "kind": "formula_package",
    "contract": {
      "kind": "formula_package",
      "window_days": 20,
      "aggregation": "constituent_mean"
    },
    "artifact_file": "D:/.../skill/output/.../industry-ranking.json",
    "row_count": 31,
    "field_mapping": {"label": "industry", "value": "return_20d"},
    "validation_receipt_file": "D:/.../skill/output/.../validation-receipt.json"
  }],
  "validated_insights": []
}
```

然后只执行一次：

```powershell
python scripts/live_page_routing.py prepare-validated-page @output/_working/<task_id>/prepare-page.json
```

该命令负责：

1. 重新执行并核对确定性 route，禁止模型用输入字段强行覆盖分类结果；
2. 校验 task/turn/query、artifact、row_count、field_mapping 和 receipt lineage；
3. 自动生成 contract fingerprint、artifact SHA256 与 receipt SHA256；
4. 构造 `qbs_computation_capsule_v1` 和 `qbs_qbv_handoff_v1`；
5. 创建或复用幂等 `qbs_qbv_job_v1`；
6. 返回 `should_spawn/qbv_job_id/handoff_file/job_file/computation_coverage`。

`validation_receipt_file` 可包含单个 object、array，或 `{ "validation_receipts": [...] }`；若其中出现 `task_id/turn_id/user_query` 或 `lineage`，必须与当前 Turn 一致。`required_roles` 可以多于 `validated_roles`，用于明确让 QBV Adapter 返回 `partial` 并只补 `missing_roles`，不得伪造已覆盖 role。

若成功 Receipt 含 `runtime_contract.schema_version=qbs_formula_runtime_contract_v1`，`prepare-validated-page` 会把它原样规范化进 Capsule 的 `formula_runtime_contract`。调用方通常不需要重复填写；只有同一请求中存在多个不同公式合同、必须明确选择时才显式传入。显式值必须与 Receipt 完全一致，否则失败关闭。公式字面、顺序和输出名是执行合同，不得为 QBV 缩写、翻译、合并或重新推导。

**请求 JSON 防转义重试规则**：Receipt 已经保存原始公式时，`validated_roles` 不要再填写 `formula`，也不要在每个 role 重复 `validation_receipt_file`。优先顶层传一次 `"validation_receipts": ["<validation_receipt_file>"]`（也兼容内联 Receipt 对象），或省略后使用同任务 Receipt 自动发现；这样 `prepare-page.json` 只保留 `data_id/row_count/date/artifact/field_mapping/value_semantics` 等无须二次转义的最小字段。

**低 PE 高 ROE Top20 固定交接**：该场景必须把 QBS 已物化结果拆成六个 `validated_roles`：`ranking_top10`、`ranking_next10`、`pe_top10`、`pe_next10`、`roe_top10`、`roe_next10`，每个 `row_count=10`，并让 `required_roles` 使用同一集合。顶层只引用一次本轮 Validation Receipt；Receipt 中的精确公式合同必须包含 11 条 Top10/Next10 公式和六个 `last_day_stats` reads。QBV Adapter 命中后应返回 `coverage=covered`、`qbs_action=skip`、`formula_runtime_action=register_exact`，不得再次调用 QBS 重算。页面端合并两段、按 Score 降序得到 20 行；标题、分享标题和元数据统一使用“A股低PE高ROE选股 Top20”，不得继承模板中的单只股票名称。

**终止性规则**：`prepare-validated-page` 返回 `code=0` 后，Capsule、Handoff 和 Job 已全部生成。禁止再次执行 `qbv_computation_capsule.py build`、`handoff`、`prepare` 或第二次不同参数的页面准备；只消费返回的 `should_spawn` 和文件路径进行真实内部子 Agent 委派。

## 7. Job 与幂等

> 若当前 leaf 使用 `prepare-fast-query-page` 或 `prepare-validated-page`，该命令已经原子完成 capsule + Handoff + Job；成功后禁止再调用本节的 `handoff` 或 `prepare`。本节两步命令只用于没有结构化 validated roles 的兼容工作流。

先构造 Handoff，再准备本地持久 Job：

```powershell
python scripts/live_page_routing.py handoff '@handoff-input.json'
python scripts/live_page_routing.py prepare '{"handoff_file":"D:/.../handoff.json"}'
```

默认 Job registry 位于系统临时目录 `quant-buddy-qbv-jobs/`；可用 `QBS_QBV_JOB_DIR` 显式覆盖。幂等键固定为：

```text
task_id + turn_id + route + normalized_page_reference
```

`prepare` 返回：

- `should_spawn=true`：本次负责启动子 Agent；
- `should_spawn=false`：已有 queued/running/completed 或不可重试失败 Job，禁止重复建页；
- `qbv_job_id`、`handoff_file`、`job_file`：交给子 Agent 和审计。

Job 状态：`queued → running → completed | failed`。相同 Turn 的网络重试必须复用原 Job。仅 `failed + retryable=true` 且显式 `retry_failed=true` 时允许重试原 Job。

## 8. 子 Agent 委派模板

当 `should_spawn=true` 时：

1. 检查当前宿主实际提供的**内部子 Agent 委派工具**，优先使用 `spawn_agent`。兼容宿主若只提供 `sessions_spawn` 等同类内部工具，可以使用真实存在的工具，但不得把某个工具名写死为唯一实现。
2. **不得使用 `create_thread`、`fork_thread` 或其他用户可见的新任务能力代替子 Agent**；它们会改变用户任务边界，也不能证明会向原任务回推第二条消息。
3. 必须存在真实的子 Agent 工具调用记录；只在思考、提示词或最终回答里说“新开一个子 Agent”不算启动。
4. 子 Agent 的任务文本必须包含绝对 `handoff_file`、绝对 `job_file`、`qbv_job_id`，并明确要求读取和使用 `quant-buddy-view/SKILL.md`，执行完整 QBV SOP。推荐提示：

```text
你是本任务的 QBV 子 Agent。
必须读取并使用 quant-buddy-view/SKILL.md。
请消费 Handoff 文件 {handoff_file}，处理 QBV Job {qbv_job_id}（Job 文件 {job_file}）：
- 复用其中的 task_id 与 turn_id，不得新建用户 Turn；
- 运行 quant-buddy-view/scripts/trace_context.py beginHandoff；
- 自行决定 direct、fork 或 unmatched，并执行页面 ownership SOP；
- 本人页面原位更新；他人页面复制到本人名下后修改；归属未知禁止写入；
- 先运行 `quant-buddy-view/scripts/qbs_handoff_adapter.py evaluate`，同时传 `handoff_file + qbv_job_id + qbv_job_file`；Adapter 会自动把对应 Job 写为 `running`；`covered` 不重复相同 role，`partial` 只补 missing roles，`unusable` 回退原 QBS bridge；
- 完成上传、发布、公开访问、内容、实时数据与 Card Runtime 验收；
- 不要手改 Job JSON；若 Adapter 已返回 `marked_running/already_running`，无需再重复调用 QBS 脚本；真实 `target_skill_id` 由终态公开 URL 提取或由已验证参数提供，禁止猜测历史 skill ID；
- 完整执行必须包在异常兜底中：确定终止且没有成功终态时，调用 `qbs_handoff_adapter.py fail-job` 写回 `failed + failure_code`，禁止遗留永久 `running`；
- 只有同时取得真实 `target_page_id`、`public_url`、`published=true`、`public_verified=true`，并完成公开访问与 Card Runtime 验收后才算完成；`publish_verified` 会自动把匹配 Job 写回 `completed`，返回的 `qbv_job_lifecycle.updated=true` 或 `reason=already_completed` 才是闭环证据；
- 最终仅返回活页标题、公开链接、创建/更新说明和验收结果，失败则返回 failure_code 与简短原因。
```

5. 委派工具返回成功回执后，把 Job 更新为 `running`，记录实际 `delegation_tool/delegation_id`；为兼容旧宿主，也可额外记录 `spawn_run_id/child_session_key`。`target_skill_id` 仅在宿主或子 Agent 确知真实 QBV skill_id 时填写，禁止猜测。进入 `running` 时 Job 会记录 `started_at/expires_at`。
6. 获得委派成功回执后立即发送 QBS 第一条完整答案，不等待子 Agent完成。父 Agent不得重复执行已经委派给子 Agent的 QBV SOP。
7. Worker 的成功终态必须包含真实 `target_skill_id + target_page_id + public_url + published=true + public_verified=true`；缺任一项时 `update completed` 会被拒绝。
8. 父 Agent或真实编排宿主必须在 `expires_at` 后执行 watchdog：`python scripts/live_page_routing.py expire-stale --qbv-job-id "<qbv_job_id>"`。它会把仍为 `queued/running` 的 Job 写成可重试失败。Skill 仓库只提供确定性 watchdog，不伪装自己拥有生产后台调度器。
9. 子 Agent终态由父 Agent或宿主回调投递到同一用户、同一任务；成功补充公开链接，失败补充简短失败状态。

Worker 完成公网验收后的终态写回示例：

```powershell
python scripts/live_page_routing.py update '{"qbv_job_id":"<id>","status":"completed","target_skill_id":"<真实QBV skill_id>","target_page_id":"page_xxx","public_url":"https://pages.quantbuddy.cn/...","published":true,"public_verified":true}'
```

委派工具不存在或调用失败时，必须执行低自由度终态命令：

```powershell
python scripts/live_page_routing.py mark-delegation-unavailable --qbv-job-id "<qbv_job_id>"
```

它会把已准备的 Job 标记为 `failed + DELEGATION_UNAVAILABLE + retryable=true`。然后正常返回 QBS 业务答案。不得留下无终态的 `queued` Job，也不得对用户声称活页正在生成。

## 9. 第二条消息合同

- 成功：`活页标题 + 公开链接 + 已创建/已更新说明`。
- 失败：简短说明活页未完成，并明确前面的 QBS 分析结果仍有效。
- 不得把内部 Job JSON、临时路径、API Key、范式搜索过程或 ownership 查询细节发给用户。
- 页面公开链接只有经过 QBV 公网验收后才能发送；上传接口成功不等于完成。
