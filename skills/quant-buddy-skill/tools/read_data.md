# read_data — 读取/验证计算结果

> 读取 `runMultiFormulaBatch` 生成的数据（indexInfo / matrixInfo），用于签名检查、采样、统计、表格读取，或按日期区间读取完整连续数据。

## 端点

`POST /skill/readData`

## 数据类型

接口自动识别数据类型：

| 类型标识 | 来源 | 说明 |
|---|---|---|
| `two_dimensional` | indexInfo（dimension = `two`） | 二维矩阵（assets × dates），如行情、因子、选股信号 |
| `one_dimensional` | indexInfo（dimension = `one-row`） | 一维时间序列，如净值、指数序列 |
| `matrix_table` | matrixInfo（含 table_json） | 表格数据，如选股结果表 |

## 通用参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|------|------|
| `ids` | string[] | ✅ | — | 数据 ID 数组（indexInfo / matrixInfo 的 `_id`），最多 10 个，超过须分批调用 |
| `mode` | string | ❌ | `signature` | 查询模式，见下方 mode 说明 |
| `start_date` | number | ❌ | — | 起始日期，格式 `YYYYMMDD` |
| `end_date` | number | ❌ | — | 结束日期，格式 `YYYYMMDD` |
| `decimal_places` | number | ❌ | `4` | 小数位数，最大 10 |
| `include_distribution` | boolean | ❌ | `false` | 是否额外计算分布信息 |
| `align_samples` | boolean | ❌ | `true` | 多数据采样时是否返回顶层 `aligned_comparison` |
| `anchor_index` | number | ❌ | `0` | 多数据对齐锚点索引 |
| `task_id` | string | ❌ | 自动注入 | 任务 ID。通过 `scripts/call.py` 调用时通常无需传入 |

> `align_samples` 不支持 `per_asset_sample`、`precheck`、`table_data` 模式。

## mode 说明

| mode | 用途 | 支持数据类型 | 专用参数 |
|------|------|-------------|----------|
| `signature`（默认） | 返回数据签名、轻量预览采样和最后一列统计 | 二维 / 一维 / 表格 | `include_samples`、`preview_assets`、`preview_points`、`sparse_threshold` |
| `smart_sample` | 智能采样查看具体数值 | 二维 / 一维 / 表格（表格走 `table_data`） | `top_assets`、`sample_points` |
| `per_asset_sample` | 每个资产单独采样 | 二维 | `top_assets`、`sample_points` |
| `last_day_stats` | 最后一个有效交易日的截面统计 | 二维 / 一维 | — |
| `last_column_full` | 最后一个有效列的完整截面；一维数据返回时间序列 | 二维 / 一维 | `max_rows`、`allow_zero_values` |
| `last_valid_per_asset` | 每个资产取最后一个有效值，适合跨市场或不同更新频率数据 | 二维 / 一维 | `max_rows` |
| `range_data` | 指定日期区间内的完整连续原始数据，不采样 | 二维 / 一维 | `start_date`、`end_date`、`assets`、`max_cells`、`nan_handling` |
| `precheck` | 数据质量预检查，可配合 `expected` 做断言式校验 | 二维 / 一维 | `expected` |
| `table_data` | 读取 matrixInfo 表格数据，支持排序和分页 | 表格 | `top_n_assets`、`last_m_columns`、`sort_by`、`sort_order` |

## mode = `range_data`

返回指定日期区间内的**完整连续数据**，不做任何采样。适用于需要读取原始连续数据做本地合成计算、区间收益复核、图表补齐或导出片段的场景。

### 参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|------|------|
| `start_date` | number | ✅ | — | 起始日期，格式 `YYYYMMDD` |
| `end_date` | number | ✅ | — | 结束日期，格式 `YYYYMMDD` |
| `assets` | string[] | ❌ | 全部资产 | 仅二维数据有效；只返回指定资产子集 |
| `max_cells` | number | ❌ | `500000` | 单元格数量安全上限，最大 200 万；超限时截断日期轴 |
| `nan_handling` | string | ❌ | `keep` | NaN 处理策略：`keep` / `fill_forward` / `drop_rows` |

`nan_handling` 选项：

| 值 | 说明 |
|---|---|
| `keep` | 保留 NaN，响应中以 `null` 返回 |
| `fill_forward` | 向前填充；序列开头无法填充的 NaN 仍为 `null` |
| `drop_rows` | 去掉全 NaN 的资产行，仅二维数据有效 |

### 二维响应结构

```json
{
  "id": "6651a...",
  "data_type": "two_dimensional",
  "signature": { "shape": { "assets": 5000, "dates": 244 } },
  "range_data": {
    "dates": [20240101, 20240102, 20240103],
    "assets": ["000001", "600519"],
    "names": ["平安银行", "贵州茅台"],
    "values": [
      [10.5, 10.8, 10.6],
      [1800.0, 1795.5, 1810.0]
    ],
    "shape": { "assets": 2, "dates": 3 },
    "nan_handling": "keep",
    "is_truncated": false,
    "warning": null
  }
}
```

> `values[i][j]` 对应 `assets[i]` 在 `dates[j]` 的值。

### 一维响应结构

```json
{
  "id": "6651a...",
  "data_type": "one_dimensional",
  "signature": { "shape": { "dates": 244 } },
  "range_data": {
    "dates": [20240101, 20240102, 20240103],
    "series_name": "沪深300指数",
    "values": [3450.5, 3462.1, 3448.8],
    "shape": { "dates": 3 },
    "nan_handling": "keep",
    "is_truncated": false,
    "warning": null
  }
}
```

### 截断响应

```json
{
  "range_data": {
    "shape": { "assets": 5000, "dates": 100 },
    "is_truncated": true,
    "warning": "数据量过大（1220000 > 500000），日期轴已截断至 100 个交易日"
  }
}
```

### 调用示例

```bash
# 读取一维/二维数据的完整区间，不采样
python scripts/executor.py readData '{
  "ids": ["6651a0b1c2d3e4f5a6b7c8d9"],
  "mode": "range_data",
  "start_date": 20240101,
  "end_date": 20241231
}'

# 只读取指定资产，并向前填充 NaN
python scripts/executor.py readData '{
  "ids": ["6651a0b1c2d3e4f5a6b7c8d9"],
  "mode": "range_data",
  "start_date": 20240101,
  "end_date": 20241231,
  "assets": ["000001", "600519", "000858"],
  "nan_handling": "fill_forward"
}'

# 控制返回规模
python scripts/executor.py readData '{
  "ids": ["6651a0b1c2d3e4f5a6b7c8d9"],
  "mode": "range_data",
  "start_date": 20200101,
  "end_date": 20241231,
  "max_cells": 1000000
}'
```

## 常见参数错误

| 错误写法 | 正确写法 | 说明 |
|---------|---------|------|
| `{"variable_names": ["趋势放量背景"]}` | `{"ids": ["60a1b2c3d4e5f6a7b8c9d0e1"]}` | 参数名是 `ids`，不是 `variable_names`；值必须是 data_id，不是中文变量名 |
| `{"ids": ["NAV", "收盘价"]}` | `{"ids": ["60a1b2...", "60a1b3..."]}` | ids 不接受变量名，只接受数据 ID |
| `{"ids": [...], "mode": "table_data", "sample_points": 12}` | `{"ids": [...], "mode": "table_data"}` | `table_data` 不支持 `sample_points` 和 `align_samples` |
| `{"ids": [...], "mode": "range_data"}` | `{"ids": [...], "mode": "range_data", "start_date": 20240101, "end_date": 20241231}` | `range_data` 必须指定起止日期 |

## 注意事项

- `ids` 使用 `runMultiFormulaBatch` 返回的 `data_id`，或 `confirmDataMulti` 返回的 `_id`。
- 仅验证结果是否合理时，优先用 `signature` / `smart_sample` / `precheck`，避免读取大体量完整数据。
- 需要完整连续原始数据时，用 `range_data`，不要用采样结果做精确计算。
- `range_data` 可能返回大数组；跨多年、全市场二维数据必须设置较窄日期区间、`assets` 子集或 `max_cells`。
- 需要最新截面排名时用 `last_column_full`；需要每个资产最新有效值时用 `last_valid_per_asset`。
- `table_data` 仅适用于 matrixInfo 表格数据；二维矩阵和一维时间序列不要使用 `table_data`。
