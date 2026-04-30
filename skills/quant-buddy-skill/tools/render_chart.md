# render_chart — 渲染图表

> 将计算结果渲染成图表，返回 base64 编码的 PNG 图片。支持折线、柱状、面积、K线图。图表 spec 自动保存，可通过 task_id 检索和重新渲染。

## 端点

`POST /skill/renderChart`

## 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `chart_type` | string | ❌ | 图表类型：`line`（默认）/ `bar` / `area` / `candlestick` / `candlestick_volume` |
| `lines` | object[] | ✅* | 曲线配置数组，**line/bar/area 类型必填**，详见下方 |
| `candlestick` | object | ✅* | K线数据配置，**candlestick/candlestick_volume 类型必填**，详见下方 |
| `title` | string | ❌ | 图表标题 |
| `start_date` | number | ❌ | 显示起始日期（格式 20150101），不传则从数据最早日期开始 |
| `width` | number | ❌ | 图片宽度（像素），默认 1200 |
| `height` | number | ❌ | 图片高度（像素），默认 600 |
| `task_id` | string | ❌ | 任务ID（UUID），用于保存和检索图表 spec |

> `*` 互斥必填：`lines` 和 `candlestick` 根据 `chart_type` 二选一。

### chart_type 说明

| chart_type | 说明 | 数据输入 |
|-----------|------|----------|
| `line` | 折线图（默认） | `lines` 数组 |
| `bar` | 柱状图 | `lines` 数组 |
| `area` | 面积图（带填充） | `lines` 数组 |
| `candlestick` | K线图（纯K线） | `candlestick` 对象 |
| `candlestick_volume` | K线+成交量 | `candlestick` 对象（含 `volume_id`） |

### lines 数组元素（line / bar / area 用）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | ✅ | 数据ID（来自 `runMultiFormulaBatch` 的 `data_id`） |
| `name` | string | ✅ | 曲线图例名称 |
| `axis` | string | ❌ | `left`（默认）或 `right`（右轴，适合量纲不同的数据） |

> ℹ️ 仅支持一维数据。二维数据需先通过公式提取为一维（如 `收盘价(贵州茅台)` 返回的就是一维时序）。

### ⚠️ 常见参数错误

| 错误写法 | 正确写法 | 说明 |
|---------|---------|------|
| `{"variable_names": ["金银比价"]}` | `{"lines": [{"id": "60a1b2...", "name": "金银比价"}]}` | 参数名是 `lines`，不是 `variable_names` |
| `{"lines": [{"name": "NAV"}]}` | `{"lines": [{"id": "60a1b2...", "name": "NAV"}]}` | `id` 必填，必须是 `runMultiFormulaBatch` 返回的 24位 hex data_id |
| `{"chart_type":"bar","x_data":[...],"series":[...]}` | `{"chart_type":"bar","lines":[{"id":"hex","name":"X"}]}` | 柱状图也用 `lines` 数组，不是 `x_data`/`series` |

### candlestick 对象（K线图用）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `open_id` | string | ✅ | 开盘价数据ID |
| `high_id` | string | ✅ | 最高价数据ID |
| `low_id` | string | ✅ | 最低价数据ID |
| `close_id` | string | ✅ | 收盘价数据ID |
| `volume_id` | string | ❌ | 成交量数据ID（`candlestick_volume` 类型必填） |

> ℹ️ 所有 ID 必须是一维数据。通过 `开盘价(资产名)` 等公式计算得到的就是一维时序。

## 返回

```json
{
  "code": 0,
  "data": {
    "base64": "data:image/png;base64,iVBORw0KGgo...",
    "lines_count": 2,
    "width": 1200,
    "height": 600,
    "chart_type": "line",
    "errors": []
  },
  "task_id": "uuid-xxx"
}
```

- `base64`：完整 data URI，可直接用作 `<img src="...">` 或解码保存为 PNG
- 图表 spec 自动按 `task_id` 持久化到 MongoDB，后续可用 `getChartSpec` 检索或 `reRenderChart` 重新渲染

## 调用示例

### 折线图（默认）

```bash
# 单条净值曲线
python scripts/call.py renderChart '{"title": "策略净值", "lines": [{"id": "nav_id", "name": "MA金叉策略"}]}'

# 多策略对比
python scripts/call.py renderChart '{"title": "策略对比", "chart_type": "line", "lines": [{"id": "id1", "name": "策略A"}, {"id": "id2", "name": "策略B"}]}'
```

### 柱状图

```bash
python scripts/call.py renderChart '{"title": "月度收益", "chart_type": "bar", "lines": [{"id": "monthly_ret_id", "name": "月度收益"}]}'
```

### 面积图

```bash
python scripts/call.py renderChart '{"title": "累计收益", "chart_type": "area", "lines": [{"id": "cum_ret_id", "name": "累计收益"}]}'
```

### K线图

需要先通过 `runMultiFormulaBatch` 计算 OHLC 数据，然后传入 4 个 data_id：

```bash
# Step 1: 计算 OHLC（同一 task_id）
python scripts/call.py runMultiFormulaBatch '{"task_id": "kline-001", "formulas": ["O=开盘价(贵州茅台)", "H=最高价(贵州茅台)", "L=最低价(贵州茅台)", "C=收盘价(贵州茅台)", "V=成交量(贵州茅台)"]}'

# Step 2: 渲染K线图
python scripts/call.py renderChart '{
  "chart_type": "candlestick_volume",
  "title": "贵州茅台K线",
  "start_date": 20250101,
  "candlestick": {
    "open_id": "<O的data_id>",
    "high_id": "<H的data_id>",
    "low_id": "<L的data_id>",
    "close_id": "<C的data_id>",
    "volume_id": "<V的data_id>"
  },
  "task_id": "kline-001"
}'
```

### 左右双轴

```bash
python scripts/call.py renderChart '{"lines": [{"id": "nav_id", "name": "策略净值", "axis": "left"}, {"id": "factor_id", "name": "换手率因子", "axis": "right"}]}'
```

---

## 图表 Spec 持久化

每次 `renderChart` 调用成功后，图表的 echarts option 和原始参数会自动保存到 MongoDB，关联 `task_id`。

### 获取 Chart Spec

`GET /skill/chartSpec/{task_id}`

```bash
python scripts/call.py getChartSpec '{"task_id": "kline-001"}'
```

返回：
```json
{
  "code": 0,
  "data": {
    "specs": [
      {
        "_id": "mongo_id",
        "task_id": "kline-001",
        "chart_type": "candlestick_volume",
        "title": "贵州茅台K线",
        "render_params": {...},
        "width": 1200,
        "height": 600,
        "lines_count": 2,
        "created_at": "2026-03-05..."
      }
    ],
    "total": 1
  }
}
```

### 重新渲染

`POST /skill/reRenderChart`

从已保存的 spec 重新渲染（可覆盖 width/height/title），**不重新读取数据**：

```bash
python scripts/call.py reRenderChart '{"task_id": "kline-001", "width": 1600, "height": 800}'
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `spec_id` | string | ✅* | spec 的 MongoDB _id（精确定位） |
| `task_id` | string | ✅* | 取该 task_id 下最新一条 spec |
| `width` | number | ❌ | 覆盖原始宽度 |
| `height` | number | ❌ | 覆盖原始高度 |
| `title` | string | ❌ | 覆盖原始标题 |

> `*` spec_id 和 task_id 二选一，优先 spec_id。

## 注意事项

- 涉跌颜色遵循中国习惯：红涨绿跌
- 仅支持一维数据。二维数据需先通过公式提取为一维（如 `收盘价(贵州茅台)` 返回的就是一维时序）

with open("chart.png", "wb") as f:
    f.write(base64.b64decode(b64))
```

## 完整示例

见 [`examples/04_render_chart.py`](../examples/04_render_chart.py)——执行两个策略回测 + 渲染对比图 + 自动保存 PNG。

## 注意事项

- **一维净值曲线**（`runMultiFormulaBatch` 里 `回测()` 的结果）：`ticker` 不传
- **二维数据**（收盘价矩阵等）：必须传 `ticker` 指定要画哪只资产
- 图片默认 2x 分辨率（高清），1200x600 像素实际输出 2400x1200
- `errors` 字段记录部分曲线加载失败的情况（不影响其他曲线渲染）
