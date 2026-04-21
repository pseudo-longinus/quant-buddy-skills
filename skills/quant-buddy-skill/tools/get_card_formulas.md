# getCardFormulas — 按卡片 ID 批量获取完整公式组

## 用途

根据 `presets/cases_index.yaml` 中找到的卡片 `id`，从平台数据库拉取一张或多张卡片的完整公式组。

支持批量拉取（1-10 张），方便对比多个参考卡片后选最贴合的公式骨架。

## 调用方式

**批量（推荐）**
```bash
python scripts/call.py getCardFormulas '{"card_ids": ["691467e9acdb52784932c7a9", "691467fbacdb52784932c80e"]}'
```

**单张（向后兼容）**
```bash
python scripts/call.py getCardFormulas '{"card_id": "691467e9acdb52784932c7a9"}'
```

## 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `card_ids` | string[] | 二选一 | MongoDB ObjectId 数组，1-10 个，从 `presets/cases_index.yaml` 中查到 |
| `card_id` | string | 二选一 | 单个 ObjectId（向后兼容），等同于 `card_ids: [card_id]` |

## 返回

**批量请求** (`card_ids`)：
```json
{
  "code": 0,
  "cards": [
    {
      "card_id": "691467e9acdb52784932c7a9",
      "card_name": "高波动率多因子筛选",
      "insight": "全A股多因子评分策略...",
      "total_steps": 7,
      "total_formulas": 62,
      "action_steps": [{ "step_no": 1, "purpose": "计算60日滚动年化波动率", "formulas": [...] }],
      "all_formulas": ["波动率_60日 = ...", "..."]
    },
    { "card_id": "691467fbacdb52784932c80e", "card_name": "优质低估值选股", "..." : "..." }
  ]
}
```

**单张请求** (`card_id`)：返回同时包含 `data`（扁平）和 `cards`（数组），向后兼容。

## 字段说明

| 字段 | 说明 |
|------|------|
| `card_name` | 卡片名称 |
| `insight` | 卡片整体洞察/策略说明（来自卡片 insight 字段） |
| `total_steps` | 步骤数量 |
| `total_formulas` | 公式总条数 |
| `action_steps` | 按步骤分组的公式列表（step_no, purpose, formulas） |
| `all_formulas` | 所有公式的扁平化列表，可直接传给 `runMultiFormula` 的 formulas 参数 |

> ⚠️ **严禁将 `action_steps` 数组直接传给 `runMultiFormula` 的 `formulas` 参数！**
> `action_steps[i]` 是对象 `{step_no, purpose, formulas}`，不是字符串。
> 传给 `runMultiFormula` 时**只能用 `all_formulas`**（字符串数组），或从 `action_steps[i].formulas` 中提取字符串。
> 错误示例：`formulas: card.action_steps` → 会产生 `[object Object]` 错误。

## 典型用法

```
Step 1a：读 presets/cases_index.yaml（~105 行，一次读完），按 tags 找 1-3 张最相关卡片
Step 1b：getCardFormulas(card_ids=["id1","id2"])
         → 对比多张卡片的 all_formulas，选最贴合的作为公式骨架
Step 5： runMultiFormula(formulas=选定卡片的 all_formulas, task_id=...)
         → 替换资产名后执行
```

## 错误码

| code | 含义 |
|------|------|
| 0 | 成功 |
| 400 | card_id 参数缺失或格式错误 |
| 404 | 卡片不存在（id 不在数据库中） |
| 401/402 | API Key 无效或过期 |
