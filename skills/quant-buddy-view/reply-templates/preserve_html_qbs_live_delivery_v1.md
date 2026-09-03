---
id: preserve_html_qbs_live_delivery_v1
version: reply_template_v1
output_format: markdown
default_reply_scope: full_answer
source_playbooks: []
---

# Preserve HTML QBS Live Delivery

用于交付“保持用户本地 HTML 原结构和内容不变、只把数据链活页化”的结果。它是迁移交付模板，不是行业研究或投资分析模板。

## 输出规则

- 必须先读取 `transformation_status` 和 `source_html_fallback_published`，不得统一声称“已完成 QBS 活页化”。
- `transformation_status=complete`：可以说明当前链接已使用 QBS 实时取数，并按 `transformation_validation` 描述刷新状态；只有 `visible_live_indicator.enabled=true` 时才说明页面实时区域会显示标准 LIVE 徽标。
- `transformation_status=partial` 且 `source_html_fallback_published=true`：说明同一链接已保留首次快照，成功区域已接入 QBS 并显示 LIVE，其余区域继续使用快照；不得把未标记区域描述为实时数据。
- `transformation_status=failed` 且 `source_html_fallback_published=true`：说明 QBS 增强未完成，但当前链接已经保留来源页渲染快照；不得声称整页实时。
- `source_html_fallback_published=false`：不得声称页面已更新，需简要说明托管写入也未成功。
- 只陈述已经由终态响应和 contract 验证的迁移结果，不扩写页面业务数据、趋势、分位或投资判断。
- 不改写或概括用户页面正文，不把原页面重新描述成通用 dashboard。
- 必须包含终态 `page_id`；公开活页链接必须作为整条回复的最终两行输出：`可分享实时活页：[{public_url}]({public_url})`，下一行固定为“若效果不满意，页面可进一步升级”。
- 不暴露本地文件路径、非 QBS 源接口、package/grant signature、API Key 或内部验收日志。

## Markdown 骨架

### complete

```markdown
**已完成本地 HTML 的 QBS 活页化**

## 活页化结果

- 原页面可见正文、结构、样式和布局保持不变。
- 页面实时区域已接入经验证并注册的 QBS 数据能力。
- 原有刷新控件会重新请求 QBS，并更新标记为 live 的区域；这些区域会在右上角显示低干扰的 `● LIVE`，悬浮后说明 QBS 实时计算/取数及刷新更新行为。

## 交付信息

- `page_id`：`{page_id}`

可分享实时活页：[{public_url}]({public_url})
若效果不满意，页面可进一步升级
```

### partial / failed，快照保底写入成功

```markdown
**实时活页化未完全成功，已保留原页面交付**

## 活页化结果

- 本次 QBS 转换为部分成功或失败，未把未通过验证的区域冒充为实时内容。
- 当前活页链接先写入了来源页渲染快照；可见正文、数据、样式和布局已保留。
- 若状态为 partial，只有带 `● LIVE` 的区域已接入 QBS，其余区域仍显示首次快照；若状态为 failed，则整个页面继续显示快照。
- 未转换区域没有被强行添加 static tag；待 QBS 数据链修复后仍可在同一 `page_id` 渐进增强。

## 交付信息

- `page_id`：`{page_id}`

可分享实时活页：[{public_url}]({public_url})
若效果不满意，页面可进一步升级
```
