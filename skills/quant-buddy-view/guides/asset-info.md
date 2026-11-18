# 选股活页附公司信息

仅用于用户明确要求选股时附主营、近期事件或上下游信息。普通选股不启用；“不要网页”优先。沿用建页路由；模板缺模块时走原有增强路线形成候选，不能直接交付未增强模板。量化结果先答，公司信息只在活页异步加载，不参与筛选、排名或已验证结论。

## 聊天交付提示

仅在本次活页已成功接入公司信息模块并通过页面验收时，在最终回复中补充一句功能说明：

> 活页已加入主营业务与近期重大事件模块，打开后按权限异步加载；本次积分消耗及缓存规则可点击卡片右上角查看。

用户指定上下游等主题时，将句中的主题改为实际接入的信息需求。此提示只证明模块已接入，不代表内容已经生成、检索或结算成功；不等待公司信息生成才交付选股结果，不在聊天里预报扣费金额。普通选股未启用、明确不要网页或模块未接入时不输出该成功提示；接入失败时如实说明，信息区待生成、只读无缓存或不可用时也不得声称信息已生成。

聊天收费说明统一沿用页面回执和最终回复合同：`llm_billing:true` 时，按顺序展示功能说明、独立的 **AI 刷新计费提醒** 与完整 `billing_notice`、原合同要求的交付链接。计费段紧邻链接之前且只展示一次；仅允许分句换行，不在功能说明中另写收费条件。`llm_billing:false` 时不加计费段；字段未返回不推断免费，true但缺少说明时按现有回复校验报缺项。功能提示、页面内规则和卡片积分不能替代这段接口说明；卡片本次积分仍读取本次响应的 `billing.charged_points`，`billing_notice` 不代表本次已扣费。保留原回复合同与单次链接交付，不额外增加其他章节。

## 需求与授权

QBS Handoff可选 `asset_info_request` 包含selection_role、prompt、word_count、output_format；默认主营＋近期事件、300字、text。selection_role引用真实已验证选股结果。将请求及 `task_id/user_query/validated_outputs` 写入参数文件，执行：

原问题明确要求选股附主营、事件或上下游资料时，遗漏请求字段会返回 `ASSET_INFO_REQUEST_REQUIRED`；按原题补齐请求后继续。编译和发布还会检查本轮原问题，不能通过漏传Handoff、模板直交付或手写静态资料绕过异步模块。普通选股及明确不要网页仍沿原行为。

```bash
python scripts/asset_info.py prepare @information.json
```

只执行返回的registration_command或registration_params_file。专属收据 `asset_info_contract_receipt_v1` 状态为contract_validated、validation_scope=request_contract、content_generated=false，不能代替金融出数或已生成内容证明。注册payload只含prompt/word_count/output_format，不传股票或身份；提示词1～4000字符，字数30～3000整数，格式text/markdown。注册不生成、不扣生成费。指纹、任务身份、登记归属和作者一致门禁保留；页面只放授权ID和签名。

## 页面绑定

取数路径为“活页 → skill_server `/skill/queryDataGrant` → 活页渲染”。官方页头仅提供120秒有效的页面身份凭证及同环境Skill地址；官方SDK缓存、到期续取凭证，并在直连接口时携带 `x-asset-info-context`。报价和分享确认也直连Skill，生成中轮询传 `cache_only:true`，不能触发生成。页面沿用下述SDK调用，不手签凭证、不放作者或模型API Key；官网 `/webapi/asset-info` 只用于身份获取，不中转取数、生成或计费。

Compose草稿、build_dashboard局部面板或compile_bespoke_page参数顶层加：

```json
{"asset_info":{"grant_id":"dg_实际授权","selection_output":"实际选股表输出","asset_field":"实际代码列","name_field":"实际名称列"}}
```

signature从同任务凭据补全，也可显式传同一签名；target_selector默认 `#qb-asset-info`。声明式模块须绑定唯一table面板output，自动使用该表排序、rank_limit后的相同名单。沿用整页/局部构建边界，unmatched整页仍由模型手写。

公式选股使用实际公式输出名；指标选股Grant使用解析后的table.output（普通授权即grant_id），不另起selected等别名。asset_field/name_field也按归一后的真实列名传入，composition_select通常为“代码”/“名称”。

Bespoke在选股业务脚本前放 `<!-- QB_ASSET_INFO -->`，编译时传asset_info。先画真实量化表，再调用 `QBAssetInfoPanel.setTable(columns, rows)`，传本轮当前展示集合；columns为列名数组，rows可为对应位置的数组行或按相同列名取值的对象行，如 `setTable(['代码','名称'],[{'代码':'SZ002148','名称':'北纬科技'}])`；不await信息区。每行必须有非空字符串代码，无效名单明确报错并保留上次内容，不能当作零入选。取数前pause()，失败unavailable(message)，空结果仍setTable。保留完整官方分享壳，初始化QBShareShell.init时传同环境embedOrigin：Test为 `https://test.quantbuddy.cn`、正式为 `https://www.quantbuddy.cn`。声明式整页自动传入；局部面板宿主应自己设置。带公司信息模块时，分享壳漏传embedOrigin会从同页完整官方SDK地址推导默认环境；显式环境不被覆盖，非官方地址不参与推导，环境不一致仍须拒绝。编译器插入同环境官方桥接与收费说明、强刷入口。

只保留一个 `<!-- QB_ASSET_INFO -->` 占位符，不手写同名公司信息容器、配置或运行脚本；由编译器插入唯一官方模块。编译、发布及浏览器门禁检查目标与模块唯一且一致；本版介绍、常驻计费说明及强刷控件必须保持hidden。名单先于分享壳页头初始化到达时等待页头地址和对应身份就绪；地址确定后仍严格拒绝跨环境。

模块串行调用官方QBAssetInfo.load；换股替换集合、忽略旧响应，中间待加载名单只保留最新一份。保留原展示数量；超过50只在信息区分页，每页最多50只，只加载当前页。普通刷新不加force_refresh。V1保留官方“确认费用并更新全部”协议，当前版本入口隐藏，范围为当前页；没有单股强刷报价。报价null/失败显示预估不可用，不能称免费。

官方 SDK 必须支持 `schedulerVersion >= 2` 与 `cancelPending()`。面板接管自动加载，在新 SDK 确认前不暴露生成元素；旧脚本只显示升级提示。换股、空名单、pause/unavailable 立即取消未开始的旧请求，已发出的请求无法撤回或承诺免单；单股异常独立展示，其余股票继续。强刷仍由官方 SDK 对当前页整批报价确认。生成中轮询缓存只读取内容，不能用缓存读取的零费用回执覆盖先前生成的费用证据；结算未确认时保留待确认状态。

当前版本按产品展示要求，不展示公司信息介绍、常驻计费说明与强刷按钮；保留hidden元素和官方data标记供SDK及发布合同核验，页面仍按权限自动加载公司信息。卡片右上角显示本次费用状态，鼠标悬停、键盘聚焦或点击可查看缓存与计费规则，支持Escape及点击外部关闭；手机以卡内展开方式显示规则。缓存命中显示本次0积分；本次响应billing.charged_points有效且无未结算状态时显示实际消耗，pending/blocked显示费用结算中，缺失或无效回执显示费用待确认，不能自行拆分整批费用。generation_cost仅为历史成本，不能证明本次扣分。内容快照状态及生成时间保留在卡片底部。规则明确各股票独立缓存、北京时间每日04:00/16:00过期、过期后首次符合权限访问才触发更新，到点不会自动生成或扣费。不要移除官方页头、绕过身份校验或改变匿名代扣设置。隐藏展示不关闭后端计费：由后端记录page_id、asset、trace_id、Token用量和billing_receipt.charged_points。

本地编译/浏览器预检不加载LLM内容；模块只在HTTPS的pages.quantbuddy.cn上登记展示集合。本地预览仍画量化表和信息区，提示内容将在公开活页中加载，避免预检意外消耗生成费用。

浏览器验收读取 `getSelectionState()` 检查名单绑定及当前页卡片是否一致；尚未绑定、名单无效或卡片缺失不能通过。合法空名单可通过；不等待内容生成，不把只读、无缓存或费用待结算判为名单失败。

纯文本显示，来源只用返回链接；标明生成/过期时间和缓存状态，仅web_search明确为true/performed才称已检索。billing.pending/blocked显示结算未完成，generation_cost不能证明本次扣费。生成中、只读无缓存、失败分别展示；保留已有内容，量化表继续使用。

公司资料按单公司卡片呈现，公司名与代码分开；仅在原文有明确主营、近期事件标签时分栏，否则保留全文通栏展示，不生成前端摘要。长正文可展开；来源默认折叠并显示条数，展开后逐条列出，长标题截断并以title保留全文，不重排或重新编号原始来源。带时区的时间转换为Asia/Shanghai，纯日期原样保留，缺失或无法明确解析的日期如实提示。生成时间常显，缓存有效期收进“更新信息”；移动端改为纵向排版。正文和来源标题均通过安全文本DOM呈现。

阅读样式使用浅底主营侧栏与事件正文、选股展示顺序编号及独立标题层级。事件原文明示的日期可强调，并在已有句号或分号后的日期前分段，不补写标题、摘要、时间线或事件评级。手机正文16px；展开、来源和更新信息的操作区至少44px，保留键盘焦点与减少动态效果设置。

## 发布与验收

publish_workflow可与金融Grant一起登记，但专属收据单列为asset_info_contract_receipt_files，不放入selected_routes或金融grant_validation_receipt_files。发布预检仅核验信息凭据登记，不发无股票查询、不生成；空缓存不表示授权或选股失败。服务端仍检查引用授权作者、官方分享壳、收费说明和强刷入口。

新任务维护旧页时，在同一 QBV_STATE_ROOT 中只读核验原任务的授权登记，保留原 ID、签名和登记归属；不复制凭证到新任务、不重新注册。仍须通过同账号、同 endpoint、合同指纹、签名、有效期和未撤销校验。只有旧签名文件或原始登记已清理时，不能推断归属，需先恢复原登记证据。

匿名默认只读，不调用assetInfoPageShare开启代扣。生成与计费由skill_server处理，身份凭证取自真实官方页头；普通作者、已授权匿名、其他用户及管理员权限按服务端决定。禁止伪造身份或签发页头上下文。

官方返回restricted或execution_allowed=false时，显示只读状态；这不代表Grant合同或量化选股失败。登录失效而返回unknown时仍可读取缓存，只有尚未收到官方身份上下文时才等待页头就绪；没有真实生成与结算回执不能标记生成验收通过。

网页登录成功不代表具备生成权限。若官方页头的身份响应（`GET /webapi/asset-info`）返回 `viewer_kind=restricted`、`execution_allowed=false`，应保留只读提示；测试用户、页面管理员或运营预览不能用于生成验收。无需重新注册授权或更换选股合同，待普通作者会话可用后读取同一页面继续验收。

Test环境与“测试用户”身份是两个概念：Test环境内的普通作者可以生成，具有测试用户标记的作者只读。用户授权使用测试账号后，继续验收量化取数、公司信息需求绑定、只读缓存和异常隔离；真实生成与计费保持待验收，不修改账号标记或开启匿名代扣。说明缺项时直接给出官方权限响应，避免让用户反复换账号试错。本地Agent测试器支持 `python scripts/asset_info.py prepare @output/参数.json`，仅开放prepare子命令，沿用输出目录参数限制；它与Test Agent候选部署是不同验收层次。

| 验收题 | 预期 |
|---|---|
| 量化选股，活页附每股公司信息 | 默认主营＋近期事件300字；量化名单先呈现 |
| 相同条件选股，附上下游公司并注明日期来源 | 只改变信息prompt，保留量化合同和排序 |

本地测试为QBS的tests/test_asset_info_handoff.py及QBV的tests/test_asset_info.py；浏览器运行 `node tests/test_asset_info_browser.cjs`，支持QBV_TEST_PYTHON、CHROME_PATH、QBV_PLAYWRIGHT_MODULE_ROOT指定依赖，QBV_BROWSER_EVIDENCE_DIR保存截图。合成协议fixture与真实Test证据分开记录；真实公开URL验收桌面/390px/320px、普通作者生成、缓存复用、强刷和实际计费。缺真实身份或结算证据不能标通过。历史页面先出本地候选，按授权原链接更新；Test业务验收后再按授权正式发布。

本次集成同时涉及 QBV 和官网 `public/asset-info-bridge.js`，须合入同一轮候选并部署同环境 SDK。浏览器测试可通过 QBV_ASSET_INFO_SDK_SOURCE 校验 fixture 与候选官方源码一致；官网独立运行 `node --test tests/assetInfoBridge.test.cjs tests/assetInfoHeader.test.cjs tests/assetInfoDirect.test.cjs`，另运行 `node tests/assetInfoDirect.browser.cjs` 验证真实跨域预检及活页直连。共同候选确定后再做 Test 真实业务验收，不能把离线协议测试算作已部署验收。
