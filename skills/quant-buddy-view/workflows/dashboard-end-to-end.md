# Workflow · 需求 → 看板分享链接（端到端）

> 前置分诊：新会话先走 [new-session-paradigm-routing.md](new-session-paradigm-routing.md) 查范式卡判命中。**① 直接命中**不走本流程：普通渠道先返回现成链接，`feishu-group` 等 `direct_deliver` 终态后才返回 playground 链接；本流程覆盖 **② fork**（换标的注册自己的 Formula Package / Data Grant 凭证）和 **③ 未命中自建**。

把 quant-buddy-skill 里探索好的指标，做成一个公开可分享、数据自动更新的网页看板。

> 场景：用户说「帮我做个沪深300指数最近一年走势 + 最新涨跌幅的监控页，要能发给同事」。

## 0. 前置：在 quant-buddy-skill 里探索并选通道（本技能之外）

先按数据性质选择实时取数通道：普通行情、估值、财务等平台直取数据优先 Data Grant；需要计算、自定义指标或公式口径时使用 Formula Package。两类凭证可以同页混用，分别验证、注册和取数；不要为了让页面成为实时页，把普通直取数据强行改写成公式。下面步骤以 Formula Package 示例为主，Data Grant 的验证与注册见 [../tools/data_grant.md](../tools/data_grant.md)。

> 本技能不维护会话 / task_id：register 与发布都凭 `config.json` 的 api_key 认身份，直接开干。
> 调用 `runMultiFormulaBatchStream` 做验证时，`user_query` 要写当前用户的真实请求和当前资产；复制旧示例时不要留下旧股票名、旧测试说明或旧 `task_id`。

## 1. 注册公式任务包（本示例的公式通道）

`params.json`（UTF-8，中文务必走 @file）：

```json
{
  "formulas": [
    "hs300_close = \"全市场每日收盘价\"*取出(沪深300)",
    "hs300_chg   = \"全市场每日回报率\"*取出(沪深300)"
  ],
  "reads": [
    { "output": "hs300_close", "read_mode": "range_data",
      "mode_params": { "lookback_days": 365 } },
    { "output": "hs300_chg", "read_mode": "last_day_stats" }
  ],
  "ttl_days": 365
}
```

```bash
python scripts/formula_package.py register @params.json
```

成功返回 `package_id` + `signature`，并落盘到 `output/formula_packages/<package_id>.json`（后续步骤可自动补全 signature）。

## 2. 生成看板 HTML

`spec.json`：

```json
{
  "title": "沪深300监控",
  "subtitle": "近一年走势 · 最新涨跌幅",
  "package_id": "pkg_xxx",
  "panels": [
    { "title": "近一年收盘价", "output": "hs300_close", "type": "line" },
    { "title": "最新涨跌幅",   "output": "hs300_chg",   "type": "number", "unit": "%" }
  ]
}
```

```bash
# 仅生成
python scripts/build_dashboard.py @spec.json
# 或生成 + 直接发布（用户要可分享页面时优先这样做）
python scripts/build_dashboard.py @<(jq '. + {upload:true}' spec.json)   # bash
```

> Windows 下把 `"upload": true` 直接写进 spec.json 即可，无需 jq。

## 3. 发布（若第 2 步未带 upload）

```bash
python scripts/static_page.py upload '{"html_file":"output/pages/沪深300监控-xxxx.html","title":"沪深300监控"}'
```

返回的原始 `url` 是内部托管链接：`https://pages.quantbuddy.cn/pages/<user>/page_xxx.html`。普通渠道可直接对外分享；`feishu-group` 不发送该 URL，只在终态使用 `agent_reply_contract.public_url` 返回 `https://www.quantbuddy.cn/playground/<user>/page_xxx`。

## 4. 后续维护

- **只是想改页面里某一个图表**（加/删一条线、改时间窗口、查真实数据）：优先走
  [edit-existing-chart.md](edit-existing-chart.md) + `scripts/chart_edit.py`，只动被要求的那一处，不要
  把页面上其它无关的公式/面板也重新验证一遍。只有目标页面是 legacy（`chart_edit.py inspect` 会标出）
  或改动本质上要求整页重算/换版式，才用下面这条整页重建。
- **legacy 页面是 bespoke（手写 canvas/SVG）页面**：折线/柱状/双轴/雷达图这类图表不必回落整页重建——
  用 `build_dashboard.py`（`emit=panel_block`）把这张图重新生成成局部嵌入的声明式图表块，替换掉原来
  手写的那部分，之后就能用 `chart_edit.py` 定点编辑，见 [guides/bespoke-page.md](../guides/bespoke-page.md)
  「图表类可视化」一节。仪表盘/水位条这类非图表指标组件不受影响。
- **页面已分享、想改内容但保留原链接**（最常见）：重跑第 2 步生成新 HTML，再用 `update` 替换同一个 `page_id`——URL 不变，访问者刷新即见新内容，也不占新的活跃页配额：
  ```bash
  python scripts/static_page.py update '{"page_id":"page_xxx","html_file":"output/pages/沪深300监控-xxxx.html"}'
  ```
  重建并替换也可一步完成：在 spec.json 里加 `"update_page_id": "page_xxx"`（优先于新上传），跑 `build_dashboard.py @spec.json` 即重建 + 替换。
- **数据更新了想刷新页面**：无需重建——页面是 live 实时取数，访问者打开即见最新；只有改版式/文案时才重跑第 2 步并按上一条 `update` 覆盖同一页面。
- **下线页面**：`python scripts/static_page.py revoke '{"page_id":"page_xxx"}'`。
- **轮换公式包签名（⚠️ 破坏性，默认不做）**：`refresh` 默认 `rotate_signature:false`、不动签名。只有需要主动换令牌 / 吊销已泄露旧签名时才轮换：`python scripts/formula_package.py refresh '{"package_id":"pkg_xxx","rotate_signature":true}'`。
  - 轮换会**立刻作废所有已发布、内嵌该包旧签名的页面**（取数报 `SIGNATURE_INVALID`），新签名只明文返回一次、丢了不可恢复。
  - 轮换后**必须紧接着**对每个内嵌该包的页面重建 HTML + `update` 覆盖同一 `page_id`，把新签名同步进去——一步不能漏。
  - 仅当本地存在凭证 `output/formula_packages/<package_id>.json` 时脚本才会回写新签名供重建；换会话/换机器、凭证不在本地时**不要轮换**（新明文会丢、页面救不回）。
  - 「数据更新想刷新页面」见上一条：页面 live 取数自动拿最新，**无需 refresh、更无需轮换**。

> 实时页可使用两条通道：Formula Package 内嵌 `package_id + signature` 并调用 `queryFormulaPackage`，Data Grant 内嵌 `grant_id + signature` 并调用 `queryDataGrant`。两类凭证可同页混用、彼此独立取数；任一通道都能让页面保持实时。前置：端点对页面域名放开 CORS、协议与页面一致、且接受 signature 公开在 HTML 里——当前 `https://www.quantbuddy.cn/skill` 均满足。
