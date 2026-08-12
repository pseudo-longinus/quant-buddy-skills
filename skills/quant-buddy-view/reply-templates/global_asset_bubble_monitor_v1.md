---
id: global_asset_bubble_monitor_v1
version: reply_template_v1
output_format: markdown
default_reply_scope: full_answer
source_playbooks:
  - 01_macro_event.md
  - 09_dashboard_guidance.md
---

# Global Asset Bubble Monitor

用于“全球资产泡沫监测”专页。只展示页面公式包实际返回的泡沫温度与宏观压力字段，不补造短期收益、板块或资金流结构。

## Output Contract

- 泡沫温度固定映射：上证 `SH_pos/SH_bias`、沪深300 `HS3_pos/HS3_bias`、创业板 `CYB_pos/CYB_bias`、科创50 `KC5_pos/KC5_bias`、恒生 `HSI_pos/HSI_bias`、纳指100 `NDX_pos/NDX_bias`、标普500 `SPX_pos/SPX_bias`。
- 宏观压力只展示本轮实际返回的 `CN10Y/US10Y/SPREAD/DXY/VIX/M2/SF`；未返回的整项直接删除。
- 每项写自己的最新可得日期。不得用单一日期包装异步数据。
- 结构性不存在的字段、整列、整行和整章节直接删除；只有有效结构中的单个偶发缺值可写 `--`。
- 不得加入当日涨跌、近5日、近20日、板块异动、融资余额、北向资金、主力资金或账户操作表。

## Markdown Skeleton

```markdown
【结论行】{基于当前泡沫温度与宏观压力的核心判断。}

## 泡沫温度

| 指数 | 最新日期 | 区间位置 | 偏离度 | 状态 |
|------|----------|---------:|-------:|------|
| {index_name} | {latest_date} | {position} | {bias} | {status} |

## 宏观压力

| 指标 | 最新日期 | 最新值 | 观察 |
|------|----------|-------:|------|
| {macro_name} | {latest_date} | {latest_value} | {interpretation} |

## 风险与口径

- {实际覆盖的市场、指标和日期口径。}
- 位置与偏离度用于描述拥挤和高温，不预测泡沫破裂时点。
- {当前数据的其他限制。}

## 公开链接

- [打开实时活页]({public_url})

> 数据以各指标最新可得日期为准；仅供研究，不构成投资建议。
```
