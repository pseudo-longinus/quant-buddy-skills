# 根据首答结构生成活页

量化查询型建页先通过 QBS 查询和验证，发送包含结果、日期和口径的完整非终止业务回复，再进入模板搜索、注册、构建和发布。默认同轮继续，不以宿主有后台能力为前提。已有文件静态托管、只读解读和纯展示维护沿原入口。若宿主只展示最终消息，继续完成任务但不宣称首答已提前可见。

直接进入 QBV 的建页任务：先建立 trace context，用 qbs_bridge 执行 QBS 查询；此阶段不要创建进度页。取得有效答案后先回复，再继续本 Skill 默认路由。上下游复用同一 task_id/turn_id。已有真实 QBS Handoff 则 beginHandoff，不重复 begin/beginTurn。

**量化先答建页的链接优先规则**：所有渠道均在页面验收成功及适用回复校验通过后才发送页面链接。首答及后续进度消息不带模板、草稿或进度页 URL；templates/new_page 返回的 URL 仅供内部继续执行。此规则覆盖下游文档或工具 hint 中“立即发首链”“下一次工具调用前发模板链接”“模板命中到首链五秒”的旧要求，不通过修改渠道或伪造送达记录实现。内部仍按原 direct/fork/unmatched、同页更新和发布门禁执行。已有文件托管不适用此例外，继续真实首链交付及 file_confirm_delivery。

## 首答最短调用路径

- 简单个股：写一份 `{"task_id":"本轮ID","user_query":"原话","asset":"用户资产","required_roles":{"snapshot":["close","pct_chg","pe_ttm","pb"]}}`，运行 `python scripts/qbs_bridge.py resolve_asset_data @params.json`。直接消费返回的 `answer_evidence`（多资产位于各 `asset_results[]`），保留字段自身日期与单位；不要为读取收据去重复 fast_query。按实际字段和日期回答；用户还要求财务/画像时仅补所需角色。业务回复后才调用 `new_asset_page`，不能用页面生成后的草稿冒充提前首答。
- 多资产：同一参数文件使用 `assets:[...]`，不能把多个资产或行业集合塞进单个 asset。
- 行业全截面挑模板时，先检查候选是否支持多行业排名。个股模板只借布局时选择 `compose`，不选 `inherit/inherit_augment` 后才改路；无合适范式则按真实能力缺口选择 `unmatched`。`INDUSTRY_UNIVERSE_TEMPLATE_MISMATCH` 在建页前返回，修正路由后仍需遵守原有授权、数据绑定与发布门禁。
- 申万一级行业全截面不是一只资产。不要向 `resolve_asset_data` 传“申万一级行业指数”。通过 bridge 的 `runMultiFormulaBatchStream` 执行 `行业近N日涨跌幅=成分平均汇总(涨跌幅("全市场每日收盘价",N),"申万资产所属指数")`，用 `readData` 的 `last_column_full` 验证全部行业，再按原值排序给前后榜。当前盘中截面使用 `use_minute_data:true`，N=1 表示日涨跌幅，不是最近一分钟收益。历史区间保持日频。说明成分股算术平均口径，不称为行业指数涨幅。
- 公式 bridge 调用沿用同一 task_id，参数通过 UTF-8 JSON 文件；具体调用名与 QBS 相同：`python scripts/qbs_bridge.py runMultiFormulaBatchStream @params.json`、`python scripts/qbs_bridge.py readData @read.json`。不先为找数据而调用模板。

完整业务答案要和后续页面工具调用位于同一持续执行流程。宿主只能记录最终消息时，首答提前可见列为未验证，不靠文本自述计为通过。使用工具返回的绝对文件路径，不猜下载产物文件名；一个结构化 CLI 错误后查对应工具合同修正，不连续猜参数消耗轮数。

## 消费结构

同时消费 adapter 返回的 page_intent：answer_structure 决定首答内容顺序，page_intent.requirements 决定复盘、监控、画线或回测的必要能力。两者共同约束模板维度检查；不能有数据表就声称完成 K 线、画线或回测图。presentation=table_only 时不生成图，但保留活页交付。缺少已请求能力时沿原规则补齐或明确失败，不在接收 Handoff 后重新把执行型请求降为一次性问答。

已有 page_reference 的追问交给原页更新/归属检查，不为“加均线、改窗口、每天复盘”重复新建。回测区间、策略参数与成本从验证合同继承，历史结果注明截止日；监控刷新不冒充后台通知或自动交易。未验证的持久画线、定时运行等能力不能仅靠页面文案宣称支持。

**计算更新不属于纯展示维护**：在原页新增均线/指标，修改计算窗口或回测参数时，先通过 QBS 补算缺失部分，回复新增结果、实际日期和口径，再执行 chart_edit/原位更新与发布验收；不能把“准备加一条线”当作业务首答，也不能等 chart_edit 已发布后才首次给出计算结果。仅改颜色、标题、布局或显示已有序列，才沿纯展示维护例外。

`qbs_handoff_adapter.py evaluate` 返回 `answer_structure_status`、`answer_layout`。valid 时以其中顺序及 role_refs/insight_refs 组织页面；absent/invalid 时沿现有 SOP，invalid 同时保留诊断。此返回是语义布局计划，不是可直接发布的 spec，不能用它绕过运行时绑定与质量门禁。

| 内容类型 | 建议面板 |
|---|---|
| summary / note | text，引用已验证说明 |
| metric | number |
| ranking | bar，保留 rank_order/rank_limit 与原数值符号 |
| comparison / table | table |
| timeseries | line |

把 role_refs 解析为 adapter 已验证的 reusable_outputs/reusable_contracts，再绑定当前页面的 output 或 grant。多字段时保持真实单位和缩放，可拆分面板；不要把任意 role 名直接当数据输出名。

covered 不重复取数或重算相同 role；partial 仅补缺失部分。完整行业表和前后榜共用完整截面。结构不是新事实来源，不从回复原文推导缺失公式或数据。

dynamic 的图表、数字与正文必须消费同一轮运行数据；dynamic 摘要需要现有受支持的数据驱动正文绑定，否则作为注明原日期的 historical 观察展示，不伪装实时分析。fixed 只用于稳定的方法解释。允许合并或折叠内容，不改变口径或漏掉核心答案。

模板只有覆盖全部请求维度和答案核心模块才能 direct；否则沿 fork/Compose/自建规则。原页身份、权限、合同哈希、公开数据与移动端、适用 Card Runtime 检查继续执行。完成后按既有终态回复合同补链接；失败调用 fail-job（有匹配 Job 时）并补简短失败说明，保留首答。

## 分钟合同

adapter 遇到分钟执行合同会返回 `formula_runtime_action:unsupported_minute_package` 和 `runtime_warning:MINUTE_PACKAGE_UNSUPPORTED`；已物化结果仍可复用，但不能作为日频包重新登记。

bridge 的验证执行与收据保留 use_minute_data；`registration_params` 也保留，注册器在鉴权/网络之前拒绝当前未支持的分钟包。日频 false/缺省保持旧指纹，true 使用不同合同。不得删除该字段、换用旧收据或跳过指纹比较。

无安全读取模式的公式也有 Receipt `execution_contract` 和胶囊 `formula_execution_contracts`。它们只证明原始执行，不证明可以注册包；adapter 同样会识别其中的分钟限制。未提供 reads 时，不能擅自用只返回十项的 `last_day_stats` 代替全截面。

只有已验证同口径的受支持运行时可替代；否则按原静态降级规则或明确未完成，不修改服务端、不新增任意放行开关。`is_live=true`、定时请求、仅有验证成功都不代表页面分钟更新已实现。

模板来源返回 SOURCE_CREDENTIAL_UNPAIRED 等合同失败时，不换 source_template_id 或重建任务绕过绑定。不满足同一来源 Compose 门禁即记录明确失败；若已有进度页，按 static_page 的 update_progress 标记失败，不把 running 链接当最终交付。
