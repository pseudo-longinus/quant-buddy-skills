---
id: generic_live_page_delivery_v1
version: reply_template_v1
output_format: markdown
default_reply_scope: full_answer
source_playbooks: []
---

# Generic Live Page Delivery

用于无法可靠匹配专业研究骨架的新活页。它保证最终回复仍完整说明页面用途、内容、结论、限制和公开链接，不退化成一句“已发布”。

## 输出规则

- 先根据 `page_context` 和当前活页数据概括用途；不得仅复述标题。
- 使用页面真实可见内容和运行时输出；结构性不存在的字段或整表直接删除，只有有效结构中的偶发缺值写 `--`。
- 不暴露本地路径、凭证、签名、内部验收日志或元数据 JSON。
- 必须包含公开活页链接。

## Markdown 骨架

```markdown
**{活页标题}**

【一句话结论】{基于当前页面数据的核心判断；若页面尚无可用结论，说明当前状态，不编造。}

## 这份活页做了什么

{page_context.summary}

## 核心模块

| 模块 | 主要内容 | 当前输出 |
|------|----------|----------|
| {core_section} | {模块用途} | {真实页面数据或“本轮未返回”} |

## 重点怎么看

- {page_context.reply_focus 对应的阅读重点}
- {关键指标、信号或交互方式}
- {需要持续观察的变化}

## 能力边界

- {page_context.limitations}
- 缺失字段不作推断，不提供保证性预测。

## 公开链接

- [打开实时活页]({public_url})

> 数据以打开活页时的实时结果为准；不构成投资建议。
```
