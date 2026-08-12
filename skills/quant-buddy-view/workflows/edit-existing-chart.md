# Workflow · 已发布页面的单个图表增删改查

> 前置：这是「自己的页面」的后续维护动作（见 [new-session-paradigm-routing.md](new-session-paradigm-routing.md)
> 「后续追问」一节）。命中的官方/社区链接要改，先转 ② fork 成自己的链接，再回到本流程。

用户只是想改**一个图表**——叠加一条线、去掉一条线、改时间窗口、或者问"这张图的真实数据是什么"——不要
默认当成整页重建处理（那意味着把页面上所有公式，包括跟这次改动无关的，重新校验/计算一遍）。这类请求
优先用 `scripts/chart_edit.py`，只动被要求的那一处；只有 §0 判定为 legacy 或改动本质上要求整页重算时，
才落回 [dashboard-end-to-end.md](dashboard-end-to-end.md) 第 4 节的整页重建流程。

设计背景/为什么要这样拆：脚本头部文档 `scripts/chart_edit.py` 与工具说明 `tools/chart_edit.md`。

## 0. 先 inspect，判断能不能走这条路

```bash
python scripts/chart_edit.py inspect '{"page_id":"page_xxx"}'
```

- 返回 `FORBIDDEN`（不是自己的页面）→ 按 `new-session-paradigm-routing.md` 的规则转 ② fork 新建自己的
  链接，不要在这条路径上纠结；fork 完成后拿到新 `page_id` 再回到本流程第 1 步。
- 返回 `"legacy": true`（页面是本次改动之前生成的老页面，运行时不支持定点编辑）→ 落回
  `dashboard-end-to-end.md` 第 4 节整页重建；这类页面因为没有留存公式文本，可能需要向用户确认原始
  公式意图（或直接复用 quant-buddy-skill 里能查到的既有校验记录）。
- 否则拿到结构化结果：`panels`（每个面板的 title/type/output(s)）+ `packages`（每个公式包的
  package_id/formulas/reads/`formulas_known`）。用这个结果定位目标面板与它当前依赖哪些 output，
  不要再临时 `grep`/`sed` 页面源码猜结构。

## 1. 按请求类型分派

把用户的请求归到下面四类之一，只调用对应的**一个**子命令；不要因为要改一条线就把页面上其它面板/公式
也带上重新验证。

### 增：叠加一条新线

只注册一个只含"这条新线所需公式"的最小公式包（不含页面上其它已有系列的公式），叠加到目标面板：

```bash
python scripts/chart_edit.py add_series '{
  "page_id": "page_xxx",
  "panel": "机器人产业链观察指数",
  "formulas": ["HS300=收盘价(沪深300)", "沪深300指数=\"HS300\"/前几天(\"HS300\",250)*100"],
  "output_name": "沪深300指数",
  "read_mode": "range_data",
  "mode_params": {"lookback_days": 2397}
}'
```

`panel` 可以是 0-based 下标、面板 title 精确匹配、或该面板已有的某个 output 名。`formulas` 里的公式必须
先在 quant-buddy-skill 用 `runMultiFormulaBatchStream` 跑通确认出数（与 `dashboard-end-to-end.md` 的硬
门槛一致），不能跳过验证直接注册。目标面板已有的系列、页面上其它面板，都不会被重新校验或重新计算。

### 删：去掉一条线（或整个面板）

不涉及任何公式/包操作，纯粹是把某个 output 从面板配置里摘掉再保存页面；对应公式包留着任其 TTL 到期，
不主动 revoke（可能被其它面板复用，撤销前无法确定是否安全）：

```bash
# 只去掉这张多线图里的一条线
python scripts/chart_edit.py remove_series '{"page_id":"page_xxx","panel":"机器人产业链观察指数","output_name":"沪深300指数"}'

# 不传 output_name：把整个面板/卡片一起删掉
python scripts/chart_edit.py remove_series '{"page_id":"page_xxx","panel":"机器人产业链观察指数"}'
```

### 改时间窗口

目标窗口如果落在"已经取过的范围"内（比如页面本来注册的是 2020 年至今，用户只是想看近半年），这纯粹是
前端展示层的事，脚本会自动只 patch 图表展示裁剪，不重新验证/注册公式包。只有目标窗口**超出**已注册范围
时，才会重新注册——而且只重新注册这一个 output 的公式，不牵连页面上其它线：

```bash
python scripts/chart_edit.py set_window '{
  "page_id": "page_xxx",
  "panel": "机器人产业链观察指数",
  "output_name": "机器人链观察指数",
  "start_date": "2022-01-01"
}'
```

返回的 `mode` 字段会标出这次到底是 `display_only`（纯前端裁剪）还是 `reregistered`（重新注册了这一个
output）。若报 `FORMULAS_UNKNOWN`（该 output 所属包没有在页面里留存公式文本——多半是老包），按提示显式
传 `formulas` 参数，或改走整页重建。

### 查：这张图的真实数据是什么

页面本身不内嵌真实数值（`SKILL.md`: "数据不焊进 HTML，运行时实时取"），HTML 里只有
`package_id + signature`；要看真实数据必须显式取数：

```bash
python scripts/chart_edit.py query_data '{"page_id":"page_xxx","output_name":"机器人链观察指数","result_mode":"summary"}'
```

`result_mode` 传 `"full"` 拿完整时间序列；默认 `"summary"` 只给首尾值/变化率/样本数，用于口头核对够用、
也更省 token。

## 2. 回复用户

按现有 `reply-templates/`、`reply-data-policies/` 的口径转述结果：只用 `chart_edit.py` 返回的
`url`/`message`/`start_date` 等字段，不要把 `signature`、完整 `formulas` 列表这类内部细节写进面向用户的
回复（signature 设计上允许写进页面 HTML 供实时取数，但不代表可以出现在聊天回复里）。

## 3. 与整页重建流程的边界

- 一次请求要同时动好几个面板、或明确要求"整体重做/换风格" → 直接走
  `dashboard-end-to-end.md` 第 4 节，别硬拆成好几次 `chart_edit.py` 调用。
- `chart_edit.py` 的每次 patch 都会顺带把页面运行时 JS 升级到当前版本（哪怕页面是旧版
  `build_dashboard.py` 生成的），但只有在有 `QBV_RENDER_JS_START/END` marker 时才能做到——没有 marker
  的页面（本次改动之前生成、从未被 `chart_edit.py` 碰过）一律判 legacy，交给整页重建，不强行升级。
