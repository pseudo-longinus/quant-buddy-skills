# search_functions — 函数检索

> 当不确定某个函数是否存在、或其调用格式/参数时使用。返回函数的中文名、调用格式、示例和说明。

## 端点

`POST /skill/searchFunctions`

## 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | string | ✅ | 检索关键词（中英文均可），支持空格/逗号/\|分隔多关键词 |
| `top_k` | number | ❌ | 返回条数，默认 8，最大 20 |
| `detail_level` | string | ❌ | `brief`（更短）/ `normal`（默认）/ `full`（top_k≤3时建议用） |
| `task_id` | string | ❌ | 任务ID（UUID） |

## 返回

```json
{
  "code": 0,
  "data": {
    "functions": [
      {
        "name": "回测",
        "internal_name": "backtest",
        "format": "回测(信号矩阵, [基准], [费率])",
        "short_instruction": "按列归一化信号，等权买入，返回复利净值曲线",
        "example": "NAV=回测(\"Signal\")",
        "notes": "第一参数必须是二维矩阵（资产×日期）"
      }
    ]
  },
  "task_id": "uuid-xxx"
}
```

## 调用示例

```bash
# 查回测函数
python scripts/executor.py searchFunctions '{"query": "回测", "top_k": 3, "detail_level": "full"}'

# 查均线相关
python scripts/executor.py searchFunctions '{"query": "均线 MA rolling"}'

# 查延迟/移位函数
python scripts/executor.py searchFunctions '{"query": "延迟 shift lag"}'

# 查缺失值处理
python scripts/executor.py searchFunctions '{"query": "缺失填零 fillna"}'

# 多关键词
python scripts/executor.py searchFunctions '{"query": "波动率|标准差|std"}'
```

## 常用函数速查（高频）

| 函数名 | 格式 | 说明 |
|--------|------|------|
| `MA` | `MA("数据", N)` | N日均线 |
| `回测` | `回测("Signal")` | 等权回测，返回净值 |
| `延迟` | `延迟("数据", N)` | 按自然日延迟 N 天 |
| `缺失填零` | `缺失填零("数据")` | NaN → 0 |
| `取前` | `取前("数据", N)` | 截取前 N 条 |
| `板块` | `板块(万得全A)` | 生成板块掩码（注：板块名不加引号） |
| `或` | `或(A, B)` | 取并集（不用 A+B） |

## ⚠️ 常见参数错误

| 错误写法 | 正确写法 | 说明 |
|---------|---------|------|
| `{"keyword": "MA均线"}` | `{"query": "MA均线"}` | 参数名是 `query`，不是 `keyword` |
| `{"intent": "移动平均"}` | `{"query": "移动平均"}` | 参数名是 `query`，不是 `intent` |
| `{}` （空 body） | `{"query": "回测"}` | `query` 是必填参数 |

## 注意事项

- 函数参数为**资产/板块名**时不加引号：`板块(万得全A)`、`收盘价(贵州茅台)`
- 引用变量/数据名必须用双引号：`"全市场每日收盘价"`、`"Signal"`
- `延迟` 按**自然日**计算（不是交易日）
