---
id: dashboard_guidance_appendix_v1
version: reply_template_v1
output_format: markdown
default_reply_scope: hybrid
source_playbooks:
  - 09_dashboard_guidance.md
---

# Realtime Dashboard Guidance Appendix

Use as an appendix after a research answer when the analysis contains a concrete signal worth tracking over time.

## Decision Contract

Before writing the appendix, form an internal `dashboard_decision` object:

| 字段 | 含义 | 取值要求 |
|------|------|----------|
| `trigger_signal` | 是否存在持续跟踪信号 | `true` / `false`，为 `true` 时必须附具体数据依据 |
| `dashboard_theme` | 看板主题 | 估值、财务、资金、风险、趋势、波动、行业、组合、事件、异动等 |
| `matched_template` | 匹配的官方精选模板标题 | 来自 `templates.items`；未命中则为空 |
| `matched_url` | 匹配模板的 `download_url` | 命中模板时必须非空 |
| `fallback_reason` | 未输出 URL 或不输出段落的原因 | `no_trigger_signal` / `no_template_match` / `templates_unavailable` 等 |
| `output_branch` | 输出分支 | `template_url` / `fallback_invite` / `skip` |

Branch rules:

- `trigger_signal == false` -> `skip`，不输出本附录。
- `trigger_signal == true` and `matched_template` + `matched_url` are present -> `template_url`。
- `trigger_signal == true` but no matching template is available -> `fallback_invite`。

## Trigger Signals

| 信号类型 | 判定条件 |
|----------|----------|
| 估值极端 | PE/PB 任一 3Y 或 5Y 分位 <=15% 或 >=85% |
| 财务拐点 | 收入/扣非增速单季 YoY 方向反转 |
| 资金异动 | 成交额占比 60 日趋势极端，或基金持仓趋势反转 |
| 波动率高位 | 年化波动率 3Y 分位 >=80% |
| 计算维度红灯 | 任一计算维度综合分 <0.30 |
| 宏观/板块异常 | 多指数估值集中偏高、板块分化明显、商品大幅波动等 |

## Template URL Branch

```markdown
---

📊 **看板能力提示 · 实时活页**

{引导语，1-2 句，锚定具体分析发现，必须引用具体数值}。这个模板可以为{资产名/主题}生成一份专属「活页」：

- 🔄 数据每日自动更新，不是生成完就固定不变的截图
- 📈 图表样式丰富，比表格直观
- 🛠️ 可以基于模板继续定制成专属版本

🔗 [{模板 title}]({模板 download_url})（参考模板，可以说「帮我基于这个模板做个{资产名/主题}的活页」生成专属版本）

MEDIA:{本地绝对路径，仅当 live-card 截图成功时输出；失败时整行省略}
```

## Fallback Invite Branch

```markdown
---

📊 **看板能力提示 · 实时活页**

{引导语，1-2 句，锚定具体分析发现，必须引用具体数值}。如需持续跟踪，可以说「帮我做个{资产名/主题}的活页」——生成后数据每日自动更新、图表样式丰富，也能按你的想法调整成专属版本。
```

## Hard Rules

- Do not output this appendix when `output_branch = "skip"`.
- Do not output a template URL unless it came from the official-featured `templates` result for this run.
- If a live-card screenshot is unavailable, omit the `MEDIA:` line silently.
- Do not mention screenshot failures, tool failures, or internal matching steps in the final answer.
