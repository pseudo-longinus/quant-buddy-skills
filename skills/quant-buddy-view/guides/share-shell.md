# Share Shell Guide

Use this guide when changing the shared QuantBuddy landing-page shell: header, footer, refresh action, share-poster modal, poster canvas, QR code, copy image, and download PNG behavior.

## Product Intent

Every generated landing page should feel like one QuantBuddy artifact even when the body template is different:

- the body answers the user's concrete data question;
- the shell provides the fixed QuantBuddy brand frame;
- the refresh action reloads live formula-package data;
- the favorite action opens the official-site 投研仓 embed and keeps authentication inside the official origin;
- the share action creates a paste-ready poster with a fixed header, fixed footer, and dynamic body content;
- the final HTML remains self-contained after build or publish.

## Source Of Truth

Shared component files live in:

```text
assets/share-shell/
  contract.json
  shell.html
  shell.css
  shell.js
  poster.js
  README.md
```

Templates must not fork private header/footer/share-modal implementations. If the shell needs a visual or behavioral change, update the shared files and recompile affected pages.

## Versioned Capability Contract

`assets/share-shell/contract.json` is the source contract for the current managed shell. The current target is `share-shell-v2 / revision 4` with seven required capabilities:

- `research_warehouse`
- `brand_warehouse_navigation`
- `mobile_web_agent_sheet`
- `desktop_playground_navigation`
- `agent_page_refresh`
- `official_header_iframe`
- `web_agent_auto_submit`

Build output exposes `QB_SHARE_SHELL_VERSION` and `QB_SHARE_SHELL_REVISION`. `scripts/share_shell_contract.py` canonicalizes the six stable Marker regions (`CSS`, `HEADER`, `RESEARCH_WAREHOUSE`, `FOOTER`, `MODAL`, `JS`) and computes their SHA-256 artifact hash. The revision-4 artifact hash is generated from the canonical managed shell and must match the released admin policy.

The complete visible header is hosted by the official `/embed/live-page-header` endpoint. Pure visual/layout changes belong to `quantbuddy-web` and do not require a shell revision or page-by-page refresh. Parent Bridge, `qb-live-page-header-v1` protocol, or capability-contract changes are managed artifact changes: bump `revision`, update `contract.json`, update `skill_server` detection, update the `dunhe_backend` target policy, and extend regression tests. A shell-only refresh must preserve the page body, Data Kernel, live-data scripts, Card Runtime, `page_id`, and public URL.

## Public Interface

Each bespoke template must expose:

```js
function load() { /* refresh live data */ }
function getPosterData() {
  return {
    headline: "...",
    summary: "...",
    metrics: [{ label: "...", value: "...", sub: "..." }],
    sections: [{ title: "...", type: "list|bars|water", items: [] }],
    asof: "..."
  };
}

QBShareShell.init({
  templateName: "个股估值体检",
  onRefresh: load,
  getPosterData
});
```

The shell owns:

- official Header iframe Host plus a lightweight 4-second fallback;
- Parent Bridge routing for header brand and `刷新数据 / 收藏 / 分享 / 问一问`;
- Header protocol `qb-live-page-header-v1`: Header sends `ready/action/resize`, Parent sends `init/state`, and both sides validate origin, exact iframe source, channel, version, and matching `page_id`; resize is limited to 44–120px;
- favorite state: the shell accepts only fixed-origin, exact-iframe-source, matching-channel and matching-`page_id` messages;
- “问一问”: derive `/playground/<完整 owner path>/<page_id>` from the current `/pages/.../<page_id>.html` URL. At `680px` and narrower, keep the live page in place and open `/embed/web-agent` as a `75dvh` bottom sheet containing chat only; wider layouts keep the current-page `/embed/auth-continue` flow and navigate to Playground only after a trusted `authenticated:true` response;
- header brand: use the same current-page authentication iframe, then enter `/dashboard?scope=favorited`;
- authentication boundary: the static page keeps pending navigation and page context locally and never reads session cookies, tokens, or identity data. The auth iframe receives no redirect target; the Web Agent iframe receives only the validated `page_id` and official `page_url`. 收藏 remains a separate functional `/embed/research-warehouse` iframe because it also owns folder selection and collection actions;
- mobile Web Agent completion: trusted `turn-complete` messages call the template `onRefresh` hook; trusted `page-updated` messages close the sheet and reload the current live page so an updated OSS artifact becomes visible;
- footer risk note and official-site link;
- share modal structure;
- poster copy/download behavior;
- poster header/footer and large QR code.

The template owns:

- page body layout;
- data loading and rendering;
- dynamic poster headline, summary, metrics, sections, and `asof`.

The poster preview is intentionally empty until the user opens the share modal. Any `<img>` whose `src` is assigned only at runtime must declare `data-qb-runtime-src`; ordinary content images still require a non-empty static `src`. Do not add a transparent placeholder image, because `shell.js` uses an empty `src` to decide whether poster generation must run before download.

## Theming

公共页头和页尾的布局固定，模板或迁移脚本只能通过 CSS 变量换颜色：

```css
:root {
  --qb-shell-chrome-bg: #101827;
  --qb-shell-header-bg: var(--qb-shell-chrome-bg);
  --qb-shell-footer-bg: var(--qb-shell-chrome-bg);
  --qb-shell-accent: #d8a54b;
  --qb-shell-accent-strong: #d8a54b;
  --qb-shell-line: rgba(216,165,75,.35);
}
```

`--qb-shell-header-bg` 和 `--qb-shell-footer-bg` 可分别覆盖；不传时都跟随 `--qb-shell-chrome-bg`。不要为了主题色复制一份 header/footer DOM。

## Build-Time Inlining

Compile bespoke pages with:

```powershell
python scripts/compile_bespoke_page.py @params.json
```

The compiler replaces these placeholders:

```html
<!-- QB_SHARED_SHELL_CSS -->
<!-- QB_SHARED_SHELL_HEADER -->
<!-- QB_SHARED_SHELL_RESEARCH_WAREHOUSE -->
<!-- QB_SHARED_SHELL_FOOTER -->
<!-- QB_SHARED_SHELL_MODAL -->
<!-- QB_SHARED_QR_MINI -->
<!-- QB_DATA_KERNEL -->
<!-- QB_SHARED_SHELL_JS -->
```

Final HTML must not contain local `script src` references to `qr-mini.js`, `data-kernel.js`, or `_shared` files.

Compiled pages preserve six stable public-shell marker regions: `CSS`, `HEADER`, `RESEARCH_WAREHOUSE`, `FOOTER`, `MODAL`, and `JS`. They are the only regions replaced by an explicit shell refresh. Marker pairs must each appear exactly once; missing or duplicated markers fail closed.

## Explicit Shell Refresh

Existing published pages are **not** upgraded during an ordinary `static_page.py update`. To replace only the marked public shell of a prepared HTML file, pass:

```json
{
  "page_id": "page_xxx",
  "html_file": "output/pages/page_xxx.html",
  "refresh_share_shell": true
}
```

The input HTML must already contain one complete set of the six stable markers. Old pages without markers must first be rebuilt locally with `compile_bespoke_page.py`; never enable this flag as a bulk migration shortcut.

Local previews may pass `pageUrl`, `embedOrigin`, and `navigationOrigin` to `QBShareShell.init()`; production pages omit them and derive the current public page URL directly.

The 投研仓 iframe keeps its existing preload and new-window fallback behavior on ordinary public pages. If `<meta name="qb-live-page-embed-context" content="webagent-preview">` is present, the Parent Bridge does not load the Header iframe or preload 投研仓; the official Preview HTML proxy also hides legacy `.qb-head` and revision-4 Header Host elements with `display:none` so no top gap remains. The authentication iframe is not loaded or used for hidden session probing; it is created only after the user clicks the header brand or “问一问”. Both protocols validate the official origin, exact iframe source, channel, and request/page identifier. The static page never reads cookies or receives tokens, user identity, or folder details.

## Retrofitting Old Pages

旧页面已经生成或发布后，不要靠提示词手工删除二维码、页头、页尾。使用迁移工具：

```powershell
python scripts/retrofit_share_shell.py '{"url":"https://pages.quantbuddy.cn/pages/.../page_xxx.html","out_file":"output/pages/page_xxx-retrofit.html","theme":{"chrome_bg":"#101827","accent":"#d8a54b"}}'
```

确认本地 HTML 后，覆盖原链接：

```powershell
python scripts/retrofit_share_shell.py '{"page_id":"page_xxx","update":true,"theme":{"chrome_bg":"#101827","accent":"#d8a54b"}}'
```

详情见 [`tools/retrofit_share_shell.md`](../tools/retrofit_share_shell.md)。

## Verification Checklist

- Run `python -m py_compile scripts/build_dashboard.py scripts/compile_bespoke_page.py scripts/retrofit_share_shell.py`.
- Confirm generated HTML has no `QB_SHARED_`, `__PLACEHOLDER__`, `pkg_replace`, or `replace_with_signature` residue.
- Verify desktop, 390px, and 320px widths have no horizontal overflow.
- Verify header actions show `刷新数据 / 收藏 / 分享 / 问一问`.
- Verify the Header iframe reaches trusted `ready`, receives `init/state`, routes all five actions, clamps resize to 44–120px, and yields to the lightweight fallback after 4 seconds without `ready`.
- Verify WebAgent Preview has no header and no top gap, does not request Header/warehouse iframes under revision 4, while the public page still shows the Header iframe.
- Verify 441px and narrower hide refresh/share labels, keep the 收藏 text visible through 320px, and have no horizontal overflow.
- Verify the header brand stays on the current live page while `/embed/auth-continue` is authenticating and navigates only after a trusted success message. At mobile widths, verify “问一问” opens the `75dvh` chat-only `/embed/web-agent` sheet without navigation; at wider widths it keeps the Auth iframe → matching Playground path. Keep the 投研仓 iframe/new-window fallback on the same `page_id`.
- Verify a trusted Web Agent `turn-complete` refreshes live data and `page-updated` reloads the current page; untrusted origin/source/channel/page messages do nothing.
- Verify the old body QR block (`手机扫码查看`) is absent.
- Verify share modal generates a `900x1400` PNG poster.
- Verify copy image works, or degrades to a clear fallback message when Clipboard permissions are unavailable.
- For browser-feedback maintenance, run `verify_page.mjs --profile ui-refinement --require-browser`; add the user's exact screenshot size with `--extra-viewport [name:]WIDTHxHEIGHT` and manually confirm clipboard/download results in the target browser.
- For public pages, use `static_page.py update` when preserving an already shared URL.
