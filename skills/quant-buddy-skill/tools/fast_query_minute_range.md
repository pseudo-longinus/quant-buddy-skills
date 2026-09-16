# fast_query_minute_range — 单资产历史跨日分钟 CSV

真实工具名 `fast_query_minute_range`，后端 `POST /skill/fastQueryMinuteRange`。原生工具可用时直接调用；没有原生绑定时才按现有 CLI fallback 使用 `scripts/call.py fast_query_minute_range @params.json`。新增声明不会自动更新宿主已经加载的工具列表；服务端也须包含该路由。

## 什么时候用

用户要某个资产历史日期/跨交易日的原始1分钟数据、历史分时或分钟CSV下载。不要把它降级为日频 fast_query，也不要用单日 fast_query_minute 冒充历史区间。

| 场景 | 工具 |
|---|---|
| 当前/最近完整交易日分钟 | fast_query_minute，保留 fields |
| 单资产历史分钟窗口 | fast_query_minute_range，不提供 fields |
| 最新标量、日频窗口 | fast_query snapshot/window，保留 fields |

先按资产库规则确认唯一资产。接口不支持多资产、日内时分筛选、5分钟聚合或自动复权。

## 分钟历史覆盖（调用前必查）

先阅读 [分钟行情支持范围与越界提示](../references/minute-data-coverage.md)。A股/美股股票与国内期货最早 **2026-05-13**，港股股票 **2026-05-20**，国内指数 **2026-08-13**；美国/香港指数及期货暂不支持。请求早于对应起点时必须先提示：全窗口越界不调用，部分重叠说明缺失区间、保留原请求窗口并如实交付可用部分。不得将返回的首条数据夸大为完整历史覆盖。

## 参数

| 参数 | 规则 |
|---|---|
| asset | 唯一资产名称/ticker，非数组 |
| start_date + end_date | 成对的 YYYY-MM-DD，双端包含；end_date 必须早于起点加三个日历月（夹紧月末） |
| start_offset / end_offset | 与绝对日期互斥；-70至-1整数**自然日**偏移；默认昨天。仅start_offset时终点-1，仅end_offset时为该单日 |

禁止 fields、format、remove_nan、window_days、trade_date、assets。返回固定CSV全列、全行，不按缺失值过滤；不能只改manifest假装已经裁列。原两个工具的 fields 不受此变化影响。

日期不得包含**市场当地今天或未来**（即使今天已经收盘）；最终时区/日期边界以服务端为准。休市日可返回空，不自动改查更早交易日。task_id/turn_id/user_query 由既有追踪通道透传，不参与行情或缓存键。

```json
{"asset":"SH600519","start_date":"2026-06-01","end_date":"2026-06-30"}
```

```json
{"asset":"C.DCE","start_offset":-5,"end_offset":-1}
```

## 返回与CSV消费

```json
{
  "code":0,
  "data":{
    "status":"ok","query_type":"minute_range","interval":"1min",
    "data_scope":"historical","mode":"csv","ticker":"C.DCE","timezone":"Asia/Shanghai",
    "start_date":"2026-06-01","end_date":"2026-06-30",
    "shape":[100,8],"csv_url":"https://example.invalid/history.csv",
    "csv_expires_at":"2026-09-16T02:00:00Z"
  }
}
```

示例仅表达结构。`columns` 可缺省，以实际CSV首行表头为准，不猜固定六列。**CSV是长表 `trade_date,timestamp,open,...`，不是日频的 `ticker,name,<dates...>` 宽表**；不能用 fetch_fastquery_csv.py 的宽表模式解析它。

下载文件即可满足纯导出请求；需读取完整数据时，把工具JSON响应存为本地文件，使用专用受控读取器：

```bash
python scripts/fetch_minute_range_csv.py @output/minute-manifest.json --output output/minute-data.json
```

在 skill 根目录运行；manifest和输出均放在本skill/output内，可为这些文件使用绝对路径。该脚本只消费返回的签名URL，不会重新取数；输出完整数据文件与SHA256收据，不把整份分钟矩阵刷到终端。保留所有列、全空行情行、null及扩展列；不复权、不补0。此产物为 `qb_minute_range_artifact_v1`，不是日频series capsule，不能冒充旧日频胶囊交给活页构建器。

`timestamp` 是UTC秒；显示时按 timezone 转换。`trade_date` 是交易日归属，期货夜盘自然日可能不同，换月必须按 trade_date 匹配。

## 附加信息与错误

- 连续期货附 `roll_events`，包含窗口内生效交易日、新旧合约和两条合约生效日各自原始**日频**收盘价；不把它解释为换月瞬间价格，不改变分钟价。
- 股票 adjustment 仅窗口内 split 事件，不承诺全历史复权链。
- 换月查询失败/超时/格式异常只附 warnings/roll_events_error；主行情成功则继续使用CSV，不把警告当作工具失败，也不伪造“无换月”。窗口查询不需要手工回看6/12/24个月；该策略仅供服务端确认单日具体合约。
- 明确空结果：empty=true、csv_url=null、shape=[0,0]，不是系统错误，也不是0价格。
- 直接调用每个认证用户滚动12小时最多10次，缓存命中也计次；Data Grant试跑/刷新/页面查询不计该专属次数。超限按 Retry-After 等待，不换key或拆请求规避。
- 行情CSV结果缓存12小时；附加事件成功短缓存60秒、失败不缓存。链接失效先通过原工具/Grant重新取得有效manifest，不能延长字符串中的到期时间或循环访问旧URL。
- 404表示后端路由/版本接入未到位，不能声称该资产无数据；CSV_EXPORT_FAILED需核对真实链接寿命；这些与仅附加换月失败不同。

要做实时取数活页：交给 quant-buddy-view 的 `data_grant`，kind=`fast_query_minute_range`。公开页面用Grant签名，不嵌API Key，不把一次性CSV URL当成长期数据源。绝对窗口保持固定，offset授权每天按市场日期滚动；本工具始终不包含今天。
