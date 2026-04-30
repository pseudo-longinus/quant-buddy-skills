# CHANGELOG — quant-buddy-skill

版本记录按**从新到旧**排列。详细 diff 见 `skill-changelog/iter-*.md` 及对应的 `*-post-diff.md`。

---

## [4.20.5] — 2026-04-30

**变更文件**：`SKILL.md`、`references/troubleshooting.md`、`workflows/run-formula-chain.md`

强化版本不匹配场景的自愈流程，堵住"Agent 改本地版本号字符串伪造一致"的欺骗式修复路径。

- `SKILL.md`：硬规则 #8 重写——区分两类版本不匹配信号：
  - (A) 本地 session ↔ 本地 SKILL.md 版本不一致（`SKILL_VERSION_MISMATCH`）：保留原 `newSession` + 重读 + 重跑流程；
  - (B) 服务端要求版本高于本地（响应文案提示 `npx skills update` / `skill 版本过低` 等）：默认 `npx skills update pseudo-longinus/quant-buddy-skills -y`；若 `update` 报 `not installed` 则回落到 `npx skills add pseudo-longinus/quant-buddy-skills -g --all`（`--all` = `--skill '*' --agent '*' -y`，CLI 内部展开，cmd/PowerShell/bash 都通用，规避 Windows cmd 把 `'*'` 当字面量传入而报 `Invalid agents: '*'` 的坑）；Windows 上 symlink/`EPERM` 报错时末尾追加 `--copy` 重试；用户拿不准装在哪可让其执行 `npx skills list -g --json` 自检。
  - 新增 **P0 红线**：禁止用 `replace_string_in_file` / `multi_replace_string_in_file` / 终端 `sed` / `echo >` 等任何方式，修改本地 `SKILL.md` / `config.json` / `scripts/*.py` / `CHANGELOG.md` 中的 `version` 字段，或改写 `.session.json` 的 `skill_version_at_creation`，企图蒙混版本校验——这种做法会让本地工具签名继续过时，后续调用必然继续失败，且服务端审计日志记录真实上报版本，伪造无效。
- `references/troubleshooting.md`：「版本不匹配」表格扩展为 7 行，覆盖「老用户更新 / 新用户首装回落 / Windows --copy / 不确定装在哪自检 / npx 命令失败」全部分支。
- `workflows/run-formula-chain.md`：失败处理表中新增服务端要求升级一行，明确指向硬规则 #8 (B)。

## [4.20.4] — 2026-04-30

**变更文件**：`tools/run_multi_formula.md`、`workflows/global-rules.md`、`workflows/quant-standard.md`、`workflows/run-formula-chain.md`、`recipes/tool-call-checklist.md`、`SKILL.md`

跟随服务端契约更新：`/skill/runMultiFormulaBatch` 的复用标记参数由布尔位对齐数组 `force_reusable_flags`（`boolean[]`，与 `formulas` 下标一一对应）改为变量名数组 `force_reusable_array`（`string[]`，写入需要保留/复用的公式左侧变量名）。

语义换算：
- 旧：`"force_reusable_flags": [false, false, false, true]`，`formulas = [MA5, MA20, Signal, TOP10]`
- 新：`"force_reusable_array": ["TOP10"]`（未列出的变量默认不复用；不传则全部复用）

服务端校验新规：
- 数组元素必须严格匹配 `formulas` 中某条公式的左侧变量名（前后空格自动忽略，大小写敏感）
- 不存在的变量名 → `code: -1`
- 当前 `formulas` 出现重复左值 → `code: -1`
- 多输出公式（如 `"净值, 持仓 = 回测(...)"`）任写一个变量名即可标记整条公式复用

> 三问法、跨批保活、被动拆批、`all-true = 规则退化` 等硬规则全部保留，仅把"`true`/`false` 标记"重新表述为"是否写入 `force_reusable_array`"。CHANGELOG 4.20.0 ~ 4.20.3 中保留了 `force_reusable_flags` 的历史描述以保持版本追溯一致。

---

## [4.20.3] — 2026-04-29

**变更文件**：`scripts/call.py`、`scripts/quant_api.py`、`SKILL.md`

修复多会话并行下 `output/.session.json` 被互相覆盖的问题。原实现把 SESSION 文件路径硬编码为单一固定路径，多个 chat 同时调用 `newSession` 时后者会覆盖前者，导致后续工具调用注入错误的 task_id（session 漂移）。`scan_dimensions.md` 第 114 行那条「扫描期间不要并发执行其他 API 调用」的限制就是这个 bug 的下游症状。

- `scripts/call.py`：新增 `_resolve_session_file()`，按优先级 `QBS_SESSION_FILE` 环境变量 → `QBS_SESSION_KEY` 派生 `.session.<key>.json` → 默认 `.session.json` 解析路径；KEY 经过 `re.sub(r"[^A-Za-z0-9_\-]", "_", key)[:64]` 清洗防止路径注入。
- `scripts/call.py`：`newSession` 调用前 best-effort 清理 `output/` 下超过 7 天未访问的 `.session.*.json`，避免长期累积垃圾文件。
- `scripts/quant_api.py`：同步引入 `_resolve_session_file()`，与 call.py 走同一套优先级。
- `SKILL.md` 硬规则 #1：新增「多会话隔离」子条款——多 chat / 共享开发机 / 并行 trace 场景下，必须在 chat 第一条 bash 命令 `export QBS_SESSION_KEY=$(python -c "import uuid;print(uuid.uuid4().hex[:12])")`，之后所有 `python scripts/call.py` 必须在同一 terminal 会话里执行。未设置时退化到默认 `.session.json`，向后兼容单会话场景。
- `SKILL.md` 目录树注释：`.session.json` → `.session.<key>.json`。
- `SKILL.md` / `metadata.version`：4.20.2 → 4.20.3

> 💡 **设计取舍**：保留默认 `.session.json` 而不是强制要求 KEY，是为了不破坏已有的单 chat 调用流程（包括平台 MCP 调用方）；只有在用户/测试台显式 `export QBS_SESSION_KEY` 时才启用隔离。Agent 端通过硬规则约束在多 chat 场景主动 export，达到「默认安全 + 显式并行」的平衡。

---

## [4.20.2] — 2026-04-29

**变更文件**：`SKILL.md`、`workflows/run-formula-chain.md`（新增）

修复一类真实场景失败：用户用 `/quant-buddy-skill 直接运行 ...md 文件里的全部公式，选出股票给我` 这种 prompt 时，Agent 会写 `python - <<'PY' ... subprocess.run(['python','scripts/call.py','runMultiFormulaBatch',...]) ... PY` 这种 inline heredoc + subprocess 多批循环驱动脚本，连锁触发 task_id 漂移、stdout 阻塞、`/tmp/gzq_out.txt` 在 Windows 不存在等问题。trace 见 `1777454879452.json`。

- `SKILL.md` 硬规则 #2：明文禁止以下"自写 driver 脚本"反模式（无论批次多少、依赖多复杂）：
  - `python - <<'PY' ... subprocess.run(['python','scripts/call.py',...]) ... PY`
  - `python -c "import subprocess; subprocess.run(['python','scripts/call.py',...])"`
  - `node -e "...child_process.execSync('python scripts/call.py ...')..."`
  - 任何在 inline 脚本里 `for/while` 循环驱动多批 `runMultiFormulaBatch` 的写法
- `SKILL.md` 硬规则 #2：补充多批 `runMultiFormulaBatch` 的合规模板——切批与编排必须由 LLM 自己在工具调用之间完成，参数预处理在推理中完成，中间产物用 `create_file` 落盘到 `output/tmp_batches/batch_K.json`，每批一条独立 shell：`GZQ_PARAMS="$(cat output/tmp_batches/batch_K.json)" python scripts/call.py runMultiFormulaBatch`
- `SKILL.md` 场景路由表新增条目：「直接运行用户给定的公式链文件」→ `global-rules.md` → `run-formula-chain.md`
- 新增 `workflows/run-formula-chain.md` leaf workflow：明确 6 步合规路径（读文件 → LLM 推理解析公式 → LLM 推理生成 force_reusable_flags → create_file 切批落盘 → 逐批独立 shell 调用 → readData 取最终输出），并在文档顶部列出违规反例。
- `SKILL.md` / `metadata.version`：4.20.1 → 4.20.2

> 💡 **设计取舍**：之所以坚持"每批一条独立 shell"而不让 Agent 写一次性 driver 脚本，是因为这条 hard rule 同时保障了 (a) call.py 的 session 注入只发生一层；(b) LLM 能看到每批返回再决定下一批；(c) 错误定位能落到具体批次；(d) token 用量可控。

---

## [4.20.1] — 2026-04-29

**变更文件**：全仓（`SKILL.md`、`workflows/*.md`、`tools/*.md`、`recipes/*.md`、`references/troubleshooting.md`、`scripts/executor.py`、`scripts/call.py`、`scripts/quant_api.py` 等）

将 LLM 可见的工具名 `runMultiFormula` 全量重命名为 `runMultiFormulaBatch`，与新端点路径同名，避免 LLM 受历史训练记忆影响仍调用旧名。

- `scripts/executor.py`：`TOOL_ROUTES` key 由 `"runMultiFormula"` → `"runMultiFormulaBatch"`；line 681 的 `tool_name == "runMultiFormulaBatch"` 同步
- `scripts/call.py`：line 460-461 的 formulas 字符串数组校验分支 `tool_name == "runMultiFormulaBatch"` 同步
- `scripts/quant_api.py`：line 280 `self._call("runMultiFormulaBatch", params)` 同步
- 所有 workflow / tool 文档 / recipe CLI 示例（`python scripts/call.py runMultiFormulaBatch '{...}'`）一并更名
- 注：`tools/run_multi_formula.md` 文件名按 snake_case 约定保留，未改名为 `run_multi_formula_batch.md`

> ⚠️ 4.20.0 条目里"工具名对 LLM 不变"的说法**已作废**——4.20.1 起工具名亦统一为 `runMultiFormulaBatch`。参数/返回结构仍与旧端点完全一致。

---

## [4.20.0] — 2026-04-29

**变更文件**：`scripts/executor.py`、`tools/run_multi_formula.md`、`SKILL.md`

切换公式执行后端到 `/skill/runMultiFormulaBatch`：

- `scripts/executor.py`：`TOOL_ROUTES` 中 `runMultiFormula` 的 HTTP 路径由 `/skill/runMultiFormula` → `/skill/runMultiFormulaBatch`（工具名对 LLM 不变；参数/返回结构与旧端点完全一致）
- `tools/run_multi_formula.md`：
  - 端点行同步 `/skill/runMultiFormulaBatch`
  - 顶部新增"后端切换说明"段：解释新端点底层用 `task.process.batch_evaluate`，公式间共享 Worker 内存，整批超时 10 分钟；服务端对单次公式数有 20 条硬上限，超出即 `code=-1` 不扣费
  - 单次公式数限制表更新为"所有 tier 后端原始上限均为 20"，硬规则文案同步说明这是服务端强制
- `SKILL.md`：版本升级 4.19.0 → 4.20.0

> 💡 **效果预期**：对依赖链密集的批次（如评分链、回测链），由于公式间在同一 Worker 内存中传递，相比旧端点的 N 次独立 fire-and-forget 应有更稳定的耗时和更低的跨任务超时风险（参考 r2 测试中 21-83 一次提交超时、同批次重跑 8s→43s 等问题）。

---

## [4.19.0] — 2026-04-29

**变更文件**：`tools/run_multi_formula.md`、`workflows/global-rules.md`、`workflows/quant-standard.md`、`SKILL.md`

依据 `datasets/test/force_reusable_flags-参数标注测试/{场景1,场景2}/r2/eval_report.md` 的诊断改进：

- **统一 20 条保守上限**（与服务端确认）：所有 tier（free/plus/pro/ultra）单次 `runMultiFormula` 一律按 20 条切批，不再按 tier 动态调整
  - `tools/run_multi_formula.md`：tier 上限表新增"实际必须遵守"列，全部 20，并加硬规则警告
  - `workflows/global-rules.md`：tier 感知段同步说明
- **强化 `force_reusable_flags` 跨调用保活语义**（`global-rules.md §13`）：
  - 把"一问"改为"三问"：是否被 `readData` / 是否被后续 batch / 是否被用户后续追问引用
  - 明确"末批最终评分变量（如 `*_Score`）即使语义像中间量也必须 `true`"——P0 防错
  - 新增"缓存兜底 ≠ flag 标对"提示，避免误判
  - 重申禁止为"保险"一律 all-true
- **新增"未来未知场景"修正语义**（`quant-standard.md`）：首批可保守标 `false`；后续轮次回引到首批早期变量时**必须先调修正接口**再继续；接口缺失时不得默默兜底
- `SKILL.md`：版本升级 4.18.0 → 4.19.0

---

## [4.18.0] — 2026-04-29

**变更文件**：`scripts/call.py`、`workflows/global-rules.md`、`workflows/quant-standard.md`、`SKILL.md`

- `scripts/call.py`：`_run_executor()` 的子进程超时阈值从 300s 调整到 900s；新增 `subprocess.TimeoutExpired` 捕获，超时时返回稳定错误码与明确提示，避免异常上抛导致调用链中断
- `workflows/global-rules.md`：补充 `runMultiFormula` 多批次场景规则，明确跨批引用变量必须保活（`true`），并将 all-true 标记为规则退化信号
- `workflows/quant-standard.md`：补充 `force_reusable_flags` 的单批/多批判定对照与分批切点原则，统一为通用依赖分析表述，移除特定案例命名
- `SKILL.md`：版本号升级至 `4.18.0`

---

## [4.17.0] — 2026-04-29

**变更文件**：`SKILL.md`、`scripts/call.py`、`scripts/quant_api.py`

- `SKILL.md`：硬规则从 7 条扩为 8 条；新增第 8 条"版本不匹配自愈"——工具返回 `SKILL_VERSION_MISMATCH` 时，LLM 须立即停止、newSession、强制重读 SKILL.md + workflow + 相关 tools/*.md、重新执行，禁止询问用户；版本号升至 4.17.0
- `scripts/call.py`：新增模块级 `_read_skill_version()`；`_write_session()` 写入 `skill_version_at_creation`；非 newSession 工具调用前添加版本守卫（不匹配则打印 `SKILL_VERSION_MISMATCH` 并退出）；`newSession` 响应新增 `skill_version`、`version_changed_from_last_session`、`previous_skill_version` 字段
- `scripts/quant_api.py`：同步上述改动；新增模块级 `_read_skill_version()`；`_write_session()` 写入 `skill_version_at_creation`；`_call()` 加版本守卫（版本不匹配时抛 `RuntimeError`）；`newSession` 分支响应扩展三个新字段

---

## [4.16.0] — 2026-04-29

**变更文件**：`SKILL.md`、`scripts/call.py`、`scripts/quant_api.py`

- `SKILL.md`：新增"版本自检"硬规则——收到 `SKILL_VERSION_MISMATCH` 错误时，自动 newSession + 强制重读 SKILL.md 及当前 workflow 后重试
- `scripts/call.py`：`newSession` 分支写入 `skill_version_at_creation` 字段到 `.session.json`；非 newSession 工具调用前置版本守卫，版本不一致时返回 `SKILL_VERSION_MISMATCH`
- `scripts/quant_api.py`：同等版本守卫逻辑；`newSession` 响应扩展 `version_changed_from_last_session` 与 `previous_skill_version` 字段

---

## [4.15.1] — 2026-04-（内部补丁，无 iter 记录）

---

## [4.14.0] — 2026-04-22 _(iter-014)_

**变更文件**：`SKILL.md`、`workflows/fast-snapshot.md`、`workflows/fast-window.md`、`workflows/global-rules-lite.md`、`recipes/tool-call-checklist.md`、`workflows/quick-report-period.md`

- `SKILL.md`：新增盘中/实时 TopN 与阈值筛选路由条目；第 5 条硬规则"最终答案首句必须是数据结论"
- `workflows/fast-snapshot.md` / `fast-window.md`：结果合同写死停止条件与输出模板
- `workflows/global-rules-lite.md`：去掉强制 RU/quota 外露，与去过程化方向统一
- `recipes/tool-call-checklist.md`：新增 `runMultiFormula` 调用前财务查询严禁 `use_minute_data: true` 检查项
- `workflows/quick-report-period.md`：财务查询严禁 `use_minute_data: true` 声明

---

## [4.10.0] — 2026-04-15 _(iter-013)_

**变更文件**：`workflows/event-study.md`、`workflows/quant-standard.md`、`workflows/render-kline.md`、`workflows/industry-aggregation.md`、`workflows/global-rules.md`

- `workflows/event-study.md`：阈值筛选必须在公式层生成布尔掩码（禁止取回完整序列后人工扫描）；新增反例说明（`last_column_full` 序列截断导致遗漏事件）
- `workflows/quant-standard.md`：变量名循环依赖禁止规则 + 正反例说明（`=` 左侧不得与右侧引用的数据集名相同）
- `workflows/render-kline.md`：`show_volume` 必须显式传参
- 回滚了 `quant-standard.md` / `read_data.md` / `cases_index.yaml` 中引发一致性下降的改动，仅保留已验证有效的 29 行规则

---

## [4.9.1] — 2026-04-14 _(iter-012)_

**变更文件**：`SKILL.md`、`workflows/event-study.md`、`workflows/global-rules.md`

- `SKILL.md`：第 5 条硬规则（最终答案首句数据结论）早期版本
- `workflows/event-study.md`：accepted candidate 最低证据字段要求（`label_evidence_quote` 等不得为空）；锚点一致性校验规则；写后必读（`write_skill_file` 后必须 `read_skill_file` 回读校验）
- `workflows/global-rules.md`：`evidence-only` 规则；去过程化文本级硬禁令（"已成功获取""让我来"等过程话术一律禁止出现在最终答案中）

---

## [4.8.1] — 2026-04-13 _(iter-011)_

**变更文件**：`SKILL.md`、`workflows/event-study.md`

- `SKILL.md`：新增"盘中/实时全市场 TopN 排名"路由条目，强制进入 `quant-standard.md` 专用微流程
- `workflows/event-study.md`：事件日期获取优先级硬规则（用户已给出明确时间锚点时，禁止先 webSearch）；`event_candidates.json` 新增 `subject_evidence_quote` / `policy_evidence_quote` / `evidence_consistency_check` 字段；新增 Step 1.8 强制生成 `event_selection.json`；`buildEventStudy.dates` 只能来自 `event_selection.accepted_dates`

---

## [4.7.1] — 2026-04-10 _(iter-010)_

**变更文件**：`SKILL.md`、`workflows/event-study.md`、`workflows/quick-snapshot.md`、`workflows/quick-window.md`、`workflows/quick-report-period.md`、`workflows/period-return-compare.md`、`workflows/render-kline.md`、`workflows/event-study.md`、`workflows/quant-standard.md`、`workflows/regime-segmentation.md`

- `SKILL.md`：新增 `period-return-compare.md` 路由条目；leaf workflow 最终回答合同优先级说明
- `workflows/event-study.md`：事件锚点优先级硬规则（公告日首选）；`event_candidates.json` 所需字段全部列出（含 `anchor_basis`、`label_confidence` 等 20+ 字段）；完成候选表后必须持久化为 `event_candidates.json`
- 10 个文件全文本规则强化（evidence-only 场景门禁、量化排名结果表证据门禁、资产歧义确认最小化模板等）

---

## [4.6.0] — 2026-04-09 _(iter-009)_

**变更文件**：`SKILL.md`、`workflows/event-study.md`、`workflows/regime-segmentation.md`、`workflows/period-return-compare.md`（新增）、`scripts/executor.py`

- `SKILL.md`：新增 `period-return-compare.md`、`regime-segmentation.md` 路由条目；路由判断口诀更新；leaf 不再声明"自包含"，改为"必读 global-rules.md 为全局合同基底"
- `workflows/event-study.md`：阈值触发模式执行步骤（可量化阈值 vs 不可量化阈值分支）
- `workflows/period-return-compare.md`：新建，专门处理固定区间累计涨跌幅对比
- `scripts/executor.py`：公式中双重转义引号防御性修复（`\"` → `"` 防 HTTP 500）

---

## [4.5.0] — 2026-04-08 _(iter-008)_

**变更文件**：`SKILL.md`、`workflows/event-study.md`、`workflows/global-rules.md`

- `SKILL.md`：路由硬排除表（固定区间/行业聚合/阈值触发强制改道）；文档层级说明（SKILL.md > global-rules.md > leaf workflow）；`quick-lookup.md` 定位重新声明（仅作路由入口和规则参考，leaf 执行时无需回读）
- `workflows/event-study.md`：完整 Checkpoint 协议（E0–E5）；Abstract Target 定义
- `workflows/global-rules.md`：leaf 必须先读 global-rules.md 的强制要求

---

## [4.4.0] — 2026-04-07 _(iter-007)_

**变更文件**：`SKILL.md`、`workflows/global-rules.md`

- `SKILL.md`：硬规则重写——原生工具优先（禁止用 `run_skill_script`/shell 命令/`GZQ_PARAMS=...` 包装原生工具）；事件研究前置证据门禁（三选一条件，均不满足则停止计算）；配置/认证错误立即停止规则
- `workflows/global-rules.md`：原生工具优先规则独立章节；`scripts/call.py` 允许用途限定为 3 类（newSession / workflow 指定脚本步骤 / 无原生等价能力时兜底）

---

## [4.2.0] — 2026-04-01 _(iter-006)_

**变更文件**：`SKILL.md`（及多个 workflow 文件，详见 `skill-changelog/iter-006-post-diff.md`）

- `SKILL.md`：全局最终交付硬规则（leaf 满足停止条件后，必须当轮立即输出最终答案，禁止继续读文档/追加分析）
- K线路由入口独立为 `workflows/render-kline.md`，路由表更新

---

## [4.1.0] — 2026-03-31 _(iter-005)_

**变更文件**：`SKILL.md`、`workflows/quick-snapshot.md`（及其他 workflow，详见 `skill-changelog/iter-005-post-diff.md`）

- `SKILL.md`：新增 `render-kline.md` 路由条目；证据分级中 `description` 最后值受控文本抽取的例外条款精确化
- `workflows/quick-snapshot.md`：受控文本抽取条件（仅 quick-snapshot 场景且满足 4 个前置条件时允许）

---

## [4.0.0] — 2026-03-30 _(iter-004)_

**变更文件**：`SKILL.md`

- 路由表重构：K线入口改为 `render-kline.md`；新增第 3 条路由（用户明确要画图时直接加载 `render-kline.md`）
- 版本号升至 4.x（major 重构）

---

## [3.5.0] — 2026-03-27 _(iter-003)_

**变更文件**：`SKILL.md`

- leaf workflow 自包含声明（读完 leaf workflow 即可直接执行，不需要回到 `quick-lookup.md`）
- 全局证据分级章节新增（A 级证据 / B 级证据 / 受控文本抽取例外规则）

---

## [3.3.0] — 2026-03-27 _(iter-002)_

**变更文件**：`SKILL.md`、`workflows/quick-lookup.md`（及 `quick-snapshot.md`、`quick-window.md`、`quick-report-period.md`）

- `SKILL.md` description 重写——面向用户可读（"查询A股收盘价…"），去掉内部实现描述
- 路由从单一 `quick-lookup.md` 拆分为三个 leaf workflow（snapshot / window / report-period）
- 禁止以"无法联网"或"无法获取实时数据"拒绝查数请求

---

## [3.2.0] — 2026-03-27 _(iter-001 post)_

**变更文件**：`SKILL.md`

- 路由描述从"优先走 quick-lookup.md"改为"按时间锚点分流到三个 leaf workflow"
- 目录树新增 `quick-snapshot.md` 条目

---

## [3.1.0] — 2026-03-26 _(iter-001)_

**变更文件**：`SKILL.md`、`workflows/quick-lookup.md`

- `SKILL.md`：新增高优先级路由规则区块（简单查数任务必须走 `quick-lookup.md`，禁止先调 `scanDimensions`/`renderKLine`）
- `SKILL.md` description：首行增加"简单查数任务优先走 quick-lookup.md"
- `workflows/quick-lookup.md`：扩展为快查强制路由 + 基础规则模板（169 行 → 499 行）

---

## [3.0.0] — 2026-03-26（初始版本）

- 首次发布，基础路由框架，支持选股 / 回测 / 因子 / 图表 / 小红书图文生成
