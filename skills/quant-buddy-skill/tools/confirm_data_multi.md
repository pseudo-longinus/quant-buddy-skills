# confirm_data_multi — 批量数据确认

> 确认数据项是否存在、维度是否正确、是否为掩码/季度财务数据。在写公式前必须先确认数据名。

## 端点

`POST /skill/confirmDataMulti`

## 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `data_desc` | string | ✅ | 数据描述，多个用逗号或空格分隔。如 `"收盘价, 市值, 净利润"` |
| `dimension` | string | ❌ | 维度筛选：`one-row`（一维时序）/ `two`（二维矩阵）。不传则两种都返回 |
| `is_bool` | boolean | ❌ | 是否布尔掩码数据（非ST等）。不传则不过滤 |
| `content` | string | ❌ | 需求背景描述，帮助更准确匹配意图 |
| `task_id` | string | ❌ | 任务ID（UUID） |

## 返回

```json
{
  "code": 0,
  "data": {
    "results": [
      {
        "query": "收盘价",
        "matched": true,
        "index_info": {
          "_id": "60a1b2c3d4e5f6a7b8c9d0e1",
          "index_title": "全市场每日收盘价",
          "dimension": "two",
          "is_bool": false,
          "provider": "guanzhao",
          "description": "A股全市场复权收盘价"
        }
      }
    ]
  },
  "task_id": "uuid-xxx"
}
```

## 维度说明

| 维度 | dimension 值 | 典型数据 |
|------|-------------|----------|
| 二维（资产×日期） | `two` | 收盘价、市值、成交量、财务指标 |
| 一维（仅日期） | `one-row` | 宏观指标、指数净值、回测净值曲线 |
| 0-1掩码 | `two` + `is_bool=true` | 非ST |

## 调用示例

```bash
# 确认基础市场数据
python scripts/executor.py confirmDataMulti '{"data_desc": "收盘价, 成交量, 市值"}'

# 确认财务数据
python scripts/executor.py confirmDataMulti '{"data_desc": "净利润, 营业收入, 市盈率"}'

# 只查一维数据（宏观/指数）
python scripts/executor.py confirmDataMulti '{"data_desc": "GDP, 上证指数净值", "dimension": "one-row"}'

# 查掩码数据
python scripts/executor.py confirmDataMulti '{"data_desc": "非ST", "is_bool": true}'

# 带背景描述（提升匹配准确率）
python scripts/executor.py confirmDataMulti '{
  "data_desc": "换手率, 流通市值",
  "content": "构建小市值低换手因子选股"
}'
```

## ⚠️ 常见参数错误（生产日志高频错误）

| 错误写法 | 正确写法 | 说明 |
|---------|---------|------|
| `{"queries": ["换手率", "市盈率"]}` | `{"data_desc": "换手率, 市盈率"}` | 参数名是 `data_desc`，不是 `queries`；类型是**逗号分隔字符串**，不是数组 |
| `{"query": "收盘价"}` | `{"data_desc": "收盘价"}` | 参数名是 `data_desc`，不是 `query` |
| `{"data_desc": "...", "dimension": "one-row"}` 且不确定维度 | `{"data_desc": "..."}` 不传 dimension | 不确定维度时不要传 dimension，让服务端返回所有匹配 |

## 重要规则

1. **优先使用通用数据名**：查"贵州茅台市盈率"→ 先查"A股市盈率"，再用 `"市盈率"*取出(贵州茅台)` 取单股
2. **用返回的 `index_title` 写公式**（不要用原始查询词）：返回 `"全市场每日收盘价"` → 公式写 `"全市场每日收盘价"`
3. **`intention` 与 `index_title` 可能不同**：查询"全市场每日涨跌幅"时，平台返回 `index_title: "全市场每日回报率"`，公式中必须写 `"全市场每日回报率"`，写"全市场每日涨跌幅"会报「数据名不存在」
4. **用返回的 `_id` 给 `readData`**：`readData` 的 `ids` 参数用 `_id` 字段
5. 季度财务数据（净利润等）是二维但按季度更新，计算时注意对齐日期
6. **根据 `dimension` 决定后续操作**：
   - `dimension: "one-row"` → 已是一维时间序列（单资产或宏观数据）→ **直接 `readData(ids=[_id])`，禁止再套 `取出()` 或 `runMultiFormula`**
   - `dimension: "two"` → 全市场二维截面 → 走规则 1（`runMultiFormula` + `取出()`），但公式左侧变量名与 `index_title` **不得相同**（否则循环依赖），命名规范：`{股票名}{指标名}` 或 `{指标名}_val`
