# search_similar_cases — 搜索相似案例

> **必须首先调用此工具**。在设计任何选股/回测策略前，先搜索已验证的公式模板，可显著提高公式编写准确率。

## 端点

`POST /skill/searchSimilarCases`

## 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | string | ✅ | 业务场景描述，如 "均线金叉"、"回测收益曲线"。用通用描述，避免过于具体 |
| `top_k` | number | ❌ | 返回案例数，默认 3，最大 5 |
| `task_id` | string | ❌ | 任务ID（UUID），不传则自动生成 |

## 返回

```json
{
  "code": 0,
  "data": {
    "cases": [
      {
        "description": "案例描述",
        "formulas": ["A=公式1", "B=公式2", "..."],
        "syntax_tips": ["注意事项1", "注意事项2"],
        "match_quality": "high | medium | low"
      }
    ]
  },
  "task_id": "uuid-xxx"
}
```

### match_quality 处理规则

| 值 | 处理方式 |
|----|----------|
| `high` | 直接参考，可直接套用公式模板 |
| `medium` | 参考模板结构，适当修改 |
| `low` | **必须**换一个 query 重试（用核心函数名或通用场景描述），最多重试 2 次 |

## 调用示例

```bash
# 搜索均线策略
python scripts/executor.py searchSimilarCases '{"query": "均线金叉选股回测", "top_k": 3}'

# 搜索因子类策略
python scripts/executor.py searchSimilarCases '{"query": "价值因子低市盈率选股"}'

# 搜索相关性分析
python scripts/executor.py searchSimilarCases '{"query": "商品价格与股票涨幅相关性分析"}'
```

## ⚠️ 常见参数错误

| 错误写法 | 正确写法 | 说明 |
|---------|---------|------|
| `{"params": {}, "body": {"query": "均线金叉"}}` | `{"query": "均线金叉"}` | 禁止多层嵌套，直接平铺参数 |
| `{"keyword": "均线"}` | `{"query": "均线"}` | 参数名是 `query`，不是 `keyword` |

## 注意事项

- query 建议使用**通用业务场景描述**，避免包含具体资产名（如"贵州茅台"、"铜期货"）
- 搜索技巧：通用场景 → 核心函数组合 → 技术细节（逐步细化）
- 返回的 `formulas` 数组可直接传给 `runMultiFormula`，是已验证的公式
