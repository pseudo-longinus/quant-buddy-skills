# fast_query_minute — 单资产日内分钟行情

> **真实工具名**：`fast_query_minute`  
> **服务端**：`POST /skill/fastQueryMinute`  
> **适用**：用户明确要某一只资产的分钟、分时、1 分钟、每分钟或日内 OHLCVA 序列。

## 调用前

1. 使用 `Grep` 在 `presets/assets_db/` 的对应资产库确认**唯一资产**；优先传确认后的 ticker/code。
2. 每个新问题先完成 `newSession`；追问先完成 `beginTurn`。task/turn 会由执行器自动注入，**不要**作为工具参数传入。
3. 只在用户需要完整分钟序列时使用。只问最新价、当前价或一个最新标量时，使用 `fast_query(query_type="snapshot")`。

## 市场覆盖

调用前按 [分钟行情支持范围](../references/minute-data-coverage.md) 确认市场与资产类型：美国/香港指数及期货暂不支持分钟行情，不能因日频可查就调用本工具。本工具仍只查询当前/最近完整交易日；用户指定历史日期时转 `fast_query_minute_range` 并执行对应最早日期提示，不能向本工具添加历史日期参数。

## 参数

```json
{
  "asset": "SH600000",
  "fields": ["close", "high", "low", "volume"]
}
```

| 参数 | 必填 | 说明 |
|---|---:|---|
| `asset` | 是 | 单个资产名称、ticker 或 code。不能是数组。|
| `fields` | 是 | 非空字段数组；按请求顺序返回，服务端会去重。|

### 支持字段

| canonical | 中文别名 |
|---|---|
| `open` | 开盘价 |
| `high` | 最高价 |
| `low` | 最低价 |
| `close` | 收盘价、最新价、现价、当前价 |
| `volume` | 成交量 |
| `amount` | 成交额、money |

## 严格边界

- 仅支持**单资产**。
- 不传、也不支持 `assets`、`trade_date`、`date`、`start_date`、`end_date`、`window_days` 或任意历史日期/时间区间。
- 不做分钟聚合；返回原始分钟 bar。
- 服务端根据 `tkrsInfo.market_id` 与市场 `trade_period` 自动选择：
  - `current_session`：当前盘中分钟数据；
  - `latest_completed`：最近完整交易日数据。

用户要求指定历史日/跨日原始分钟时，改用 `fast_query_minute_range`，不能偷换为本工具或日频。多资产、分钟聚合不属于两个单资产分钟工具的能力；按实际需求另行确认支持的路径。

## 返回结构

```json
{
  "code": 0,
  "data": {
    "success": true,
    "query_type": "minute",
    "interval": "1min",
    "asset_name": "浦发银行",
    "ticker": "SH600000",
    "trade_date": 20260807,
    "data_scope": "current_session",
    "timezone": "Asia/Shanghai",
    "dates": ["2026-08-07 09:31", "2026-08-07 09:32"],
    "fields": {
      "close": [10.01, 10.02],
      "high": [10.02, 10.03],
      "volume": [123456, 234567]
    }
  }
}
```

`dates[i]` 与每一个 `fields.<field>[i]` 是同一根分钟 bar；数组严格对齐，遇到空值保留 `null`，不得单独过滤某字段的空值。时间已经按资产市场时区格式化；回答时保留 `trade_date`、`data_scope` 和 `timezone` 的语义。

正常空结果会返回 `dates: []` 及每个请求字段对应的空数组；这不等同于资产解析失败。

## 错误处理

- `ASSET_NOT_FOUND`：重新核对本地资产库名称/ticker/code。
- `INVALID_MINUTE_FIELD`：只使用上述 OHLCVA 字段及别名。
- `UNSUPPORTED_MINUTE_MARKET`：该 `market_id` 尚未接入分钟行情。
- `UPSTREAM_MINUTE_QUERY_FAILED` / `MINUTE_QUERY_TIMEOUT`：说明分钟数据源暂不可用；如仍需要结果，向用户说明并考虑后续重试。

成功取得分钟序列后直接分析/回答并停止，不再额外调用 fast_query、readData 或公式链路重复取数。

## 连续期货附加返回（4.25.38）

主/次主连在行情 data 中增加 `contract_info: {"contract":"C2611.DCE","status":"inferred"}`。它对应**顶层 trade_date**（含夜盘归属或最近完整日回退），不是墙上“今天”。status=inferred 表示依据已有事件推导，不能宣称独立实时核验。

单日分钟不返回 roll_events、多日期 contracts、lookup_start_date，也无需 Agent 手工查换月。内部按需回看6→12→24个日历月，找到即停，共用最多2秒附加预算；这不是期货固定三个月换月的保证。无法确认时 contract=null、status=unavailable 并带 reason；附加查询失败另有 warnings。保留已成功 dates/fields，不因附加警告重查或降级行情，不把未知合约说成没有合约。

历史/跨日原始分钟改用 [fast_query_minute_range](fast_query_minute_range.md)，不要往本工具追加日期参数。**本工具仍需要 fields**。
