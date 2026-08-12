# build_dashboard — spec → 自包含看板 HTML

## image panel

`type:"image"` 只接受 `image_upload` 返回的绝对同域 WebP `image_url`，不接受本地文件、外部 CDN 或来源 page_id 的 URL，且不参与公式/授权输出健康检查。

```json
{
  "type": "image",
  "title": "商业模式",
  "image_url": "https://pages.quantbuddy.cn/pages/assets/page_xxx/asset_xxx.webp",
  "alt": "公司商业模式与收入结构示意图",
  "caption": "资料来源：公司公告",
  "span": "full",
  "fit": "contain",
  "zoomable": true,
  "width": 1600,
  "height": 900
}
```

`alt` 必填；`fit` 支持 `cover/contain/fill/none/scale-down`。正文图片默认 `zoomable:true`：点击后在当前页面打开大图，支持关闭按钮、点击遮罩和 `Esc` 退出，不跳转图片 URL；Logo、海报或纯装饰图可传 `zoomable:false`。首屏/海报区域默认 eager，只有明确位于正文下方时才传 `loading:"lazy"`。

页面全部由 `text/image` 面板组成时可直接生成静态看板，不要求公式包或数据授权；只要出现 `line/bar/table/number/raw` 等数据型面板，仍必须提供对应的 `output` 或 `grant_id`。

> 把「公式任务包 + 看板 spec」编译成一份自包含 HTML（样式内联，图表用公网 CDN ECharts）。可顺带上传发布。
> 通过本地脚本 `scripts/build_dashboard.py` 调用（单命令，无子命令）。

> 分支门禁：同一 `task_id` 已由 `fork_prepare` 绑定为 prepared fork 时，本命令返回 `FORK_TASK_BOUND`，并指向应继续编辑的 `working_html_file`；此时必须改走 `static_page.py fork_validate`，不能重建通用看板。

## 调用方式

```bash
# 写好 spec.json，生成 live 实时取数 HTML
python scripts/build_dashboard.py @spec.json

# 生成并一步发布（upload 凭 config.json 的 api_key 认身份）
BD_PARAMS='{"title":"...","panels":[...],"upload":true}' python scripts/build_dashboard.py
```

## spec 参数（优先级：BD_PARAMS > @file > 命令行 JSON > stdin）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `title` | string | ✅ | 看板标题（`<title>` + 页头） |
| `subtitle` | string | ❌ | 副标题 |
| `description` | string | ❌ | 页面说明（≤1000 字），仅作 `static_page` 列表/详情展示；显式传才随 upload/update 透传，不传则不动 |
| `page_context` | object | ❌ | 当前活页稳定语义；不传时根据最终标题、面板和输出重新生成，禁止复制来源模板上下文 |
| `agent_reply_template` | object | ❌ | 显式回复骨架；不传时按页面主题匹配专业骨架，无法匹配则使用 `generic_live_page_delivery_v1` |
| `package_id` | string | ❌ | 公式包 id；缺省取**最近一次**本地凭证 |
| `signature` | string | ❌ | 缺省从本地凭证补全；会写入页面供实时取数，必须可得 |
| `panels` | object[] | ✅ | 面板数组，见下 |
| `out_file` | string | ❌ | 输出 HTML 路径，默认 `output/pages/<slug>.html` |
| `upload` | bool | ❌ | true 则生成后调用 `static_page` 上传，结果回填 `url` |
| `update_page_id` | string | ❌ | 替换已发布页面，URL/page_id 不变 |
| `verify_packages` | bool | ❌ | 上传/替换后强制解析页面内 package_id + signature 做一次轻量 query 校验；默认仅服务端提示公式包异常时触发 |
| `ttl_days` | number | ❌ | 配合 upload 透传 |
| `live_card` | bool/object | ❌ | 在同页产出独立 card runtime artifact（`embedded-card-v1`）宽宝活卡；对象可传 `title`、`description`、`theme`、`primary`、`metrics`、`tags`、`date_output` |
| `brand` | object | ❌ | 统一分享外壳配置，见下 |
| `official_url` | string | ❌ | 官网入口，默认 `https://www.quantbuddy.cn` |
| `show_qr` | bool | ❌ | 是否显示页面二维码，默认 `true` |
| `share_url` | string | ❌ | 二维码指定链接；缺省时浏览器用最终页面 `location.href` 生成 |
| `page_type` | string | ❌ | 页头标签，默认 `量化看板` |
| `template` | string | ❌ | 页面模板标识；单标的画像页请传 `single-stock`，会启用模板契约校验 |

### 统一分享外壳

`build_dashboard` 默认给所有标准页面加上 QuantBuddy 分享外壳：品牌页头、官网入口、扫码二维码、标准页尾和风险提示。
二维码在浏览器端生成：未传 `share_url` 时使用当前页面 `location.href`，因此上传到 `pages.quantbuddy.cn` 后，二维码自动指向最终公开链接。
二维码卡仅在桌面/宽屏展示；移动端默认隐藏二维码区域，把首屏空间留给标题、摘要和官网入口。

`brand` 可覆盖展示文案：

Share shell design and verification rules live in [`guides/share-shell.md`](../guides/share-shell.md).

Default brand logo: standard pages inline `assets/logo.svg` into the share header so uploaded HTML does not depend on a local file path. If the SVG is missing or fails the safety check, the header falls back to the text mark `QB`.

```json
{
  "brand": {
    "name": "QuantBuddy",
    "cn_name": "观照量化",
    "tagline": "Agent 调用 Skill 计算 · HTML 可调",
    "homepage": "https://www.quantbuddy.cn",
    "page_type": "个股画像",
    "official_label": "进入官网",
    "share_title": "手机扫码查看",
    "footer_note": "页面仅作市场观察与数据展示，不构成投资建议。",
    "show_qr": true
  }
}
```

### `panels[]` 元素

| 字段 | 必填 | 说明 |
|---|---|---|
| `output` | ✅* | 对应公式包 `reads` 的产出名（= query 返回 outputs 的 key）。`text` 面板不需要；数据授权面板改填 `grant_id`，二者其一 |
| `grant_id` | ✅* | 数据授权面板：填 `dg_...`，构建期自动补 signature、运行时走 `queryDataGrant`（普通 JSON）。与 `output` 互斥，可与公式包面板同页混用 |
| `title` | ❌ | 面板标题，缺省用 `output` |
| `type` | ❌ | `line` / `bar` / `radar`（雷达图） / `table`（默认） / `number` / `text` / `raw` |
| `x` | ❌ | line/bar 横轴字段（缺省取首列；range_data 自动取 dates） |
| `y` | ❌ | line/bar 纵轴字段数组（缺省取除 x 外的数值列） |
| `columns` | ❌ | table 指定列（缺省自动推断） |
| `value_field` | ❌ | number 取值字段（缺省取**最后一个数值列的末个有效值**，自动跳过尾部 null；range_data 即取序列值，不会误命中日期列。仅当默认列不对时才需指定） |
| `unit` | ❌ | number 单位 |
| `description` | ❌ | 面板说明；number 面板会显示在数值下方，其它面板显示在标题下方 |
| `span` | ❌ | `full` / `wide` / `auto`；line/bar 默认 `full`，number/table 默认 `auto` |
| `height` | ❌ | 图表高度，单位 px；仅 line/bar/radar 有效 |
| `text` | ❌ | `text` 面板正文，用于摘要、解读、风险提示等无取数输出的说明块 |
| `dual_axis` / `right_series` | ❌ | line/bar 双轴：`dual_axis:true` + `right_series:["output名",...]` 声明哪些系列归右轴，其余归左轴；单 output 面板用 `chart_edit.py add_series` 的 `axis:"right"` 追加第二条线时自动写入 |
| `sparkline` | ❌ | line/bar 面板传 `true` 时去掉坐标轴/图例/网格留白，只画曲线本身（迷你走势图场景） |
| `max` | ❌ | radar 面板每个维度的满分刻度，缺省 `1`（比例型 0..1 分数） |
| `target_selector` | ❌ | 仅 `emit=panel_block` 局部产出模式使用，见下 |

> 渲染器会自动把公式包各 read_mode 的 `data` 归一为 {列, 行}：
> `range_data.{dates,values}` → 折线；`last_day_stats` 对 1 维序列返回的 `last_value.{date,value}` → 数值；
> `last_day_stats.top_values[]` / `last_valid_per_asset[]` → 表格。多数 panel 只需写 `output` + `type`。
> 渲染器已内置：整数日期 `YYYYMMDD` → `YYYY-MM-DD`、裁掉序列尾部 null、折线 `connectNulls`、number 跳空取末个有效值——**这些后处理不必再在 spec 里手写**。
> `text` 面板不需要 `output`，构建期体检会跳过它；适合在单标的画像页里放一句摘要或观察点。

> ⚠️ **构建期取数失败即硬失败**：构建时会先取一次数做质量体检（只用于校验，不内联进 HTML）。若有任一产出失败或体检为空（如 range_data 全 null / 区间无数据），`build_dashboard` 返回 `code:1` 并在 `failed_outputs` 指明哪个 output、疑因，**不生成 HTML**。务必检查返回 `code`，不要把「没报错」当成功。

### 宽宝活卡（`live_card` → card runtime artifact）

传 `"live_card": true`（或对象）时，标准看板会在同一份 HTML 内产出独立 **card runtime artifact**（`embedded-card-v1`：`<template data-qb-card-template>` + `data-qb-card-style` + `data-qb-card-manifest` + `QBCardRuntimeV1` runtime），供官网卡片流 / 截图工具在空白宿主里 `QBCardRuntimeV1.mount()` 独立 hydrate 出 4:3 卡片。上传/更新可传 `verify_card_runtime:true` 做 artifact 门禁。

```json
{
  "title": "市场温度监测",
  "live_card": {
    "theme": "red",
    "title": "短线情绪一眼看懂",
    "description": "核心指标实时刷新，打开即取最新公式包输出。",
    "metrics": [
      {"label": "温度", "output": "TEMP", "field": "value", "unit": "分"},
      {"label": "涨停", "output": "LIMIT_UP", "field": "count"}
    ],
    "tags": ["实时取数", "重点摘要"]
  }
}
```

`metrics` 不传时会优先从 number panels 自动取 2-3 个核心指标。card runtime artifact 的 manifest 钉死 `package_id/signature/required_outputs`，hydrate 时实时取数、不写死数值；不要新增 `ratio/gallery` 参数。卡片左上角只保留官方标签预留位，不显示固定「宽宝活卡」文案。

### 模板契约校验

单标的画像页必须使用在线模板接口复用合适模板，或自行提供满足契约的 spec，并保留 `template: "single-stock"`。

如果标题或 `page_type` 表明是“个股画像”，但 spec 仍是旧版 `1 条价格线 + 少量数字卡`，`build_dashboard` 会返回 `code:1`，并提示补齐：

- 阅读摘要 `text` panel；
- 最新收盘价 `px` number panel；
- `chg` / `ret20` / `ret60` / `pe` / `pb` / `amt_yi` 默认 outputs；
- 近一年收盘价 `px` line panel。

单标的画像页还会校验 `subtitle` 和阅读摘要中的关键数值是否匹配构建期实时取数结果（最终 outputs）。若文案里写了收盘价、涨跌幅、20/60 日表现、PE、PB、成交额，但数值与最终取数不一致，脚本返回 `code:1`、`mismatches` 和 `facts`。用 `facts` 重写文案后再生成/上传。

## 实时取数

页面是实时取数的：HTML 骨架自包含（样式/脚本内联），数据在浏览器打开时实时 `fetch` 最新——底层数据更新后无需重新 build，页面打开即最新。

- HTML 内写入 `endpoint / package_id / signature`，打开时调 `queryFormulaPackage` 取数（signature 会公开在页面里）。
- 前置：端点须对页面域名放开 **CORS**，且页面与端点协议一致（https 页面配 https 端点，否则 mixed-content 被拦）。当前 `https://www.quantbuddy.cn/skill` 已满足。
- 构建期仍会取一次数，用于质量体检 + 单标的文案一致性校验 + 产出 `facts`，不会内联进 HTML。
- spec 不需要写 `mode` 字段；旧 spec 里残留的 `"mode"` 会被忽略。

## 输出

```json
{ "code": 0, "out_file": "output/pages/xxx.html", "mode": "live",
  "package_id": "pkg_...", "panels": 3, "size": 12345,
  "manifest": "output/pages/xxx.manifest.json",
  "facts": {"px":{"value": 166.41, "date": 20260616}},
  "url": "https://pages.quantbuddy.cn/..."  // 仅 upload=true 且成功时 }
```

同名 `*.manifest.json` 会记录 `page_id`、URL、HTML sha256、endpoint、公式包角色、package_id、构建时间与验证结果。不会记录 API key 或 signature。

> **产物目录约定（本 skill 所有脚本共用）**：一切生成物——看板 HTML、manifest、公式包/数据授权凭证、临时预览与 demo——**只落在 `output/` 下**（`output/pages/`、`output/formula_packages/`、`output/data_grants/`；随手的试验/demo 放 `output/_demo/`）。`output/` 已在 `.gitignore` 里，属会话级 scratch。**不要在 skill 根目录另建 `_demo`、`tmp`、`preview` 等顶层文件夹**——顶层只保留 `SKILL.md / CHANGELOG.md / scripts / tools / guides / workflows / templates / reply-templates / tests / assets / config.json` 这套固定骨架。本地预览也从 `output/` 起服务（如 `python -m http.server 8899 --bind 127.0.0.1`，cwd 指向 `output/_demo/`）。

## 局部产出模式（`emit: "panel_block"`）

不生成整页 HTML，只生成一段带 `QBV_RENDER_JS_START/END` marker 的 `<script>` 片段，供 bespoke（手写）页面把某几个图表交给标准声明式引擎画。用法：

```bash
python scripts/build_dashboard.py '{
  "emit": "panel_block",
  "package_id": "pkg_xxx", "signature": "sig_xxx",
  "panels": [
    { "title": "价格趋势与均线", "type": "line", "target_selector": "#priceChart", "outputs": ["px","ma20","ma60"] }
  ]
}'
```

- 每个 panel 必须传 `target_selector`：bespoke 页面里已经排好版、已有自己样式的容器选择器（如 `#priceChart`）。运行时会把这个 panel 直接渲染进该容器，不包卡片外壳（无标题/边框/间距），bespoke 布局不受影响；选择器命中不到时退化为标准网格卡片（不整页报错，但需要页面里存在 `#grid`）。
- `panels`/`package_id`/`signature`/`formulas`/`reads`/`grant_id` 与整页模式同源，不需要 `title`/`out_file`/`upload` 等整页专属字段。
- 返回 `{code, script_html, package_id, panels, size}`；`script_html` 是完整字符串，粘贴进 bespoke 页面 `<body>`（放在对应容器**之后**）即可。默认带 ECharts CDN `<script>` 标签，若 bespoke 页面已引入 ECharts 可传 `"include_echarts_cdn": false` 跳过。
- 生成的图表带标准 marker，之后可用 `chart_edit.py` 的 `add_series`/`remove_series`/`set_window`/`query_data` 对其定点编辑（`chart_edit.py inspect`/`_patch_page` 会自动识别这是嵌入式启动、编辑后不会误换成接管整页的引导逻辑）。
- 详见 [guides/bespoke-page.md](../guides/bespoke-page.md) 「图表类可视化」一节。

> 端到端示例：[workflows/dashboard-end-to-end.md](../workflows/dashboard-end-to-end.md)。
