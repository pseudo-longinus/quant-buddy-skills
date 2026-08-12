---
id: meta_tooling_response_v1
version: reply_template_v1
output_format: markdown
default_reply_scope: full_answer
source_playbooks:
  - 00_meta_tooling.md
---

# Meta Tooling Response

用于回答接入、配置、模板、提示词、版本差异、模型信息和展示规则等工具本身的问题，不用于行情或研究数据答复。

## 输出规则

- 只回答能够确认的事实；不确定时直接说明无法确认。
- 链接必须真实可核验；无法确认精确入口时不编造 URL、命令、API 路径或产品规划。
- 用户问不同 Agent 为什么回答不同，只能说明模型、Skill 版本、数据源和上下文可能不同，不能臆测另一侧配置。
- 不适用的章节可以省略；完全不了解时仍保留“一句话答”和“限制”。

## Markdown 骨架

```markdown
【一句话答】{最直接、可确认的答案}

## 步骤 / 配置

1. {步骤一；不适用则省略本节}
2. {步骤二}
3. {验证结果或完成标准}

## 可参考链接

- [{真实文档名称}]({真实 URL})

## 可能的限制 / 已知问题

- {无法确认的部分、版本差异或已知限制}
- {若完全不了解：对该功能的实现细节目前无法确认，建议以官方文档或帮助中心为准。}
```
