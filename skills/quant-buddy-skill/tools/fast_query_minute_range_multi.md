# fast_query_minute_range_multi — 多资产 / 全市场原始1分钟行情

后端 `POST /skill/fastQueryMinuteRangeMulti`。优先直接调用同名原生工具；没有原生绑定时沿用 `scripts/call.py fast_query_minute_range_multi @params.json`。工具声明不会自动更新宿主已加载的工具列表，后端也须部署该路由。

## 选择工具

| 需求 | 工具 |
|---|---|
| 单资产当前/最近完整日、指定OHLCVA字段 | `fast_query_minute` |
| 单资产历史全日CSV、自然日负offset | `fast_query_minute_range` |
| 多资产/全市场、每日分钟窗口、最近N个交易日或当前交易日规则 | `fast_query_minute_range_multi` |

先按现有资产库规则确认市场和类型，资产名称、简称、代码原样放入 `assets`，由服务端匹配标准代码。分钟覆盖范围沿用[覆盖表](../references/minute-data-coverage.md)；不因新增批量接口扩大历史覆盖或假设所有资产均有数据。不确定资产时先澄清，不能把名称数组放进内部 `tickers`。

## 参数

| 参数 | 合同 |
|---|---|
| `assets` / `asset` / `market` | 必须且只能选一个。assets为1～5000个名称/简称/代码；asset兼容单资产；market为cn_stock/cn_index/us_stock/hk_stock/cn_future |
| `date_mode` | absolute（默认）/rolling/current_trade_day |
| `start_date` / `end_date` | 仅absolute；start必填、end默认同日；YYYY-MM-DD或YYYYMMDD整数/字符串，含首尾最多373自然日 |
| `lookback_trade_days` | 仅rolling，1～373整数，默认1，真实交易日 |
| `end_trade_offset` | 仅rolling，-372～0整数，默认0=最近收盘且超过30分钟缓冲的交易日；-1再向前一天 |
| `start_minute` / `end_minute` | 每个交易日分别过滤，含边界；HH:MM或HHMM整数/字符串；null不限，0=00:00 |
| `timezone` | 默认Asia/Shanghai；IANA时区，只影响分钟过滤，不改变trade_date归属。美股当地时段显式用America/New_York |
| `with_adjustment` | 布尔值，默认false；附股票窗口内split事件，价格仍为原始未复权值 |

禁止 `tickers`、`fields`、`format`、`remove_nan`、旧自然日offset及其他未知参数；task_id/turn_id/user_query沿既有追踪通道透传。不要给客户端添加 `format=auto`，由服务端在一次Celery派发前决定json/csv。

- absolute禁止rolling参数，可跨市场；rolling禁止绝对日期；current_trade_day禁止日期和回看参数。
- rolling/current_trade_day必须属于同一日历域，跨域拆开。日历由服务端查询真实交易日，不在skill里推导工作日/节假日。
- current_trade_day取最近已开始的交易日；休市可能返回最近已完成日，不保证当下有新数据。
- 历史与仍更新的交易日（包括收盘后至少30分钟缓冲）必须分成历史窗口和当前单日两请求/授权。不要静默裁剪日期或扩大查询。
- 股票必须正向分钟窗口；反向窗口仅全为国内期货且timezone=Asia/Shanghai，例如21:00～02:30，仍按同一trade_date取夜盘/凌晨。不要按自然日重分组。
- 5000资产/373日是参数上限，不保证任意组合可执行。预算拒绝后按用户目标缩小范围，避免自动全市场大批重试。

```json
{"assets":["贵州茅台","SZ000001"],"date_mode":"rolling","lookback_trade_days":5,"start_minute":"09:30","end_minute":"10:00"}
```

```json
{"market":"cn_future","start_date":"2026-10-09","start_minute":"21:00","end_minute":"02:30","timezone":"Asia/Shanghai"}
```

## 返回与消费

先检查HTTP状态和外层 `code===0`。业务结果在 `data`，没有请求参数副本：

- `mode=json`：按 `columns` 对应 `data` 二维数组读取。前两列trade_date/ticker，timestamp为UTC秒，其余按实际列名读取。混合市场缺列值为null，保留0与全空行情行。
- `mode=csv`：下载地址是 **`url` / `url_expires_at`**，不是旧接口的csv_url/csv_expires_at；shape/file_size为文件规模，columns可缺省，以CSV表头为准。CSV同样是trade_date,ticker,...长表，不能用日频宽表解析器。
- `empty=true` 是合法空结果，不冒充有数据；`unrouted` 和 `warnings` 原样说明，不把附加split失败当主行情失败。
- start_date/end_date是服务端实际解析日期；lifecycle为active/settling/completed_recent/completed_history；generated_at是数据生成时点，不能改成访问时间。

纯导出展示下载链接、到期时间和规模；需要计算时，沿用受控读取器消费已保存的完整响应（JSON和CSV均支持）：

```bash
python scripts/fetch_minute_range_csv.py @output/minute-multi-response.json --output output/minute-multi-data.json
```

产物为 `qb_minute_range_multi_artifact_v1`，保留ticker/交易日/UTC时间戳、所有列及警告，不打印整份矩阵。旧单资产30分钟聚合器不接受此多资产产物；需要派生数据时按ticker+trade_date独立聚合并显式标注来源与派生间隔，不把原始1分钟改名冒充30分钟。

## 错误与授权

失败沿现有 `code=-1/success=false/error` 结构，读取error.code/message/guidance/parameter/details和task_id。输入错误按提示修改；HISTORICAL_REALTIME_MIXED_NOT_ALLOWED拆历史/当前日，MIXED_CALENDAR_DOMAIN按市场日历拆，QUERY_BUDGET_EXCEEDED缩范围。CALENDAR_UNAVAILABLE/CALENDAR_NIGHT_COVERAGE_UNAVAILABLE及配置错误联系维护者，不改用户参数绕过。429等待Retry-After；超时任务可能仍运行，不立即重发。404路由不存在属于部署问题，不是资产无数据。

QBV数据授权kind同名 `fast_query_minute_range_multi`，payload就是上述业务参数。注册有真实试跑，不能validate_data=false；冻结资产/市场和日期规则，rolling/current_trade_day每次取数动态解析，禁止浏览器覆盖参数。历史和实时用两份独立授权；查询只交grant_id/signature，refreshDataGrant是重新验证，不是每日刷新。由QBV现有授权验证、登记、内核和发布流程处理；外层授权失败code=1，不能套用直接接口code=-1。
