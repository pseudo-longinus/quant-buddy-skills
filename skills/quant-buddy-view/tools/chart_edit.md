# chart_edit — 已发布页面单个图表的增删改查

> 已发布页面的一次编辑（叠加/去掉一条线、改时间窗口、查真实数据）不必当成整页重建。`build_dashboard.py`
> 生成的页面 HTML 里有一段可定点定位、可整体替换的运行时 `<script>`（`QBV_RENDER_JS_START/END` marker
> 包住），里面的 `BOOT.packages`（多公式包数组）+ `panel.outputs`（多产出叠加面板）承载了"这条线归哪个
> 公式包、用什么公式、什么窗口"的溯源信息。本工具就是在这层能力上包的四个定点操作，只动被要求的那一处，
> 页面其余内容（壳、样式、无关面板/公式包）字节级不变。
>
> 使用场景/决策路径：[workflows/edit-existing-chart.md](../workflows/edit-existing-chart.md)。

## 前置

- 只能编辑**自己的**页面：底层复用 `static_page.py download`/`update`，归属由 `config.json` 的 `api_key`
  认定；不是自己的页面会透传服务端 `FORBIDDEN`，不要重试，转 fork。
- 只能编辑**本次改动之后生成**的页面（有 `QBV_RENDER_JS_START/END` marker）。更早生成的页面 `inspect`
  会返回 `"legacy": true`，落回 `workflows/dashboard-end-to-end.md` 的整页重建。
- 新公式必须先在 quant-buddy-skill 用 `runMultiFormulaBatchStream` 跑通确认出数，才能传给 `add_series` /
  `set_window` 注册——这条硬门槛和 `formula_package.py register` 一致，`chart_edit.py` 不会替你跳过。

## 子命令

### `inspect`

```bash
python scripts/chart_edit.py inspect '{"page_id":"page_xxx"}'
```

只读。返回：

```json
{
  "code": 0,
  "legacy": false,
  "panels": [
    {"index": 0, "title": "机器人产业链观察指数", "type": "line", "output": "机器人链观察指数", "outputs": null, "x_range": null}
  ],
  "packages": [
    {"role": "primary", "package_id": "pkg_xxx", "formulas": ["HC=..."], "reads": [...], "formulas_known": true}
  ],
  "grants": []
}
```

`formulas_known=false` 表示这个包在页面里没有留存公式文本（多半是没传 `spec.formulas`/`spec.reads` 就跑
`build_dashboard.py` 生成的页面，或早期由 `chart_edit.py` 之外的方式改过）——针对它的 `set_window` 扩窗会
失败，需要显式补传 `formulas`。**不要把这段结果原样贴进面向用户的回复**：公式文本本身不算敏感，但没必要
把内部结构暴露给最终用户。

### `add_series`

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

| 字段 | 必填 | 说明 |
|---|---|---|
| `page_id` | ✅ | 目标页面 |
| `panel` | ✅ | 目标面板：0-based 下标 / title 精确匹配 / 该面板已有的某个 output 名 |
| `formulas` / `formula` | ✅ | 只传**这条新线需要的公式**（含它依赖的中间变量），不要带上页面上其它系列的公式 |
| `output_name` | ✅ | 对外产出名，必须是 `formulas` 里某条公式的左值 |
| `read_mode` / `mode_params` | ❌ | 同 [formula_package.md](formula_package.md)，默认 `range_data` |
| `begin_date` / `ttl_days` / `intents` | ❌ | 透传给 `formula_package.py register` |
| `axis` | ❌ | `"right"` 时新系列归右轴（自动给面板打上 `dual_axis:true` + 累加 `right_series`），缺省 `"left"`（单轴，向后兼容） |

行为：只注册一个只含这条新线公式的最小包，追加进页面 `BOOT.packages`；目标面板从单 `output` 转成
`outputs` 数组（多线共存），页面上其它面板/公式包不受影响，也不会被重新校验或重新计算。

### `remove_series`

```bash
# 只去掉多线图里的一条
python scripts/chart_edit.py remove_series '{"page_id":"page_xxx","panel":"机器人产业链观察指数","output_name":"沪深300指数"}'

# 不传 output_name：整个面板一起删
python scripts/chart_edit.py remove_series '{"page_id":"page_xxx","panel":"机器人产业链观察指数"}'
```

纯配置 patch，不调用任何 `formula_package` 接口。对应公式包**不会**被 revoke——它可能还被同页其它面板
引用，撤销前无法确认安全，留给 TTL 自然到期即可。若某面板只剩这一条线，删掉这条线会连面板一起摘除。

### `set_window`

```bash
python scripts/chart_edit.py set_window '{
  "page_id": "page_xxx",
  "panel": "机器人产业链观察指数",
  "output_name": "机器人链观察指数",
  "start_date": "2022-01-01"
}'
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `page_id` / `panel` / `output_name` | ✅ | 同上 |
| `start_date` | 二选一 | `YYYYMMDD` 或 `YYYY-MM-DD` |
| `lookback_days` | 二选一 | 回溯天数，脚本换算成 `start_date` |
| `ttl_days` | ❌ | 仅扩窗重新注册时用 |

行为分两种，返回体 `mode` 字段标出实际走了哪种：

- `display_only`：目标窗口落在该 output 已注册范围内（按包记录的 `begin_date` 或
  `reads[].mode_params.lookback_days` 折算判断）→ 只在面板上写 `x_range.start_date`，图表渲染时按这个
  日期裁剪展示；**不调用 `formula_package.py register`**，不重新验证/计算任何公式。
- `reregistered`：目标窗口超出已注册范围 → 从包里取回这个 output 的原始公式（`formulas_known` 必须为
  true，否则报 `FORMULAS_UNKNOWN`），只重新注册这一个 output（新 `lookback_days`/`begin_date`），只替换
  这一个面板绑定的包；页面上其它系列/包不受影响。

### `query_data`

```bash
python scripts/chart_edit.py query_data '{"page_id":"page_xxx","output_name":"机器人链观察指数","result_mode":"summary"}'
```

页面本身不内嵌真实数据（只有 `package_id`+`signature`），这是显式取数的路径：从页面找到该 output 所属
的公式包凭证，转发给 `formula_package.py query`。`result_mode` 语义与 [formula_package.md](formula_package.md)
一致：`summary`（默认，首尾值/变化率/样本数）、`full`（完整序列）、`last_values`。同页多个包且无法从
`reads` 判断某 output 归属时，显式传 `package_id`（连同同一凭证的 `signature`）跳过自动匹配。

## 与 `formula_package.py` / `static_page.py` 的关系

`chart_edit.py` 不是它们的替代品，是薄封装：`add_series`/`set_window`（扩窗分支）内部调用
`formula_package.py` 的注册逻辑，所有子命令的页面写回都走 `static_page.py` 的下载/更新逻辑（因此继承同一
套 `page_id` 归属校验、HTML 体积上限、share shell 校验）。想直接操作公式包/页面本身，仍用那两个脚本；
只有"改一个已发布图表的一部分"这个场景才用 `chart_edit.py`。

## 错误码（节选）

| error | 场景 |
|---|---|
| `PANEL_NOT_FOUND` | `panel` 选择器（下标/title/output 名）在页面里找不到匹配 |
| `OUTPUT_NOT_ON_PANEL` | `remove_series` 指定的 `output_name` 不在该面板当前引用的产出里 |
| `LEGACY_PAGE` | 页面没有 `QBV_RENDER_JS_START/END` marker，本次改动之前生成，不支持定点编辑；若是 bespoke 手写页面，折线/柱状/双轴/雷达图这类图表可以用 `build_dashboard.py`（`emit=panel_block`）重建成局部嵌入的声明式图表块换取定点编辑能力，见 [guides/bespoke-page.md](../guides/bespoke-page.md) |
| `FORMULAS_UNKNOWN` | `set_window` 扩窗时，该 output 所属包在页面里没有留存公式文本 |

服务端透传错误（`FORBIDDEN`、`PAGE_NOT_FOUND` 等）与 `static_page.py`/`formula_package.py` 一致，不重复
定义。
