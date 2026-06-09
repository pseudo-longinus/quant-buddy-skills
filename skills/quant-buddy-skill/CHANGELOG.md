# CHANGELOG — quant-buddy-skill

版本记录按**从新到旧**排列。详细 diff 见 `skill-changelog/iter-*.md` 及对应的 `*-post-diff.md`。

> ⚠️ **本文件不是规则源**。
> 这里只是变更审计：按时间叠加，**会包含已被后续版本反转或废弃的旧口径**。
> 当前执行规则一律以 `SKILL.md` + `workflows/**` + `tools/**` + `references/troubleshooting.md` 为唯一权威；本文件与上述文件冲突时，以上述文件为准。
> 详见 `SKILL.md` 硬规则 #11。

---

## [4.21.1] — 2026-06-09

**变更文件**：`SKILL.md`、`scripts/formula_package.py`、`presets/assets_db/stock_a.yaml`、`presets/assets_db/stock_us.yaml`

本次小版本两件事：把公式任务包的调用流程并入与其它工具一致的统一规范；并扩充本地资产库支持的境内外 ETF。

- **公式任务包调用流程对齐统一规范**（`scripts/formula_package.py`）：此前该脚本独立于 `call.py`，注册/取数/管理会绕过「先 newSession + 版本检查」前置，且请求不带 `task_id` / `user_query`。现复用 `call.py` 的 session 读取与版本守卫——
  - 调用前统一做**版本守卫**：session 创建版本与当前 skill 版本不一致时返回 `SKILL_VERSION_MISMATCH`，提示先 `newSession` 再继续；
  - 每个请求自动注入 **`task_id` / `user_query`**（连同既有的 `x-skill-version` 头），与其它工具「每个请求带当前版本 + user_query」的固定口径一致；
  - `register` / `list` / `revoke` / `refresh` 等需 api_key 的管理类操作，未建 session 时直接返回 `SESSION_REQUIRED`，强制先 `newSession`；
  - 对外取数 `query` 仍保持**无凭证、无版本门禁**（浏览器 / 第三方只读直连行为不变），从 skill 内调用时附带 session 上下文供服务端审计。
  > 配套：服务端 `registerFormulaPackage` / `refreshFormulaPackage` / `listFormulaPackages` / `revokeFormulaPackage` 同步要求 `task_id`（缺失返回 `TASK_ID_REQUIRED`）；该改动在服务端仓库，不在本 skill 内。

- **新增支持资产：境内外 ETF**（`presets/assets_db/stock_a.yaml`、`presets/assets_db/stock_us.yaml`）：
  - **A 股场内 ETF**：宽基（上证50 `SH510050` / 沪深300 `SH510300` / 中证500 `SH510500` / 中证1000 `SH512100` / 中证A500 `SZ159361` / 创业板 `SZ159915` / 科创50 `SH588000` / 科创芯片 `SH588990`）、行业（有色 `SH512400` / 钢铁 `SH515210` / 煤炭 `SH515220` / 化工 `SH516120` / 建材 `SZ159745` / 养殖 `SZ159865` / 半导体设备 `SZ159516` / 红利低波 `SH512890`）、跨境（恒生 `SH513210` / 恒生科技 `SH513180` / 中概互联 `SH513050` / 港股科技 `SH513010` / 港股通互联网 `SZ159792` / 中韩半导体 `SH513310`）、商品与债券（黄金 `SH518880` / 石油 `SH561360` / 十年国债 `SH511260` / 城投债 `SH511220`）。
  - **美股及境外 ETF**：SPDR 系列（`SPY.A` / `XLF.A` / `XLE.A` / `XLK.A` / `XLV.A` / `KRE.A` / `KBE.A` / `FEZ.A`）、iShares 安硕系列（`SOXX.O` / `LQD.A` / `HYG.A` / `EWT.A` / `EWZ.A` / `EWJ.A` / `EWU.A`）、VanEck `SMH.O`、KraneShares `KWEB.A`、全球X `ARGT.A`，以及 `JETS.A` / `MAGS.BAT` / `IGV.BAT` / `DWPP.O` 等。
  - ⚠️ ETF 仍按所在市场口径：A 股场内 ETF 行情正常，估值/财务以工具返回为准；境外 ETF **仅支持行情价格**，不支持估值/财务。
- `SKILL.md`：版本号升至 `4.21.1`；目录树资产计数同步为 `stock_a.yaml` 5540 条、`stock_us.yaml` 1068 条。

---

## [4.21.0] — 2026-06-05

**变更文件**：`SKILL.md`、`scripts/formula_package.py`（新增）、`tools/formula_package.md`（新增）、`recipes/formula-package.md`（新增）、`config.json`

新增「公式任务包（Formula Package）」对外取数能力：把一组公式注册成长期任务包，得到 `package_id` + `signature`，之后**无需 API Key**即可凭凭证流式取数（SSE），底层数据更新自动重算。适合前端页面 / 第三方只读接入。

- `scripts/formula_package.py`（新增）：公式包客户端，子命令 `register` / `query` / `list` / `revoke` / `refresh`；复用 `executor.py` 的 `load_config` / 无代理 opener / skill 版本头；`query` 走 SSE 解析并组装为 `outputs` dict，签名可由本地凭证自动补全；注册/轮换成功后凭证落盘 `output/formula_packages/<package_id>.json`。
- `tools/formula_package.md`（新增）：端点、注册参数、三种 `read_mode`（`last_day_stats` / `last_valid_per_asset` / `range_data`）的 `result.data` 结构、错误码、与 `runMultiFormulaBatchStream` 的选型对照。
- `recipes/formula-package.md`（新增）：使用说明（设计公式组 → 注册 → 取数 → 前端用 `fetch` 读 SSE 直连渲染 → 管理），含一个页面型用法的参考写法，但不在 skill 内附带成品页。
- `SKILL.md`：版本号升至 `4.21.0`；场景路由新增「对外发布公式组 / 做取数页面 / 注册任务包」一行；目录树补充 `scripts/formula_package.py` 与 `tools/formula_package.md`；frontmatter `networkEndpoints` 增列公式包注册/取数端点。
- `config.json`：`endpoint` 协议修正为 `http://`（该部署 :3010 端口为明文 HTTP，`https://` 会 SSL 握手失败）。

---

## [4.20.22] — 2026-06-03

**变更文件**：`SKILL.md`、`tools/fast_query.md`、`workflows/fast-window.md`、`workflows/render-kline.md`、`workflows/quick-lookup.md`

修复“螺纹钢最近走势”被静态判定为期货不支持的问题：将可识别期货行情/窗口序列改为有条件支持，普通“看走势”优先走数值走势，只有明确要求 K 线图片时才进入 K 线渲染流程。

- `SKILL.md`：版本号升至 `4.20.22`；数据覆盖范围中将“期货”从“完全不支持”拆为“行情/窗口序列有条件支持”，保留期权不支持；快速查数路由新增“最近走势/看走势”默认走 `fast-window.md`、未给 N 时按最近 20 个交易日；仅“画图 / K线 / 图片 / 带成交量图”进入 `render-kline.md`；新增命中 `future.yaml` 后禁止静态输出“平台不支持期货”的红线。
- `workflows/fast-window.md`：资产解析跨市场检索加入 `future.yaml`；期货主连/次主连同时命中且用户未指定时默认主连（如“螺纹钢”→“沪螺纹钢主连 / RB.SHF”）；期货仅尝试行情字段；`fast_query(window)` 不可用时转完整链路尝试 `收盘价(资产名)` / `涨跌幅("收盘", 1)`，仍失败则按工具证据受控说明。
- `workflows/render-kline.md`：适用范围收窄为明确可视化 artifact 请求；期货命中时禁止调用 `renderKLine`，普通“看走势”转数值走势，明确要求期货 K 线图时说明当前 K 线渲染工具只支持 A 股。
- `tools/fast_query.md` / `workflows/quick-lookup.md`：同步期货行情“尝试支持、以工具返回为准”的边界，不承诺期货估值、财务或 K 线图。

---

## [4.20.21] — 2026-06-01

**变更文件**：`SKILL.md`、`tools/fast_query.md`、`scripts/fetch_fastquery_csv.py`（新增）、`workflows/fast-snapshot.md`、`workflows/fast-window.md`、`workflows/fast-report-period.md`、`workflows/event-study.md`、`workflows/period-return-compare.md`、`workflows/quant-standard.md`、`workflows/quick-lookup.md`、`workflows/quick-snapshot.md`、`workflows/global-rules.md`

`fast_query` 接口大幅扩容（≤3 资产 → ≤1000 资产），同时新增 CSV 自动降级模式与限流说明；相关 workflow 中的资产数量限制描述全部同步更新。

- `tools/fast_query.md`：
  - 资产数上限从 1~3 扩至 ≤1000，`window_days` 上限从 1~60 扩至 1~2500；删除"≥4 资产"的不适用限制。
  - 新增**限流表**：最大资产数 1,000（`ASSETS_EXCEED_LIMIT`）、最大交易日数 2,500（`WINDOW_DAYS_EXCEED_LIMIT` / `DATE_RANGE_EXCEED_LIMIT`）、单次最大数据点 200,000（`DATA_POINTS_EXCEED_LIMIT`）、每日用户级数据点 1,000,000、每日 CSV 下载 50 次；数据点计算公式同步说明。
  - 新增 **CSV 模式返回结构**：数据点 > 500 时服务端自动切换 CSV 格式，`mode:"csv"` + `csv_fields[].csv_url` + `summary`；处理规则包括汇报 `summary`、展示下载链接、禁止在对话中展开 CSV 内容。
  - 错误码表新增 6 条限流错误。
- `scripts/fetch_fastquery_csv.py`（新增）：下载并解析 `fast_query` CSV 模式返回的 `csv_url`，支持宽表格式（`ticker,name,<日期1>,<日期2>…`），对每个资产计算首值/末值/最高/最低/区间涨跌幅，输出 JSON；仅依赖 Python 标准库（`urllib`/`csv`/`json`），支持 `--full` 全序列输出与 `--max-points` 截断。
- `workflows/global-rules.md` / `workflows/quick-lookup.md` / `workflows/quick-snapshot.md`：资产数量描述从"1~3 个"统一改为"≤1000 个（明确列出的资产）"。
- 其余 workflow（`fast-snapshot.md`、`fast-window.md`、`fast-report-period.md`、`event-study.md`、`period-return-compare.md`、`quant-standard.md`）：细节描述与新接口规格对齐。

---

## [4.20.20] — 2026-05-26

**变更文件**：`SKILL.md`、`tools/fast_query.md`、`workflows/quant-standard.md`

修正 `fast_query` 字段市场范围：总市值仅 A 股（之前版本误标为 A/US/HK）；财务字段 ROE/毛利率统一扩展至 A/US/HK；`stock_us.yaml` 注释更正为"美股及境外ETF"。

- `tools/fast_query.md`：
  - `总市值`：从"A/US/HK 均支持"改回"仅 A 股"（亿元）；港美股查询返回 `FIELD_MARKET_MISMATCH`。
  - 财务字段：`ROE` 从"仅 A 股"升为"A/US/HK 均支持"；`毛利率` 显式加入 A/US/HK 均支持列表；派生字段 `资产负债率` 同步注明公式 `(总资产 - 净资产) / 总资产 × 100`。
  - 财务字段说明头部注明"所有财务字段统一返回**单季**数据，A/US/HK 一致"。
  - `FIELD_MARKET_MISMATCH` 错误描述更新为"港/美股查总市值/流通市值/换手率等仅 A 股字段"。
- `SKILL.md`：目录树注释 `stock_us.yaml` 说明改为"美股及境外ETF"。
- `workflows/quant-standard.md`：资产确认表格"美股 → `stock_us.yaml`"备注同步为"美股及境外ETF"。

---

## [4.20.19] — 2026-05-25

**变更文件**：`scripts/call.py`

扩展流式进度转发：`resumeJob` 工具与 `runMultiFormulaBatchStream` 共享实时 stderr 转发路径，用户在终端可逐条看到后台任务进度。

- `scripts/call.py`：`_run_executor()` 中将流式进度工具集合从单个 `runMultiFormulaBatchStream` 扩为 `{"runMultiFormulaBatchStream", "resumeJob"}`，注释从"runMultiFormulaBatchStream：实时转发 stderr"改为"流式进度工具：实时转发 stderr"；逻辑不变，仅扩展触发范围。

---

## [4.20.18b] — 2026-05-22

**变更文件**：`SKILL.md`、`workflows/render-kline.md`、`workflows/fast-snapshot.md`、`workflows/fast-window.md`、`workflows/global-rules.md`、`recipes/download-data.md`

补充 K 线工作流的 `newSession` 前置门禁规则；新增模糊词处理规则，明确综合分析请求直行与单点定义性请求反问的分支。

- `SKILL.md`：新增**模糊词处理规则**——技术分析类/走势判断类/盘面定性类/健康度类词的判定流程：①综合分析请求（≥2 维度或明确说"全面/综合分析"）→ 走 `stockProfile` 直行，报告首句告知口径；②孤立的单点定义性请求 → 必须反问澄清。
- `workflows/render-kline.md`：新增 **K-1 门禁**（`newSession 已建立`）——调用任何平台工具前本轮必须已有 `newSession` 记录，未通过则 MISSING_NEW_SESSION（HIGH 级）；Step 0 同步补充 `newSession` 前置步骤。

---

## [4.20.18a] — 2026-05-21

**变更文件**：`tools/fast_query.md`、`workflows/fast-report-period.md`、`workflows/fast-snapshot.md`、`workflows/fast-window.md`、`workflows/period-return-compare.md`

将所有 workflow 中对 `fast_query` 返回结构的描述从旧版嵌套数组（`results[].fields[]`）更新为新版 compact 格式（顶层提升 `dates`/`fields_meta`，`results.{资产名}.{字段名}` 直接是数值）。

- `tools/fast_query.md`：返回结构重写——新增顶层 `fields_meta`（单位+日期类型，只声明一次）；`value` 模式改为字典 `results.{资产名}.{字段名}` 直接是数值，公共日期提升至 `dates.{date_type}`；日期 fallback 时字段值为 `{v, d, fallback: true}`；`series` 模式改为列式 `dates` 共享日期轴 + 等长值数组，日期轴不同时为 `{dates, values}` 对象。
- `workflows/fast-snapshot.md` / `fast-window.md` / `fast-report-period.md` / `period-return-compare.md`：取值规则、首句模板、统计规则全部对齐 compact 格式；删除所有 `results[i].fields[j]` 写法，改为 `results.{资产名}.{字段名}`；日期字段从 `fields[j].date` 改为 `dates.trade_date` / `dates.report_period`；单位从 `fields[j].unit` 改为 `fields_meta.{字段名}.unit`。

---

## [4.20.18] — 2026-05-20

**变更文件**：`SKILL.md`、`tools/fast_query.md`、`workflows/fast-snapshot.md`、`workflows/fast-window.md`、`workflows/quick-snapshot.md`、`presets/assets_db/stock_hk.yaml`、`presets/assets_db/stock_us.yaml`、`presets/data_catalog.yaml`

统一 A 股/港股/美股估值白名单：港美股新增 TTM〔估值数据〕（日频），PE_TTM/PB/PS_TTM/股息率/PCF 三市场全部支持，不再需要替换为单季版。

- `tools/fast_query.md`：估值白名单从"仅 A 股"改为"A/US/HK 均支持（TTM〔估值数据〕）"，新增 PCF/市现率/PCF_现金净流量；FIELD_MARKET_MISMATCH 错误描述缩减为仅提及流通市值/换手率/ROE。
- `workflows/fast-snapshot.md`：字段映射表 PE_TTM/PB/PS_TTM/股息率从"仅 A 股"改为"A/US/HK"，新增 PCF 两行；市场范围警告同步更新。
- `workflows/fast-window.md`：参数提取规则中估值字段市场范围同步更新。
- `workflows/quick-snapshot.md`：估值类公式模板注释从"仅适用 A 股"改为"A 股 index_title 模板，港美股走 fast_query"。
- `SKILL.md`：Fast Path 白名单判断从"自动替换为单季版"改为"TTM 估值已统一支持"；港美股数据范围限制同步更新，估值类改为 A/US/HK 全市场支持。
- `presets/assets_db/stock_hk.yaml` / `stock_us.yaml`：头部注释从"仅支持行情价格数据"改为"支持行情价格 + TTM 估值 + 财务"。
- `presets/data_catalog.yaml`：新增 A 股 PCF 两条（经营活动现金流/现金净流量），港股 TTM 估值 6 条，美股 TTM 估值 6 条。

---

## [4.20.17] — 2026-05-20

**变更文件**：`SKILL.md`、`tools/stock_profile.md`、`tools/fast_query.md`、`workflows/stock-profile.md`、`workflows/quick-lookup.md`、`workflows/quant-standard.md`、`scripts/executor.py`、测试台 `agent/tools_schema.py`、`agent/local_tools.py`、`agent/tool_contracts.py`

新增 `stockProfile` 个股预计算指标画像能力，承接“分析一下 XX 个股 / 个股画像 / 指标概览 / 估值财务资金走势综合看一下”等开放式单股综合分析请求，同时保留简单查数走 `fast_query`、IC 预测力走 `scanDimensions` 的边界。

- `SKILL.md`：版本号升至 `4.20.17`；description 新增单股预计算指标画像能力；目录树、工具清单和场景路由新增 `stock-profile.md` / `stockProfile`；快速查数路由新增开放式单股指标画像分支，并将 `stockProfile` 纳入“读取 leaf workflow 前禁止直接调用”的红线。
- `tools/stock_profile.md`：新增 `stockProfile` 工具文档，明确实际工具名、参数、返回结构、维度口径、日内 `close_price` 刷新注意事项、错误处理和输出规则。
- `workflows/stock-profile.md`：新增单股指标画像 leaf workflow，规定 `newSession`、资产确认、`stockProfile` 调用、按维度输出事实摘要，以及禁止买卖建议、目标价和价格预测。
- `tools/fast_query.md` / `workflows/quick-lookup.md` / `workflows/quant-standard.md`：同步防误路由说明，开放式个股画像走 `stockProfile`，单字段行情/估值/财务、窗口序列和量化任务仍走原有路径。
- `scripts/executor.py`：注册 `stockProfile -> POST /stockProfile`，并配置 900s 工具超时。
- 测试台 `agent/tools_schema.py`、`agent/local_tools.py`、`agent/tool_contracts.py`：同步暴露 `stockProfile` schema 和平台工具名集合，确保 agent 可调用、审计识别并禁止 Bash 包装原生工具。

---

## [4.20.16] — 2026-05-19

**变更文件**：`scripts/call.py`

修复 `version/check` 调用缺少追踪参数 + 空串 `user_query` 注入失效两个小问题，提升服务端 audit 的追踪完整度。

- `scripts/call.py`：
  - `newSession` 在调用 `GET /skill/version/check` 时，将本次生成的 `task_id` 与 `user_query`（如有）拼入 query string，服务端 audit 中间件可通过 `req.query` 读取并落库，userHistory 可见完整 trace。
  - 业务工具自动注入 `user_query` 时，条件从 `"user_query" not in params` 改为 `not params.get("user_query")`，Agent 误传空串时同样从 `.session.json` 恢复，避免 `user_query` 大量为空导致后台无法追踪原始问题。

---

## [4.20.15] — 2026-05-15

**变更文件**：`SKILL.md`、`tools/fast_query.md`、`workflows/global-rules.md`、`workflows/period-return-compare.md`、`workflows/event-study.md`、`workflows/fast-window.md`、`workflows/fast-report-period.md`、`workflows/quick-report-period.md`、`workflows/quant-standard.md`、`scripts/executor.py`、`scripts/call.py`、`scripts/quant_api.py`、测试台 `agent/*.py`

收敛公式执行工具契约与高频 fast path：统一使用 `runMultiFormulaBatchStream`，减少 fixed-window / 单事件窗口 / 港美股财务查询误入公式链或静态拒答的问题；同时保留 5/14 的 SSE 必填参数与 session 上报修复。

- `SKILL.md`：版本号升至 `4.20.15`；首屏改为短路径优先，新增工具名与 unknown-tool 红线，明确公式执行唯一工具名为 `runMultiFormulaBatchStream`，旧名 `runMultiFormulaBatch` / `runMultiFormula` / `run_multi_formula` 0 次重试；移除普通查数前的 `.session` 本地探测，禁止 Bash / shell / Python / `scripts/call.py` 包装已有原生工具。
- `tools/fast_query.md`：同步说明 `window` 支持 `window_days` 或 `start_date`/`end_date`，固定返回序列且无需传 `result_mode`；`report` 财务字段说明改为 A/US/HK 部分字段以工具返回为准。
- `workflows/global-rules.md`：在关键规则速查顶部新增工具名与错误恢复红线，防止 unknown tool 后重复试错。
- `workflows/period-return-compare.md`：固定区间累计涨跌幅对比改为 `fast_query(query_type="window")` 日期范围模式，禁止再走公式链、`readData`、`force_reusable_*` 或分钟频参数。
- `workflows/event-study.md`：新增单事件单资产窗口收益 Fast Path，一次 `fast_query(window)` 拉取事件日后序列，再在返回 `series` 内定位 T+N/T+M；固定起止区间收益改路由至 `period-return-compare.md`。
- `workflows/fast-window.md`：新增 `report_period` 稀疏序列收敛规则；报告期/单季口径字段返回稀疏 series 时可直接回答，不因稀疏升级到公式链。
- `workflows/fast-report-period.md` / `workflows/quick-report-period.md`：港股/美股财务不再静态拒答，先尝试 `fast_query(query_type="report")`，仅按工具返回说明不支持或字段缺失；FIELD_UNRESOLVABLE fallback 复用当前 session。
- `scripts/executor.py`：在网络调用前新增 `runMultiFormulaBatchStream` 必填参数校验；缺 `task_id` 或 `formulas` 时本地返回结构化错误并退出，不再向服务端发送空 body 或不完整请求。
- `scripts/call.py`：在包装层增加同类前置校验，避免无 `GZQ_PARAMS` / 空参数时静默使用 `{}`；同时修正 `@file` 模式下自动注入 session 后未回写参数文件的问题。
- `scripts/quant_api.py` + `agent/test_agent.py`：直连 `QuantAPI` 创建 `newSession` 时，同步向 `/skill/session/begin` fire-and-forget 上报 `task_id` 与当前题目 `user_query`；上报失败不阻断本地 session 创建。
- 测试台 `agent/tools_schema.py`、`agent/tool_contracts.py`、`agent/trace_audit.py`、`agent/local_tools.py`、`agent/check_force_reusable_full.py`：同步可见工具、契约校验与审计口径为 `runMultiFormulaBatchStream`，将旧名纳入 deprecated 识别；补齐 `resumeJob` 工具定义。

---

## [4.20.14] — 2026-05-13

**变更文件**：`SKILL.md`、`tools/fast_query.md`、`workflows/fast-window.md`、`workflows/fast-snapshot.md`

两类独立修改：① 认证体验改进；② 同步 `fastQuery` 接口最新规格（`window` 模式支持日期范围 + 估值/财务字段市场范围扩展）。

### 认证体验改进

- `SKILL.md` 硬规则 0：检查时机列表从 3 条扩展为 4 条，新增 ④**首次使用检测**——
  - 在本对话中准备调用第一个平台工具**之前**，先检查 `output/` 下是否存在任何 `.session*.json` 文件。
  - **不存在**（从未建立过 session）：主动读取 `config.json` 检查 `api_key`；为空则立即输出新用户引导消息并停止，非空则继续执行，后续不再重复检查。
  - **存在**（已有 session 文件）：跳过此检查，走原有后验路径，行为与 4.20.13 完全一致。
  - 说明：此条仅作为新用户体验保障（单次豁免），不影响正常使用路径；已有 Key 的老用户完全不受影响。

### fastQuery 接口规格同步

`window` 模式原生支持 `start_date`/`end_date`（此前只支持 `window_days`），估值/财务字段市场范围由"仅A股"扩展至 A/US/HK（部分字段仍仅A股）。

- `tools/fast_query.md`：
  - 参数表：`window_days` 改为可选，说明与 `start_date`/`end_date` 二选一；`start_date`/`end_date` 移除"仅 snapshot/report 可用"限制，三种 `query_type` 均可传。
  - 日期规则：删除 `DATE_RANGE_WINDOW_CONFLICT`（已移除）；新增 `DATE_BEFORE_SYSTEM_LIMIT`（日期早于 `20050104`）；修正 `MISSING_START_DATE` 触发条件（仅 `result_mode=series` 且未传 `start_date` 时）。
  - fields 白名单：估值字段 PE/PE_TTM/PB/PS_TTM/总市值/股息率 → A/US/HK 均支持；流通市值/换手率仍仅A股；财务字段除 ROE 外扩展至 A/US/HK。
  - 错误表 Layer 4：新增 `DERIVED_COMPUTE_FAILED`。
- `workflows/fast-window.md`：
  - 标题/描述：改为"最近N日序列 / 固定区间序列"，移除"固定日期范围不属于本 workflow"限制。
  - 执行步骤 ①④：允许传 `start_date`/`end_date`，删除日期范围禁止说明。
  - 参数表：新增 `start_date`/`end_date` 行；删去"禁止参数"中"日期范围与 window 互斥"项。
  - 调用示例：新增固定日期区间示例。
  - 错误表：删 `DATE_RANGE_WINDOW_CONFLICT`；`MISSING_WINDOW_DAYS` → `MISSING_WINDOW_PARAMS`。
- `workflows/fast-snapshot.md`：
  - 字段映射表顶部警告改为精确说明：PE/PB/PS_TTM/总市值/股息率 → A/US/HK；流通市值/换手率 → 仅A股。
  - 字段表中各估值行的"仅A股"备注同步更新。

---

## [4.20.13] — 2026-05-09

**变更文件**：`scripts/executor.py`、`scripts/call.py`、`scripts/quant_api.py`、`tools/run_multi_formula.md`

`runMultiFormulaBatch` 内部切换为 SSE 主路径（spec：`docs/runMultiFormulaBatch-sse-spec.md`）。LLM 可见工具名与返回结构**完全保持不变**，本次升级不需要清空旧 session。

- `scripts/executor.py`：新增 `call_run_multi_formula_batch_stream()`，逐行解析 SSE（`ready` / `progress` / `result` / `formula_error` / `done` / `fatal` / `: keepalive`）；在 `main()` 主分发处为 `runMultiFormulaBatch` 特判走 SSE。
  - **Idempotency-Key**：基于 `task_id+formulas+begin_date+use_minute_data+force_reusable_array` 哈希派生，跨子进程重调仍一致；避免重复扣费。
  - **断线续传**：拿到 `trace_id` 后按 `task_id+trace_id+last_event_id` 重连，最多 3 次，退避 1s/3s/9s。
  - **可控 fallback**：仅在首次 POST 且尚未读到任何事件且 HTTP 返回 404/405/406 时，才回退到同步老接口 `/skill/runMultiFormulaBatch`；中途断线一律走 resume，不重复提交。
  - `TOOL_TIMEOUTS["runMultiFormulaBatch"]` 900s → 1800s，与服务端取消 5min 网关超时对齐。
- `scripts/call.py`：subprocess 外层超时参数化，`runMultiFormulaBatch` 1800s，其余工具仍为 900s，避免与内层 SSE 超时互相打架；响应中的 `trace_id` 持久化到 `.session.json` 后从输出中剥离，不暴露给 LLM。
- `scripts/quant_api.py`：同步特判 `runMultiFormulaBatch` 走 SSE，避免 Python API 划过 SSE 继续打同步。
- `tools/run_multi_formula.md`：底部新增「实现说明（无需 LLM 关心）」一节，明确不允许 LLM 直调 `runMultiFormulaBatchStream`。
- 后续按最新接口说明补齐 `research_24h` / `deferred` 行为：`ready` 事件额外记录 `job_id` / `execution_profile` / `queue` / `stream_url`；收到 `deferred` 时直接返回 job ack；`execution_profile` 纳入幂等键；deferred 响应保留 `trace_id` / `stream_url` 给后续 resume。
- 日志名修订：走 SSE 主路径时 `logs/*.jsonl` 中 `tool` 字段记录为 `runMultiFormulaBatchStream`，仅在回退到同步老接口时才记 `runMultiFormulaBatch`，便于审计/计费区分两条路径。

> 封面保证：工具名、参数、同步 JSON 返回与 v4.20.12 完全一致；公式上限、计费表未变。

---

## [4.20.12] — 2026-05-09

**变更文件**：`SKILL.md`、`scripts/call.py`

针对 claude-sonnet-4.6 等不会主动加载 `tools/*.md` 的模型，加固执行端参数容错与入口处的 schema 显眼提示，避免同类 schema 错误重复消耗工具调用预算。

- `scripts/call.py` `_normalize_params`：
  - `confirmDataMulti`：自动把 `queries` / `query` / `descriptions` / `names` 等常见错误参数名归一化为 `data_desc`（list 自动逗号合并）。
  - `readData`：自动把 `variable_names` / `variable_name` / `index_title` / `index_titles` 归一化为 `ids`；并新增 hex `_id` 客户端校验，传入中文变量名等非法 id 时立即返回结构化错误，**不再发出无效远程调用**。
- `scripts/call.py` 新增 `_maybe_abort_on_client_validation`，让客户端校验错误在调用 executor 之前阻断。
- `SKILL.md`：硬规则之前新增**「平台工具参数速查」**段，用 ✅/❌ 表格列出三个最高频的 schema 错误（`confirmDataMulti.data_desc` 字符串、session 中间变量必须双引号引用、`readData.ids` 必须是 hex `_id`）。前置位置确保即便模型不读 `tools/*.md` 也能命中。

---

## [4.20.11] — 2026-05-09

**变更文件**：`SKILL.md`、`workflows/global-rules.md`、`workflows/quant-standard.md`、`workflows/event-study.md`、`workflows/regime-segmentation.md`

修复 v4.20.10 中因规则过硬导致的过度工具调用问题：字段确认改为保留用户口径但优先使用平台中文规范查询词，TopN 数值读取不再强制 `precheck`，工具清单自检不再诱导 Agent 搜索或读取 checklist 文件。

- `SKILL.md`：版本号升至 `4.20.11`；工具调用前清单改为三条心内自检，明确禁止为执行清单而搜索、加载或读取 `recipes/tool-call-checklist.md`。
- `workflows/global-rules.md`：指标口径规则从“查询词必须包含用户原始表达”改为“用户口径即需求，不等于查询词原样照抄”；用户要 `PE(TTM)` 时首选 `confirmDataMulti("市盈率 TTM")` 并回检 TTM 口径。
- `workflows/quant-standard.md`：当前截面 TopN 读取中，`precheck` 降级为大表保护；已通过 `取前(..., 返回数值)` 收敛的 TopN 展示值直接用 `readData(mode="last_column_full")`，且 `precheck` 不支持时禁止围绕它重试。
- `workflows/event-study.md` / `workflows/regime-segmentation.md`：修正 `PE(TTM)` 作为 `confirmDataMulti` 示例时的说明，避免事件研究和区间识别路径继续把 `PE(TTM)` 原样当查询词。

---

## [4.20.10] — 2026-05-07

**变更文件**：`SKILL.md`、`tools/fast_query.md`、`workflows/fast-snapshot.md`、`tools/get_card_formulas.md`、`presets/cases_index.yaml`、`workflows/quant-standard.md`、`tools/run_multi_formula.md`、`scripts/quant_api.py`、`recipes/value-pe-strategy.md`、`recipes/ma-crossover-backtest.md`、`recipes/industry-aggregation.md`

修复 Fast Path 今日行情查询被错误排除、`getCardFormulas` 接口参数变更为名称搜索、全市场公式写法和 readData 参数两处高频错误；另修复工具名混淆导致的高频 `未知工具` 死循环，新增失败熔断与受控失败答复两条硬规则。

- `SKILL.md` + `tools/fast_query.md` + `workflows/fast-snapshot.md`：Fast Path 条件 #4 去除对"今天/今日/当日/当前/实时/盘中"的过度排除，仅保留"排名/筛选/全市场"语义的拦截；新增"日内刷新行为"说明——`snapshot` 模式不传 `start_date` 时服务端自动启用盘中刷新（等效 `use_minute_data: true`），无需在参数中额外声明。
- `tools/get_card_formulas.md`：接口参数由 `card_ids`（MongoDB ObjectId 数组）变更为 `card_names`（卡片名称数组），支持服务端大小写不敏感的子串模糊匹配；移除单张兼容写法 `card_id`；更新示例、错误码说明。
- `presets/cases_index.yaml`：头部注释同步更新为 `getCardFormulas(card_names=["卡片名称"])`。
- `workflows/quant-standard.md`：
  - 资产宇宙收敛规则新增 ⚠️ 警告：`收盘价("万得全A")` 返回指数一维序列，**禁止**用于全市场筛选，必须改用 `"全市场每日收盘价" * 板块(万得全A)`；
  - 公式引用预确认表"全市场数据集"示例区同步补充相同反例；
  - 工具速查表 Step6 `readData` 行内新增提示：`ids` 必须是 hex `_id`，不能传中文变量名。
- `tools/run_multi_formula.md`：文件顶部新增 `⛔` 警告框，明确 LLM 可调用的唯一工具名为 `runMultiFormulaBatch`，禁止使用 `runMultiFormula` 或 `run_multi_formula`（均为无效名），收到 `未知工具` 后禁止以任何名称变体重试。
- `SKILL.md`（续）：原硬规则 3–8 整体后移为 5–10，插入两条新规则：
  - 规则 3（**工具失败熔断**）：同一工具名 + 同类错误最多重试 1 次；`runMultiFormula`/`run_multi_formula` 是无效旧名，收到 `未知工具` 后禁止再次调用同名；第 2 次仍失败必须切换备用路径或输出受控失败答复。
  - 规则 4（**受控失败答复**）：任何 workflow 失败退出时禁止空白结束，必须输出含"①问题复述 ②失败步骤 ③原因说明"的结构化答复。
  - 文档层级说明中"硬规则 4 条"同步更新为"硬规则 10 条"。
- `scripts/quant_api.py`：`get_card_formulas()` 函数签名及内部 payload 由 `card_ids` → `card_names`，与接口变更对齐。
- `recipes/value-pe-strategy.md` / `recipes/ma-crossover-backtest.md` / `recipes/industry-aggregation.md`：bash 调用示例中 `'{"card_ids": ["<相关卡片id>"]}'` 统一改为 `'{"card_names": ["<相关卡片名称>"]}'`。

---

## [4.20.9] — 2026-05-07

**变更文件**：`SKILL.md`、`workflows/fast-snapshot.md`、`workflows/fast-window.md`、`workflows/fast-report-period.md`、`workflows/quick-snapshot.md`

强制任何涉及资产的操作在调用远程工具前都先查本地资产库，消除服务端 `asset_resolve` 耗时并在歧义时主动澄清用户。

- `SKILL.md`：硬规则 #2 中"确认资产也必须先查本地库"扩展为**任何场景**——不再局限于用户显式说「确认资产/找代码」的情况；凡是出现资产名称、简称或代码，均须先 `grep presets/assets_db/{类型}.yaml`；命中唯一则用 ticker 替换中文名传参，命中多条则向用户澄清，未命中才保留原始名由服务端兜底；禁止绕过本地库直接把中文名传给远程工具。
- `workflows/fast-snapshot.md`：执行步骤 3→4，在 ① 和 ② 之间插入步骤 ①.5（本地 grep 资产确认）。
- `workflows/fast-window.md`：执行步骤 3→4，在 ① 和 ② 之间插入步骤 ①.5（本地 grep 资产确认）。
- `workflows/fast-report-period.md`：执行步骤 3→4，在 ① 和 ② 之间插入步骤 ①.5（本地 grep 资产确认）。
- `workflows/quick-snapshot.md`：Step 1 资产确认范围由「2~3 个资产才查本地库」改为「**含单资产在内**均须先查本地库」。

---

## [4.20.8] — 2026-05-06

**变更文件**：`SKILL.md`、`agent/tools_schema.py`、`scripts/executor.py`、`scripts/call.py`、`scripts/quant_api.py`、`presets/assets_db/*.yaml`、`presets/sectors.yaml`、`presets/themes.yaml`、`tools/read_data.md`、`tools/download_data.md`、`workflows/*.md`、`recipes/download-data.md`、`references/troubleshooting.md`、`datasets/**/*.json`

将资产确认默认路径切换为本地全量资产库 `presets/assets_db/`，移除旧的 `presets/assets.yaml` 与远程 `confirmMultipleAssets` 工具入口；资产未唯一命中时直接报错/澄清，不再远程兜底。

- `presets/assets.yaml`：物理删除，所有有效 workflow 改为 grep `presets/assets_db/{类型}.yaml`。
- `scripts/executor.py` / `scripts/call.py` / `scripts/quant_api.py` / `agent/tools_schema.py`：删除 `confirmMultipleAssets` 路由、参数归一化、Python wrapper 和工具 schema。
- `SKILL.md` / `workflows/*.md` / `references/troubleshooting.md`：资产确认规则改为本地 `assets_db` 唯一命中；未命中或多命中时停止并说明/澄清。
- `tools/read_data.md` / `agent/tools_schema.py`：按新版 `POST /skill/readData` 接口更新 mode 与参数说明，新增 `mode="range_data"` 及 `assets` / `max_cells` / `nan_handling` 参数。
- `workflows/*.md` / `tools/download_data.md` / `recipes/download-data.md`：将连续区间原始数据、下载 403 替代路径和短窗序列读取切换为受限日期区间的 `readData(mode="range_data")`，移除旧 `full` / `last_n_rows` 指引。
- `datasets/**/*.json`：从有效 `expected_tools` 中移除 `confirmMultipleAssets`。

---

## [4.20.7] — 2026-05-06

**变更文件**：`SKILL.md`、`scripts/self_update.py`、`references/troubleshooting.md`、`tools/fast_query.md`、`workflows/fast-snapshot.md`、`workflows/fast-window.md`、`workflows/fast-report-period.md`

强化服务端强制版本拦截后的更新恢复链路，将单一 npx 更新路径扩展为 `npx update` → `npx add` → `Python Zip Fallback`，降低无 Node、无 npx、网络失败、Windows 权限失败场景下的用户卡死率。

> 📌 **后续已反转**：本条所述「npx 优先」顺序已在更晚版本被改回「Python Zip 优先」，详见当前 `references/troubleshooting.md` 与服务端协议块 `try_order` 字段。本段保留仅作历史审计。

- `SKILL.md`：版本号从 `4.20.6` 升至 `4.20.7`；硬规则 #8 (B) 新增 `[QBS:SKILL_UPDATE_REQUIRED]` 协议块解析，支持读取 `required_version` / `update_cmd` / `add_cmd` / `python_zip_available` / `zip_url` / `zip_sha512` / `zip_root` / `github_zip_skill_path`。
- `SKILL.md`：服务端要求升级时的处理顺序改为先 `npx skills update`，仅在明确未安装时执行 `npx skills add`；npx/node/权限/symlink/网络失败时进入 Python Zip Fallback，不再把 `add --copy` 作为默认分支。
- `SKILL.md`：Python Zip Fallback 要求下载官方 zip 后先流式校验 SHA-512；不一致时放弃该 zip 包，禁止解压或替换正式 skill 目录；解压必须走 staging，拒绝路径穿越，并保留 `config.json` / `config.local.json`。
- `scripts/self_update.py`：新增标准库自更新脚本，支持 `--url` / `--zip-path`、`--sha512`、`--version`、`--zip-skill-path`、`--dry-run`；执行下载、SHA-512 校验、安全解压、必要文件检查、版本校验、备份、保留配置和替换安装。
- `references/troubleshooting.md`：版本不匹配表格同步新的三段更新链路，补充 Python Zip、SHA-512 不一致、包版本不匹配、全部路径失败等处理方式。
- `tools/fast_query.md`：补充 `start_date`、`end_date`、`result_mode` 参数与返回结构，明确 `value` 默认返回最后有效值、`series` 返回完整序列，`window` 与固定日期范围互斥。
- `workflows/fast-snapshot.md` / `workflows/fast-report-period.md`：支持固定日期范围下的最后有效值与完整序列取值规则，补充 `result_mode="series"` 示例。
- `workflows/fast-window.md` + `SKILL.md`：明确 `fast-window.md` 只处理最近 N 日，不处理固定起止日期；固定日期范围行情/估值序列路由到 `fast-snapshot.md`，财务序列路由到 `fast-report-period.md`。

---

## [4.20.6] — 2026-04-30

**变更文件**：`scripts/call.py`、`SKILL.md`、`workflows/run-formula-chain.md`、`workflows/global-rules.md`、`tools/run_multi_formula.md`

修复 Windows GBK 终端下终端打印失败的问题，以及 `runMultiFormulaBatch` 返回 `code=0` 但 `data.success=false` 时未能识别失败的问题（接 `r4alpha_qbs_runmultiformula_empty_stdout_repro_20260430` 复盘）；同步将服务端切批硬上限更新为 10 条/批。

- `scripts/call.py`：
  - 新增 `_configure_parent_stdio()`：`main()` 启动时把 `sys.stdout/stderr` 重设为 `UTF-8 + errors='replace'` 的 `TextIOWrapper`，从源头消除 GBK 终端打印 emoji/中文的编码异常。best-effort 实现，失败不抛。
  - 新增 `_safe_print(text, *, is_stderr=False)`：三层兜底——① 正常 `print`；② 捕获 `UnicodeEncodeError` 后用 `buffer.write(... encode(replace))`；③ 仍失败时打印纯 ASCII 提示，告知结果已存入 `gzq_out.txt`。
  - 主 executor 路径（`_run_executor` 后 stdout/stderr 打印）的 `except UnicodeEncodeError: pass` 改为 buffer 直写 + `errors='replace'`；原有行为是静默跳过，Agent 得到空 stdout 却无法感知需要回读 `gzq_out.txt`。
  - 替换三处裸 `print()` 路径为 `_safe_print()`：`newSession` 结果、`webSearch / buildEventStudy` 结果、`SKILL_VERSION_MISMATCH` 错误信封（三处在主 executor 修复时被遗漏）。
  - 新增 `_process_run_multi_formula_batch()` 后处理钩子，触发条件：`code=0` 且 `data.success=false`；在顶层注入 `success: false`；将 `data.errors[]` 提升至顶层并精简为 `formula / leftName / error / errorType` 四字段；注入区分「全部失败」/「部分成功」的可读 `message`；不篡改服务端 `code` 与进程退出码。
  - `import io` 一同补入。
- `SKILL.md`（工具调用方式章节）：`gzq_out.txt` 回读路径从硬写 `/tmp/` 改为跨平台说明——Linux/macOS 用 `cat /tmp/gzq_out.txt`，Windows PowerShell 用 `Get-Content "$env:TEMP\gzq_out.txt" -Encoding UTF8`。原文 `/tmp/` 在 Windows 上实际为 `%TEMP%`，路径错误导致回读彻底失效。
- `workflows/run-formula-chain.md`（失败处理表）：
  - 「stdout 截断」行：补充 Windows PowerShell 回读路径，与 SKILL.md 保持一致。
  - 新增「stdout 完全为空（exit code=0）」行：明确指引 ① 先查 `%TEMP%\gzq_out.txt`；② 再查 `quant-buddy-skill/logs/<task_id>.jsonl`；只要其一含 `code=0`、`success:true`、`index_info._id`，可直接进入 `readData`，不必重跑公式。来自复盘文档 Section 12 实测结论：服务端结果已落盘，仅终端打印失败。
- `tools/run_multi_formula.md` + `workflows/global-rules.md`（切批上限）：服务端对单次 `runMultiFormulaBatch` 的公式数硬上限由 20 调整为 **10**，本 skill 切批阈值与服务端对齐（原“保守收紧为 10”的说法同步去除，两者已一致）。限制表中各 tier 的服务端上限一列由 20 改为 10。

---

## [4.20.5] — 2026-04-30

**变更文件**：`SKILL.md`、`references/troubleshooting.md`、`workflows/run-formula-chain.md`

强化版本不匹配场景的自愈流程，堵住"Agent 改本地版本号字符串伪造一致"的欺骗式修复路径。

- `SKILL.md`：硬规则 #8 重写——区分两类版本不匹配信号：
  - (A) 本地 session ↔ 本地 SKILL.md 版本不一致（`SKILL_VERSION_MISMATCH`）：保留原 `newSession` + 重读 + 重跑流程；
  - (B) 服务端要求版本高于本地（响应文案提示 `npx skills update` / `skill 版本过低` 等）：默认 `npx skills update pseudo-longinus/quant-buddy-skills -y`；若 `update` 报 `not installed` 则回落到 `npx skills add pseudo-longinus/quant-buddy-skills -g --all`（`--all` = `--skill '*' --agent '*' -y`，CLI 内部展开，cmd/PowerShell/bash 都通用，规避 Windows cmd 把 `'*'` 当字面量传入而报 `Invalid agents: '*'` 的坑）；Windows 上 symlink/`EPERM` 报错时末尾追加 `--copy` 重试；用户拿不准装在哪可让其执行 `npx skills list -g --json` 自检。
  - 新增 **P0 红线**：禁止用 `replace_string_in_file` / `multi_replace_string_in_file` / 终端 `sed` / `echo >` 等任何方式，修改本地 `SKILL.md` / `config.json` / `scripts/*.py` / `CHANGELOG.md` 中的 `version` 字段，或改写 `.session.json` 的 `skill_version_at_creation`，企图蒙混版本校验——这种做法会让本地工具签名继续过时，后续调用必然继续失败，且服务端审计日志记录真实上报版本，伪造无效。
- `references/troubleshooting.md`：「版本不匹配」表格扩展为 7 行，覆盖「老用户更新 / 新用户首装回落 / Windows --copy / 不确定装在哪自检 / npx 命令失败」全部分支。
- `workflows/run-formula-chain.md`：失败处理表中新增服务端要求升级一行，明确指向硬规则 #8 (B)。

## [4.20.4] — 2026-04-30

**变更文件**：`tools/run_multi_formula.md`、`workflows/global-rules.md`、`workflows/quant-standard.md`、`workflows/run-formula-chain.md`、`recipes/tool-call-checklist.md`、`SKILL.md`

跟随服务端契约更新：`/skill/runMultiFormulaBatch` 的复用标记参数由布尔位对齐数组 `force_reusable_flags`（`boolean[]`，与 `formulas` 下标一一对应）改为变量名数组 `force_reusable_array`（`string[]`，写入需要保留/复用的公式左侧变量名）。

语义换算：
- 旧：`"force_reusable_flags": [false, false, false, true]`，`formulas = [MA5, MA20, Signal, TOP10]`
- 新：`"force_reusable_array": ["TOP10"]`（未列出的变量默认不复用；不传则全部复用）

服务端校验新规：
- 数组元素必须严格匹配 `formulas` 中某条公式的左侧变量名（前后空格自动忽略，大小写敏感）
- 不存在的变量名 → `code: -1`
- 当前 `formulas` 出现重复左值 → `code: -1`
- 多输出公式（如 `"净值, 持仓 = 回测(...)"`）任写一个变量名即可标记整条公式复用

> 三问法、跨批保活、被动拆批、`all-true = 规则退化` 等硬规则全部保留，仅把"`true`/`false` 标记"重新表述为"是否写入 `force_reusable_array`"。CHANGELOG 4.20.0 ~ 4.20.3 中保留了 `force_reusable_flags` 的历史描述以保持版本追溯一致。

---

## [4.20.3] — 2026-04-29

**变更文件**：`scripts/call.py`、`scripts/quant_api.py`、`SKILL.md`

修复多会话并行下 `output/.session.json` 被互相覆盖的问题。原实现把 SESSION 文件路径硬编码为单一固定路径，多个 chat 同时调用 `newSession` 时后者会覆盖前者，导致后续工具调用注入错误的 task_id（session 漂移）。`scan_dimensions.md` 第 114 行那条「扫描期间不要并发执行其他 API 调用」的限制就是这个 bug 的下游症状。

- `scripts/call.py`：新增 `_resolve_session_file()`，按优先级 `QBS_SESSION_FILE` 环境变量 → `QBS_SESSION_KEY` 派生 `.session.<key>.json` → 默认 `.session.json` 解析路径；KEY 经过 `re.sub(r"[^A-Za-z0-9_\-]", "_", key)[:64]` 清洗防止路径注入。
- `scripts/call.py`：`newSession` 调用前 best-effort 清理 `output/` 下超过 7 天未访问的 `.session.*.json`，避免长期累积垃圾文件。
- `scripts/quant_api.py`：同步引入 `_resolve_session_file()`，与 call.py 走同一套优先级。
- `SKILL.md` 硬规则 #1：新增「多会话隔离」子条款——多 chat / 共享开发机 / 并行 trace 场景下，必须在 chat 第一条 bash 命令 `export QBS_SESSION_KEY=$(python -c "import uuid;print(uuid.uuid4().hex[:12])")`，之后所有 `python scripts/call.py` 必须在同一 terminal 会话里执行。未设置时退化到默认 `.session.json`，向后兼容单会话场景。
- `SKILL.md` 目录树注释：`.session.json` → `.session.<key>.json`。
- `SKILL.md` / `metadata.version`：4.20.2 → 4.20.3

> 💡 **设计取舍**：保留默认 `.session.json` 而不是强制要求 KEY，是为了不破坏已有的单 chat 调用流程（包括平台 MCP 调用方）；只有在用户/测试台显式 `export QBS_SESSION_KEY` 时才启用隔离。Agent 端通过硬规则约束在多 chat 场景主动 export，达到「默认安全 + 显式并行」的平衡。

---

## [4.20.2] — 2026-04-29

**变更文件**：`SKILL.md`、`workflows/run-formula-chain.md`（新增）

修复一类真实场景失败：用户用 `/quant-buddy-skill 直接运行 ...md 文件里的全部公式，选出股票给我` 这种 prompt 时，Agent 会写 `python - <<'PY' ... subprocess.run(['python','scripts/call.py','runMultiFormulaBatch',...]) ... PY` 这种 inline heredoc + subprocess 多批循环驱动脚本，连锁触发 task_id 漂移、stdout 阻塞、`/tmp/gzq_out.txt` 在 Windows 不存在等问题。trace 见 `1777454879452.json`。

- `SKILL.md` 硬规则 #2：明文禁止以下"自写 driver 脚本"反模式（无论批次多少、依赖多复杂）：
  - `python - <<'PY' ... subprocess.run(['python','scripts/call.py',...]) ... PY`
  - `python -c "import subprocess; subprocess.run(['python','scripts/call.py',...])"`
  - `node -e "...child_process.execSync('python scripts/call.py ...')..."`
  - 任何在 inline 脚本里 `for/while` 循环驱动多批 `runMultiFormulaBatch` 的写法
- `SKILL.md` 硬规则 #2：补充多批 `runMultiFormulaBatch` 的合规模板——切批与编排必须由 LLM 自己在工具调用之间完成，参数预处理在推理中完成，中间产物用 `create_file` 落盘到 `output/tmp_batches/batch_K.json`，每批一条独立 shell：`GZQ_PARAMS="$(cat output/tmp_batches/batch_K.json)" python scripts/call.py runMultiFormulaBatch`
- `SKILL.md` 场景路由表新增条目：「直接运行用户给定的公式链文件」→ `global-rules.md` → `run-formula-chain.md`
- 新增 `workflows/run-formula-chain.md` leaf workflow：明确 6 步合规路径（读文件 → LLM 推理解析公式 → LLM 推理生成 force_reusable_flags → create_file 切批落盘 → 逐批独立 shell 调用 → readData 取最终输出），并在文档顶部列出违规反例。
- `SKILL.md` / `metadata.version`：4.20.1 → 4.20.2

> 💡 **设计取舍**：之所以坚持"每批一条独立 shell"而不让 Agent 写一次性 driver 脚本，是因为这条 hard rule 同时保障了 (a) call.py 的 session 注入只发生一层；(b) LLM 能看到每批返回再决定下一批；(c) 错误定位能落到具体批次；(d) token 用量可控。

---

## [4.20.1] — 2026-04-29

**变更文件**：全仓（`SKILL.md`、`workflows/*.md`、`tools/*.md`、`recipes/*.md`、`references/troubleshooting.md`、`scripts/executor.py`、`scripts/call.py`、`scripts/quant_api.py` 等）

将 LLM 可见的工具名 `runMultiFormula` 全量重命名为 `runMultiFormulaBatch`，与新端点路径同名，避免 LLM 受历史训练记忆影响仍调用旧名。

- `scripts/executor.py`：`TOOL_ROUTES` key 由 `"runMultiFormula"` → `"runMultiFormulaBatch"`；line 681 的 `tool_name == "runMultiFormulaBatch"` 同步
- `scripts/call.py`：line 460-461 的 formulas 字符串数组校验分支 `tool_name == "runMultiFormulaBatch"` 同步
- `scripts/quant_api.py`：line 280 `self._call("runMultiFormulaBatch", params)` 同步
- 所有 workflow / tool 文档 / recipe CLI 示例（`python scripts/call.py runMultiFormulaBatch '{...}'`）一并更名
- 注：`tools/run_multi_formula.md` 文件名按 snake_case 约定保留，未改名为 `run_multi_formula_batch.md`

> ⚠️ 4.20.0 条目里"工具名对 LLM 不变"的说法**已作废**——4.20.1 起工具名亦统一为 `runMultiFormulaBatch`。参数/返回结构仍与旧端点完全一致。

---

## [4.20.0] — 2026-04-29

**变更文件**：`scripts/executor.py`、`tools/run_multi_formula.md`、`SKILL.md`

切换公式执行后端到 `/skill/runMultiFormulaBatch`：

- `scripts/executor.py`：`TOOL_ROUTES` 中 `runMultiFormula` 的 HTTP 路径由 `/skill/runMultiFormula` → `/skill/runMultiFormulaBatch`（工具名对 LLM 不变；参数/返回结构与旧端点完全一致）
- `tools/run_multi_formula.md`：
  - 端点行同步 `/skill/runMultiFormulaBatch`
  - 顶部新增"后端切换说明"段：解释新端点底层用 `task.process.batch_evaluate`，公式间共享 Worker 内存，整批超时 10 分钟；服务端对单次公式数有 20 条硬上限，超出即 `code=-1` 不扣费
  - 单次公式数限制表更新为"所有 tier 后端原始上限均为 20"，硬规则文案同步说明这是服务端强制
> ⚠️ 注：服务端硬上限后于本版本在 4.20.6 调整为 10，参见 `[4.20.6]`。- `SKILL.md`：版本升级 4.19.0 → 4.20.0

> 💡 **效果预期**：对依赖链密集的批次（如评分链、回测链），由于公式间在同一 Worker 内存中传递，相比旧端点的 N 次独立 fire-and-forget 应有更稳定的耗时和更低的跨任务超时风险（参考 r2 测试中 21-83 一次提交超时、同批次重跑 8s→43s 等问题）。

---

## [4.19.0] — 2026-04-29

**变更文件**：`tools/run_multi_formula.md`、`workflows/global-rules.md`、`workflows/quant-standard.md`、`SKILL.md`

依据 `datasets/test/force_reusable_flags-参数标注测试/{场景1,场景2}/r2/eval_report.md` 的诊断改进：

- **统一 20 条保守上限**（与服务端确认）：所有 tier（free/plus/pro/ultra）单次 `runMultiFormula` 一律按 20 条切批，不再按 tier 动态调整
  - `tools/run_multi_formula.md`：tier 上限表新增"实际必须遵守"列，全部 20，并加硬规则警告
  - `workflows/global-rules.md`：tier 感知段同步说明
- **强化 `force_reusable_flags` 跨调用保活语义**（`global-rules.md §13`）：
  - 把"一问"改为"三问"：是否被 `readData` / 是否被后续 batch / 是否被用户后续追问引用
  - 明确"末批最终评分变量（如 `*_Score`）即使语义像中间量也必须 `true`"——P0 防错
  - 新增"缓存兜底 ≠ flag 标对"提示，避免误判
  - 重申禁止为"保险"一律 all-true
- **新增"未来未知场景"修正语义**（`quant-standard.md`）：首批可保守标 `false`；后续轮次回引到首批早期变量时**必须先调修正接口**再继续；接口缺失时不得默默兜底
- `SKILL.md`：版本升级 4.18.0 → 4.19.0

---

## [4.18.0] — 2026-04-29

**变更文件**：`scripts/call.py`、`workflows/global-rules.md`、`workflows/quant-standard.md`、`SKILL.md`

- `scripts/call.py`：`_run_executor()` 的子进程超时阈值从 300s 调整到 900s；新增 `subprocess.TimeoutExpired` 捕获，超时时返回稳定错误码与明确提示，避免异常上抛导致调用链中断
- `workflows/global-rules.md`：补充 `runMultiFormula` 多批次场景规则，明确跨批引用变量必须保活（`true`），并将 all-true 标记为规则退化信号
- `workflows/quant-standard.md`：补充 `force_reusable_flags` 的单批/多批判定对照与分批切点原则，统一为通用依赖分析表述，移除特定案例命名
- `SKILL.md`：版本号升级至 `4.18.0`

---

## [4.17.0] — 2026-04-29

**变更文件**：`SKILL.md`、`scripts/call.py`、`scripts/quant_api.py`

- `SKILL.md`：硬规则从 7 条扩为 8 条；新增第 8 条"版本不匹配自愈"——工具返回 `SKILL_VERSION_MISMATCH` 时，LLM 须立即停止、newSession、强制重读 SKILL.md + workflow + 相关 tools/*.md、重新执行，禁止询问用户；版本号升至 4.17.0
- `scripts/call.py`：新增模块级 `_read_skill_version()`；`_write_session()` 写入 `skill_version_at_creation`；非 newSession 工具调用前添加版本守卫（不匹配则打印 `SKILL_VERSION_MISMATCH` 并退出）；`newSession` 响应新增 `skill_version`、`version_changed_from_last_session`、`previous_skill_version` 字段
- `scripts/quant_api.py`：同步上述改动；新增模块级 `_read_skill_version()`；`_write_session()` 写入 `skill_version_at_creation`；`_call()` 加版本守卫（版本不匹配时抛 `RuntimeError`）；`newSession` 分支响应扩展三个新字段

---

## [4.16.0] — 2026-04-29

**变更文件**：`SKILL.md`、`scripts/call.py`、`scripts/quant_api.py`

- `SKILL.md`：新增"版本自检"硬规则——收到 `SKILL_VERSION_MISMATCH` 错误时，自动 newSession + 强制重读 SKILL.md 及当前 workflow 后重试
- `scripts/call.py`：`newSession` 分支写入 `skill_version_at_creation` 字段到 `.session.json`；非 newSession 工具调用前置版本守卫，版本不一致时返回 `SKILL_VERSION_MISMATCH`
- `scripts/quant_api.py`：同等版本守卫逻辑；`newSession` 响应扩展 `version_changed_from_last_session` 与 `previous_skill_version` 字段

---

## [4.15.1] — 2026-04-（内部补丁，无 iter 记录）

---

## [4.14.0] — 2026-04-22 _(iter-014)_

**变更文件**：`SKILL.md`、`workflows/fast-snapshot.md`、`workflows/fast-window.md`、`workflows/global-rules-lite.md`、`recipes/tool-call-checklist.md`、`workflows/quick-report-period.md`

- `SKILL.md`：新增盘中/实时 TopN 与阈值筛选路由条目；第 5 条硬规则"最终答案首句必须是数据结论"
- `workflows/fast-snapshot.md` / `fast-window.md`：结果合同写死停止条件与输出模板
- `workflows/global-rules-lite.md`：去掉强制 RU/quota 外露，与去过程化方向统一
- `recipes/tool-call-checklist.md`：新增 `runMultiFormula` 调用前财务查询严禁 `use_minute_data: true` 检查项
- `workflows/quick-report-period.md`：财务查询严禁 `use_minute_data: true` 声明

---

## [4.10.0] — 2026-04-15 _(iter-013)_

**变更文件**：`workflows/event-study.md`、`workflows/quant-standard.md`、`workflows/render-kline.md`、`workflows/industry-aggregation.md`、`workflows/global-rules.md`

- `workflows/event-study.md`：阈值筛选必须在公式层生成布尔掩码（禁止取回完整序列后人工扫描）；新增反例说明（`last_column_full` 序列截断导致遗漏事件）
- `workflows/quant-standard.md`：变量名循环依赖禁止规则 + 正反例说明（`=` 左侧不得与右侧引用的数据集名相同）
- `workflows/render-kline.md`：`show_volume` 必须显式传参
- 回滚了 `quant-standard.md` / `read_data.md` / `cases_index.yaml` 中引发一致性下降的改动，仅保留已验证有效的 29 行规则

---

## [4.9.1] — 2026-04-14 _(iter-012)_

**变更文件**：`SKILL.md`、`workflows/event-study.md`、`workflows/global-rules.md`

- `SKILL.md`：第 5 条硬规则（最终答案首句数据结论）早期版本
- `workflows/event-study.md`：accepted candidate 最低证据字段要求（`label_evidence_quote` 等不得为空）；锚点一致性校验规则；写后必读（`write_skill_file` 后必须 `read_skill_file` 回读校验）
- `workflows/global-rules.md`：`evidence-only` 规则；去过程化文本级硬禁令（"已成功获取""让我来"等过程话术一律禁止出现在最终答案中）

---

## [4.8.1] — 2026-04-13 _(iter-011)_

**变更文件**：`SKILL.md`、`workflows/event-study.md`

- `SKILL.md`：新增"盘中/实时全市场 TopN 排名"路由条目，强制进入 `quant-standard.md` 专用微流程
- `workflows/event-study.md`：事件日期获取优先级硬规则（用户已给出明确时间锚点时，禁止先 webSearch）；`event_candidates.json` 新增 `subject_evidence_quote` / `policy_evidence_quote` / `evidence_consistency_check` 字段；新增 Step 1.8 强制生成 `event_selection.json`；`buildEventStudy.dates` 只能来自 `event_selection.accepted_dates`

---

## [4.7.1] — 2026-04-10 _(iter-010)_

**变更文件**：`SKILL.md`、`workflows/event-study.md`、`workflows/quick-snapshot.md`、`workflows/quick-window.md`、`workflows/quick-report-period.md`、`workflows/period-return-compare.md`、`workflows/render-kline.md`、`workflows/event-study.md`、`workflows/quant-standard.md`、`workflows/regime-segmentation.md`

- `SKILL.md`：新增 `period-return-compare.md` 路由条目；leaf workflow 最终回答合同优先级说明
- `workflows/event-study.md`：事件锚点优先级硬规则（公告日首选）；`event_candidates.json` 所需字段全部列出（含 `anchor_basis`、`label_confidence` 等 20+ 字段）；完成候选表后必须持久化为 `event_candidates.json`
- 10 个文件全文本规则强化（evidence-only 场景门禁、量化排名结果表证据门禁、资产歧义确认最小化模板等）

---

## [4.6.0] — 2026-04-09 _(iter-009)_

**变更文件**：`SKILL.md`、`workflows/event-study.md`、`workflows/regime-segmentation.md`、`workflows/period-return-compare.md`（新增）、`scripts/executor.py`

- `SKILL.md`：新增 `period-return-compare.md`、`regime-segmentation.md` 路由条目；路由判断口诀更新；leaf 不再声明"自包含"，改为"必读 global-rules.md 为全局合同基底"
- `workflows/event-study.md`：阈值触发模式执行步骤（可量化阈值 vs 不可量化阈值分支）
- `workflows/period-return-compare.md`：新建，专门处理固定区间累计涨跌幅对比
- `scripts/executor.py`：公式中双重转义引号防御性修复（`\"` → `"` 防 HTTP 500）

---

## [4.5.0] — 2026-04-08 _(iter-008)_

**变更文件**：`SKILL.md`、`workflows/event-study.md`、`workflows/global-rules.md`

- `SKILL.md`：路由硬排除表（固定区间/行业聚合/阈值触发强制改道）；文档层级说明（SKILL.md > global-rules.md > leaf workflow）；`quick-lookup.md` 定位重新声明（仅作路由入口和规则参考，leaf 执行时无需回读）
- `workflows/event-study.md`：完整 Checkpoint 协议（E0–E5）；Abstract Target 定义
- `workflows/global-rules.md`：leaf 必须先读 global-rules.md 的强制要求

---

## [4.4.0] — 2026-04-07 _(iter-007)_

**变更文件**：`SKILL.md`、`workflows/global-rules.md`

- `SKILL.md`：硬规则重写——原生工具优先（禁止用 `run_skill_script`/shell 命令/`GZQ_PARAMS=...` 包装原生工具）；事件研究前置证据门禁（三选一条件，均不满足则停止计算）；配置/认证错误立即停止规则
- `workflows/global-rules.md`：原生工具优先规则独立章节；`scripts/call.py` 允许用途限定为 3 类（newSession / workflow 指定脚本步骤 / 无原生等价能力时兜底）

---

## [4.2.0] — 2026-04-01 _(iter-006)_

**变更文件**：`SKILL.md`（及多个 workflow 文件，详见 `skill-changelog/iter-006-post-diff.md`）

- `SKILL.md`：全局最终交付硬规则（leaf 满足停止条件后，必须当轮立即输出最终答案，禁止继续读文档/追加分析）
- K线路由入口独立为 `workflows/render-kline.md`，路由表更新

---

## [4.1.0] — 2026-03-31 _(iter-005)_

**变更文件**：`SKILL.md`、`workflows/quick-snapshot.md`（及其他 workflow，详见 `skill-changelog/iter-005-post-diff.md`）

- `SKILL.md`：新增 `render-kline.md` 路由条目；证据分级中 `description` 最后值受控文本抽取的例外条款精确化
- `workflows/quick-snapshot.md`：受控文本抽取条件（仅 quick-snapshot 场景且满足 4 个前置条件时允许）

---

## [4.0.0] — 2026-03-30 _(iter-004)_

**变更文件**：`SKILL.md`

- 路由表重构：K线入口改为 `render-kline.md`；新增第 3 条路由（用户明确要画图时直接加载 `render-kline.md`）
- 版本号升至 4.x（major 重构）

---

## [3.5.0] — 2026-03-27 _(iter-003)_

**变更文件**：`SKILL.md`

- leaf workflow 自包含声明（读完 leaf workflow 即可直接执行，不需要回到 `quick-lookup.md`）
- 全局证据分级章节新增（A 级证据 / B 级证据 / 受控文本抽取例外规则）

---

## [3.3.0] — 2026-03-27 _(iter-002)_

**变更文件**：`SKILL.md`、`workflows/quick-lookup.md`（及 `quick-snapshot.md`、`quick-window.md`、`quick-report-period.md`）

- `SKILL.md` description 重写——面向用户可读（"查询A股收盘价…"），去掉内部实现描述
- 路由从单一 `quick-lookup.md` 拆分为三个 leaf workflow（snapshot / window / report-period）
- 禁止以"无法联网"或"无法获取实时数据"拒绝查数请求

---

## [3.2.0] — 2026-03-27 _(iter-001 post)_

**变更文件**：`SKILL.md`

- 路由描述从"优先走 quick-lookup.md"改为"按时间锚点分流到三个 leaf workflow"
- 目录树新增 `quick-snapshot.md` 条目

---

## [3.1.0] — 2026-03-26 _(iter-001)_

**变更文件**：`SKILL.md`、`workflows/quick-lookup.md`

- `SKILL.md`：新增高优先级路由规则区块（简单查数任务必须走 `quick-lookup.md`，禁止先调 `scanDimensions`/`renderKLine`）
- `SKILL.md` description：首行增加"简单查数任务优先走 quick-lookup.md"
- `workflows/quick-lookup.md`：扩展为快查强制路由 + 基础规则模板（169 行 → 499 行）

---

## [3.0.0] — 2026-03-26（初始版本）

- 首次发布，基础路由框架，支持选股 / 回测 / 因子 / 图表 / 小红书图文生成
