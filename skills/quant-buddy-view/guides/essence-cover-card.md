# Guide · 宽宝活卡（范式卡 / card runtime artifact）

> 场景：用户要把一个 QuantBuddy 页面浓缩成一张固定 4:3 卡片，用作官网范式卡或「一眼看懂」摘要。
> 新版实现是**独立 card runtime artifact**（`embedded-card-v1`）：在页面里内嵌一份「卡片模板 + 样式 + 取数清单 + runtime」，官网卡片流 / 截图工具能在空白宿主里 `QBCardRuntimeV1.mount()` 独立 hydrate 出这张卡，而不依赖旧的 `?cover=1` 整页 URL 模式。
> 功能和对外称呼仍可叫「宽宝活卡」；卡片左上角只预留官网统一注入的标签位，不内置固定品牌文案。「精华卡 / 封面卡 / 范式卡」作为开发/路由别名保留。

两种资源必须分开理解：Card Runtime artifact 是可执行的 HTML/CSS/manifest/runtime 契约；`card_snapshot_url` 是 `skill_server` 针对某个 `card_artifact_hash` 生成的不可变静态首帧，也是页面封面的唯一来源。manifest 不得写入任何服务端图片字段（`card_snapshot_url` / 历史的 `thumbnail_url`）。

## 触发词

用户提到这些词时默认走本指南：精华卡、摘要卡、封面卡、cover card、范式卡、4:3 卡片、封面、缩略图源图、单独拎出来。

## card runtime artifact 结构（`embedded-card-v1`）

页面里嵌入四段（由 `build_dashboard`（有 live_card 配置时自动产出）或 `static_page.py retrofit_card_runtime` 生成）：

```html
<!-- 1) 卡片模板：mount 时被克隆进宿主根节点 -->
<template data-qb-card-template>
  <article class="essence-card" data-qb-live-card data-qb-card-visual-kind="basis-structure">
    <div class="live-card-meta">
      <span data-qb-live-card-brand></span>
      <time data-qb-live-card-date datetime="2026-07-14">2026-07-14</time>
    </div>
    <h1 data-qb-live-card-title>一句重点结论标题</h1>
    <p data-qb-live-card-description>一行解释判断依据。</p>
    <section class="live-card-core" data-qb-live-card-core>
      <!-- 数字 / 图标 / 圆环 / 结构条 / 曲线 / 指标 chip -->
    </section>
  </article>
</template>

<!-- 2) 卡片样式（来自 assets/live-card.css，浅色官网系统） -->
<style data-qb-card-style> ... </style>

<!-- 3) 取数清单 manifest -->
<script type="application/json" data-qb-card-manifest>
{ "version":"1.1.0", "kind":"embedded-card-v1", "visual_kind":"basis-structure",
  "package_id":"pkg_xxx", "signature":"sig_xxx", "endpoint":"https://www.quantbuddy.cn/skill",
  "required_outputs":["SCORE","..."], "aspect_ratio":"4/3" }
</script>

<!-- 4) runtime：暴露 window.QBCardRuntimeV1.mount / hydrate -->
<script id="qb-card-runtime-v1" data-qb-card-runtime> ... </script>
```

宿主（官网卡片流 / 截图工具）这样独立 hydrate：读取 manifest → 用 `package_id + signature` 取 `required_outputs` → `QBCardRuntimeV1.mount(root, {outputs})`，把 `<template>` 克隆进 `root` 并回填数值。hydrate 完成后，卡片根节点必须带 `data-qb-card-ready="true"`。卡片数值实时取数、**不写死**。

## 快照生成与更新边界

- 页面 `upload/update` 或模板 `submit/update` 后，服务端对 template、style、manifest、runtime 四段按固定顺序计算 artifact hash。
- 只有 hash 相对当前记录发生变化时，才创建一次 durable snapshot job；同一 `page_id + hash` 由唯一索引去重。
- Worker 在 720×540 空白宿主中取数并 hydrate，等 `data-qb-card-ready="true"` 和字体 ready 后截图，写入 `pages/card-snapshots/{page_id}/{hash}.png`。
- 浏览官网、硬刷新、切换筛选、进入/离开视口、行情数据更新都不创建快照任务；这些动作只读取静态首帧并在前端 hydrate 实时卡片。
- 快照失败不阻断页面发布；旧 hash 的任务通过条件更新不能覆盖新 artifact。
- 整页缩略图（`thumbnail_url`）能力已下线：页面封面只有本契约产出的 `card_snapshot_url` 这一个来源，没有其它兜底图。

## 必须满足的契约

1. **独立 artifact**：卡片是页面内自包含的 `embedded-card-v1` artifact，能脱离整页在空白宿主里 mount，不依赖 `?cover=1` 整页视口。
2. **实时更新**：manifest 的 `package_id/signature/required_outputs` 决定取数；runtime hydrate 时回填日期、主数字、指标，不把数值写死进模板。
3. **4:3 比例**：`aspect_ratio:"4/3"`，卡片模板根节点 `aspect-ratio: 4 / 3`，至少在 720×540、410×308、320×240 三种空白宿主里都要填满、贴齐，不靠截图裁切伪造比例。
4. **官网浅色系**：必须浅色卡片系统，禁止整卡暗色/黑底/深蓝底。主题色（红蓝绿橙）只作强调色，用在顶部细线、核心图形、关键数字、标签或结构条。
5. **固定信息骨架**：顶部左侧官方标签预留位（`data-qb-live-card-brand` 可为空、不显示固定品牌文案），右侧 `YYYY-MM-DD` 日期；第二行标题/一句重点结论；第三行描述；第四行核心表达区。字号走统一 token。
6. **可验收 DOM 标记**：模板根节点带 `data-qb-live-card`，标签预留位/日期/标题/描述/核心区分别加 `data-qb-live-card-brand` / `data-qb-live-card-date` / `data-qb-live-card-title` / `data-qb-live-card-description` / `data-qb-live-card-core`；hydrate 成功后再写 `data-qb-card-ready="true"`。
7. **本地先对齐**：先本地生成/改造并 `verify_page.mjs --card-runtime` 验收、截图给用户确认，再走 `static_page.py update` / `retrofit_card_runtime` 写回。
8. **视觉合同 fail-closed**：完整重建必须命中页面专属视觉或显式提供 `visual_contract`。没有视觉方案时返回 `CARD_VISUAL_REQUIRED`，禁止从 output 名称自动选前三项、禁止用三行 `qb-mini-metric` 冒充范式卡。
9. **协议升级不改视觉**：已有完整 artifact 只缺新版本/ready 契约时，用 `preserve_visual:true`；该路径逐字节保留 template/style，不要求旧卡补视觉标记。

## 视觉系统

宽宝活卡 = 统一浅色官网外壳 + 固定信息层级 + 可变核心可视化。样式统一来自 `assets/live-card.css`（`build_dashboard` 会把它作为 `data-qb-card-style` 内嵌进 artifact）。推荐 token：

```css
:root {
  --qb-live-bg: #fffaf2;
  --qb-live-surface: #ffffff;
  --qb-live-ink: #201713;
  --qb-live-muted: #6f5a43;
  --qb-live-border: #ead8c6;
  --qb-live-brand: #ffd45a;
  --qb-live-accent: #d71920;
  --qb-live-pad-x: clamp(18px, 5.6vw, 44px);
  --qb-live-pad-y: clamp(16px, 5vw, 38px);
  --qb-live-core-gap: clamp(8px, 1.5vw, 12px);
  --qb-live-meta-size: 11px;
  --qb-live-title-size: 28px;
  --qb-live-desc-size: 13px;
  --qb-live-body-size: 12px;
}
@media (max-width: 420px) {
  :root { --qb-live-meta-size: 9px; --qb-live-title-size: 18px; --qb-live-desc-size: 11px; --qb-live-body-size: 10px; }
}
```

主题色只覆盖 `--qb-live-accent`（`.essence-card[data-theme="blue"]{--qb-live-accent:#1f5fbf;}` 等），不要覆盖成暗色整卡背景。

## 固定四行骨架与空间预算

卡片模板必须是稳定四行骨架，差异只落在第四区：

1. **Meta 行**：左侧官方标签预留位（可为空，不显示固定「宽宝活卡」文案）；右侧 `YYYY-MM-DD` 日期，muted 色、字重 `700`、走 `--qb-live-meta-size`。
2. **标题行**：一句重点结论，统一标题 token、字重约 `900`、行高 `1.05-1.12`；与外层模板标题重复时改成判断句。
3. **描述行**：一句解释依据，muted、`--qb-live-desc-size`、字重 `500-600`、行高 `1.25-1.45`，默认 1 行、最多 2 行。
4. **核心表达区**：`data-qb-live-card-core`，吃满前三行之后的剩余空间。

```css
.essence-card[data-qb-live-card] {
  aspect-ratio: 4 / 3;
  padding: var(--qb-live-pad-y) var(--qb-live-pad-x);
  display: grid;
  grid-template-rows: auto auto auto minmax(0, 1fr);
  gap: var(--qb-live-core-gap);
}
[data-qb-live-card-core] { min-height: 0; overflow: hidden; }
```

外层内边距四周一致、随视口等比收敛；第四区吃满剩余空间，图形/数字/指标不留大块空白，不保留空的 `1fr` 行或隐藏模块遗留轨道。

## 生成方式

- **标准看板**：`build_dashboard` 的 spec 带 `live_card` 配置时，会自动在页面里产出 card runtime artifact（`card_runtime_artifacts` + `card_runtime_script`）。spec 例：

```json
{
  "title": "页面核心结论一眼看懂",
  "package_id": "pkg_xxx",
  "live_card": {
    "theme": "blue",
    "title": "页面核心结论一眼看懂",
    "description": "核心指标实时刷新，打开即取最新公式包输出。",
    "primary": {"output": "SCORE", "field": "value", "unit": "分"},
    "metrics": [{"label": "主指标", "output": "SCORE", "field": "value", "unit": "分"}],
    "tags": ["实时取数", "重点摘要"]
  },
  "panels": [ ... ]
}
```

- **已发布/官方精选页补 artifact**：已有好看 artifact 用 `static_page.py retrofit_card_runtime '{"page_id":"page_xxx","preserve_visual":true,"update":true}'` 只升级协议；artifact 缺失时先确定页面专属视觉，或显式传 `visual_contract` 后再完整重建。未知页面不允许无方案重建。
- **bespoke 页**：直接内嵌上面四段（template/style/manifest/runtime），manifest 填本页 `package_id/signature/endpoint/required_outputs`。
- **页面与 Card 共用凭证**：在 `publish_workflow.py` 的同一 package/grant 注册项里，把 `markers.package_id` / `markers.grant_id` / `markers.signature` 写成数组，分别列出正文和 Card manifest 的全局唯一 marker；发布器只注册一次，再把同一凭证扇出到所有位置。
- **禁止空壳和重复注册**：不要把 Card manifest 的 `package_id/grant_id/signature` 留空等待发布后修补，也不要为了 Card Runtime 另注册一个公式、outputs 和 reads 等价的 package/grant。
- **发布前结构门禁**：含 Card Runtime artifact 的页面会在任何 QBS 验证、注册、图片上传或发布前，以假凭证执行 `verify_page.mjs --card-runtime-structure-only`；结构失败时零网络写副作用。

## 核心表达区

先判断原页面最有辨识度的「玩法」，把它浓缩成一个轻量可视化，只在 `data-qb-live-card-core` 里变化。二选一，不要同时用大数字和主图形：

- **数字主导 numeric-focus**：市场温度、涨跌停结构、估值水位、风险评分等指标页。一句结论标题 + 1 个大数字/等级 + 2-3 个解释指标 + 1 条结构条 + 2-3 个短标签。
- **视觉主导 visual-focus**：组合画像、多因子、趋势曲线、雷达图、泡沫场等有标志性图形的页。一句结论标题 + 1 个简化图形 + 2-3 个 chip；图形只表达主判断，不复制整页图表。

完整重建时把选择写成显式 `visual_contract`，并同步落到 template 的 `data-qb-card-visual-kind` 与 manifest 的 `visual_kind`。当前生成器内置：

- `event-flow`：事件链、传导链、阶段剧本；核心区必须有 `data-qb-card-visual`。
- `basis-structure`：期货相对现货的贴水/升水结构，用基差轴而不是三行价格。
- `numeric-focus`：仅适合明确的评分/温度/水位页；必须显式传 1-3 个带中文标签的 metrics，首项为唯一主数字，后两项只解释。

后续扩展优先使用 `bubble-field`、`signal-curve`、`ladder`、`rotation-wheel`、`waterline`、`relative-lines` 等页面语义名；未实现的 kind 必须返回 `CARD_VISUAL_UNSUPPORTED`，不能偷偷降级成 numeric-focus。

机器验收按内容预算检查：标题 ≤ 24 紧凑字符，描述 ≤ 56，整卡文本 ≤ 170，解释指标 ≤ 3，短标签 ≤ 3，不保留二级阅读块、排行榜或脚注式方法说明。示例映射：泡沫监测→随评分变大小的泡泡；涨跌停→红绿结构条 + 指标矩阵；多因子→雪花/雷达；估值财务→估值水位仪表 + PE/PB 分位；研究回测→净值小图。

## 内容口径

- 左上角：`data-qb-live-card-brand` 官方标签预留位，默认不显示固定文案。
- 日期：模板只放“待更新”与空 `datetime`，不内置历史日期；hydrate 按实时数据口径从所有 required outputs 的嵌套记录和有效值序列中选择最新可用日期，回填为 `YYYY-MM-DD`。
- 标题：一句重点结论；与外层标题重复时改判断句。
- 主指标：全页最重要的 1 个分数/价格/热度/风险等级。
- 标志性小图：保留原页最能被记住的可视化语言（泡沫场、涨跌停结构、估值水位、净值曲线）。
- 指标组：2-3 个解释结论的核心指标；标签 2-3 个短标签。

不要把整页表格、长解释、公式审计搬进卡片；卡片是封面不是报告正文，也不要把暗色 dashboard 截图当背景。

## 验收清单

1. 整页默认验收：`verify_page.mjs <html_file> --require-browser` 通过（完整页面正常，无占位符/横向溢出/核心取数错误）。
2. card runtime artifact 验收（二选一）：
   - 连同整页：`node scripts/verify_page.mjs "<html_or_url>" --require-browser --card-runtime`
   - 只验 artifact：`node scripts/verify_page.mjs "<html_or_url>" --card-runtime-only`
   - 新建/完整重建严格视觉验收：`node scripts/verify_page.mjs "<html_or_url>" --card-runtime-only --require-card-visual-contract`
   - 同时保存 720×540 候选图：在严格命令后加 `--card-screenshot output/card-candidate.png`
   - 批量：`python scripts/static_page.py verify_card_runtime '{"page_ids":["page_xxx"]}'`
   检查项：存在 `data-qb-card-template` / `data-qb-card-style` / `data-qb-card-manifest` / `data-qb-card-runtime`；manifest 为 `embedded-card-v1@1.1.0`、`aspect_ratio:"4/3"`、含 `required_outputs` 且不含任何图片地址；在 720×540、410×308、320×240 空白宿主里独立 hydrate 成功、根节点含 `data-qb-live-card` 和 `data-qb-card-ready="true"`；标题 ≤24 / 描述 ≤56、`numeric-focus` 或 `visual-focus` 二选一；卡片浅色系；只有 hydrate 后仍残留「待更新 / 取数中 / —」才判失败。严格视觉模式还会检查 template/manifest 的 visual kind 一致、拒绝通用文案、可见原始 output key、重复 `qb-mini-metric` 和缺失主视觉标记。

如要更新线上已分享页面：普通静态页 `static_page.py update`（保持同一 `page_id`/URL）或 `retrofit_card_runtime update:true`；已转公共模板且普通 update 报 `PAGE_NOT_FOUND` 时先 `template --page_id` 确认——本 skill 侧不提供该类模板的写回命令（`retrofit_card_runtime` 会返回 `TEMPLATE_WRITE_UNSUPPORTED`），需要保留原模板链接更新只能走后台/admin 管理入口，不要新建链接冒充原链接。
