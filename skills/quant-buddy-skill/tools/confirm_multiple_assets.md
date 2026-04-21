# confirm_multiple_assets — 批量资产确认

> 将自然语言描述的资产名/板块名标准化，返回可用于公式的标准名称与代码。

## 端点

`POST /skill/confirmMultipleAssets`

## 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `intentions` | string[] | ✅ | 资产/板块意图数组，支持模糊描述 |
| `types` | string[] | ❌ | 过滤类型：`asset`（个股）/ `index`（指数）/ `future`（期货）/ `sector`（板块）。不传则查所有 |
| `task_id` | string | ❌ | 任务ID（UUID） |

## 返回

```json
{
  "code": 0,
  "data": {
    "results": [
      {
        "intention": "贵州茅台",
        "matched": true,
        "type": "asset",
        "name": "贵州茅台",
        "ticker": "600519.SH",
        "alternatives": []
      },
      {
        "intention": "有色金属",
        "matched": true,
        "type": "sector",
        "name": "有色金属（申万）",
        "ticker": null,
        "alternatives": ["有色金属概念"]
      }
    ]
  },
  "task_id": "uuid-xxx"
}
```

## 支持的资产类型

| 类型 | 有效 intentions 写法 | ❌ 不要用的写法 |
|------|---------------------|----------------|
| 个股 | `贵州茅台`、`宁德时代`、`600519.SH` | - |
| 指数 | `沪深300`、`中证500`、`万得全A` | - |
| 期货 | `铜`、`黄金`、`螺纹钢`、`原油` | `CMX-铜`、`SHFE-铜`（前缀格式无效，会30次重试后超时） |
| 板块（申万行业） | `有色金属`、`银行`、`消费者服务` | - |
| 概念板块 | `机器人概念`、`消费电子`、`新能源汽车` | - |

**期货特别说明**：确认期货时用简洁的中文品种名（`铜`/`黄金`/`铁矿石`）而非交易所前缀格式。返回的 `name` 字段（如 `CMX-铜`、`沪铜主力合约`）才是公式中可以使用的标准名称。

## 调用示例

```bash
# 确认个股
python scripts/executor.py confirmMultipleAssets '{"intentions": ["贵州茅台", "宁德时代", "比亚迪"]}'

# 确认指数（仅查指数类型）
python scripts/executor.py confirmMultipleAssets '{
  "intentions": ["沪深300", "中证500", "创业板指"],
  "types": ["index"]
}'

# 确认期货（用简洁品种名，不加前缀）
python scripts/executor.py confirmMultipleAssets '{
  "intentions": ["铜", "黄金", "螺纹钢", "原油"],
  "types": ["future"]
}'

# 确认板块
python scripts/executor.py confirmMultipleAssets '{
  "intentions": ["有色金属", "银行", "消费电子"],
  "types": ["sector"]
}'
```

## 公式中的用法

确认后，在公式中如何使用返回的名称：

```
# 个股单独取数（用 ticker 或 name）
价格=收盘价(贵州茅台)

# 板块筛选（用 name，不加引号）
板块内=板块(有色金属（申万）)

# 指数作为回测基准
NAV=回测("Signal", 沪深300)
```

## ⚠️ 常见参数错误（生产日志高频错误）

| 错误写法 | 正确写法 | 说明 |
|---------|---------|------|
| `{"assets": ["国电南瑞", "沪深300"]}` | `{"intentions": ["国电南瑞", "沪深300"]}` | 参数名是 `intentions`，不是 `assets` |
| `{"query": "国电南瑞"}` | `{"intentions": ["国电南瑞"]}` | 参数名是 `intentions`，不是 `query`；类型是**数组** |
| `{"assets": [{"asset_name":"X","ticker":"Y"}]}` | `{"intentions": ["X"]}` | 不接受对象数组，只接受**字符串数组** |
| `{"intentions": ["CMX-铜", "SHFE-铜"]}` | `{"intentions": ["铜", "黄金"]}` | 期货用简洁中文名，不加交易所前缀 |

## 注意事项

- 板块名包含空格或特殊字符（如括号）时，公式中直接用标准名，**不加引号**
- 若 `matched=false`，检查 `alternatives` 字段中的候选名称
- 申万行业板块名通常以 `（申万）` 结尾，概念板块以 `概念` 结尾
