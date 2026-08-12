# 模板路由（在线模板接口）

模板已**统一走在线接口**，本目录不存放模板文件，只说明路由。

## 在线公共模板

用户要生成、复用、发布或更新固定页面形态时：

1. `python scripts/static_page.py templates` —— 列出在线公共模板（普通用户只见 `published`）。
2. `python scripts/static_page.py template '{"page_id":"page_xxx"}'` —— 看某模板详情，拿 `download_url`。
3. 直连 `download_url`（OSS）取回 HTML，替换标的、文案、公式包凭证后，再 `upload` 成用户自己的页面。

详见 [tools/static_page.md](../tools/static_page.md) 的 `templates` / `template` 小节。

## 公共页头页尾组件

所有落地页共用的页头、页尾、刷新按钮、分享海报弹层等，由 **[`../assets/share-shell/`](../assets/share-shell/README.md)** 提供（是公共组件，不是模板）。
