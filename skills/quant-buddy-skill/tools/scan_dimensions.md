# scanDimensions — 九维度 IC 扫描

对单只股票执行八大维度的 IC 预测力全量扫描，返回每个维度的核心指标当前值、IC_IR（历史预测力）、综合评分及季节性统计。

**结果自动保存到** `output/ic_data/{股票名}_dimension_ic.json`，同时打印精简摘要。

---

## 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `asset` | object | ✅ | `{"name": "中控技术", "code": "688777.SH"}` |
| `industry` | string | 可选 | 行业指数名，如 `"自动化设备（申万）"` |
| `dimensions` | string\[\] \| `"all"` | 可选 | 指定要扫描的维度；缺省或 `null` = 全量 8 维度 |
| `begin_date` | number | 可选 | 历史计算起始日 YYYYMMDD，默认 `20160101` |
| `task_id` | string | 可选 | 由 `call.py` 自动从 `.session.json` 注入 |

**`dimensions` 合法值**：
`D1_估值` / `D3_资金` / `D4_波动率` / `D5_宏观胜率` / `D6_相关资产` / `D7_技术形态` / `D8_季节性` / `D9_财务`

---

## 调用规范

> **🚫 禁止全量调用**（`dimensions` 参数缺省、`null` 或 `"all"`）——会触发所有 8 维度并行计算，耗时 3-5 分钟，体验极差。
> **✅ 必须每次只传一个维度**，扫完立即读取结果，再扫下一个。结果自动合并到同一 JSON，不覆盖已有维度。

---

## 标准调用顺序（每次一个维度，执行后立即读取结果）

```bash
# ① 技术形态（~40 RU，最快）
python scripts/call.py scanDimensions '{"asset":{"name":"中控技术","code":"688777.SH"},"dimensions":["D7_技术形态"]}'

# ② 估值（需要 industry 参数）
python scripts/call.py scanDimensions '{"asset":{"name":"中控技术","code":"688777.SH"},"industry":"自动化设备（申万）","dimensions":["D1_估值"]}'

# ③ 资金
python scripts/call.py scanDimensions '{"asset":{"name":"中控技术","code":"688777.SH"},"dimensions":["D3_资金"]}'

# ④ 波动率
python scripts/call.py scanDimensions '{"asset":{"name":"中控技术","code":"688777.SH"},"dimensions":["D4_波动率"]}'

# ⑤ 宏观胜率
python scripts/call.py scanDimensions '{"asset":{"name":"中控技术","code":"688777.SH"},"dimensions":["D5_宏观胜率"]}'

# ⑥ 相关资产
python scripts/call.py scanDimensions '{"asset":{"name":"中控技术","code":"688777.SH"},"dimensions":["D6_相关资产"]}'

# ⑦ 财务（~90 RU，公式最多）
python scripts/call.py scanDimensions '{"asset":{"name":"中控技术","code":"688777.SH"},"dimensions":["D9_财务"]}'

# ⑧ 季节性（纯统计，最快）
python scripts/call.py scanDimensions '{"asset":{"name":"中控技术","code":"688777.SH"},"dimensions":["D8_季节性"]}'
```

> **合并机制**：每次调用结束后，`call.py` 自动读取已有 JSON → 合并新维度 → 重算 `overall_score` / `overall_signal` / `top_dimension` / `bottom_dimension` → 写回文件。摘要输出中的 `file_has_dimensions` 字段显示文件当前已积累几个维度，`note` 字段提示还剩哪些未扫。

---

## 响应结构（精简摘要，完整数据见 JSON 文件）

```json
{
  "code": 0,
  "data": {
    "asset": {"name": "中控技术", "code": "688777.SH"},
    "scan_date": 20260317,
    "overall_score": 52,
    "signal": "中性 ->",
    "dimensions": {
      "D1_估值": {
        "score": 48,
        "signal": "中性",
        "indicators": [
          {"name": "PE水位", "current": 0.91, "ic_ir": -0.45},
          {"name": "PB水位", "current": 0.76, "ic_ir": -0.38}
        ]
      },
      "D7_技术形态": {
        "score": 63,
        "signal": "偏强",
        "indicators": [
          {"name": "MACD金叉", "current": 1, "ic_ir": 2.10},
          {"name": "站上MA20", "current": 1, "ic_ir": 1.85}
        ]
      }
    },
    "saved_to": "output/ic_data/中控技术_dimension_ic.json",
    "note": "完整结果已保存到文件，直接使用以上数据构建报告"
  },
  "task_id": "..."
}
```

---

## RU 成本

| 扫描范围 | 估算 RU |
|----------|---------|
| 全量 8 维度 | ~320 RU |
| 单维度（如 D7） | ~68 RU |
| 自定义 3 维度 | ~150 RU |

计费公式：`base(26) + Σdim_ru`，各维度 RU：D1=36 / D3=48 / D4=30 / D5=30 / D6=24 / D7=42 / D8=6 / D9=84

---

## 注意事项

- 扫描期间**不要并发执行其他 API 调用**，避免 `.session.json` 并发写入导致 task_id 漂移
- **执行前先检查缓存**：若 `output/ic_data/{股票名}_dimension_ic.json` 已存在且为今日，直接读取，跳过调用
- 结果 JSON 包含所有维度的完整指标数据，Step 4 写报告直接从中取值，无需再调 `readData`
