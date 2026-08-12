# retrofit_share_shell — 旧页面迁移公共页头页尾

> 把已经生成或已经发布的旧 HTML 改成统一公共 share shell：删除旧二维码、旧页尾，保留旧页面主体 hero、取数配置和图表逻辑。

## 什么时候用

- 用户给了 `pages.quantbuddy.cn` 旧页面链接，要求“去掉二维码 / 当前页头 / 页尾”。
- 已有本地 HTML 要适配固定公共页头页尾。
- 已分享出去的页面要保持原 URL，只替换内容。

不要靠长提示词手工删 DOM。先跑本工具生成本地迁移版，检查通过后再 `update:true` 覆盖同一个 `page_id`。

默认语义：旧 `<header class="share-shell">` 里的标题、摘要、标签等属于页面主体 hero，必须原样保留；右侧二维码卡片不可见，但保留原布局占位，避免左侧内容重排。公共页头会作为新的固定外壳插入到页面最上方。

插入策略很简单：公共页头直接插到 `<body>` 后，公共页尾直接插到 `</body>` 前。工具不会把旧节点当作公共组件的挂载点。

## 调用方式

```powershell
# 1) 只生成本地迁移版，不覆盖线上
python scripts/retrofit_share_shell.py '{"url":"https://pages.quantbuddy.cn/pages/.../page_xxx.html","out_file":"output/pages/page_xxx-retrofit.html","theme":{"chrome_bg":"#101827","accent":"#d8a54b"}}'

# 2) 确认后覆盖同一个 page_id，URL 不变
python scripts/retrofit_share_shell.py '{"page_id":"page_xxx","update":true,"theme":{"chrome_bg":"#101827","accent":"#d8a54b"}}'

# 3) 本地文件迁移
python scripts/retrofit_share_shell.py '{"html_file":"output/pages/old.html","out_file":"output/pages/old-retrofit.html"}'
```

`url` 模式会直接抓公开 HTML；只有 `page_id` 下载或 `update:true` 覆盖线上页面时才需要 `config.json` / `QUANT_BUDDY_API_KEY` 鉴权。

## 参数

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `url` | string | 三选一 | 已发布公开链接；可直接抓取 HTML，并从 URL 推断 `page_id` |
| `page_id` | string | 三选一 | 已发布页面 id；通过 `static_page.py download` 鉴权取回 |
| `html_file` | string | 三选一 | 本地旧 HTML 路径，相对路径按 skill 根目录解析 |
| `html` | string | 三选一 | 直接传 HTML 全文 |
| `out_file` | string | 否 | 输出路径；不传时写到 `output/pages/*-retrofit.html` |
| `update` | bool | 否 | `true` 时用迁移后的 HTML 覆盖同一个 `page_id` |
| `remove_legacy_hero` | bool | 否 | 默认 `false`；仅明确要移除整块旧 hero 时才设为 `true` |
| `collapse_qr_space` | bool | 否 | 默认 `false`；设为 `true` 时删除二维码卡片占位，让 hero 重新排版 |
| `title` / `description` / `ttl_days` | mixed | 否 | `update:true` 时透传给 `static_page.py update` |
| `theme.chrome_bg` | CSS color | 否 | 页头页尾共用背景色 |
| `theme.header_bg` | CSS color | 否 | 仅页头背景色，缺省等于 `chrome_bg` |
| `theme.footer_bg` | CSS color | 否 | 仅页尾背景色，缺省等于 `chrome_bg` |
| `theme.accent` | CSS color | 否 | 公共按钮、链接、强调色 |
| `theme.line` | CSS color | 否 | 公共边线色 |

主题只改公共页头页尾和弹层的颜色变量，不改变固定元素布局。

## 工具会删除

- 旧 hero 区域中的二维码内容；默认保留同尺寸隐形占位；
- 旧 `shareQrCanvas` 节点；
- 旧 `<footer class="site-footer">...</footer>`；
- 旧 `setupShareShell()` 和调用；
- 旧 QRCode CDN script。

默认不会删除旧 `<header class="share-shell">...</header>`；这块通常承载页面标题、摘要和标签。只有传 `remove_legacy_hero:true` 才会移除整块。只有传 `collapse_qr_space:true` 才会删除二维码占位并允许 hero 重排。

## 验收

工具会在编译后检查：

- 不再包含 `手机扫码查看`、`shareQrCanvas`、`setupShareShell`；
- 不再包含旧 `footer.site-footer`；
- 不残留 `QB_SHARED_` / `__QB_LOGO_SRC__` 占位符；
- 不残留旧 QRCode 外链；
- HTML 小于 2MB。

公共页头、页尾、刷新、分享海报弹层、复制/下载 PNG 由 `assets/share-shell/` 统一提供。
