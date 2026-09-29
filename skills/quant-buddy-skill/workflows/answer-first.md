# 先交业务答案，再同轮继续活页

适用：量化查询/分析且已有活页意图，包括每日/定期复盘、监控、画线/画图、执行回测、看 K 线等操作请求；不要求出现“网页”字样。概念解释不属于操作请求。普通一次性查数继续只回答；已有文件静态托管、页面只读解读、纯样式维护不套用本流程。

图表首答也遵守日期和口径要求：“图已生成”加图片不是完整交付。说明日/分钟周期、指标定义和实际数据日期；渲染接口未返回的日期、单位或复权口径应补核验，或明确标为未核验，不得从请求日期、点数或图片生成时间推断。

原页新增均线/指标或修改计算窗口仍属于计算任务：QBS 补算后先回复新增结果、日期和口径，再同轮交给 QBV 原位更新。仅样式、标题、布局或已有序列显隐属于纯展示维护；不能用该例外跳过新增指标的业务首答。

## 顺序

本地交付链接：原生渲染直接使用工具返回的 `artifact_markdown`。自行生成 HTML/SVG 时，使用 `write_skill_file` 返回的 path；若为 `output/...` 相对路径，前缀取 route CLI 返回的 `artifact_base_dir`，组成绝对文件链接。不能把相对链接、未生成路径或另一 Skill 的工作目录当作可打开附件。

1. 保留原始 user_query，按现有 route 分类。本轮操作意图已由上下文明确但原话省略对象或页面词时，传 `--page-requested`；更新原页同时传 `--page-reference`，不要改写原始 user_query（JSON 为 `page_requested:true`）；仅安装了 QBV 不构成建页意图。“不要网页/暂不发布/只要本地图片”仍优先；“只要表格/不要画图”不覆盖明确或场景隐含的活页意图。普通行业 TopN 不自动建页。
2. 完成 QBS 查询、计算、日期/口径/完整性校验。已有上游 task/turn 时继承，不新建第二条任务链。宿主管理生命周期时，newSession/beginTurn 自动采用宿主身份，不重复登记会话；prepare 同样校验身份。直接使用返回的 task_id/turn_id，不读环境、不手改收据或创建第二个 Job 来纠正编号。
3. **下一条用户可见消息先发完整业务答案**：结果、实际日期、单位、统计口径与限制。使用宿主允许继续工具调用的非终止消息。不能只发“正在查询/生成”，不能先结束本轮再假设后台继续；此时不承诺“已后台启动”。
   个股综合分析沿 `stock-profile.md` 的完整六章合同，不因“先答/快速通道”降为少量指标摘要；用户明确要求简短或限定字段时才按请求缩减。
4. 首答发出后再准备胶囊、Handoff、Job，执行模板查询、包注册、页面构建与验收。优先 `prepare-validated-page @params.json`；返回 `should_continue=true` 时，当前 Agent 读取 QBV Skill，调用 `beginHandoff` 与 adapter，继续完整 SOP，不再重复业务计算。
5. 默认 `execution_mode:"same_turn"`。确有可靠的内部委派及回推能力时，可在首次 prepare 指定 `execution_mode:"delegated"`；只消费 `should_spawn=true` 的一次真实委派。不得使用用户可见的新聊天工具代替；委派成功后父流程不得重复建页。
6. 两个执行标志都为 false 表示已存在任务，读取现有状态，不重复创建/换执行模式。已明确失败且可重试时通过 `retry_failed:true` 重试，沿用原执行模式。
7. 同轮流程结束前必须得到已验收的页面链接或写回 `failed + failure_code`，失败补充简短说明，不撤销首答。成功按 QBV 的最终回复合同补链接。

`prepare` 的 `code=0` 只表示交接材料已生成。按返回的 `next_action` 继续；`page_delivery_ready=false` 时不得声称“图已生成/活页已完成”。如宿主只暴露 QBS、读取 QBV 被拒绝或明确未安装，立即调用本 Skill：`python scripts/live_page_routing.py update @failure.json`，文件内容为返回的 `qbv_job_id` 与 `on_unavailable` 字段合并。不反复猜 sibling 路径、不绕过宿主权限、不把 Job 留在 queued。若已进入 QBV，开始时写 running，结束时按真实验收写 completed 或 failed。

如果宿主只展示最终答案、无法证明中途消息已可见，正常完成用户任务，但将首答可见性记为未验证，不声称实现了后台或提前送达。不要为了探测能力调用不存在的发消息工具。真实模型测试以宿主观察到的消息/工具事件为准。

## 答案结构（可选，轻量）

裸 A 股固定快页使用 `live-page-routing.md` 的 `single_a_stock_fast` 入口：QBV standalone 复用同一 task/turn，bridge 验证首答后 `new_asset_page`。此窄入口不要求额外通用 Handoff/Job，也不改变首答先于建页及成功验收后才发链接的顺序。

首答和结构使用同一份已验证结果，不增加一次模型调用做页面规划。`prepare-validated-page` 和胶囊 build 都接受 `answer_structure`：

```json
{
  "schema_version": "qbs_answer_structure_v1",
  "blocks": [{
    "id": "leaders", "type": "ranking", "title": "涨幅前五",
    "role_refs": ["industry_return"], "insight_refs": [],
    "as_of": "2026-09-28 10:12", "unit": "%", "methodology": "成分股等权日收益",
    "update_mode": "dynamic", "rank_order": "desc", "rank_limit": 5
  }]
}
```

- 类型为 `summary/metric/ranking/comparison/timeseries/table/note`；数组顺序就是首答逻辑顺序。
- role_refs 引用本轮 validated_outputs.role，insight_refs 引用 validated_insights.id；说明/摘要必须引用已验证解释，不在结构里再次编写结论。
- update_mode 为 dynamic/fixed/historical。日期、单位、口径未知时如实写“未核验/不适用”，不能编造；历史观察必须具有实际观察日期。
- 排名保留全量数据引用，不裁剪成前后十行；数值缩放由已验证字段单位决定，不能为了画后五把数值取反。
- 多 data_ids 展开后的 role_refs 使用返回的实际角色名，不手改数据 ID。
- 旧胶囊不含结构仍可用；结构损坏会返回 invalid 和原因并丢弃该可选结构，数据与公式合同继续沿原 SOP 验证。禁止为修结构重算已验证结果。
- 新建 `validated_roles` 按首答顺序排列，并带实际 `date/unit/description`。省略结构时，准备器按这些字段生成保守的有序数据表，标记 `answer_structure_source=validated_role_order`；未知元数据标未核验，不猜图形、TopN 或文字结论。要保留前五/后五、摘要/图表等完整首答结构，应显式传上面的 blocks。旧胶囊读取不自动补结构，损坏结构不自动修补。

## 分钟边界

行情截面“最新”按最新可得行情处理；依据市场/交易日历和数据证据判定盘中或最近收盘。明确盘中使用受支持的 `use_minute_data:true`，历史/收盘/财务不误开启。行业日涨跌的当前截面不是最近一分钟收益。实际日期早于预期时先如实披露，不用 description 的“应更新到”替代 readData 日期，也不额外调用 refreshSnapshotTime 代替模式选择。

分钟公式的 Receipt 和 formula_runtime_contract 原样交接。当前公式包注册服务不支持该模式，QBV 返回 `MINUTE_PACKAGE_UNSUPPORTED` 时，不删除 true 或改称日频来绕过。只有同口径且已验证的受支持运行时才可替代；否则遵循原发布降级门禁或明确页面未完成。

Receipt 的 `execution_contract` 总是保存可验证的实际公式执行参数；`runtime_contract` 只在读取语义已安全确认时存在。Top50 等无安全 reads 的执行证据仍随胶囊 `formula_execution_contracts` 交接，但不能凭此自动注册包，也不能把其分钟模式当成日频。

## 顺序证据

`python scripts/answer_first.py @events.json` 可核对宿主已记录的有序事件。输入 `answer_text` 为已人工/数据验证的完整首答原文；`events` 使用 `{type:"assistant_message",text,channel:"commentary"|"intermediate"|"final"}` 和 `{type:"tool_call",name,arguments}`。此脚本不发送消息，也不判断答案数值正确性。事件必须从真实宿主记录转换，不得由 Agent 自报“已经发送”；没有消息或后续工具证据时返回 unverified，不算通过。
