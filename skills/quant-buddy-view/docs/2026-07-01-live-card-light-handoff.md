# quant-buddy-view 宽宝活卡浅色统一交接

日期：2026-07-01

## 背景

本次需求不是修改官网 `/templates` 的展示壳，而是修改 `quant-buddy-view` 生成和改造 card HTML 的规范：以后 Agent 生成的「宽宝活卡」必须统一为官网浅色系、固定信息骨架、实时取数、4:3 card-only 模式。

用户可见名称统一为「宽宝活卡」。`精华卡`、`封面卡`、`cover card` 只能作为开发别名，不应出现在用户可见 UI。

## 已落地的 qbv 变更

当前修改在 `D:\project\skill-lab\quant-buddy-view`，尚未提交。

已改文件：

- `SKILL.md`
  - 版本提升到 `0.4.3`。
  - 增加宽宝活卡硬规则：浅色官网系、固定顶部/标题/描述/核心区骨架、标准入口 `?cover=1`、禁止新增 `ratio/gallery` 等旧参数、必须带可验收 DOM 标记。

- `guides/essence-cover-card.md`
  - 新增或重写宽宝活卡开发指南。
  - 定义浅色主题契约、DOM 标记、数据接入方式、验收流程。

- `guides/README.md`
  - 增加宽宝活卡指南索引。

- `assets/live-card.css`
  - 新增共享浅色外壳样式。
  - 提供统一 4:3 card-only 布局、字体 token、浅色背景、主题强调色。

- `assets/live-card.js`
  - 新增轻量辅助函数：判断 `?cover=1`、切换显示、格式化日期、填充文本/指标。

- `scripts/compile_bespoke_page.py`
  - 新增占位符内联：
    - `<!-- QB_LIVE_CARD_CSS -->`
    - `<!-- QB_LIVE_CARD_JS -->`
  - 也兼容直接引用 `assets/live-card.css/js` 时的内联。

- `scripts/verify_page.mjs`
  - `--cover-card` 增强验收：
    - 720x540、580x435、390x292、320x240 四个 4:3 viewport 填满。
    - 禁止整卡深色底、黑底、深蓝底。
    - 必须显示「宽宝活卡」，不得显示「精华卡」。
    - 必须存在：
      - `data-qb-live-card`
      - `data-qb-live-card-brand`
      - `data-qb-live-card-date`
      - `data-qb-live-card-title`
      - `data-qb-live-card-description`
      - `data-qb-live-card-core`
    - 更新日期必须是 `YYYY-MM-DD`。
    - 顶部 meta、标题、描述字号在统一范围内。
    - 禁止长期停留在「取数中 / 判断生成中 / —」等占位态。

- `tests/fixtures/live-card-smoke.template.html`
  - 新增 smoke fixture，用于编译并跑 `--cover-card` 验收。

## 活卡 HTML 规范

所有新生成或改造的宽宝活卡必须在同一份页面 HTML 内实现，不创建独立 card HTML 页面。默认完整页不显示卡片；只有 URL 显式传 `?cover=1` 时进入 card-only 模式。

固定结构：

1. 顶部 meta
   - 左侧固定显示「宽宝活卡」。
   - 右侧显示更新日期，格式 `YYYY-MM-DD`。

2. 标题
   - 页面的一句话结论或主题。

3. 描述
   - 说明核心判断依据。

4. 核心表达区
   - 用数字、圆环、结构条、曲线、小图表、指标矩阵等表达页面最核心内容。
   - 可视化形式可变，但必须放在统一 `data-qb-live-card-core` 容器里。

最小 DOM 契约：

```html
<section class="essence-section" id="essenceSection" aria-label="宽宝活卡" hidden>
  <article class="essence-card" id="essenceCard" data-qb-live-card data-theme="orange">
    <div class="live-card-meta">
      <span data-qb-live-card-brand>宽宝活卡</span>
      <time data-qb-live-card-date datetime="2026-07-01">2026-07-01</time>
    </div>
    <h1 data-qb-live-card-title>页面核心结论标题</h1>
    <p data-qb-live-card-description>用一行描述说明核心判断依据。</p>
    <section class="live-card-core" data-qb-live-card-core>
      <!-- Agent 基于页面提炼核心可视化 -->
    </section>
  </article>
</section>
```

主题规则：

- 根背景必须是浅色官网系。
- 禁止整卡深色底、黑底、深蓝底。
- 红、蓝、绿、橙等主题色只能作为强调色，用在顶部细线、核心图形、关键数字、标签、结构条。
- 字号必须使用共享 token；不同模板在同 viewport 下不要各自发挥。
- 小视口只允许按统一 breakpoint 缩放。

数据规则：

- 宽宝活卡数据必须复用完整页面同一轮实时取数结果。
- 不允许硬编码数值。
- 取数失败时可以显示浅色错误兜底，但不能显示旧暗色卡或长期占位。

## 当前示例页

已改造并发布的示例：

- 页面：`全球资产泡沫监测`
- page/template id：`page_973ce4a8bff9a7bbd814f11c`
- 完整页：
  `https://pages.quantbuddy.cn/pages/skill_1773824558486_02dfce/page_973ce4a8bff9a7bbd814f11c.html`
- 活卡页：
  `https://pages.quantbuddy.cn/pages/skill_1773824558486_02dfce/page_973ce4a8bff9a7bbd814f11c.html?cover=1`

本地相关文件：

- 原线上快照：
  `output/pages/page_973ce4a8bff9a7bbd814f11c.public-current.html`
- 浅色改造版：
  `output/pages/page_973ce4a8bff9a7bbd814f11c.live-card-light.html`
- 发布结果：
  `output/pages/page_973ce4a8bff9a7bbd814f11c.updateTemplate.light-card.json`
- 线上活卡验收：
  `output/pages/page_973ce4a8bff9a7bbd814f11c.verify-light-public-cover.json`
- 线上完整页验收：
  `output/pages/page_973ce4a8bff9a7bbd814f11c.verify-light-public-default.json`

这张页面原本已有暗色 `qb-cover-*` 活卡。本次只替换了 card-only 的外壳、DOM 标记、日期格式和响应式约束，页面主体和实时取数公式包未变。

## 验收命令

基础脚本检查：

```powershell
python -m py_compile scripts\compile_bespoke_page.py
node --check scripts\verify_page.mjs
node --check assets\live-card.js
git diff --check -- quant-buddy-view
```

本地活卡验收：

```powershell
node scripts\verify_page.mjs "output\pages\page_973ce4a8bff9a7bbd814f11c.live-card-light.html?cover=1" --require-browser --cover-card
```

本地完整页验收：

```powershell
node scripts\verify_page.mjs "output\pages\page_973ce4a8bff9a7bbd814f11c.live-card-light.html" --require-browser
```

线上活卡验收：

```powershell
node scripts\verify_page.mjs "https://pages.quantbuddy.cn/pages/skill_1773824558486_02dfce/page_973ce4a8bff9a7bbd814f11c.html?cover=1" --require-browser --cover-card
```

线上完整页验收：

```powershell
node scripts\verify_page.mjs "https://pages.quantbuddy.cn/pages/skill_1773824558486_02dfce/page_973ce4a8bff9a7bbd814f11c.html" --require-browser
```

## 发布和模板页注意事项

普通私有静态页可以继续走：

```powershell
python scripts\static_page.py update @params.json
```

但公共模板页可能已经从普通 page 转成 published template。此时：

- `static_page.py download/update` 可能返回 `PAGE_NOT_FOUND`。
- 先用 `static_page.py template --page_id ...` 或 `template @params.json` 确认 `template_status: "published"`。
- 若必须保留原模板链接，不能创建新 URL 顶替；应走后台/admin `POST /skill/updateTemplate`。

本次示例页就是 published template。安全流程：

1. 查询模板详情，记录 `template_id/title/description/category/download_url/package_ids`。
2. 直连下载当前线上 HTML，计算 hash，与最初快照比对。
3. 本地改造并跑默认页和 `?cover=1` 验收。
4. 写回前重新查询 metadata；若 `download_url/title/description/category/size/sha256/updated_at` 等关键字段变化，应停止并 rebase。
5. 调 `POST /skill/updateTemplate`，保持同一个 `template_id/page_id/public_url`。
6. 发布后重新跑线上验收。
7. 若官网范式库需要展示 live iframe，还要补模板元数据 `cover_card_url=<public_url>?cover=1` 与 `has_cover_card=true`。详见官网交接文档。

## 当前已知坑

- `updateTemplate` 当前会更新 HTML，但会忽略 `cover_card_url` 和 `has_cover_card`，不能只靠它完成官网范式库展示切换。
- `static_page.py template` 当前返回中没有暴露 `cover_card_url/has_cover_card`，即使官网 API 已能读到这些字段。后续建议补齐脚本输出。
- 已发布模板不应由 Agent 创建新页面链接冒充修复。
- Windows PowerShell 传中文 JSON 容易出编码问题，复杂参数继续用 `@params.json`。
- 小视口 320x240 下不要使用 `100svh` 撑高 card-only 容器；示例页改用 `100dvh/100vh` 固定 viewport。

## 后续迭代建议

1. 把 `assets/live-card.css/js` 更深地接进所有 bespoke/template 生成路径，避免每张旧页手工复制浅色规则。
2. 给 `static_page.py` 增加安全的 admin/helper 命令，用于 published template 的 `updateTemplate` 与 cover metadata 更新，避免临时脚本。
3. 让 `static_page.py template/templates` 返回 `cover_card_url` 和 `has_cover_card`。
4. 把当前 7 个 published 模板逐个改造为浅色宽宝活卡，并全部跑 `--cover-card`。
5. 增加 visual screenshot regression，至少覆盖 720x540、390x292、320x240。
6. 更新 `render_existing_page_thumbnail.py`：如果页面已有合格 `?cover=1`，优先截图 live cover，而不是旧 thumbnail。
7. 清理旧文案中的 `精华卡 / cover / gallery / ratio` 用户可见表述。

## 给新 Agent 的接手顺序

1. 先阅读 `SKILL.md` 中“宽宝活卡”硬规则。
2. 阅读 `guides/essence-cover-card.md`。
3. 跑 smoke fixture 验收，确认本机浏览器路径可用。
4. 选一个现有模板复制示例页流程改造。
5. 本地和线上均通过 `--cover-card` 后，再更新官网展示元数据。
