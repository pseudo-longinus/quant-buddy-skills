# QuantBuddy Share Shell

公共落地页组件，供 `quant-buddy-view` 的 bespoke 主体和 `build_dashboard.py` 标准页在构建期内联使用。它只提供官网页头 iframe 宿主、页尾、投研仓收藏弹层、分享弹层和 Parent Bridge 运行时行为，不是页面模板；Agent 不应把这里的片段复制成完整页面起点。

## 文件

- `contract.json`：当前 Share Shell 的 `version`、`revision` 与必须能力清单，是构建、检测和后台策略同步的源契约。
- `shell.html`：官网页头 iframe Host、轻量 fallback、页尾、投研仓/鉴权/Web Agent iframe 与分享海报弹层结构。
- `shell.css`：页头 Host/fallback、暗色品牌外壳、弹层和移动端约束；完整可见页头视觉在官网 endpoint 中维护。
- `poster.js`：固定海报页头/页尾、大二维码、canvas 绘制；默认前端截取页面主体作为预览，失败时再程序化降级，宁缺毋滥。
- `shell.js`：官网页头 Parent Bridge、刷新、投研仓与鉴权通信、移动端 Web Agent 底部对话框、桌面端 Playground 跳转、页面问题携题自动发送、分享弹层、复制链接、复制图片、下载 PNG 行为。

## 模板契约

模板负责主体内容和数据解释，必须暴露：

- `load()`：刷新当前页面实时数据。
- `getPosterData()`：返回当前模板的动态海报内容。

接入方式：

```html
<!-- QB_SHARED_SHELL_CSS -->
<!-- QB_SHARED_SHELL_HEADER -->
<!-- QB_SHARED_SHELL_RESEARCH_WAREHOUSE -->
<main>模板主体内容</main>
<!-- QB_SHARED_SHELL_FOOTER -->
<!-- QB_SHARED_SHELL_MODAL -->
<!-- QB_SHARED_QR_MINI -->
<!-- QB_DATA_KERNEL -->
<!-- QB_SHARED_SHELL_JS -->
<script>
function getPosterData(){ return { headline, summary, metrics, sections, asof }; }
QBShareShell.init({ onRefresh: load, getPosterData, templateName: "个股估值体检" });
load();
</script>
```

最终发布前用 `scripts/compile_bespoke_page.py` 编译，输出 HTML 必须自包含，不保留本地 `script src`、公共组件占位符或模板凭证占位符。

## 版本与 artifact 契约

- 当前目标为 `share-shell-v2 / revision 5`，必须包含 `research_warehouse`、`brand_warehouse_navigation`、`mobile_web_agent_sheet`、`desktop_playground_navigation`、`agent_page_refresh`、`official_header_iframe`、`web_agent_auto_submit`、`public_page_serial_update` 八项能力。
- 编译后的 HTML 注入 `QB_SHARE_SHELL_VERSION` 和 `QB_SHARE_SHELL_REVISION`，供服务端 fail-closed 检测；未识别版本或 revision 不得标记为 verified。
- `scripts/share_shell_contract.py` 只提取 `QB_SHELL_CSS/HEADER/RESEARCH_WAREHOUSE/FOOTER/MODAL/JS` 六组 Marker，统一换行和区块首尾空白后计算 SHA-256。当前标准 artifact hash 由 canonical managed shell 生成，并必须与后台目标策略一致。
- `refresh_share_shell:true` 只能替换这六组 Marker；正文、Data Kernel、实时数据脚本和 Card Runtime 必须保持不变。
- 完整可见页头由官网 `/embed/live-page-header` 托管：纯视觉与排版调整只更新官网 endpoint，不需要逐页刷新。只有 Parent Bridge、`qb-live-page-header-v1` 通信协议或能力契约变化才提升 `contract.json` revision，并同步检测规则、后台目标策略和回归测试。

## 海报策略

默认海报不理解业务结构，而是前端截取当前页面状态：

- 优先截 `[data-qb-poster-target]`；
- 没有标记时截 `main`；
- 再没有则截 `.wrap` / `body`；
- 截图会自动排除公共页头、页尾、分享弹层、按钮、旧二维码以及 `[data-qb-poster-exclude]`。

模板可以给最想展示的主体容器加 `data-qb-poster-target`，但不要为海报单独复制一套 DOM。截图失败或显式传 `posterMode: "structured"` 时，才使用下面的结构化候选数据兜底。

## `getPosterData()` 返回结构

```js
{
  headline: "贵州茅台 个股估值体检报告",
  summary: "1-2 行核心说明",
  metrics: [{ label: "PE(TTM)", value: "23.1", sub: "实时取数" }],
  sections: [
    { title: "估值水位", type: "water", items: [{ label: "PB", value: 55, display: "55%" }] },
    { title: "归因拆解", type: "bars", items: [{ label: "价格变化", value: -8.2, display: "-8.2%" }] }
  ],
  asof: "2026.06.23"
}
```

结构化兜底会再次程序化筛选：

- `metrics` 最多展示 6 个，空值、占位值、口径类字段会被丢弃；
- `sections` 最多展示 1 个，高优先级为 `water` / `bars`，口径提示、免责声明等不会上图；
- 数据不够干净时不硬凑模块，只保留标题、摘要、二维码和“打开完整实时页”提示；
- 模板不要为了海报美观手搓 canvas，也不要把整页内容塞进 `sections`。

## 验收

- 页头固定为 `QuantBuddy · 宽宝`，右侧固定 `刷新数据 / 收藏 / 分享 / 问一问`。
- “问一问”按当前公开页 URL 生成对应 `/playground/<owner path>/<page_id>`：移动端（`max-width: 680px`）在当前页打开 `75dvh` 的 chat-only `/embed/web-agent` 底部对话框，桌面端继续经当前页鉴权 iframe 进入 Playground。
- Web Agent 回答结束后，可信 `turn-complete` 调用页面 `onRefresh` 刷新实时数据；检测到活页 HTML 更新时，可信 `page-updated` 关闭对话框并重载当前页。
- 收藏和 Web Agent 通信都必须同时校验官网/本地允许 origin、精确 iframe source、channel 与 `page_id`；Web Agent 额外只接受匹配的官方 `page_url`。
- 投研仓 iframe 五秒未通信时降级为新窗口；静态页不读取 Cookie，也不接收 Token、用户名或文件夹明细。
- 页面中不再出现旧的“手机扫码查看”二维码块或模板自带刷新按钮。
- 分享海报可预览、复制链接、复制图片、下载 PNG，二维码尺寸可扫。
- 移动端 320px 无横向溢出，Web Agent 底部对话框约占 3/4 屏，遮罩、关闭按钮和 Escape 均可关闭。

## 公开页两步更新（revision 5）

官网页头 ready 声明 public_update；外壳 init/state 声明 public_update 和 update_busy。新旧两端均支持时显示「更新活页」，旧外壳继续原「刷新数据」。action:update 触发外壳旧 onRefresh；结束或失败后发送 update-data-settled（flow_id、data_failed、可选 job_id、resume）。官网来源内 GET 既有 refresh 接口检查创建者权限，随后仅 POST mode:text。401/403跳过，不弹登录或创建副本；无外部链接不阻断文字更新。

官网通过 update-progress 回传同页、同flow的有限状态，外壳展示非模态两步时间线。第一步明确失败仍允许创建者继续。后台任务实际发布且验收通过才回传 reload:true/version_no；外壳整页加载一次并尽量恢复锚点或scrollY，无变化不重载。resume只读取原任务，不能重新POST不确定的请求。此功能不在WebAgent Preview中启用。

此变更修改受管理的HTML/CSS/JS及能力合同。上线或迁移已有页前，配套发布quantbuddy-web，并同步skill_server检测、dunhe_backend目标策略及新版canonical artifact hash；仅部署官网不会更新已内嵌的旧外壳。本次源码改动不自动覆盖任何线上页面。
