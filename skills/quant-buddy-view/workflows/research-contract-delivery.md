# 有界恢复与研究状态

从 QBS Handoff 或执行计划继承 research_contract、research_checks、research_status 与 delivery_kind。缺字段按 unknown；完整名单必须有同合同的计算、日期和成员验证证据。完整筛选还须有全股票池 coverage_rows 的字段可用性、field_dates 实际日期证据和审计哈希，只有数量声明或 Top10 成员不能标为 complete。保留 require_live_data=true，部分成果交付不能被记作实时研究完成。

合同冻结仍是草稿、数据无法计算时，交接 methodology/unavailable；原始问题和已确认策略照常展示，草稿继续阻止名单计算，不将未冻结合同冒充已确认计算证明。

页面初始化请求结果未知时保留 page-bootstrap 收据，不再调用 new_page 重新注册。若无法公开发布，可交付本地验收通过的完整 HTML，明确尚未发布；宿主通过附件接口交付，不把容器路径发给用户。两次明确失败的模板服务读取也允许该备用路径；单次参数错误或尚无执行计划不能直接当作服务不可用。

用户确认了上一轮默认条件时，同合同保存 confirmation_messages 与 source_quote；> 与 ≥ 必须保持原比较符。不能只保留“确认”而丢掉被确认的阈值。

发布收据已确认且本地与公开内容检查已过，但元数据读取失败时，可用原候选 publish_verified 参数增加 verify_existing_publication=true 进行只读复验。该路径核对候选、元数据和已确认远端版本，不发送更新；任一不一致即停止。结果未知时仍禁止重发。

Compose 的 module_order 必须是当前全部模块的排列，默认有真实数据的模块在前、详细方法在后。改顺序调用 execution_plan 并传 expected_revision、revision_reason、module_order；不要手改收据、hash 或凭证。面板顺序不能越过模块顺序。

ranking 来自 research_contract，指定 rank_by、rank_order、rank_limit。TopN 表格和柱图都必须显式声明相同排序与数量；不能在布局修复时删排序、过滤条件、输出、单位。核对榜首、成员和实际渲染值与首答一致。仅标题含 Top10 时也检查排序；不靠中文排名关键词推断完整合同。

实时文字使用 binding 或 `date_binding:{outputs:["资金净额","突破"],labels:{"资金净额":"资金","突破":"量价"}}`，引用同一轮输出的实际日期。固定历史分析声明 as_of_mode=historical 并明确历史日期，不称当前最新。date_binding 面板只展示当前字段观察日，方法说明放独立文本面板，防止刷新后正文过期。

publish_verified 首屏失败时查看报告中的 firstScreenDiagnostics：失败元素、top、height、width、viewportHeight。执行返回的 recover_delivery；最多两轮针对性修复，相同候选不重复验收。`python scripts/static_page.py recover_delivery @recovery.json` 参数为 task_id 和当前 plan_hash，必要时附 user_query 或 research_contract。按新的 next_action 编辑、compose_page、publish_verified、验收回复，保持同一 task/turn/page。

两轮后优先复用验证收据物化快照。完整快照为 result；缺条件或未满足明确实时要求为 partial_research + partial；全部数据缺失为 methodology + unavailable。方法页需要确认的研究范围，不使用数字占位，不填假股票，不把缺数据写成符合为零。方法页检查首屏可读研究摘要；其他结果页继续检查手机首屏真实数据。所有页面继续检查公开地址、内容正确性、手机可读性和错误/占位内容。

已有正确页面不能被错误或缺数据页覆盖；恢复返回 PRESERVED_LAST_GOOD_PAGE 时保留旧版本，说明本轮尚未更新。未知写入先查 delivery_status 和远端版本，不盲目重发。注册未知也不盲目重试。发布服务不可用时交付生成的完整 HTML 备用文件及其真实状态，明确未公开发布，并保存计划与恢复信息，不能声称公开活页交付。

Run completed 只表示执行结束。Job、交付导出与最终回复分别保留研究状态、live_data_mode 和页面状态；公开验收与回复验收成功才交付链接。删掉失效的“链接随后补上”，不再要求用户发起常规技术重试。

宿主因研究轮数/预算耗尽进入收尾时，沿用同一task/turn和已存在的page_id；若尚未建页，则用原始问题或冻结合同经正常模板路由初始化唯一方法页。此阶段不重新查全市场、不调试函数、不以Unicode空白绕缓存。读取已有验证收据和数据，仅有可靠输出时交付partial_research，无法核实计算时交付methodology/unavailable；说明“标的结果尚未完成验证”，不能笼统说所有数据不可用。普通非终止首答先说明研究缺口，再按next_action建页、公开验收和回复验收。

宿主确定性收尾：claw-backend 在 SDK 可恢复终态及预留恢复阶段结束后，可调用受保护的 finish_research_delivery.py。该入口不允许模型直接调用，不做研究计算；无计划时读取在线模板并留存候选，按“当前无法提供结果模板要求的标的证据”初始化方法页。已有计划时只通过正常修订恢复已验证快照或方法页，保留page_id、require_live_data与原合同；不更新最后正确版本，不重发未知写入。仍使用compose_page、publish_verified、本地/公开浏览器验收和回复验收；只有这些均通过才能提供链接。发布服务不可用或写入未知时只交付经本地验收的HTML附件，明确尚未发布。

固定历史观察池可使用text面板中的Markdown主榜，显式声明rank_by、rank_order、rank_limit，并用output_labels映射可见排序列；生成前检查数字、行数和方向，浏览器再核对实际单元格与成员。辅助个股行情表可声明ranking_scope=supporting，但必须同时保留一张匹配合同的主榜，不能把所有表标为辅助来删排序。主榜验证不等于全市场数据完整；partial仍需显示覆盖缺口。
