# fast-report-period · 财务报告期快照与固定区间序列

适用：≤1000 只 A股/港股/美股；查询最近报告期财务，或固定日期范围内的财务最后有效值/完整序列；`fast_query` 单次调用。港股/美股财务不要静态拒答，应先尝试 `fast_query(query_type="report")`，按工具实际返回决定是否支持。

## 执行（5 步）

```
① 提取 assets + fields + 可选日期范围
→ ② 调用 newSession（若本轮尚未显式调用；调用 fast_query 前不可省略）
→ ③ 对每个 asset 执行 grep presets/assets_db/{类型}.yaml 查本地库：
       命中唯一 → 用 ticker（如 SH600303）替换原始中文名传参
       命中多条（歧义）→ 向用户澄清选哪个，禁止继续查数
       未命中 → 保留原始名称，由服务端兜底解析
→ ④ fast_query(query_type="report", user_query=<用户原始问题>；区间序列时传 result_mode="series")
→ ⑤ 取值输出
```

> **`user_query` 必填**：调用 `fast_query` 时仍需在参数中携带用户原始问题，供服务端 trace 分析（不依赖 call.py 自动注入）。

停止：`success: true` 且 `results.{资产名}` 中全部字段均有值 → 立刻输出。

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

### value 模式（默认）— compact 字典格式

- `results.{资产名}.{字段名}` 直接是数值；日期从顶层 `dates.report_period` 获取
- 若某字段值是对象 `{v, d, fallback}` 而非数字，取 `v` 为值、`d` 为实际报告期日期
- 单位从 `fields_meta.{字段名}.unit` 获取
- 元值换算亿元（÷1e8，保留 2 位小数）
- 首句：`{资产} 最新报告期（{dates.report_period}）：{字段} {val}{unit}，…`
- 固定区间最后有效值首句：`{资产} 在 {start_date} 至 {end_date} 的最后可得报告期（{date}）：{字段} {val}{unit}，…`
- 不同字段日期不一致（fallback 对象各有不同 `d`）→ 分字段各自报告期，不合并计算派生指标

#### report_period 复述规则（强规则，修复 T-039）

> Fast Path 不加载 global-rules.md，故此处显式声明证据边界。

**根源（务必理解，否则改不对）**：`report_period` 是一个**原始日期**（如 `2026-03-31`）。模型看到日期会本能地"帮用户翻译"成"第几季度 / 第几财季"——这是越界补全：① 用户没要这个映射；② 工具没返回这个映射；③ **港美股财年≠自然年**（如阿里巴巴财年 3 月底结束），一翻译就错（把 `2026-03-31` 说成"2025 年第四季度"是错的，它是自然年 Q1）。工具其实已经把**口径**标全了（`hint` 与 `index_title` 都写了「单季、非累计」），缺的从来不是口径，而是**约束模型别去翻译日期**。

**因此**：
- 报告期**只能原样复述 `dates.report_period`（YYYY-MM-DD）** + 字段值 + `hint`/`fields_meta` 已明确的口径（如「单季、非累计值」）。
- **禁止**把 `report_period` 翻译/推断成任何工具未返回的标签：「某年Qx」「某财年第x财季」「年报/中报/一季报/三季报」等一律不得输出（A 股也不例外——即使你"算得出"，也属于工具外补全）。
- 用户主动问「这是第几季度/财年」时，只能答「工具返回的报告期为 {report_period}，单季口径；未提供财季/财年映射」，不得推断。

> 一句话：**report_period 是日期不是季度名。照抄日期 + 工具已标的「单季」，绝不把日期翻译成季度/财年。**

### series 模式 — compact 列式格式

- `results.{资产名}.dates` 为升序日期数组，`results.{资产名}.{字段名}` 为等长值数组
- 若某字段日期轴不同，该字段值为 `{dates: [...], values: [...]}`
- 元值字段对值数组逐项换算亿元（÷1e8，保留 2 位小数）
- 百分比字段（ROE、净利率、资产负债率、毛利率）直接加 `%`，不再乘 100
- dates 已升序，直接按序展示；若用户只问序列，不额外推断趋势原因

### CSV 模式（数据点 > 500 时自动触发）

当查询的资产 × 字段 × 日期数 > 500 时，服务端自动返回 CSV 模式（`mode: "csv"`）。

- 检查响应 `mode` 字段：若为 `"csv"`，按 CSV 模式处理
- **禁止**在对话中逐行展开 CSV 内容
- 用户要具体数值/序列时：调 `python scripts/fetch_fastquery_csv.py "<csv_url>" --labels <字段>` 下载解析后据其 JSON 作答（许可路径，见 `SKILL.md` 硬规则 2 csv 例外）
- 仅当用户明确要导出 CSV 文件时：直接给 `csv_fields[].csv_url` + `summary`（资产数/字段数/总点数），无需解析

## 错误处理

| fast_query 返回 | 处理 |
|---|---|
| Layer 1 ASSETS_EXCEED_LIMIT / DATA_POINTS_EXCEED_LIMIT / DAILY_*_EXCEEDED | 告知用户超限，按错误 message 引导 |
| Layer 1 MARKET_NOT_SUPPORTED | 按工具返回说明当前市场暂不支持该 report 查询，退出 |
| Layer 1 INVALID_RESULT_MODE | 修正为 `value/series` 或退出 → `global-rules.md` → `quick-report-period.md` |
| Layer 1 MISSING_START_DATE / INVALID_DATE_RANGE | 退出 → `global-rules.md` → `quick-report-period.md` 或完整链路 |
| Layer 1 DATE_RANGE_WINDOW_CONFLICT | report 不应触发；若触发则退出 fast path |
| Layer 1 其他 | 退出 → `global-rules.md` → `quick-report-period.md` |
| Layer 2 ASSET_NOT_FOUND | 告知，其余资产继续 |
| Layer 3 FIELD_MARKET_MISMATCH | 按工具返回说明该字段在当前市场不可用 |
| Layer 3 FIELD_UNRESOLVABLE | 见下方恢复流程 |
| Layer 4 其他 | 告知该字段暂无数据 |

### FIELD_UNRESOLVABLE 恢复（partial_ok: true）

```
① 保留 fast_query 已成功字段的值（不重查）
② 仅对失败字段：confirmDataMulti 确认字段全名
③ 若 confirmDataMulti 精确命中同一市场字段，再复用当前 session 调用 runMultiFormulaBatchStream（公式："字段全名"*取出(资产名)）；若只命中其他市场字段，直接告知字段不可用
④ readData → 合并①结果 → 输出
```

⚠️ 公式**只能用** `"字段全名"*取出(资产名)`，**禁止 LAST() 语法**  
⚠️ **不得**因 FIELD_UNRESOLVABLE 重读 `quick-report-period.md` 或 `global-rules.md`  
若 field_error 带 `fallback_hint`，优先按其操作。
