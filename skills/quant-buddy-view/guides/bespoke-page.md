# Guide · 手搓 bespoke 页（自由排版 + 共享取数内核）

## 正文图片

bespoke 页面不得直接引用本地路径、HTTP 图片或其他 page_id 的托管图片。先 `image_upload`，再使用绝对 `https://pages.quantbuddy.cn/pages/assets/{当前 page_id}/{asset_id}.webp`。每个 `<img>` 明确写 `width`、`height`、有意义的 `alt` 和稳定布局尺寸；首屏或 `[data-qb-poster-target]` 内图片禁止 lazy，正文下方图片可使用 `loading="lazy" decoding="async"`。

`verify_page.mjs` 会触发懒加载、等待 `img.decode()`、检查 `complete/naturalWidth`、记录图片 requestfailed/非 2xx，并对同域 WebP 检查海报目标包含关系与 canvas 可导出性。错误摘要会移除 URL 查询签名。

> 场景：`build_dashboard` 的通用 panel 满足不了——你要的是有版式设计感、自定义 SVG/交互的那种页面
> （像商品期货研报、泡沫监测终端、个股画像卡）。**呈现自由发挥，但"拿数据"这层别再各写各的。**

## 三条生产路，先选对

| 路 | 怎么做 | 何时用 |
|---|---|---|
| **在线模板** `static_page.py templates` / `template` | 先找公共模板，下载 HTML 后替换标的、文案和公式包凭证 | 个股画像、估值体检、异动榜、选股看板等固定页面形态 |
| **快路** `build_dashboard` | 写 `spec.json`，声明式出 line/bar/number/table | 没有合适在线模板，但标准看板足够 |
| **手搓 bespoke**（本剧本） | Agent 直接写 HTML/CSS/SVG，数据层调**取数内核** | 在线模板和快路都做不出的自定义版式/交互 |

> 快路里那套"取数 + 清洗 + 容错"已经写对了一份（内联在生成的 HTML 里）。手搓页够不着它，
> 所以单独抽了一份同口径的 **取数内核** `assets/data-kernel.js` 给手搓页用——**别再自己抄 `fetch`/解包逻辑**。
> 手搓只负责主体内容。公共 shell 不是页面模板；不要复制 demo 样式或另起一套页头、页尾、二维码、刷新按钮。

## 统一原则：配置活在声明式结构里，不要写死进某次 JS 调用参数

不管接下来选哪种呈现方式，判断"这段以后好不好定点编辑"只看一件事：**这个组件用哪个 output、显示哪些行/颜色/参数这类绑定关系，是不是能从结构化的地方（BOOT.packages/panels 或 HTML 的 `data-*` 属性）读出来，而不是硬编码在某一次 JS 函数调用的参数里**。按组件类型分两种做法：

### 折线/柱状/双轴/雷达图这类"图表"：优先局部嵌入声明式引擎，不要手写 SVG/canvas

`build_dashboard.py` 现在支持 `emit=panel_block`：只生成一段带 `QBV_RENDER_JS_START/END` marker 的 `<script>`（不是整页 HTML），可以直接嵌进 bespoke 页面已经排好版的容器里。用法：

```bash
python scripts/build_dashboard.py '{
  "emit": "panel_block",
  "package_id": "pkg_xxx", "signature": "sig_xxx",
  "panels": [
    {
      "title": "价格趋势与均线", "type": "line", "target_selector": "#priceChart",
      "outputs": ["px", "ma20", "ma60"]
    },
    {
      "title": "估值水位", "type": "line", "target_selector": "#valuationChart",
      "outputs": ["pe", "pb"], "dual_axis": true, "right_series": ["pb"]
    }
  ]
}'
```

返回的 `script_html` 粘贴进 bespoke 页面 `<body>`（放在 `#priceChart`/`#valuationChart` 这些容器**之后**）即可——页面布局、颜色、间距完全由你的 bespoke 布局决定，脚本只负责把图画进你指定的容器，不包卡片外壳。`panel.type` 支持 `line`/`bar`/`radar`（雷达图）/`table`/`number`/`text`/`image`；折线图额外支持 `dual_axis:true` + `right_series:[output名...]` 做双轴；`sparkline:true` 出无坐标轴/图例的迷你走势图。

这样生成的图表带着标准 marker，之后可以用 `chart_edit.py` 的 `add_series`/`remove_series`/`set_window`/`query_data` 定点编辑，不用再手写 `svg.innerHTML = grid + paths` 这类拼接逻辑，也不用现场重新理解一段陌生的绘图函数。

**只有 `emit=panel_block` 目前还表达不出的可视化（仪表盘、分位水位条、现金流对比条、行业排名榜这类非"图表"型指标组件）才继续手写**——这些多数时候本来就不需要 SVG/canvas，见下一节。

### 仪表盘/水位条/排名榜这类指标组件：纯 HTML+CSS+JS 就够，但绑定关系必须走 `data-*` 属性

这类组件的视觉本质是"改一个 `<div>` 的宽度百分比"或"拼几行 `<span>/<b>`"，不需要 SVG，也不需要 ECharts。但同一个渲染函数完全可能同时有"好"和"坏"两种调用方式，只有"好"的这种才好定点编辑：

```html
<!-- 好：绑定关系写在 data-* 属性里，JS 是通用遍历渲染，不含任何具体业务数据 -->
<div id="valuationBars" data-qb-bar-list>
  <div data-qb-bar-row data-output="pe_pctile" data-label="PE一年水位" data-color="var(--red)"></div>
  <div data-qb-bar-row data-output="pb_pctile" data-label="PB一年水位" data-color="var(--blue)"></div>
</div>
```

```js
// 通用渲染函数，跨页面复用，函数体里不含任何具体图表的绑定信息
function renderBarList(container, outputs) {
  container.querySelectorAll('[data-qb-bar-row]').forEach(row => {
    const value = QB.lastValue(outputs, row.getAttribute('data-output'));
    setBar(row.querySelector('.bar-fill'), value);
  });
}
```

```js
// 坏：禁止这种写法——加一条新水位条要去找到这次调用、改数组字面量，跟手写 SVG 是同一类问题
setBar($("valuationBars"), [
  { label: "PE一年水位", value: peRank, color: "var(--red)" },
  { label: "PB一年水位", value: pbRank, color: "var(--blue)" },
]);
```

一句话判断标准：**渲染函数的参数列表里不应该出现"这一行具体是什么"（label/value/color 这些），只应该出现"容器"和"通用取数上下文"（outputs）；具体是哪几行、每行绑定什么，必须能从 DOM 的 `data-*` 属性读出来。** 改动"加一条新行"就变成"往 HTML 里加一个 `data-qb-bar-row` 节点"，不用碰 JS、不用理解渲染函数内部逻辑。

## 核心原则：分层

- **公共外壳（固定统一）**：页头、页尾、刷新按钮、分享海报弹层、复制/下载 PNG —— 全交给 `assets/share-shell/`。
- **数据层（往死里统一）**：怎么连服务器、读流、解包、清洗缺口、出错怎么喊 —— 全交给内核，一份，改一处全好。
- **呈现层（完全自由）**：页面长什么样、用什么图形、配色版式 —— 你随意，内核不管。
- **环境配置（保持灵活）**：取数地址 `endpoint` 由你按环境填（测试/正式），内核不写死。

## 五步接入

1. 先查在线模板；没有合适模板时，才写 bespoke 主体 HTML。
2. 主体 HTML 放入 `QB_SHARED_*` 占位，并调用 `QBShareShell.init({ onRefresh: load, getPosterData })`。
3. 填 `CONFIG = { endpoint, package_id, signature }`；地址按测试/正式环境填写。
4. 用 `QB.query(CONFIG)` 取数，再用 `QB.series` / `QB.lastValue` / `QB.topValues` 解包。
5. 用 `compile_bespoke_page.py` 编译发布，脚本会内联 share shell、logo、qr-mini 和 data-kernel。

```js
const CONFIG = { endpoint, package_id, signature };

async function load() {
  const out = await QB.query(CONFIG);
  const px = QB.series(out, "px", { dropZero: true });
  const chg = QB.lastValue(out, "chg");
  const leaders = QB.topValues(out, "GAIN").slice(0, 5);
  return { px, chg, leaders };
}
```

> 发布是自包含 HTML，所以不要手工保留 `<script src>` 外链。用 `python scripts/compile_bespoke_page.py @params.json` 编译，编译器负责内联公共组件和运行时资产。

## 数据契约：产出形态 → 用哪个内核函数

公式包每个产出按其 `read_mode` 回来一种形态，对应一个解包函数：

| 产出形态（read_mode） | 长相 | 取它用 | 说明 |
|---|---|---|---|
| `range_data` | `{dates:[], values:[]}` | `QB.series(out,k,{dropZero})` → `[{d,v}]` | 序列/折线；`QB.values(...)` 只要数值数组 |
| `last_day_stats`（1维序列） | `{last_value:{date, value}}` | `QB.lastValue(out,k)` / `QB.lastDate(out,k)` | 单值卡；注册时不要写 `last_value` read_mode |
| `last_day_stats` | `{date, top_values:[{asset,name,value}]}` | `QB.topValues(out,k)` / `QB.statDate(out,k)` | 截面榜单 |

日期整数 `YYYYMMDD` → `QB.fmtDate(d)` 出 `'YYYY-MM-DD'`（分隔符可换：`QB.fmtDate(d,'.')`）。

## 两个必须记住的坑（内核已替你处理，但你要会用对）

1. **价格的假 0**：平台数据缺口时会喂 `0`。价格/成交额这种"不可能为 0"的序列，取数时**开 `{dropZero:true}`**，
   否则会画出一条掉到 0 的假线还不报错（这就是"假成功"）。
   ——但**涨跌幅/收益率的 0 是合法平盘值，绝不能 dropZero**。按数据含义选。
2. **出错就喊,别画假图**：`QB.query` 在 HTTP 失败 / 服务端报错 / 三件套没填时会 `throw`。
   页面必须 `try/catch`，把 `e.message` 显式塞进一个"错误槽"展示，**不要 catch 后当无事发生继续画**。

## 发布前自查（手搓页最容易翻车的三处）

- [ ] **地址协议**：页面要发布到 `https://` 的话，`endpoint` 必须也是 `https://`。
      填了 `http://` 测试地址，本地能开、一发布到线上就被浏览器拦（mixed-content）。内核会 `console.warn` 提醒，但不强改。
- [ ] **价格序列开了 `dropZero`**：所有价格/成交额类折线，确认带了 `{dropZero:true}`。
- [ ] **错误槽接好了**：断网/换个错 `package_id` 试一次，确认页面显示"取数失败：…"而不是一片空白或假图。
- [ ] **公共 shell 接好了**：页头为 `QuantBuddy · 宽宝`，按钮为 `刷新数据 / 收藏 / 分享 / 问一问`，页面正文不再保留旧的“手机扫码查看”二维码块。

## 前置硬门槛（与其它剧本一致）

手搓页用的公式包，**仍须先在 quant-buddy-skill 用 `runMultiFormulaBatchStream` 跑通确认出数、再 `register`**
（见 [SKILL.md](../SKILL.md) 硬规则 2）。手搓只改"呈现层"，不改"公式必须先验证"这条。
