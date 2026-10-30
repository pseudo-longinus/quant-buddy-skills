# Workflow · 需求 → 看板分享链接（端到端）

> 优先例外：已有文件（JPG/HTML/PDF 等）转活页，包括先研究改造的复合请求，先走 [existing-file-static-first.md](existing-file-static-first.md)。本篇查数、资产验证与范式路由不得前置阻断首次静态交付。

> 量化建页先按 [先答后建页](../guides/answer-first.md) 完成 QBS 查询并发送完整业务首答，再走 [new-session-paradigm-routing.md](new-session-paradigm-routing.md) 查范式卡判命中。**① 直接命中**沿用既有链接交付规则；本流程覆盖 **② fork**（换标的注册自己的 Formula Package / Data Grant 凭证）和 **③ 未命中自建**。

把 quant-buddy-skill 里探索好的指标，做成一个公开可分享、数据自动更新的网页看板。

自建分支先执行 [自建质量底线](../guides/self-build-quality.md)：按问题组织首屏与主证据，由模型手写完整 bespoke HTML/CSS/JS；`build_dashboard` 只能生成 `panel_block` 局部图表脚本，不能生成 unmatched 整页。fork/已有页面保持其原有视觉合同。

> 场景：用户说「帮我做个沪深300指数最近一年走势 + 最新涨跌幅的监控页，要能发给同事」。

## 0. 前置：在 quant-buddy-skill 里探索并选通道（本技能之外）

先按数据性质选择实时取数通道：普通行情、估值、财务等平台直取数据优先 Data Grant；需要计算、自定义指标或公式口径时使用 Formula Package。两类凭证可以同页混用，分别验证、注册和取数；不要为了让页面成为实时页，把普通直取数据强行改写成公式。

### 多资产收益 + 估值 + 回撤的 bespoke 路径

1. 一份 `assets:[...]` 参数调用一次 `qbs_bridge.py resolve_asset_data`，只探测平台直取的行情/估值字段。
2. `templates` 调用一次并确定 direct/fork/unmatched；fork/unmatched 立即 `new_page` 绑定首链。
3. 普通行情/估值直接消费第 1 步返回的 `registration_files` 注册已验证 Data Grant，保留每个资产的合同和收据。
4. 收益/回撤只需注册一组跨资产原始价格 Formula Package，`validate_package_set` / register 各一次。
5. **若本轮为 `unmatched`，模型直接手写完整 HTML/CSS/JS**：
   - 用 Data Grant 表呈现最新行情与估值；
   - 用原始价格序列在页面内计算累计收益与历史回撤；
   - 首屏给出三资产核心差异，再放收益/回撤主图和口径；
   - 可用 `build_dashboard emit:"panel_block"` 生成局部图表脚本，但外层整页必须是模型手写 bespoke。
6. 执行计划明确要求角色绑定时，先运行 `static_page.py bind_runtime_route @params.json`，再携带返回的路由、轮次、资产与验证收据。
7. 用 `compile_bespoke_page.py` 内联公共 shell 与 data-kernel，再按 `publish_verified` 返回的 `next_action.params_file` 发布。始终写回第 2 步的同一 `page_id`，完成本地浏览器、公网和终态验收后才交付。

## 1. 注册公式任务包（本示例的公式通道）

公式参数必须是合法 JSON。不要写会破坏 JSON 的裸内嵌引号；例如优先写：

```json
{
  "formulas": [
    "mt_close = 收盘价(贵州茅台)",
    "wly_close = 收盘价(五粮液)",
    "lzlj_close = 收盘价(泸州老窖)"
  ]
}
```

先在 QBS 验证并注册；不要从旧 `output/` 复制 task、凭证或公式。Data Grant 与 Formula Package 的验证收据必须与当前任务和资产一致。

## 2. 模型手写 bespoke HTML

按 [自建质量底线](../guides/self-build-quality.md) 与 [bespoke 页指南](../guides/bespoke-page.md)：

1. 写完整主体 HTML/CSS/JS，根节点声明 `data-qb-page-design="bespoke-v1"`。
2. 首屏放核心结论、关键数字和主证据，不从等权卡片网格开始。
3. 数据层复用 `assets/data-kernel.js`；价格序列处理假 0 时用 `{dropZero:true}`，涨跌幅/收益率的合法 0 必须保留。
4. 多资产对比使用透视结构：指标为行、资产为列；收益与回撤图使用同窗口、同起点口径。
5. 如需声明式图表，只能生成 `panel_block` 嵌入模型手写容器，不得让标准面板成为整页。
6. 用 `compile_bespoke_page.py @compile-params.json` 编译自包含页面。

示例编译参数：

```json
{
  "template": "output/bespoke/body.html",
  "out_file": "output/bespoke/final.html",
  "inline_data_kernel": true,
  "inline_qr_mini": true
}
```

## 3. 发布与公网验收

使用 `publish_verified` 发布同一个 `page_id`，参数必须包含真实研究内容 `description`、当前 `task_id/page_id/plan_hash`、候选 `html_file`、标题、实时/快照合同与验证收据。缺参数时补齐后重发，不把参数缺项当成页面失败。必须完成：

- 本地桌面 / 390 / 320 浏览器验收；
- 公网浏览器验收；
- 版本与 hash 回读；
- 终态回复合同校验。

不得只因为生成 HTML 或 upload 成功就声称交付。

## 4. 后续维护

- **只是想改页面里某一个图表**（加/删一条线、改时间窗口、查真实数据）：优先走
  [edit-existing-chart.md](edit-existing-chart.md) + `scripts/chart_edit.py`，只动被要求的那一处，不要
  把页面上其它无关的公式/面板也重新验证一遍。只有目标页面是 legacy（`chart_edit.py inspect` 会标出）
  或改动本质上要求整页重算/换版式，才用下面这条整页重建。
- **legacy 页面是 bespoke（手写 canvas/SVG）页面**：折线/柱状/双轴/雷达图这类图表不必回落整页重建——
  用 `build_dashboard.py`（`emit=panel_block`）把这张图重新生成成局部嵌入的声明式图表块，替换掉原来
  手写的那部分，之后就能用 `chart_edit.py` 定点编辑，见 [guides/bespoke-page.md](../guides/bespoke-page.md)
  「图表类可视化」一节。仪表盘/水位条这类非图表指标组件不受影响。
- **本人 legacy 页面要求修改并保留原链接**：用户对“修改本人页面 + 保持原链接”的明确要求，已经授权完成该修改所必需的技术性结构升级；不得因 `NO_RENDER_JS_MARKER`、旧版 bespoke 结构或定点编辑工具返回 `LEGACY_PAGE` 再向用户确认。固定闭环是：下载原页 → 在本地做最小语义重建/Marker 化（保留未要求改动的正文和运行身份）→ `verify_page.mjs --require-browser` → `static_page.py update` 写回同一 `page_id` → 公网浏览器验收 → 若返回终态合同则写草稿并运行 validator。只有缺少会影响业务语义的原始公式/目标定义时才询问；技术实现选择不询问。**不得只生成本地 HTML，也不得把 legacy 错误直接回复给用户。**
  - `stock_analysis_instance_v1` 的时间窗口不要手写临时补丁：下载原页后运行 `scripts/stock_window.py apply`，再按其返回的 `html_file` 继续本地验收和同页 `update`。
- **页面已分享、想改内容但保留原链接**（最常见）：重跑第 2 步生成新 HTML，再用 `update` 替换同一个 `page_id`——URL 不变，访问者刷新即见新内容，也不占新的活跃页配额：
  ```bash
  python scripts/static_page.py update '{"page_id":"page_xxx","html_file":"output/pages/沪深300监控-xxxx.html"}'
  ```
  标准整页 legacy 维护可按原合同使用 `build_dashboard.py`；`unmatched` 自建页则重新模型手写 bespoke 主体，再更新同一个 `page_id`。
- **数据更新了想刷新页面**：无需重建——页面是 live 实时取数，访问者打开即见最新；只有改版式/文案时才重跑第 2 步并按上一条 `update` 覆盖同一页面。
- **下线页面**：`python scripts/static_page.py revoke '{"page_id":"page_xxx"}'`。
- **轮换公式包签名（⚠️ 破坏性，默认不做）**：`refresh` 默认 `rotate_signature:false`、不动签名。只有需要主动换令牌 / 吊销已泄露旧签名时才轮换：`python scripts/formula_package.py refresh '{"package_id":"pkg_xxx","rotate_signature":true}'`。
  - 轮换会**立刻作废所有已发布、内嵌该包旧签名的页面**（取数报 `SIGNATURE_INVALID`），新签名只明文返回一次、丢了不可恢复。
  - 轮换后**必须紧接着**对每个内嵌该包的页面重建 HTML + `update` 覆盖同一 `page_id`，把新签名同步进去——一步不能漏。
  - 仅当本地存在凭证 `output/formula_packages/<package_id>.json` 时脚本才会回写新签名供重建；换会话/换机器、凭证不在本地时**不要轮换**（新明文会丢、页面救不回）。
  - 「数据更新想刷新页面」见上一条：页面 live 取数自动拿最新，**无需 refresh、更无需轮换**。

> 实时页可使用两条通道：Formula Package 内嵌 `package_id + signature` 并调用 `queryFormulaPackage`，Data Grant 内嵌 `grant_id + signature` 并调用 `queryDataGrant`。两类凭证可同页混用、彼此独立取数；任一通道都能让页面保持实时。前置：端点对页面域名放开 CORS、协议与页面一致、且接受 signature 公开在 HTML 里——当前 `https://www.quantbuddy.cn/skill` 均满足。
## 终态回复门禁

bespoke 页发布成功后不得只读取内联 `agent_reply_contract` 就直接回复：必须使用发布器顶层返回的 `reply_draft_file` 和 `reply_validation_command`，先写入最终 Markdown 草稿，再执行 hash-bound validator。公网浏览器验收和 `valid:true` 缺一不可；validator 通过后停止工具调用并发送草稿。
