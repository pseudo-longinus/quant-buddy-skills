# render_kline — 渲染 K 线图

> 通过 ticker 直接渲染 K 线图（OHLCV），**无需提前 runMultiFormula**。只需传资产代码和起始日期，后端自动获取 OHLC 行情数据并渲染。支持叠加技术指标（MA / MACD / BOLL / RSI），自动处理指标预热期。

## 端点

`POST /skill/renderKLine`

## 参数

### 基础参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `ticker` | string | ✅ | 资产 ticker 代码，如 `SH600519`、`SZ300750`、`SH000300` |
| `begin_date` | number | ❌ | 起始日期（格式 YYYYMMDD），不传返回全量历史 |
| `title` | string | ❌ | 图表标题，不传默认显示 ticker |
| `show_volume` | boolean | ❌ | 是否显示成交量子图，默认 `true` |
| `width` | number | ❌ | 图片宽度（像素），默认 1200 |
| `height` | number | ❌ | 图片高度（像素），默认 600（有子面板时自动升至 800） |
| `task_id` | string | ❌ | 任务ID，用于保存和检索图表 spec |

### 技术指标参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `indicators` | string[] | ❌ | 技术指标列表（见下方支持列表），不传则渲染纯 K 线 |
| `annotations` | object[] | ❌ | 图表标注（预留），如买卖点标记 |

> **ticker 格式说明**：使用 `SH`/`SZ` 前缀 + 6位代码，如 `SH600519`（贵州茅台）、`SZ000858`（五粮液）、`SH000300`（沪深300）。

### ⚠️ 常见参数错误

| 错误写法 | 正确写法 | 说明 |
|---------|---------|------|
| `{"ticker": "600519.SH"}` | `{"ticker": "SH600519"}` | 前缀格式，不是点号后缀 |
| `{"ticker": "贵州茅台"}` | `{"ticker": "SH600519"}` | 必须是代码，不接受中文名 |
| `{"asset": "国电南瑞", "code": "600406.SH"}` | `{"ticker": "SH600406"}` | 参数名是 `ticker`，不是 `asset`/`code` |

### 支持的技术指标

| 指标名 | 说明 | 面板 |
|--------|------|------|
| `ma5` | 5日均线 | 主图叠加 |
| `ma10` | 10日均线 | 主图叠加 |
| `ma20` | 20日均线 | 主图叠加 |
| `ma30` | 30日均线 | 主图叠加 |
| `ma60` | 60日均线 | 主图叠加 |
| `ma120` | 120日均线 | 主图叠加 |
| `ma250` | 250日均线（年线） | 主图叠加 |
| `ema5` ~ `ema250` | 指数移动均线，周期同上 | 主图叠加 |
| `boll` / `boll20` | 布林带（20日） | 主图叠加（上/中/下三条线 + 填充区） |
| `boll10` / `boll30` | 布林带（10日 / 30日） | 主图叠加 |
| `macd` | MACD（12,26,9） | 独立子面板（DIF / DEA / 柱状） |
| `rsi` / `rsi14` | RSI（14日） | 独立子面板（含 70/30 参考线） |
| `rsi6` / `rsi24` | RSI（6日 / 24日） | 独立子面板 |
| `vol` / `volume` | 成交量柱状图 | 独立子面板（与 `show_volume` 等效） |

**面板布局**：主图（K线 + MA/BOLL）始终在顶部；子面板（VOL / MACD / RSI）按出现顺序纵向排列，每个面板自动分配高度。

### 预热机制

当传入 `indicators` 且指定了 `begin_date` 时，后端会**自动**将数据请求的起始日期向前推 `warmupDays × 1.5` 个自然日（例如 MA60 需要预热 60 个交易日 ≈ 90 个自然日），确保指标从用户指定的 begin_date 开始就有完整数值。最终图表只显示 begin_date 之后的数据，预热区间不可见。

## 返回

```json
{
  "code": 0,
  "data": {
    "base64": "data:image/png;base64,iVBORw0KGgo...",
    "width": 1200,
    "height": 800,
    "lines_count": 2,
    "ticker": "SH600519",
    "data_points": 243,
    "indicators": ["ma5", "ma20", "macd"],
    "warmup_days": 26
  },
  "task_id": "uuid-xxx"
}
```

- 图表 spec 自动按 `task_id` 持久化，后续可用 `getChartSpec` 检索或 `reRenderChart` 重新渲染

## 调用示例

### 基础 K 线

```bash
# 贵州茅台近一年 K 线图（含成交量）
python scripts/call.py renderKLine '{"ticker": "SH600519", "begin_date": 20240101, "title": "贵州茅台K线"}'
```

```bash
# 沪深300 纯K线（不显示成交量）
python scripts/call.py renderKLine '{"ticker": "SH000300", "begin_date": 20250101, "show_volume": false}'
```

### 带技术指标

```bash
# 茅台 K 线 + MA5/MA20 + MACD（自动 800 高度）
python scripts/call.py renderKLine '{"ticker": "SH600519", "begin_date": 20240101, "title": "贵州茅台技术分析", "indicators": ["ma5", "ma20", "macd"]}'
```

```bash
# 宁德时代 布林带 + RSI
python scripts/call.py renderKLine '{"ticker": "SZ300750", "begin_date": 20250101, "title": "宁德时代", "indicators": ["boll", "rsi"]}'
```

```bash
# 沪深300 全套技术分析：MA5/MA10/MA20 + BOLL + MACD + RSI
python scripts/call.py renderKLine '{"ticker": "SH000300", "begin_date": 20240701, "title": "沪深300技术分析", "indicators": ["ma5", "ma10", "ma20", "boll", "macd", "rsi"]}'
```

## 与 renderChart（candlestick 模式）的区别

| | renderKLine | renderChart (candlestick) |
|---|---|---|
| 需要 runMultiFormula | ❌ 不需要 | ✅ 需要（先算出 4 个 data_id） |
| 步骤数 | 1步 | 2步 |
| 技术指标 | ✅ 内置 MA/MACD/BOLL/RSI | ❌ 需自行计算 |
| 适用场景 | 直接查看某资产的行情 K 线、技术分析 | 用自定义公式处理后的数据画 K 线 |
| 成交量 | 内置，`show_volume=true` 开启 | 需传 volume_id |

## 注意事项

- ticker 格式必须是 `SH`/`SZ` + 6位代码，不支持 `600519.SH` 等点号分隔格式
- 不支持港股、期货等非 A 股资产（由 getKLineDataByTicker 底层决定）
- 渲染颜色遵循中国习惯：红涨绿跌
- 含子面板（MACD/RSI）时高度自动升至 800px，也可手动指定更大值
- `indicators` 中的重复项会自动去重
- 无需手动计算预热期——传 `begin_date` + `indicators` 后端自动处理
