# RU 计费体系

> 更新于 2026-04-15。统一 RU（Resource Unit）体系，所有端点共享一个 RU 池。
> 每个请求按端点类型 + 请求参数动态扣减 RU（1～26 RU）。
> 规划流程时优先减少冗余调用。

---

## RU 权重速查表

| 工具 | 模式 | RU 消耗 | 说明 |
|------|:---:|:---:|------|
| `search_functions` | fixed | 1 | |
| `get_card_formulas` | fixed | 1 | |
| `upload_preview` | fixed | 1 | |
| `upload_confirm` | fixed | 1 | |
| `download_data` | fixed | 1 | |
| `render_kline` | fixed | 1 | |
| `re_render_chart` | fixed | 1 | |
| `read_data` | fixed | 2 | |
| `search_similar_cases` | fixed | 5 | |
| `confirm_multiple_assets` | deferred | 1～6 × 意图数 | DB 精确匹配 1 RU，LLM 路径 6 RU |
| `confirm_data_multi` | deferred | 1～26 × 意图数 | DB 精确匹配 1 RU，LLM 路径 26 RU |
| `run_multi_formula` | dynamic | **7 × 公式数** | 单次最多 20/30/40 个（free/plus/pro） |
| `scan_dimensions` | dynamic | **12 × 维度数** | 全维度(8) = 96 RU |
| `render_chart` | dynamic | **1 × 线数** | 如 3 条线 = 3 RU |

> **deferred 模式**：先预扣 1 RU/意图，请求完成后按实际路径补扣差额。
> **错误请求退款**：所有端点发生错误时（4xx/5xx），实际 RU 降为 1 RU。

---

## 配额池说明

| 池 | 重置方式 | 说明 |
|------|------|------|
| **窗口 RU** | 个人滚动（最早请求 +4h） | 不是全部一次恢复，按请求逐批恢复 |
| **日 RU** | 每天 00:00（北京时间） | 次日零点统一重置 |

---

## 场景成本参考

| 场景 | 典型 RU 消耗 |
|------|:---:|
| 单只股票价格/PE/PB | ~3 RU |
| 条件选股（1 条公式）| ~10 RU |
| 条件选股+回测（5 公式）| ~37 RU |
| IC 全维度扫描 | 96 RU |
