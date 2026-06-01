# 快速执行 · 行情/估值快照与固定区间序列

> **适用范围**：≤1000 个资产，查询最新交易日的行情/估值字段（标量），或固定日期范围内的行情/估值最后有效值/完整序列。含"今天/今日/当日/当前/现在/实时/盘中"的单资产行情查询也属于本 workflow 适用范围。
> 本 workflow 使用 `fast_query` 单次调用完成（无需 runMultiFormulaBatchStream / readData）。
> **日内刷新**：`query_type="snapshot"` 且不传 `start_date` 时，服务端自动启用盘中刷新——盘中返回最后一分钟行情，收盘后返回收盘价。无需在参数中额外声明任何 `use_minute_data` 字段。

---

## 执行步骤（4 步，严格顺序）

```
① 从用户意图提取 assets、fields 和可选日期范围（参照下方字段映射表）
→ ② 调用 newSession（若本轮尚未显式调用；调用 fast_query 前不可省略）
→ ③ 资产解析（见下方「资产解析硬规则」：批量 grep + 跨市场唯一性）
→ ④ 调用 fast_query（query_type="snapshot"；区间序列时传 result_mode="series"）
→ ⑤ 从 value/date 或 series[] 提取结果，输出最终答案
```

**停止条件**：fast_query 返回 `success: true`，且 `results.{资产名}` 中目标字段均有值 → 立刻停止，不得再调用任何工具。

### 资产解析硬规则（步骤 ③，修复 T-042 逐个 grep / T-003·T-044 跨市场同名）

1. **批量 grep（多资产必须）**：用户给出多个资产时，**一次** grep 用 `名1|名2|名3|…` 合并匹配，禁止对每个名字单独 grep。仅对未命中项再补查。
2. **跨市场唯一性（用户只给名称、未带市场/后缀时）**：grep 必须**跨市场**搜索（`presets/assets_db/stock_a.yaml`、`stock_hk.yaml`、`stock_us.yaml`、`index.yaml` 一并检索，而非默认只搜 `stock_a.yaml`）。
   - 同一名称在 ≥2 个市场命中（如「宁德时代」= A股 SZ300750 + 港股 HK3750）→ **必须先向用户确认选哪个市场，禁止默认 A 股后继续查数**。
   - 用户已给完整代码/后缀（如 `000063`、`HK0700`）→ 做完整代码精确匹配，禁止按数字子串模糊命中选资产。
3. **未命中表述**：某资产跨市场均未命中 → 只能说「当前资产库未识别到『{名称}』，本次未返回该资产数据」；**禁止**写「请核对名称/代码是否有误」之类把原因归到用户的表述。其余已命中资产正常输出（多资产时 `options.partial_ok = true`，先返回已识别结果，未识别项单列说明，不因个别未命中中断整批）。

---

## ① 字段映射表（fields 参数写法）

> ⚠️ 估值字段市场范围：**PE/PE_TTM/PB/PS_TTM/股息率/PCF** 支持 A/US/HK（TTM〔估值数据〕，日频，港美股自动映射）；**总市值** 支持 A/US/HK；**流通市值、换手率** 仅 A 股。

| 用户描述的字段 | 传入 fields 的写法 | 返回 unit | 备注 |
|---|---|---|---|
| 收盘价 / 最新价 / close | `收盘价` | 元 | |
| 开盘价 / open | `开盘价` | 元 | |
| 最高价 / high | `最高价` | 元 | |
| 最低价 / low | `最低价` | 元 | |
| 涨跌幅 / 日涨幅 / 回报率 / pct_change | `涨跌幅` | % | value 已 ×100，直接加 % |
| 成交额 / amount | `成交额` | 元 | |
| 成交量 / volume | `成交量` | 股 | |
| PE / 市盈率TTM / PE_TTM | `PE_TTM` | 倍 | A/US/HK |
| PB / 市净率 | `PB` | 倍 | A/US/HK |
| 市销率 / PS_TTM | `PS_TTM` | 倍 | A/US/HK |
| 总市值 / 市值 | `总市值` | 亿元 | A/US/HK |
| 流通市值 | `流通市值` | 亿元 | 仅 A 股 |
| 换手率 / turnover | `换手率` | % | 仅 A 股 |
| 股息率 / dividend | `股息率` | % | A/US/HK |
| PCF / 市现率 | `PCF` | 倍 | A/US/HK |
| PCF（现金净流量） | `PCF_现金净流量` | 倍 | A/US/HK |
| PE（单季）/ PE_单季 | `PE_单季` | 倍 | A/US/HK |
| PB（单季）/ PB_单季 | `PB_单季` | 倍 | A/US/HK |
| 市销率（单季）/ PS_单季 | `PS_单季` | 倍 | A/US/HK |
| 股息率（单季）/ 股息率_单季 | `股息率_单季` | % | A/US/HK |

> 字段不在上表时：原样传入 `fields`，服务端自动解析（约 +2s）。

---

## ② 调用示例

> ⛔ **leaf 级硬闸门（重复声明 SKILL.md 硬规则 1，每次进入本 workflow 都必须遵守）**：
> 调用 `fast_query` 之前必须先调用 `newSession`。若本轮上一步只有 `Read` / `Grep` / `read_skill_file` 痕迹而没有 `newSession` 调用记录，**第一件事就是 `newSession`，不是 `fast_query`**。
> 这条规则优先级高于"参数已经提取完毕"等任何后续步骤说明；跳过 `newSession` 直接调 `fast_query` = MISSING_NEW_SESSION 契约失败（HIGH 级）。

> ⛔ **P0 红线**：调用 `fast_query` 前必须以本节示例为参数模板构造请求体，禁止自行推断参数结构；必传字段 `query_type`、`assets`、`fields` 缺一不可，不得用 `query` 等非标字段替代。

> **`user_query` 必填**：调用 `fast_query` 时仍需在参数中携带用户原始问题，供服务端 trace 分析（不依赖 call.py 自动注入）。

最新值 / 区间最后有效值使用默认 `result_mode="value"`，可省略：

```json
{
  "assets": ["贵州茅台", "比亚迪"],
  "query_type": "snapshot",
  "fields": ["收盘价", "涨跌幅", "PE_TTM"],
  "user_query": "<用户的原始问题>"
}
```

固定区间最后有效值：

```json
{
  "assets": ["贵州茅台"],
  "query_type": "snapshot",
  "fields": ["收盘价", "PE_TTM"],
  "start_date": 20210101,
  "end_date": 20211231,
  "user_query": "<用户的原始问题>"
}
```

固定区间完整序列：

```json
{
  "assets": ["贵州茅台"],
  "query_type": "snapshot",
  "fields": ["收盘价"],
  "start_date": 20210101,
  "end_date": 20211231,
  "result_mode": "series",
  "user_query": "<用户的原始问题>"
}
```

---

## ③ 取值与输出规则

### value 模式（默认）— compact 字典格式

- 响应为字典：`results.{资产名}.{字段名}` 直接是数值（日期已提升到顶层 `dates.{date_type}`）
- 若某字段值是对象 `{v, d, fallback}` 而非数字，说明该字段日期与公共日期不同（fallback 回退），取 `v` 为值、`d` 为日期
- 单位从 `fields_meta.{字段名}.unit` 获取
- **涨跌幅**：值已是百分比数（如 `-2.74`），直接加 `%`，**不再乘 100**
- 未传日期范围时，`dates.trade_date` 为最新交易日；若早于当前自然日，声明「以下为最后可得交易日 YYYY-MM-DD 的数据」
- 传入日期范围时，值为该区间内最后一个有效值

**输出首句格式**：`{资产名} 最新数据（{dates.trade_date}）：{字段1} {value1}{unit}，{字段2} {value2}{unit}…`

#### 指数类资产口径覆盖（强规则，修复 T-005 指数说成「元」）

当资产是**指数**（命中 `presets/assets_db/index.yaml`，或用户明确问「指数/点位」，或 ticker 为指数代码如 `000300.SH`/`000905.SH`）时，价格类字段的对外单位必须改写，**不得照抄 `fields_meta.unit` 的「元」**：

| 字段 | 指数对外表述 | 单位 |
|---|---|---|
| 收盘价 | 收盘点位 | 点 |
| 开盘价 | 开盘点位 | 点 |
| 最高价 | 最高点位 | 点 |
| 最低价 | 最低点位 | 点 |

- 涨跌幅、换手率等百分比字段不受影响，仍用 `%`。
- 个股的价格字段仍用「元」，本规则只对指数生效。

#### 单资产快照简答规范（修复 T-001 过度格式化）

工具已返回最终标量时，默认按**工具原值、原单位、原精度**直答（一句话或短列表）：
- 除非用户明确要求，不擅自把「元」换算成「亿元/万元」、不对百分比额外四舍五入、不改字段名口径。
- 用户已给「中文名 + 代码」时，回答优先沿用用户写法（如 `中兴通讯（000063）`），平台 ticker 可补充但不替代用户写法。

#### 日期解释硬规则（修复 T-001 类回答漂移）

- 字段对应的交易日期 = `dates.<fields_meta.<字段>.date_type>`（通常是 `dates.trade_date`）；这是回答中**唯一可用**的"交易日期"来源。
- **禁止**仅凭工具未明确返回的元信息（如 `meta.latest_trade_date`、`query_time_ms`、对话外部的"今天/最新交易日"）自行写出"真正最新交易日是 X，但快照返回是 Y"之类的二元日期说明。
- 工具未显式声明数据延迟时，禁止追加任何"数据延迟"/"非实时"解释；只输出 `字段 + 数值 + dates.trade_date`，由用户自行判断。
- 多字段日期不一致（部分字段返回 fallback 对象 `{v, d, fallback}`）时，按各字段自带的 `d` 标注真实日期，禁止用 `dates.trade_date` 强行覆盖。

固定区间最后有效值首句：`{资产名} 在 {start_date} 至 {end_date} 的最后可得数据（{date}）：{字段1} {value1}{unit}…`

### series 模式 — compact 列式格式

- `results.{资产名}.dates` 为共享日期轴（升序），`results.{资产名}.{字段名}` 为等长值数组
- 若某字段日期轴不同（如混合 trade_date + report_period），该字段值为 `{dates: [...], values: [...]}`
- 单位从 `fields_meta.{字段名}.unit` 获取
- **涨跌幅序列**：值已是百分比数，直接加 `%`，**不再乘 100**
- 若用户只要走势/序列，按 dates 对应输出日期和值；若用户要区间统计，可基于值数组计算最高、最低、首末变化等简单统计

---

### CSV 模式（数据点 > 500 时自动触发）

当查询的资产 × 字段 × 日期数 > 500 时，服务端自动返回 CSV 模式（`mode: "csv"`）。

- 检查响应 `mode` 字段：若为 `"csv"`，按 CSV 模式处理
- 向用户汇报 `summary` 中的资产数、字段数、总数据点数
- **禁止**在对话中逐行展开 CSV 内容
- 用户要走势/序列/具体数值时：调 `python scripts/fetch_fastquery_csv.py "<csv_url>" --labels <字段>` 下载解析后据其 JSON 作答（每字段一个 url，url 整体加引号；许可路径，见 `SKILL.md` 硬规则 2 csv 例外）
- 仅当用户明确要导出 CSV 文件时：直接给 `csv_fields[].csv_url` + `summary`，无需解析

---

## 错误处理（退出规则）

| fast_query 返回 | 处理方式 |
|---|---|
| Layer 1（ASSETS_EXCEED_LIMIT / DATA_POINTS_EXCEED_LIMIT / DAILY_*_EXCEEDED） | 告知用户超限，按错误 message 引导缩小范围或明天重试 |
| Layer 1（MISSING_START_DATE / INVALID_DATE_RANGE / INVALID_RESULT_MODE / DATE_RANGE_WINDOW_CONFLICT） | 退出 fast path → `global-rules.md` → `quick-snapshot.md` 或完整链路 |
| Layer 1（任何其他 code） | 退出 fast path → `global-rules.md` → `quick-snapshot.md` |
| Layer 2（ASSET_NOT_FOUND） | 告知用户该资产未识别；其余资产结果正常输出 |
| Layer 3（FIELD_MARKET_MISMATCH） | 告知用户该字段仅支持 A 股（如流通市值/换手率/ROE） |
| Layer 3（FIELD_UNRESOLVABLE） | 告知用户字段不在支持范围，其余字段正常输出 |
| Layer 4（DATA_UNAVAILABLE） | **立即退出 fast path → 完整链路**；禁止重试 fast_query，禁止 confirmDataMulti 换字段名后再重试 |
| HTTP 500 / 任何网络错误 | **立即退出 fast path → 完整链路**；禁止重试同一接口 |

---

## 保护规则（4 条）

1. **evidence-only**：只输出 `results.{资产名}.{字段名}` 中的实际值；禁止推断归因
2. **去过程化**：首句必须是资产名 + 数据结论；禁止「已成功获取」「让我来」等话术
3. **涨跌幅**：值已是百分比数，直接加 `%`，**不再乘 100**
4. **条件冻结**：用户条件原样传入，不改写
