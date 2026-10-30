# data_grant — 数据授权（把一次直取数请求钉死成签名凭证 → 页面免 key 取数）

`validate_grant_set` 对日频 CSV 下载并逐资产验证后才生成收据；`status:partial/failed` 不表示全部通过。注册失败时按返回的 recover_snapshot/materialize_snapshot 继续同页研究；未知注册不重复发送。历史快照不会自动更新，不能冒充实时授权。

> 脚本 `scripts/data_grant.py` 已可用；`build_dashboard` 与 `assets/data-kernel.js` 已支持 grant 面板。服务端设计见 `skill_server/docs/dataGrant相关文档/数据授权-技术设计文档.md`（v0.2）。

> 把一次 `fastQuery` / `fastQueryMinute` / `fastQueryMinuteRange` / `stockProfile` / `selectByComposition` 请求在注册时**钉死**，得到 `grant_id` + `signature`；之后**无需 API Key**，页面凭这两个凭证就能反复取数。底层数据更新后，取数永远拿最新结果（钉死的是"查什么"，不是"某天的值"）。
>
> 与公式任务包（`formula_package`）的关系：**同一套签名免 key 心智**。公式包钉死的是"一组公式 + 读取模式"；数据授权钉死的是"一次平台直取数请求"。**算出来的指标用公式包；平台白名单直取的行情/估值/画像/维度分 TopN 用数据授权**（取舍见 SKILL.md「数据授权 vs 公式包」）。

## 五种 kind

| kind | 底层接口 | 钉死内容 | 页面拿到 |
|------|---------|---------|---------|
| `fast_query` | fastQuery | 一次快查请求（assets/query_type/fields…），字段须命中平台白名单 | 值 / 序列 |
| `fast_query_minute_range` | fastQueryMinuteRange | `{asset,start_date,end_date}` 或 `{asset,start_offset,end_offset}`；历史全列，无fields/format/remove_nan | CSV分钟长表manifest，内核物化为columns/rows；见下方新增规则 |
| `fast_query_minute_range_multi` | fastQueryMinuteRangeMulti | assets/asset/market三选一；absolute/rolling/current_trade_day及每日分钟窗口；无tickers/fields/format | JSON columns/data或CSV url；内核归一为含ticker的长表，见「多资产分钟授权」 |
| `fast_query_minute` | fastQueryMinute | `{ asset, fields }`，单资产，字段限 OHLCVA；无历史/区间参数 | 共享 `dates` + 列式 `fields` 分钟数据 |
| `stock_profile` | stockProfile | `{ asset, dimensions }` | 个股画像卡 |
| `composition_select` | selectByComposition | 一次按权重选股/筛选请求（mode/universe/composition/screens/top_n…），indicator_id 须为已上线维度分 | TopN 榜单表 |

## 分钟行情覆盖预检与提示

分钟授权注册、Fork替换资产/修改窗口前必须按 [分钟行情支持范围](../references/minute-data-coverage.md) 检查：A股/美股股票从 **2026-05-13**、国内期货从 **2005-01-04**、港股股票从 **2026-05-20**、国内指数从 **2026-08-13** 开始；境外期货主力连续已支持，分钟起点按ticker区分（见分钟覆盖参考）；美国/香港指数及香港期货暂不支持。全窗口早于起点时先提示且不注册，部分窗口越界时说明缺失区间并在页面标出真实覆盖，不能静默裁剪授权payload或把空数据伪造成完整行情。市场起点不保证单个资产当天就有数据；offset按市场当地自然日折算，绝对窗口/滚动窗口语义不变。Grant仍返回原始1分钟数据；30分钟图表必须由页面或上游派生，并标注来源间隔。

## 发布链路能力预检

`resolve_asset_data` 发现可选字段不可用时，会保留限制说明，移除该字段并重新验证精简后的合同，再生成注册参数与收据；必需字段缺失仍阻断。普通完整合同不重复查数。不能把首次探测的收据绑定到改动后的合同。

`resolve_asset_data` 成功返回的每个 `grants[]` 已含当前合同的验证收据、`registration_params_file` 和 `registration_command`。先发送业务首答并完成模板/页面路由，再执行该注册命令；不修改生成文件，不再次调用 `validate_grant_set`。原样把 `publication_evidence` 合并进看板 spec；它保留实际资产、路由及所有验证收据。

只有新增或改动的合同才用 `qbs_bridge.py validate_grant_set`，结构为 `{"task_id":"当前任务","user_query":"用户原话","grants":[{"name":"snapshot","contract":{"kind":"fast_query","payload":{"assets":["已确认资产"],"query_type":"snapshot","fields":["close"],"result_mode":"value"}}}]}`。新合同省略 `contract_fingerprint`，由脚本计算；若显式提供则必须精确匹配，否则联网前拒绝。成功后直接用返回的注册文件，不能自己生成或复制旧指纹。

Grant类型由共同能力表约束注册、Fork合同及qbs_bridge。`validate_grant_set`会在查询前聚合结构/类型/fingerprint错误，返回errors[]；不要只处理首个失败角色。

单日 `fast_query_minute` Grant使用专用验证器检查共享dates/fields对齐、必需字段、交易日期、时区、排序及有效数值；正常空结果属于数据不可用，不能生成成功收据。仅支持当前/最近完整交易日，不能传历史日期、区间或多资产参数；历史研究不要继承与目标需求无关的分钟角色。

## 端点（对齐公式包）

| 操作 | 方法 + 路径 | 认证 |
|------|-------------|------|
| 注册 | `POST /skill/registerDataGrant` | `Authorization: Bearer <api_key>` |
| 取数 | `POST /skill/queryDataGrant` | `grant_id`+`signature` 必需；API Key 可选（CLI 有 Key 时附带用于审计归因，普通 JSON） |
| 列表 | `GET /skill/listDataGrants?page=&page_size=` | Bearer |
| 撤销 | `POST /skill/revokeDataGrant` | Bearer |
| 刷新 | `POST /skill/refreshDataGrant` | Bearer |

> `endpoint` / `api_key` 读 `config.json`（与 `formula_package.py` / `static_page.py` 共用同一 endpoint）。`signature` 仅在**注册响应中明文返回一次**，服务端不可再取出；有task_id时脚本保存到任务根目录 `credentials/grant/<grant_id>.json`，并保存合同绑定登记收据；无任务的旧调用仍使用 `output/data_grants/<grant_id>.json`。

## 调用方式（与 formula_package.py 同款 CLI）

```bash
# 注册（凭 config.json 的 api_key 认身份，无需会话）
python scripts/data_grant.py register @params.json

# 取数（只需 grant_id，signature 可由本地凭证自动补全）
DG_PARAMS='{"grant_id":"dg_xxx"}' python scripts/data_grant.py query

# 管理
python scripts/data_grant.py list   '{"page":1,"page_size":20}'
python scripts/data_grant.py revoke  '{"grant_id":"dg_xxx"}'
python scripts/data_grant.py refresh '{"grant_id":"dg_xxx","rotate_signature":true}'
```

## 注册参数

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `kind` | `string` | ✅ | `option_contracts` / `fast_query` / `fast_query_minute` / `fast_query_minute_range` / `fast_query_minute_range_multi` / `stock_profile` / `composition_select` |
| `payload` | `object` | ✅ | 冻结的完整请求体，形状随 kind（见下） |
| `ttl_days` | `number` | ❌ | 有效期（天），默认 365 |
| `task_id` / `user_query` | `string` | ❌ | 随 audit 落库 |

### payload 按 kind

```jsonc
// fast_query —— 字段必须命中平台白名单（否则注册拒 FIELD_NOT_WHITELISTED）
{ "assets": ["600519.SH"], "query_type": "snapshot", "fields": ["收盘价","涨跌幅"] }

// fast_query —— 固定日期的日频行情/估值快照；单值时可按字段实际更新时间对齐
{ "assets": ["600519.SH"], "query_type": "snapshot", "fields": ["收盘价","PE_TTM","PB"],
  "start_date": 20260917, "end_date": 20260917 }

// fast_query_minute —— 单资产、当前盘中或最近完整交易日；字段会规范为 open/high/low/close/volume/amount
{ "asset": "600519.SH", "fields": ["收盘价", "最高价", "成交量"] }

// stock_profile
{ "asset": "600519.SH", "dimensions": ["估值","财务质量"] }

// composition_select —— indicator_id 必须是已上线维度分（否则注册拒 INDICATOR_NOT_FOUND）
{ "mode": "score", "universe": { "asset_scope": "A股" },
  "composition": [{ "indicator_id": "ind_a_share_momentum_reversal", "weight": 1 }],
  "top_n": 10, "with_breakdown": true }
```

## 注册响应

```jsonc
{ "code": 0, "grant_id": "dg_xxx", "signature": "<明文仅此一次>", "kind": "fast_query",
  "whitelist_fields": ["收盘价","涨跌幅"], "whitelist_indicators": [], "expires_at": "2027-06-17T..." }
```

## 取数返回（与在线接口同构，build_dashboard/data-kernel 据此渲染）

- `fast_query`：与在线 fastQuery 同构的值/序列结构。固定日期的 `value` 查询中，日频行情和估值刷新时点不同是正常情况：服务端先选请求区间，若 PE/PB 等字段尚未更新才回看 10 个自然日并返回 `{v, d, fallback:true}` + `DATE_RANGE_FALLBACK`。页面必须使用字段自己的 `d` 显示日期，不能把该字段显示为空、也不能用公共 `dates.trade_date` 覆盖；`series` / `window` 仍严格只含请求区间内的数据。
- `option_contracts`：`data={ticker,records,notes?}`，美股records为11项扁平合约字段，国内另有product_id及decision_date/underlying_contract/status，empty行附empty_reason；build_dashboard归一为行数组。按每行真实trade_date展示，不改成刷新时间；changes可带is_baseline。
- `fast_query_minute`：`data.dates` 为共享分钟时间轴，`data.fields.<field>` 为同索引值数组；自定义活页直接按该列式结构渲染。
- `stock_profile`：与在线 stockProfile 同构的画像卡结构。
- `composition_select`：TopN 表（排名/名称/代码/score）+ `composition_used` + `as_of` / `last_date` + `date_alignment_status` + `date_alignment`。`date_alignment_status:"mixed"` 表示组合指标来自不同有效快照，此时全局 `as_of` / `last_date` 为 `null`，页面须逐项展示 `date_alignment`，不能渲染为单一数据日期。

外层统一带 `grant_id`；失败返回 `code:1` 并附错误。

当 FastQuery 数据点超过服务端阈值时，`queryDataGrant` 会返回 `mode:"csv"` 和当次生成的
`csv_fields[].csv_url`。页面仍先调用 `queryDataGrant`，随后由内联 `data-kernel` 下载 CSV 并
hydrate 为 `results[].fields[].series`；刷新时重新请求 Grant 获取新 URL，不缓存或持久化
presigned URL。生产环境优先返回 `https://pages.quantbuddy.cn/exports/...`，与活页同源，
无需 OSS CORS。页面下载仍固定 `credentials:"omit"`、`cache:"no-store"`，访问能力完全由
presigned URL 控制；如果兼容期仍返回 OSS 跨域地址，则 Bucket 必须额外允许无 Cookie 的
`GET/HEAD` CORS。

旧页升级只替换内核，不改页面业务脚本：

```bash
DKR_PARAMS='{"html_file":"old.html","out_file":"old-new.html"}' python scripts/data_kernel_retrofit.py
# 也可用公开 url 读取，但 url 模式必须显式给 out_file
```

工具优先匹配新 `QB_DATA_KERNEL_START/END` marker；没有 marker 时只接受唯一一个同时包含
`const QB`、`queryGrant`、公开 API 返回表和 `SKILL_VERSION` 的旧脚本块。

## 硬门槛与约束

- **先验证再注册**：注册任何 grant 前，必须先在 **quant-buddy-skill** 用 api-key 跑通对应接口（fastQuery / stockProfile / selectByComposition），确认命中/出数，再回本技能注册。不要凭空注册未验证的请求。
- **免 key 执行强制 `access_dunhe=false`**：数据授权页面绝不返回付费/敦和数据；只放行平台白名单字段与已上线维度分。
- **不让页面改参数**（本期）：grant 是钉死式，页面只能原样重放；交互式选股/选字段是二期作用域子集模式。
- **signature 是凭证**：不要打印到面向最终用户的对话里；它会写进公开页面 HTML 供实时取数，发布前确认可接受。丢失即不可恢复，可 `refresh` 轮换。

## 错误码（节选）

| code | 场景 |
|------|------|
| `FIELD_NOT_WHITELISTED` | fast_query 字段未命中平台白名单 |
| `INDICATOR_NOT_FOUND` | composition_select 的 indicator_id 未在服务端可用指标库命中 |
| `INVALID_PAYLOAD` | payload 形状/参数非法 |
| `PARAMS_REQUIRED` | 取数缺 `grant_id` 或 `signature` |
| `GRANT_NOT_FOUND` / `GRANT_EXPIRED` / `GRANT_INACTIVE` | grant 不存在 / 过期 / 已撤销 |
| `SIGNATURE_INVALID` | 签名校验失败 |
| `OWNER_QUOTA_EXCEEDED` / `RATE_LIMITED` | 所有者配额耗尽 / 触发限流 |

## 计费

注册计 `register_data_grant`；取数计 `QUERY_RU`，**费用计入 grant 所有者配额**，取数方不消耗自己配额、也无需 API Key。


## 计划任务的登记与重试

register携带本地`validation_receipt_file`；返回`registration_receipt_file`绑定该grant_id与真实请求fingerprint。相同有效合同直接复用登记；未知结果不自动再次创建。refresh/revoke同步更新任务登记，轮换使旧构建收据失效。`registration_status`仅查看本地状态，不会重发请求。完整流程见[计划与恢复](../workflows/planned-delivery-recovery.md)。

## 历史分钟与连续期货（0.6.76）

### 注册历史分钟Grant

```json
{"kind":"fast_query_minute_range","payload":{"asset":"C.DCE","start_offset":-5,"end_offset":-1}}
```

绝对模式改传成对 YYYY-MM-DD start_date/end_date，终点早于起点加三个日历月；offset为-70至-1自然日，不是交易日。两模式互斥，不传 fields、format、remove_nan、window_days 或日内时分。日期不得含市场今天/未来；默认昨天，休市为空不擅自回退。注册后只凭 grant_id/signature 查询，不追加资产/日期来覆盖授权。

- 固定绝对窗口不会因刷新变化；offset授权按当天市场日期滚动，仍不含今天。历史数据的实时刷新不等于当日实时分钟。
- `QB.queryGrant` 和 Python CSV校验器会识别 query_type=minute_range，下载 `csv_url` 长表并保留全部 `columns/rows`。这不是日频 csv_fields 宽表；columns缺省就读实际表头。
- 原始第一列 trade_date、第二列 timestamp（UTC秒），后续列按上游配置，不限六列。零/空/null不混淆，不过滤全空行情行；事件/拆股/警告保留在原始 data 中。
- 图表X轴用 timestamp，显示时转 timezone；行情trade_date用于交易日归属，按事件effective_trade_date匹配换月，不能按自然日验证期货夜盘。原始报价保持不变；需要连续参考图时按 [连续期货口径](../references/continuous-futures.md) 的加法价差规则另建派生数据，标明尺度、锚点和事件范围。
- Grant 原样提供1分钟数据；若页面需要30分钟K线，先将物化的分钟artifact交给 `scripts/resample_minute_bars.py` 生成 `interval=30min`、`source_interval=1min`、`derived=true` 的派生数据，再交给页面图表。不要修改Grant响应的 `interval` 字段，也不要把派生artifact注册成新的分钟Grant。
- 页端保存Grant配置，不把临时CSV URL硬编码成长效数据源。每次刷新先queryDataGrant；CSV下载401/403/404最多重新取manifest一次，不循环刷新、不修改签名到期字符串。
- 行情缓存12小时，事件60秒短缓存。专属每用户12小时10次仅直接调用 fast_query_minute_range 计数，Grant注册试跑/刷新/页面取数不计该专属次数；一般鉴权/计费规则不变。

### 老工具新增元信息

- fast_query_minute：原 fields 不变，只看顶层 trade_date 和简洁 contract_info={contract,status}。inferred表示事件推导，不是独立实时合约映射；unavailable/null显示“暂未确认”。不期待 roll_events、contracts数组或lookup_start_date。
- fast_query：future_context按ticker分组。窗口用roll_events；snapshot多字段日期不同时用contract_info.contracts逐日关联。CSV物化不得丢失future_context。
- fast_query_minute_range：新版roll_events列为decision_trade_date/effective_trade_date/old_contract/new_contract/old_close/new_close，按columns解析并原样保留。窗口按生效日筛选，两条close是决策日各自合约的原始日频收盘价；决策日可早于窗口起点。fast_query的future_context沿用相同事件语义；旧版事件trade_date兼容为生效日。股票adjustment仅窗口内split，不承诺完整历史链。
- 日频连续价已复权，原始分钟及换月参考close未复权；跨频核对先统一尺度。日分钟来源及构建流程可能不同，不承诺分钟重聚合等于日线；量相等校验仅在同来源口径、同合约、完整时段、无缺失重复、单位/单双边和版本一致时成立。局部缺失或对齐差异只影响依赖它的路径/模块，继续有效内容和页面交付，按上述参考披露范围，不作为新增发布门禁。
- 附加信息失败仅warnings（范围结果也可含roll_events_error），行情仍有效；不把它误判成必需角色失败/发布失败，不自动删掉行情。页面可用独立提示区显示缺失，不能把失败当作“无换月”。通用图表只归一化行情表格，不自动绘制换月标记；定制页从 `out[grant_id].data` 读取元信息显示。

404 Not Found: POST /skill/fastQueryMinuteRange 是后端接入/版本问题，不是资产无数据。真实后端、OSS CORS、授权有效期仍须联调；本地schema通过不代表上游或部署已就绪。


## 多资产分钟授权

kind为 `fast_query_minute_range_multi`，接入现有验证→注册→query→页面验收流程。QBV编排调用 `scripts/qbs_bridge.py validate_grant_set @params.json`，传同一task_id/user_query及带fingerprint的合同；成功后用返回的validation_receipt_file原样注册，不另开session。

```json
{"kind":"fast_query_minute_range_multi","payload":{"assets":["贵州茅台","SZ000001"],"date_mode":"rolling","lookback_trade_days":5,"start_minute":"09:30","end_minute":"10:00","timezone":"Asia/Shanghai"}}
```

- assets为1～5000个名称/简称/代码，兼容asset或market（cn_stock/cn_index/us_stock/hk_stock/cn_future/os_future），三选一。服务端匹配标准ticker，客户端不传tickers。无fields/format/remove_nan/旧自然日offset。
- absolute默认：start_date必填，end_date默认同日，真实YYYY-MM-DD或YYYYMMDD整数/字符串，包含首尾最多373自然日。禁止rolling参数。
- rolling：lookback_trade_days为1～373整数，默认1；end_trade_offset为-372～0整数，默认0。按服务端日历取最近收盘且超过30分钟缓冲日，再向前偏移（外盘默认按上游会话日口径）；不传start_date/end_date。
- current_trade_day禁止所有日期/回看参数，返回最近已开始交易日，休市不保证有新记录。自动日期模式跨日历域必须拆开。
- start_minute/end_minute为每日过滤窗口，HH:MM/HHMM（整数或字符串），含边界，null不限、0为00:00；timezone默认Asia/Shanghai，仅过滤分钟，不改变trade_date。美股当地窗口用America/New_York，外盘期货当地窗口用America/Chicago，由服务端处理夏冬令时；外盘默认日期按上游会话日规则，不跳过节假日。
- 股票正向窗口；反向窗口支持国内期货+Asia/Shanghai（例如21:00～02:30）或境外期货+America/Chicago（例如17:00～02:30）；夜盘依trade_date，不按自然日重分组。
- with_adjustment默认false，仅附股票split事件，不复权。分钟覆盖先读[覆盖表](../references/minute-data-coverage.md)，新接口不扩大来源覆盖。
- 注册强制真实试跑，不能validate_data=false。冻结资产/市场与日期规则，rolling/current_trade_day每次取数重算日期；market冻结范围规则，不冻结当天名单。_contract_version由服务端内部保存，客户端不传。
- 历史窗口和交易中/收盘缓冲期单日分成两份授权。不要反复刷新包含实时数据的历史CSV，不自行裁剪日期绕过服务端检查。
- 查询只提交grant_id/signature，禁止覆盖资产/日期。refreshDataGrant为重新验证，日常刷新使用queryDataGrant；动态计费归owner，不叠加旧授权固定查询费。

业务JSON为 `columns` + `data` 二维数组，CSV为 **url/url_expires_at**（不是旧接口csv_url）；CSV columns可省略，以文件表头为准，shape也可能省略。前两列trade_date/ticker，timestamp为UTC秒；按真实列名读取。Python验证器及QB.queryGrant物化CSV为columns/rows，JSON原始data保留，build_dashboard前后端均可归一成表格。多资产图表必须按ticker分组，不能把不同资产连为一条曲线。现有单资产30分钟聚合器不接此多资产产物。

页面保存授权配置，刷新先queryDataGrant取本次manifest，不能硬编码临时URL；大CSV优先展示下载入口或缩小范围后做图，避免高频全量下载。generated_at为数据生成时点，start_date/end_date为实际解析日期，lifecycle保留交易中/缓冲/完成状态，不能把刷新时间当数据日期。

合法empty成功应展示无数据；空表、全无有效行情或unrouted不足以证明必需角色已完成，不发成功验收收据。warnings/adjustment保留，附加事件失败不抹掉主行情。

直接接口失败code=-1，授权沿既有code=1/error；同时检查HTTP和业务code。按error.code/guidance处理：HISTORICAL_REALTIME_MIXED_NOT_ALLOWED拆历史和当前日，MIXED_CALENDAR_DOMAIN拆市场，QUERY_BUDGET_EXCEEDED缩范围；日历/策略缺失联系维护者，不在页面造工作日日历。429按Retry-After等待，超时后台可能仍在运行，不立即重发；CSV下载401/403/404最多重新query授权一次，禁止循环。

后端须部署fastQueryMinuteRangeMulti及同名授权kind；工具/本地回归通过不代表生产端到端已验收。

## 美股及国内商品期权槽位合约授权

支持部分美股和国内商品品种；国内股指期权暂未开放。合约身份只读assignment，不是行情检查或完整期权链。
QBS使用query_option_contracts验证，QBV通过qbs_bridge.py validate_grant_set获取收据，再原样注册；无需公式包。
国内依赖配套skill_server及新增dataServer任务，不能仅凭Skill更新宣称接口上线。

```json
{"kind":"option_contracts","payload":{"asset":"螺纹钢","slots":["E1-ATM-CALL","E1-25P"],"query_type":"snapshot"}}
```

```json
{"kind":"option_contracts","payload":{"asset":"RB.SHF","slots":["E1-ATM-CALL"],"query_type":"window","lookback_days":90,"mode":"changes"}}
```

- asset为单个名称/简称/代码，复用多字段匹配；国内使用商品品种，不传具体月份合约。slots省略查全部八槽，E1/E2不是期货主力/次主力。
- snapshot禁止lookback_days/mode；返回最新已生效记录，保留实际trade_date。国内全部请求槽取同日完整批次，empty也必须保留。
- window的lookback_days为1～366整数自然日，包含市场截止日，mode默认daily或changes；changes包含首条基准。
- 美股截止日为纽约当地今天；国内按北京时间和品种夜盘所属交易日，夜盘可能对应下一交易日。日历不足返回明确服务错误。
- 公开参数由skill_server转换，各市场Celery只收ticker/start_date/end_date/slots/mode，不附加行情检查任务。
- 授权冻结标准资产/市场/品种/槽位/查询规则，不冻结日期；网页只用grant_id/signature，不能覆写资产或范围。
- 美股保留原十一项记录字段；国内增加decision_date、underlying_contract、status，empty时额外返回empty_reason，data另有product_id。
- empty为有效选约状态，合约及规格为null，不补旧active合约；active↔empty计为changed，empty→empty不计；无前序为null。
- previous_date有值而previous_contract为空代表真实前序为空槽；strike为十进制字符串，不按代码猜测规格或使用锚点代替真实标的。
- build_dashboard展示中文合约字段、空槽、真实标的、原因和实际业务日期。所有槽位为空也可展示为空槽映射，records空数组仍是暂不可用。
- 页面按行情实际trade_date匹配映射，多日行情使用window daily；不能把最新snapshot合约标到旧行情上。映射存在不代表行情更新，也不保证精确重放历史发布批次。
- 400按error.parameter/error.usage改正；502批次/数据异常、503配置/日历/服务问题、504超时按既有失败流程处理，不立即重复提交。
- 过期、撤销和签名轮换沿用既有规则。刷新失败保留上次有效内容并明确失败，不更改业务日期。

## 外盘期货分钟授权

资产与起点按[外盘覆盖表](../references/minute-data-coverage.md#外盘期货主力连续)逐ticker检查；三个既有kind沿用原验证和刷新流程。单日仍传asset+fields，历史Range不传fields/format；多资产示例：

```json
{"kind":"fast_query_minute_range_multi","payload":{"assets":["ES.CME","TU.CBT"],"start_date":"2021-11-01","end_date":"2021-12-10","start_minute":"08:30","end_minute":"15:00","timezone":"America/Chicago"}}
```

全市场用market=os_future替换assets。TU在2021-12-01前的缺口须在页面说明，不能截掉ES可用的更早记录；所有资产都越界时不注册。页面保留coverage_by_ticker/warnings，标明实际数据日期，不把起点或可刷新授权当作最新端已更新保证。

外盘分钟Range授权附roll_events，RangeMulti授权仅解析去重后单资产时附同结构roll_events，多资产和market请求不附带；单日分钟授权的contract_info仅解释所选分钟会话来源合约。外盘fast_query日频授权不使用这些事件，日频换月信息当前缺失。kind/payload与计费不变。事件缺失/旧上游不支持时保留可用行情、披露警告，不把缺失当无换月；详见[外盘换月入口](../references/continuous-futures.md#外盘换月返回入口2026-10-28)。
