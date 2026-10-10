# 筛选研究合同与交付

用户确认策略后，先写一份 research_contract_v1。保存 task_id、原始多轮 user_messages、requested_date、selection_output、conditions、ranking、证据引用和输出要求。每项条件有 id、description、spec；spec 包含资产范围、排除项、阈值、单位、价格基准、日期、确认的代理口径。公式条件同时记录 formula_name 和 predicate，最终掩码同时冻结 selection_output/selection_predicate，用于阻止额外过滤。不能把最近涨停日收盘换成窗口最高收盘，不能漏掉板块或市值，也不能擅自新增过滤。

用 `python scripts/research_contract.py freeze @intent.json` 生成 research_contract，保存返回对象；执行 `call.py runMultiFormulaBatchStream` 时附带该对象或其文件路径。executor 在发起计算前核对公式和 selection_output 的引用链，拒绝遗漏、替换和未应用条件。只修公式，不改合同来掩盖不匹配。此检查验证结构化条件，原始对话与条件的语义一致性仍须逐项核对。

保存完整用户原文；用户以“确认”接受上一轮建议时，还须将该条建议原文存入 confirmation_messages。新筛选合同设置 require_confirmation_evidence=true，数值阈值条件提供其中逐字可匹配、只含一个比较符或明确比较词（如低于、超过、至少）的 source_quote。严格 > 不得改成 ≥，严格 < 不得改成 ≤。例如 source_quote="当日涨跌幅 > -3%" 对应 operator=gt、value=-0.03。剔除“小于60日”转换为“至少60日”须声明 source_transform=exclude_complement；金额单位换算须声明 source_transform=unit_conversion 和正数 source_scale；同时发生剔除补集与单位换算时使用 source_transform=["exclude_complement","unit_conversion"]，不能用这些标记改变比较方向或阈值。不同条件、两种默认量能选项分别保留，不能将“换手率 > 3%（或成交额 > 2 亿）”擅自改为同时满足两项。

freeze 必须 code=0 后才计算；失败时先修合同字段，不能跳过或删合同继续。先 confirmDataMulti/检索公式语法确定真实字段名，再填写 formula_name/predicate。ranking 的字段名严格如下，不能写 metric/direction/top_n：

```json
{
  "task_id": "本任务真实ID",
  "user_messages": ["沪深主板，成交额超过2亿，前10"],
  "requested_date": "2026-10-08",
  "selection_output": "入选池",
  "selection_predicate": "\"范围闸\"*\"量能闸\"",
  "conditions": [
    {"id":"universe","description":"沪深主板","spec":{"scope":"沪深主板"},"formula_name":"范围闸","predicate":"板块(沪深主板)"},
    {"id":"amount","description":"成交额超过2亿元","spec":{"field":"amount","operator":"gt","value":200000000,"unit":"元"},"formula_name":"量能闸","predicate":"\"成交额原始值\">200000000"}
  ],
  "ranking":{"rank_by":"成交额展示值","rank_order":"desc","rank_limit":10}
}
```

例中字段/板块名称仅演示 JSON 结构，必须替换为本次已确认的真实公式名称与用户原文。保存成功后，同任务 CLI/Python API 会自动加载合同；辅助公式批次只记为 partial，最终 selection_output 的计算会核对跨批次已提交公式引用链。预检仍不能替代实际数据和名单审计。

计算后再用 `research_contract.py audit @checks.json`，其中包含 research_contract、实际 formulas、实际 applied_conditions、observation_date 和 asset_rows。applied_conditions 记录真正执行的过滤，不能直接复制需求假装执行；名单记录要含硬条件所需字段。原始结果、漏斗、名单、首答和页面全部引用同一份合同与审计结果。公式预检成功只代表公式条件通过，不能代替实际数据日期、名单成员和字段证据验证。

audit 的 applied_conditions 是数组 `[{"id":"实际执行的条件ID","spec":{"实际执行的口径":"值"}}]`，不能写成以 id 为键的 object。asset_rows 是真实最终名单记录数组，包含排序字段原始数值与硬条件证据，不能只提供股票名。没有实际成员证据时仍为 partial；零命中需同时提供 coverage 的 data_complete=true 和真实 rows_evaluated>0，证明有效数据上已执行筛选，不能用空数组代替数据缺失。

筛选的 coverage 同时保存该股票池的 universe_count 与 rows_evaluated，并提供 coverage_rows 全股票池逐行证据（或 coverage_rows_file 指向真实查询输出的 UTF-8 JSON 数组）。单纯声明 data_complete=true 和两个相等的数量不能证明完整性。coverage_rows 必须覆盖所有被评估标的，包括未入选标的；不能只放最终 Top10。每项条件 spec.input_fields 列明其实际输入字段，field/benchmark_field 也会检查缺失值；派生条件须包括基准价格、原始量能等必要输入。审计同时提供 field_dates（字段名到实际观察/计算截止日的映射），不能把请求的 end_date 当作滞后字段的实际日期。历史基准的值保留其原始来源日期，派生字段在 spec.derived_fields 或 benchmark_field 中声明，并另记录本次 evaluation_date；原始字段必须使用 observation_date/date，不能被 evaluation_date 掩盖滞后；源数据更新日仍须如实展示。字段缺少日期或与合同/截面日期不符即为 partial。审计记录实际证据数量与内容哈希，任何必要字段缺失均为 partial。条件字段有缺失、两者不相等或未取得股票池覆盖证据时必须为 partial，不能把有数据部分的 Top10 说成整个股票池的完整排名。对动态基准条件可提供实际公式布尔输出（以 formula_name 为行字段，数值为0/1）或 benchmark_field 的真实值；不能用文字基准作数值比较。合同可传 freeze 返回的 research_contract_file，不能传未冻结的意向 JSON。

完整研究才设 research_status=complete；缺少任何硬条件的观察池设 partial，不能称全部符合。prepare_validated_page 增量接收 research_contract、research_checks、research_status 和 delivery_kind，并交给 QBV。旧调用缺这些字段按 unknown，不能推断完整成功。

冻结工具报错时必须按 next_action 修正 JSON 或编码，不能把参数错误解释为用户未确认。动态基准（如 close > 前60日高点）记录 benchmark/benchmark_field，无固定 value，不要求伪造数值来源。自然语言“主力资金净流入”对应净额严格 > 0。用户没有指定突破/放量窗口时，先按既有模板口径继续并在 assumptions 中说明采用60/20日定义；这是假设，不写为用户已确认。若不适用或无法核实，则交付注明缺口的研究页，不能以再次确认结束已经授权的建页任务。

“今日”字段不齐时，分别展示当天已验证部分条件池，以及最近完整历史榜单，列明日期、已覆盖条件和缺口。不能以历史榜单替代今日答案；不能把无数据写成零命中。缺少字段先按现有外部核验流程尝试宿主 WebSearch，宿主不可用再尝试本地 webSearch；记录可靠来源链接、实际日期、单位和统计定义。不同定义的主力资金不能拼成同口径榜单，联网片段也不代表全市场覆盖。无可靠补证时明确缺口。

已授权活页同轮完成。实时优先，最多两轮有依据的技术修复，然后在同一 page_id 恢复已验证快照、部分研究或方法研究页。方法页展示确认策略、已有公开证据、缺失条件和核验方法，不造名单。继续阅读 QBV workflows/research-contract-delivery.md；保留 require_live_data=true，页面交付成功与实时研究完成分开记录。

日期冲突、公式预检失败也不得以“请用户再确认日期/重试”收尾。requested_date 保持原值，不能跟随字段最新日期改合同；辅助结果另标实际日期。predicate 必须与将提交的公式右侧完全相同（包括双引号、缺失填零等），selection_predicate 对应 selection_output 本身，不是某个中间掩码。先在输出 JSON 中核对语法，再 freeze，避免把不能执行的拼写冻结。

没有有效数据时，用已有 `handoff`→`prepare` 交接方法研究页，validated_outputs/validation_receipts 为空数组、research_status=unavailable、delivery_kind=methodology，保留 frozen research_contract 与原始 user_query。不要伪造 computation_capsule。prepare 之后立即读取宿主提供的 QBV Skill 同轮继续；单 Skill runner 无 QBV 能力时如实记录环境限制，不能称交付成功。示例参数：

```json
{"task_id":"本任务真实ID","turn_id":"本轮真实ID","user_query":"原始研究问题和已确认条件","route":"create","route_reason":["已授权研究页，数据未完成"],"validated_outputs":[],"validation_receipts":[],"research_status":"unavailable","delivery_kind":"methodology"}
```

漏斗归零后，未执行的后续条件仍须对观察名单逐行核验。没有全部条件的行级证据，不得把归零前观察池称为“仅差一项”或“唯一短板”；记录各项已通过、失败及未核验状态。审计为 partial 时，首答、页面与终答均不得声称完全符合或完整零命中。audit 的结构化结果会保存当前 task/turn 收据，即使 stdout 被重定向，宿主也可读取真实审计状态。

研究调试有界：同一关键条件连续两次修正后仍出现缺值、维度错位、异常量纲或无法核实的缓存，应停止追求完整名单。最多做12次选股计算调用（正常readData/resumeJob取回已有结果不计），宿主上限更低时服从宿主；不能更换脚本入口或新建session规避。此时审计保持partial，立即把已验证部分交接QBV；没有可验证标的数据则交接methodology/unavailable。达到SDK轮数或预算上限后的恢复阶段，不再跑全市场或调试函数。

最近涨停日收盘基准先做小样本验证：选择有真实涨停/封板证据的标的，读取最近交易日序列，逐日核对最近板日与板日收盘价；不得仅凭日回报>=9.9%替代未确认的涨停字段。自然日位移、前值延续和缺失填充必须先验证实际函数口径，不能跨节假日或非交易日猜值。同比对当前收盘、回落深度和金额/成交量单位，异常回落不进入全市场榜单。

合同固定用户条件，辅助计算可以重建，但必须保留基准定义、比较符、窗口和量能OR。改变已执行的辅助依赖后，旧输出没有新的验证收据即为待核验；不得插入Unicode空白、改会话或声称新data_id就证明口径正确。若服务未提供可靠重算/依赖更新机制，停止并交付缺口页，后续修复计算实例机制，不要求用户重新确认原条件。
