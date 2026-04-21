# read_data — 读取/验证计算结果

> 读取 `runMultiFormula` 生成的数据结果，用于验证选股是否合理、净值曲线是否正常、查看数值分布。

## 端点

`POST /skill/readData`

## 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `ids` | string[] | ✅ | 数据ID数组（来自 `runMultiFormula` 返回的 `data_id`），最多 10 个。超过须分批调用 |
| `mode` | string | ❌ | 查询模式，详见下方。默认 `verify` |
| `start_date` | number | ❌ | 起始日期（格式 20250101） |
| `end_date` | number | ❌ | 结束日期（格式 20251231） |
| `max_items` | number | ❌ | 限制返回条数，默认 20，最大 1000 |
| `decimal_places` | number | ❌ | 小数位数，默认 4，最大 10 |
| `sample_points` | number | ❌ | `smart_sample` 模式：采样时间点数，默认 12，最大 500 |
| `top_assets` | number | ❌ | `smart_sample` 模式：采样资产数，默认 3，最大 50 |
| `align_samples` | boolean | ❌ | 是否启用对齐采样，默认 true（多数据时按锚点对齐） |
| `anchor_index` | number | ❌ | 对齐锚点索引，默认 0 |
| `task_id` | string | ❌ | 任务ID（UUID） |

### ⚠️ 常见参数错误

| 错误写法 | 正确写法 | 说明 |
|---------|---------|------|
| `{"variable_names": ["趋势放量背景"]}` | `{"ids": ["60a1b2c3d4e5f6a7b8c9d0e1"]}` | 参数名是 `ids`，不是 `variable_names`；值必须是 `runMultiFormula` 返回的 24位 hex data_id，不是中文变量名 |
| `{"ids": ["NAV", "收盘价"]}` | `{"ids": ["60a1b2...", "60a1b3..."]}` | ids 不接受变量名，只接受 hex ID |
| `{"ids": [...], "mode": "table_data", "sample_points": 12}` | `{"ids": [...], "mode": "table_data"}` | `table_data` 模式不支持 `sample_points` 和 `align_samples` 参数，会报 500 错误。一维数据建议用 `last_column_full` 配合 `start_date`/`end_date` 读取 |

## mode 说明

| mode | 用途 | 适用场景 |
|------|------|----------|
| `verify`（默认） | 智能验证，自动根据数据类型返回统一摘要（二维掩码→有效资产数/覆盖率/Top选中；二维浮点→分布统计/Top-Bottom；一维净值→首尾值/涨幅/采样曲线） | **首选**，执行公式后立即调用验证 |
| `smart_sample` | 抽样查看具体数值，验证数据合理性 | 需要画表格或展示更多数据点时 |
| `signature` | 仅看维度、覆盖率、NaN率 | 快速检查数据健康度 |
| `last_day_stats` | 查看最后一天的统计数据 | 需要查看最新值（个股价格/PE/PB等） |
| `per_asset_sample` | 按资产采样 | 需要查看特定资产的数据分布 |
| `last_column_full` | 获取最后一列完整数据 | 需要最新截面的完整数据 |
| `last_valid_per_asset` | 每个资产的最新有效值 | 需要所有资产的最新状态 |
| `precheck` | 预检查数据状态 | 在正式处理前快速检查 |
| `table_data` | 获取表格格式数据 | 需要导出或展示数据表。⚠️ 不兼容 `sample_points`/`align_samples`；一维数据请改用 `last_column_full` |

## 返回示例

> ⚠️ **不同 mode 的响应结构不同**：`smart_sample` 返回 `data.results[]`；`last_column_full` 返回 `data.data[]`，注意层级差异。

### last_column_full 模式 - 布尔掩码（选股名单）

```json
{
  "code": 0,
  "data": {
    "code": 0,
    "data": [
      {
        "id": "69ddefc8acdb527849c60da8",
        "signature": {"is_bool": true, "dimension": "two"},
        "last_column_full": {
          "matched_count": 75,
          "matched_names": ["维科技术", "中国巨石", "...（共75个）"],
          "values": [
            {"asset": "SH600152", "value": 1, "name": "维科技术"},
            {"asset": "SH600176", "value": 1, "name": "中国巨石"}
          ],
          "total_rows": 9851,
          "returned_rows": 5082,
          "_note": "布尔掩码已过滤零值行：5007 行 value=0 已移除，保留命中 75 条"
        }
      }
    ],
    "elapsed_ms": 2690
  },
  "task_id": "b70bdf04-..."
}
```

> **关键路径**：命中名单 = `data.data[0].last_column_full.matched_names`（call.py 后处理注入，无需手动遍历 values）。
> 原始完整 values 列表只保留 value=1 的行；若需原始全量数据，直接调 executor.py 绕过 call.py 后处理。

### smart_sample 模式 - 二维掩码（选股信号）
```json
{
  "code": 0,
  "data": {
    "results": [
      {
        "id": "data_id_xxx",
        "type": "mask_2d",
        "valid_assets": 287,
        "coverage_rate": 0.063,
        "top_assets": ["600519.SH", "300750.SZ", "000858.SZ"],
        "description": "每日选中约63只股票（6.3%覆盖率）"
      }
    ]
  }
}
```

### 二维浮点（因子数据）
```json
{
  "code": 0,
  "data": {
    "results": [
      {
        "id": "data_id_xxx",
        "type": "float_2d",
        "stats": {
          "mean": 1.023,
          "std": 0.156,
          "p10": 0.87,
          "p25": 0.95,
          "p50": 1.01,
          "p75": 1.09,
          "p90": 1.22
        }
      }
    ]
  }
}
```

### 一维净值（回测结果）
```json
{
  "code": 0,
  "data": {
    "results": [
      {
        "id": "data_id_xxx",
        "type": "nav_1d",
        "first_value": 1.0,
        "last_value": 3.47,
        "total_return": 2.47,
        "curve_samples": [[20150101, 1.0], [20200101, 1.85], [20260101, 3.47]],
        "sampling_strategy": "等间距采样"
      }
    ]
  }
}
```

## 调用示例

```bash
# 验证回测净值（最常用）
python scripts/executor.py readData '{
  "ids": ["60a1b2c3d4e5f6a7b8c9d0e1"],
  "mode": "precheck"
}'

# 验证选股信号（查看每日选股数量）
python scripts/executor.py readData '{
  "ids": ["signal_data_id"],
  "mode": "precheck"
}'

# 对比多条净值曲线
python scripts/executor.py readData '{
  "ids": ["nav1_id", "nav2_id"],
  "mode": "smart_sample",
  "sample_points": 100
}'

# 只查最近一年
python scripts/executor.py readData '{
  "ids": ["data_id"],
  "mode": "precheck",
  "start_date": 20250101,
  "end_date": 20260101
}'
```

## 注意事项

- `ids` 用 `runMultiFormula` 返回的 `data_id`，或 `confirmDataMulti` 返回的 `_id`
- `precheck` 模式会快速预检数据状态，适合在正式读取前检查数据健康度
- 绘制净值曲线时建议 `sample_points` 设为 200-500（数据点较多时）
- 多数据对齐比较时，`align_samples=true` 会返回 `aligned_comparison` 字段（可直接用于画表格）
