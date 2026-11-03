# Compose Presentation Mode

Compose Presentation Mode 让模型负责首屏叙事和布局，数据面板仍由标准 QBV renderer 消费已验证 runtime role / snapshot。它不是自由上传整页 HTML，不能绕过数据、权限、发布和浏览器门禁。

## 参数

在 `compose_page` draft 顶层加入：

```json
{
  "presentation": {
    "version": 1,
    "mode": "bespoke",
    "html_file": "output/qbv/<task_id>/compose-presentation.html",
    "design": "compose-bespoke-v1"
  }
}
```

每个需要渲染的 panel 都要有稳定 `id`，并在 presentation HTML 中放置同值挂载点。Presentation 必须且只能包含一个 `<h1>`；该 `<h1>` 是页面唯一主标题，标准 shell 会把自己的默认 H1 让位给它：

```html
<style>
.qb-hero{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
</style>
<main data-qb-page-design="compose-bespoke-v1">
  <h1>标题</h1>
  <p data-qb-summary>一句话结论，说明研究对象、窗口和核心差异。</p>
  <div class="qb-hero">
    <div data-qb-metric>指标一</div>
    <div data-qb-metric>指标二</div>
    <div data-qb-metric>指标三</div>
    <div data-qb-metric>指标四</div>
  </div>
  <section><h2>主图</h2><div data-qb-panel="main-chart"></div></section>
  <details><summary>完整明细</summary><div data-qb-panel="detail-table"></div></details>
</main>
```

Compose 会把 `panels[].id="main-chart"` 的标准 `line/bar/table/number/text/image` 面板渲染进对应挂载点。缺失、重复、越界或证据不匹配都会失败。

## 安全边界

- 文件必须在当前任务的 `SESSION_WORKSPACE` / `QBV_OUTPUT_ROOT` 下。
- 只允许白名单结构标签和展示类 CSS；禁止 script、iframe、form、外部资源、inline event、`javascript:` URL、`position:fixed`、`@import/url()`。
- 禁止写入 signature、api key、grant_id、package_id 或任何运行时凭据。
- 数据面板仍由 `compose_page` 校验 runtime role / snapshot role，并使用标准 renderer；模型不能手写取数内核或伪造数据合同。

## 页面组织

- 首屏先给：标题、一句话结论、3–4 个核心指标、主图或主表。
- 原始长表放 `<details>` 或页面底部；不能搬到首屏充当“证据”。
- 用户要求 ECharts、缩放、悬停或时间窗时，使用标准 `line/bar/candlestick` 面板，不用 PNG 替代。
- `compose_page` 返回的 `composeQuality.warnings` 当前只提示不阻断发布，但不能通过移动长表、放置假指标或删除数据角色来消除。
