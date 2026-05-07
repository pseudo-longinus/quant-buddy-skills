# fast-report-period · 财务报告期快照与固定区间序列

适用：≤3 只 A 股；查询最近报告期财务，或固定日期范围内的财务最后有效值/完整序列；`fast_query` 单次调用。港股/美股财务不支持，直接告知。

## 执行（4 步）

```
① 提取 assets + fields + 可选日期范围
→ ①.5 对每个 asset 执行 grep presets/assets_db/{类型}.yaml 查本地库：
       命中唯一 → 用 ticker（如 SH600303）替换原始中文名传参
       命中多条（歧义）→ 向用户澄清选哪个，禁止继续查数
       未命中 → 保留原始名称，由服务端兜底解析
→ ② fast_query(query_type="report", user_query=<用户原始问题>；区间序列时传 result_mode="series")
→ ③ 取值输出
```

> **`user_query` 必填**：调用 `fast_query` 时仍需在参数中携带用户原始问题，供服务端 trace 分析（不依赖 call.py 自动注入）。

停止：`success: true` 且全部字段有 `value/date`（value 模式）或 `series[]`（series 模式）→ 立刻输出。

## 字段速查

| 用户说法 | 传 fields | unit |
|---|---|---|
| 营业收入/收入 | `营业收入` | 元 |
| 净利润 | `净利润` | 元 |
| 归母净利润 | `归母净利润` | 元 |
| 营业成本 | `营业成本` | 元 |
| 总资产 | `总资产` | 元 |
| 净资产 | `净资产` | 元 |
| 经营现金流 | `经营现金流` | 元 |
| 投资活动现金流 | `投资活动现金流` | 元 |
| 筹资活动现金流 | `筹资活动现金流` | 元 |
| ROE/净资产收益率 | `ROE` | % |
| 净利率 | `净利率` | % |
| 资产负债率 | `资产负债率` | %（派生） |
| 毛利率 | `毛利率` | %（派生） |

不在上表 → 原样传入，服务端解析（+2s）。

## 调用示例

最近报告期（默认 `result_mode="value"`）：

```json
{
  "assets": ["贵州茅台"],
  "query_type": "report",
  "fields": ["营业收入", "ROE"],
  "user_query": "<用户的原始问题>"
}
```

固定区间最后报告期值：

```json
{
  "assets": ["贵州茅台"],
  "query_type": "report",
  "fields": ["营业收入", "ROE"],
  "start_date": 20200101,
  "end_date": 20251231,
  "user_query": "<用户的原始问题>"
}
```

固定区间财务序列：

```json
{
  "assets": ["贵州茅台"],
  "query_type": "report",
  "fields": ["营业收入"],
  "start_date": 20200101,
  "end_date": 20251231,
  "result_mode": "series",
  "user_query": "<用户的原始问题>"
}
```

## 输出规则

### value 模式（默认）

- 每字段取 `results[i].fields[j].value` 和 `fields[j].date`
- 元值换算亿元（÷1e8，保留 2 位小数）
- 首句：`{资产} 最新报告期（{date}）：{字段} {val}{unit}，…`
- 固定区间最后有效值首句：`{资产} 在 {start_date} 至 {end_date} 的最后可得报告期（{date}）：{字段} {val}{unit}，…`
- 不同字段 date 不一致 → 分字段各自报告期，不合并计算派生指标

### series 模式

- 每字段取 `results[i].fields[j].series`，结构为 `[{date, value}, ...]`
- 元值字段对 `series[*].value` 逐项换算亿元（÷1e8，保留 2 位小数）
- 百分比字段（ROE、净利率、资产负债率、毛利率）直接加 `%`，不再乘 100
- 按日期升序展示；若用户只问序列，不额外推断趋势原因

## 错误处理

| fast_query 返回 | 处理 |
|---|---|
| Layer 1 MARKET_NOT_SUPPORTED | 告知仅支持 A 股，退出 |
| Layer 1 INVALID_RESULT_MODE | 修正为 `value/series` 或退出 → `global-rules.md` → `quick-report-period.md` |
| Layer 1 MISSING_START_DATE / INVALID_DATE_RANGE | 退出 → `global-rules.md` → `quick-report-period.md` 或完整链路 |
| Layer 1 DATE_RANGE_WINDOW_CONFLICT | report 不应触发；若触发则退出 fast path |
| Layer 1 其他 | 退出 → `global-rules.md` → `quick-report-period.md` |
| Layer 2 ASSET_NOT_FOUND | 告知，其余资产继续 |
| Layer 3 FIELD_MARKET_MISMATCH | 告知该字段仅 A 股 |
| Layer 3 FIELD_UNRESOLVABLE | 见下方恢复流程 |
| Layer 4 其他 | 告知该字段暂无数据 |

### FIELD_UNRESOLVABLE 恢复（partial_ok: true）

```
① 保留 fast_query 已成功字段的值（不重查）
② 仅对失败字段：confirmDataMulti 确认字段全名
③ newSession → runMultiFormulaBatch（公式："字段全名"*取出(资产名)）
④ readData → 合并①结果 → 输出
```

⚠️ 公式**只能用** `"字段全名"*取出(资产名)`，**禁止 LAST() 语法**  
⚠️ **不得**因 FIELD_UNRESOLVABLE 重读 `quick-report-period.md` 或 `global-rules.md`  
若 field_error 带 `fallback_hint`，优先按其操作。
