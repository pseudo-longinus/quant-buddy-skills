# 快速执行 · 最新时点行情/估值快照

> **适用范围**：≤3 个资产，查询最新交易日的行情/估值字段（标量）。  
> 本 workflow 使用 `fast_query` 单次调用完成（无需 confirmMultipleAssets / runMultiFormulaBatch / readData）。

---

## 执行步骤（3 步，严格顺序）

```
① 从用户意图提取 assets 和 fields（参照下方字段映射表）
→ ② 调用 fast_query（query_type="snapshot"）
→ ③ 从 results[].fields[].value + date 提取结果，输出最终答案
```

**停止条件**：fast_query 返回 `success: true`，目标字段均有 `value` → 立刻停止，不得再调用任何工具。

---

## ① 字段映射表（fields 参数写法）

> ⚠️ 估值字段（PE/PB/总市值/换手率/股息率）仅适用于 A 股。

| 用户描述的字段 | 传入 fields 的写法 | 返回 unit | 备注 |
|---|---|---|---|
| 收盘价 / 最新价 / close | `收盘价` | 元 | |
| 开盘价 / open | `开盘价` | 元 | |
| 最高价 / high | `最高价` | 元 | |
| 最低价 / low | `最低价` | 元 | |
| 涨跌幅 / 日涨幅 / 回报率 / pct_change | `涨跌幅` | % | value 已 ×100，直接加 % |
| 成交额 / amount | `成交额` | 元 | |
| 成交量 / volume | `成交量` | 股 | |
| PE / 市盈率TTM / PE_TTM | `PE_TTM` | 倍 | 仅 A 股 |
| PB / 市净率 | `PB` | 倍 | 仅 A 股 |
| 市销率 / PS_TTM | `PS_TTM` | 倍 | 仅 A 股 |
| 总市值 / 市值 | `总市值` | 亿元 | 仅 A 股 |
| 流通市值 | `流通市值` | 亿元 | 仅 A 股 |
| 换手率 / turnover | `换手率` | % | 仅 A 股 |
| 股息率 / dividend | `股息率` | % | 仅 A 股 |

> 字段不在上表时：原样传入 `fields`，服务端自动解析（约 +2s）。

---

## ② 调用示例

> **`user_query` 必填**：调用 `fast_query` 时仍需在参数中携带用户原始问题，供服务端 trace 分析（不依赖 call.py 自动注入）。

```json
{
  "assets": ["贵州茅台", "比亚迪"],
  "query_type": "snapshot",
  "fields": ["收盘价", "涨跌幅", "PE_TTM"],
  "user_query": "<用户的原始问题>"
}
```

---

## ③ 取值与输出规则

- 每字段取 `results[i].fields[j].value` 和 `fields[j].date`
- `unit` 字段已给出单位，直接使用
- **涨跌幅**：`value` 已是百分比数（如 `-2.74`），直接加 `%`，**不再乘 100**
- `date` 为最新交易日；若 `date` 早于当前自然日，声明「以下为最后可得交易日 YYYY-MM-DD 的数据」

**输出首句格式**：`{资产名} 最新数据（{date}）：{字段1} {value1}{unit}，{字段2} {value2}{unit}…`

---

## 错误处理（退出规则）

| fast_query 返回 | 处理方式 |
|---|---|
| Layer 1（任何 code） | 退出 fast path → `global-rules.md` → `quick-snapshot.md` |
| Layer 2（ASSET_NOT_FOUND） | 告知用户该资产未识别；其余资产结果正常输出 |
| Layer 3（FIELD_MARKET_MISMATCH） | 告知用户该字段仅支持 A 股 |
| Layer 3（FIELD_UNRESOLVABLE） | 告知用户字段不在支持范围，其余字段正常输出 |
| Layer 4（DATA_UNAVAILABLE） | **立即退出 fast path → 完整链路**；禁止重试 fast_query，禁止 confirmDataMulti 换字段名后再重试 |
| HTTP 500 / 任何网络错误 | **立即退出 fast path → 完整链路**；禁止重试同一接口 |

---

## 保护规则（4 条）

1. **evidence-only**：只输出 `results[].fields[].value`；禁止推断归因
2. **去过程化**：首句必须是资产名 + 数据结论；禁止「已成功获取」「让我来」等话术
3. **涨跌幅**：`value` 已是百分比数，直接加 `%`，**不再乘 100**
4. **条件冻结**：用户条件原样传入，不改写
