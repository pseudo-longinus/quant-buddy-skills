# 快速执行 · 最近 N 日短窗序列 / 固定区间序列

> **适用范围**：≤1000 个资产，最近 N 日（1~2500）序列或固定日期范围序列（行情/成交）；窗口统计量。  
> 本 workflow 使用 `fast_query` 单次调用完成（无需 runMultiFormulaBatchStream / readData）。

---

## 执行步骤（4 步，严格顺序）

```
① 从用户意图提取 assets、fields，以及窗口参数：window_days（1~2500）或 start_date/end_date（二选一）
→ ② 调用 newSession（若本轮尚未显式调用；调用 fast_query 前不可省略）
→ ③ 资产解析（见下方「资产解析硬规则」：批量 grep + 跨市场唯一性）
→ ④ 调用 fast_query（query_type="window"；传 window_days=N 或 start_date/end_date；不传 result_mode）
→ ⑤ 从 results.{资产名} 的列式数据提取结果，输出最终答案
```

### 资产解析硬规则（步骤 ③，修复 T-044 跨市场同名 / 多资产逐个 grep）

1. **批量 grep（多资产必须）**：多个资产时一次 grep 用 `名1|名2|…` 合并匹配，仅对未命中项补查；禁止逐个 grep。
2. **跨市场唯一性（用户只给名称、未带市场/后缀时）**：grep 必须跨 `stock_a.yaml`/`stock_hk.yaml`/`stock_us.yaml`/`index.yaml` 检索，不得默认只搜 `stock_a.yaml`。同名在 ≥2 个市场命中 → **先向用户确认市场，禁止默认 A 股继续查数**。用户已给完整代码 → 完整代码精确匹配，禁止数字子串模糊命中。
3. **未命中表述**：跨市场均未命中 → 只能说「资产库未识别到『{名称}』」，禁止写「请核对名称/代码」。
4. **指数口径**：若资产是指数（命中 `index.yaml` 或指数代码），价格序列对外表述为「点位」、单位「点」，不写「元」（参照 `fast-snapshot.md` 指数口径覆盖表）。

**N > 2500 时**：安全失败，告知用户「最多支持 2500 日窗口（约 10 年交易日），请缩小范围」。

**停止条件**：fast_query 返回 `success: true`，目标序列已到手 → 立刻停止。

**report_period 稀疏序列收敛规则**：当 `fast_query(window)` 成功返回 `date_type="report_period"`，或目标字段是港/美股单季估值、财报/报告期口径字段时，`series` 稀疏不是失败。若用户只要求区间走势、最高/最低值、有效日期或序列展示，应直接基于已返回的 `series` 回答，并说明该字段按报告期更新、不是逐交易日连续数据；禁止仅因序列稀疏升级到 `confirmDataMulti` / `runMultiFormulaBatchStream` / `readData` 链路。

---

## ① 参数提取规则

| 参数 | 提取方式 |
|---|---|
| `assets` | 用户提到的资产（≤1000） |
| `fields` | 参照 fast-snapshot.md 字段映射表（行情字段；估值字段 `PE_TTM`/`PB`/`PS_TTM`/`股息率`/`PCF`/`总市值` 及单季版 `PE_单季`/`PB_单季`/`PS_单季`/`股息率_单季` 在 window 模式同样支持 A/US/HK；`流通市值`/`换手率` 仅 A 股） |
| `window_days` | 用户说”最近 N 日”时使用（整数，1~2500）；与 `start_date`/`end_date` 二选一 |
| `start_date`/`end_date` | 用户给出明确起止日期时使用，格式 YYYYMMDD |

注意：
- 不传 `result_mode`：`window` 固定返回 `series[]`，无需显式传
- `window_days` 与 `start_date`/`end_date` 同时传时优先使用日期范围（忽略 window_days）

**begin_date（服务端自动管理）**：

| window_days | 服务端 begin_date |
|---|---|
| ≤ 20 | 今天 − 3 个月 |
| 21 ~ 60 | 今天 − 6 个月 |
| > 60 | 服务端自动扩展 |

> 本 workflow 无需手动设 begin_date，服务端已处理。

---

## ② 调用示例

> **`user_query` 必填**：调用 `fast_query` 时仍需在参数中携带用户原始问题，供服务端 trace 分析（不依赖 call.py 自动注入）。

```json
{
  "assets": ["贵州茅台"],
  "query_type": "window",
  "fields": ["收盘价", "涨跌幅"],
  "window_days": 10,
  "user_query": "<用户的原始问题>"
}
```

多资产示例：

```json
{
  "assets": ["贵州茅台", "比亚迪"],
  "query_type": "window",
  "fields": ["收盘价"],
  "window_days": 5,
  "user_query": "<用户的原始问题>"
}
```

固定日期区间示例：

```json
{
  "assets": ["贵州茅台"],
  "query_type": "window",
  "fields": ["收盘价", "涨跌幅"],
  "start_date": 20250101,
  "end_date": 20250331,
  "user_query": "<用户的原始问题>"
}
```

---

## ③ 序列取值与统计规则（compact 列式格式）

- `results.{资产名}.dates` 为升序日期数组，`results.{资产名}.{字段名}` 为等长值数组；日期轴不同的字段为 `{dates: [...], values: [...]}`
- 值数组长度 = window_days（或日期范围内的数据点数）

### 序列题强制后处理（硬规则，修复 T-038 类最值日期错答）

当响应结构含 `dates[]` + 同字段 `values[]` 时，**必须先做 date-value 配对再得结论**：

1. 在内部构造数组 `pairs = [{date: dates[i], value: values[i]} for i in range(len(dates))]`。
2. `min_value / min_date / max_value / max_date / first / last` 一律基于 `pairs` 计算，禁止凭肉眼扫长数组直接口述。
3. 校验：报出的 `min_date` 对应的 value 必须真等于 `min(values)`；`max_date` 同理。任一校验未过，**禁止输出**，先内部修正再回答。
4. 用户要求"每日走势 / 日度序列 / 逐日 / 每个交易日"时，区间长度 ≤ 60 个交易日的情况下**默认附完整 `(date, value)` 表格**；只给摘要不给逐日表 = 违反 Publish Discipline。

### 统计与展示

- **只需统计量**（最高/最低/区间收益/振幅）→ 直接从值数组计算，无需额外工具调用：
  - 窗口最高 = `max(值数组)`（同时取出对应日期）
  - 窗口最低 = `min(值数组)`（同时取出对应日期）
  - 区间收益 = `(末值 - 首值) / 首值 × 100%`
  - 振幅 = `(窗口最高 - 窗口最低) / 窗口最低 × 100%`
- **涨跌幅** 值已 ×100，为百分比数，直接展示加 `%`
- dates 已升序，直接按序展示，禁止中间暴露「排序」过程

---

### CSV 模式（数据点 > 500 时自动触发）→ 下载解析后作答（强规则）

当 资产 × 字段 × 日期数 > 500 时，服务端**按设计**返回 CSV 模式（`mode:"csv"`，每个字段一个 `csv_url`，OSS 链接、有有效期）。**CSV 链接是大数据量的正常交付路径，不是失败**；但**把链接直接丢给用户不算完成**——除非用户明确只要下载文件。

处理（默认：用户要走势/序列/对比/统计）：
1. 对响应里每个 `csv_fields[].csv_url`，调用本 skill 脚本下载并解析（url 含 `&`，**必须整体加引号**；多字段一次传多个 url，`--labels` 按顺序对应 `csv_fields[].intent`）：
   ```
   python scripts/fetch_fastquery_csv.py "<csv_url1>" ["<csv_url2>" ...] --labels <字段1>,<字段2>
   ```
2. 脚本输出 JSON：每个资产的 `first / last / min / max / count / period_return_pct`（要逐日序列再加 `--full`，大序列按 `--max-points` 截断并标注 `series_truncated`）。
3. 据脚本输出作答：实际日期区间 + 各资产 首值/末值/最高/最低 + 区间涨跌幅 + 1~3 条总体观察；明细多时不必逐日展开，但**不得只给链接无摘要**。

> 这是「消费工具返回的 csv_url」，是**许可路径**，不受「禁止 Bash 包装原生工具」约束（见 `SKILL.md` 硬规则 2 的 csv 解析例外）。脚本对某个 url 报 `error` 时，按其错误说明该字段未取到、其余字段正常作答；**不要**改用裸 `curl`/自写解析绕过脚本。

仅当用户明确要「导出/下载原始明细 CSV 文件」时：直接给 `csv_url` + 汇报 `summary`（资产数/字段数/总点数），无需下载解析；禁止在对话中逐行展开 CSV 内容。

---

## 错误处理

| fast_query 返回 | 处理方式 |
|---|---|
| Layer 1（ASSETS_EXCEED_LIMIT / WINDOW_DAYS_EXCEED_LIMIT / DATA_POINTS_EXCEED_LIMIT / DAILY_*_EXCEEDED） | 告知用户超限，按错误 message 引导 |
| Layer 1（MISSING_WINDOW_PARAMS / INVALID_WINDOW_DAYS） | 退出 fast path → `global-rules-lite.md` → `quick-window.md` |
| Layer 2（ASSET_NOT_FOUND） | 告知用户，其余资产正常输出 |
| Layer 3（FIELD_MARKET_MISMATCH / FIELD_UNRESOLVABLE） | 告知用户，其余字段正常输出 |
| Layer 4（DATA_UNAVAILABLE） | **立即退出 fast path → 完整链路（newSession → grep presets/assets_db/{类型}.yaml → runMultiFormulaBatchStream → readData）**；禁止重试 fast_query，禁止 confirmDataMulti 换字段名后再重试 |
| HTTP 500 / 任何网络错误 | **立即退出 fast path → 完整链路**；禁止重试同一接口 |

---

## 保护规则（4 条）

1. **仅窗口内计算**：所有统计只能基于 `series` 返回的 N 行数据
2. **去过程化**：首句必须是资产名 + 数据结论；禁止过程性话术
3. **涨跌幅**：`value` 已是百分比数，直接加 `%`，**不再乘 100**
4. **序列展示**：按日期升序输出，禁止中间暴露排序过程
