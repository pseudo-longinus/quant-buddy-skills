# 快速执行 · 最近 N 日短窗序列/窗口统计

> **适用范围**：≤3 个资产，最近 N 日（1~60）的价格/成交序列或窗口统计量。  
> 本 workflow 使用 `fast_query` 单次调用完成（无需 runMultiFormulaBatch / readData）。
> 固定起止日期范围不属于本 workflow；应改走 `fast-snapshot.md + result_mode="series"` 或完整链路。

---

## 执行步骤（4 步，严格顺序）

```
① 从用户意图提取 assets、fields 和 window_days（1~60）
→ ①.5 对每个 asset 执行 grep presets/assets_db/{类型}.yaml 查本地库：
       命中唯一 → 用 ticker（如 SH600303）替换原始中文名传参
       命中多条（歧义）→ 向用户澄清选哪个，禁止继续查数
       未命中 → 保留原始名称，由服务端兜底解析
→ ② 调用 fast_query（query_type="window", window_days=N；不传 result_mode/start_date/end_date）
→ ③ 从 results[].fields[].series 提取数据，输出最终答案
```

**N > 60 时**：安全失败，告知用户「最多支持 60 日窗口；如需更长窗口，请走完整链路」。

**固定日期范围**：本 workflow 禁止传 `start_date/end_date`；用户给出明确起止日期且要走势/序列时，改读 `fast-snapshot.md` 并传 `result_mode="series"`。

**停止条件**：fast_query 返回 `success: true`，目标序列已到手 → 立刻停止。

---

## ① 参数提取规则

| 参数 | 提取方式 |
|---|---|
| `assets` | 用户提到的 1~3 个资产 |
| `fields` | 参照 fast-snapshot.md 字段映射表（行情字段；估值字段不适用窗口模式） |
| `window_days` | 用户明确说的 N（整数，1~60） |

禁止参数：
- 不传 `result_mode`：`window` 固定返回 `series[]`
- 不传 `start_date/end_date`：日期范围与 `window` 互斥

**begin_date（服务端自动管理）**：

| window_days | 服务端 begin_date |
|---|---|
| ≤ 20 | 今天 − 3 个月 |
| 21 ~ 60 | 今天 − 6 个月 |

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

---

## ③ 序列取值与统计规则

- `results[i].fields[j].series` 为 `[{value, date}, ...]` 升序时间序列，长度 = window_days
- **只需统计量**（最高/最低/区间收益/振幅）→ 直接从 `series` 计算，无需额外工具调用：
  - 窗口最高 = `max(series[*].value)`
  - 窗口最低 = `min(series[*].value)`
  - 区间收益 = `(末值 - 首值) / 首值 × 100%`
  - 振幅 = `(窗口最高 - 窗口最低) / 窗口最低 × 100%`
- **涨跌幅** `value` 已 ×100，为百分比数，直接展示加 `%`
- 按日期升序展示，禁止中间暴露「排序」过程

---

## 错误处理

| fast_query 返回 | 处理方式 |
|---|---|
| Layer 1（MISSING_WINDOW_DAYS / INVALID_WINDOW_DAYS / WINDOW_DAYS_OUT_OF_RANGE） | 退出 fast path → `global-rules-lite.md` → `quick-window.md` |
| Layer 1（DATE_RANGE_WINDOW_CONFLICT） | 改走 `fast-snapshot.md + result_mode="series"` 或完整链路 |
| Layer 1（ASSETS_LIMIT_EXCEEDED 等） | 退出 fast path → 完整链路 |
| Layer 2（ASSET_NOT_FOUND） | 告知用户，其余资产正常输出 |
| Layer 3（FIELD_MARKET_MISMATCH / FIELD_UNRESOLVABLE） | 告知用户，其余字段正常输出 |
| Layer 4（DATA_UNAVAILABLE） | **立即退出 fast path → 完整链路（newSession → grep presets/assets_db/{类型}.yaml → runMultiFormulaBatch → readData）**；禁止重试 fast_query，禁止 confirmDataMulti 换字段名后再重试 |
| HTTP 500 / 任何网络错误 | **立即退出 fast path → 完整链路**；禁止重试同一接口 |

---

## 保护规则（4 条）

1. **仅窗口内计算**：所有统计只能基于 `series` 返回的 N 行数据
2. **去过程化**：首句必须是资产名 + 数据结论；禁止过程性话术
3. **涨跌幅**：`value` 已是百分比数，直接加 `%`，**不再乘 100**
4. **序列展示**：按日期升序输出，禁止中间暴露排序过程
