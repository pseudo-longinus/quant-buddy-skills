# fast-report-period · 最近报告期财务

适用：≤3 只 A 股；`fast_query` 单次调用。港股/美股财务不支持，直接告知。

## 执行（3 步）

```
① 提取 assets + fields → ② fast_query(query_type="report", user_query=<用户原始问题>) → ③ 取值输出
```

> **`user_query` 必填**：调用 `fast_query` 时仍需在参数中携带用户原始问题，供服务端 trace 分析（不依赖 call.py 自动注入）。

停止：`success: true` 且全部字段有 `value` + `date` → 立刻输出。

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

## 输出规则

- 元值换算亿元（÷1e8，保留 2 位小数）
- 首句：`{资产} 最新报告期（{date}）：{字段} {val}{unit}，…`
- 不同字段 date 不一致 → 分字段各自报告期，不合并计算派生指标

## 错误处理

| fast_query 返回 | 处理 |
|---|---|
| Layer 1 MARKET_NOT_SUPPORTED | 告知仅支持 A 股，退出 |
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
