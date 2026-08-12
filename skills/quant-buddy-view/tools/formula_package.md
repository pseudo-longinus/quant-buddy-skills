# formula_package — 公式任务包（注册一组公式 → 凭包凭证取数）

> 把一组公式注册成「任务包」，得到 `package_id` + `signature`；之后**无需 API Key**，凭这两个凭证就能反复取数。底层数据更新后服务端自动重算，取数永远拿最新结果。
> 看板（`build_dashboard`）正是消费这里产出的 `package_id` + `signature`。
>
> ⚠️ 本工具通过本地脚本 `scripts/formula_package.py` 调用公式包专用 REST 端点（`/skill/registerFormulaPackage` 等）。

## 端点

| 操作 | 方法 + 路径 | 认证 |
|------|-------------|------|
| 注册 | `POST /skill/registerFormulaPackage` | `Authorization: Bearer <api_key>` |
| 取数 | `POST /skill/queryFormulaPackage` | `package_id`+`signature` 必需；API Key 可选（CLI 有 Key 时附带用于审计归因） |
| 列表 | `GET /skill/listFormulaPackages?page=&page_size=` | Bearer |
| 撤销 | `POST /skill/revokeFormulaPackage` | Bearer |
| 刷新 | `POST /skill/refreshFormulaPackage` | Bearer |

> `endpoint` / `api_key` 读 `config.json`。`signature` 仅在**注册响应中明文返回一次**，服务端不可再取出；脚本会自动落盘到 `output/formula_packages/<package_id>.json` 以防丢失。

## 调用方式（中文公式务必用 @file 或 FP_PARAMS，规避 PowerShell GBK 截断）

```bash
# 注册（凭 config.json 的 api_key 认身份，无需会话）
python scripts/formula_package.py register @params.json

# 2. 取数（只需 package_id，signature 可由本地凭证自动补全）
FP_PARAMS='{"package_id":"pkg_xxx"}' python scripts/formula_package.py query

# direct：只请求所需输出并返回紧凑统计，不打印原始时间数组
FP_PARAMS='{"task_id":"task_xxx","package_id":"pkg_xxx","outputs":["bubble"],"result_mode":"summary"}' python scripts/formula_package.py query

# 管理
python scripts/formula_package.py list   '{"page":1,"page_size":20}'
python scripts/formula_package.py revoke '{"package_id":"pkg_xxx"}'
# 刷新：默认不动签名（rotate_signature 省略即 false）。绝大多数情况根本不需要 refresh——
# 页面是 live 实时取数、底层数据更新后 query 会自动重算，见下方 ⚠️。
python scripts/formula_package.py refresh '{"package_id":"pkg_xxx"}'
```

> ⚠️ **`rotate_signature:true` 是破坏性操作，默认不要用。**
> - 轮换会**立刻作废所有已发布、内嵌该包旧签名的页面**（页面取数报 `SIGNATURE_INVALID`）。新签名只在本次响应里**明文返回一次**、服务端只存哈希，**丢了不可恢复**。
> - 如果确实要轮换（仅当需要主动换令牌、吊销已泄露的旧签名时），必须**紧接着**对每一个内嵌该包的页面重建 HTML + `static_page update` 覆盖，把新签名同步进去——这是一步不能漏的善后，不是可选项。
> - **只有在本地存在该包凭证 `output/formula_packages/<package_id>.json` 时**，脚本才会把新签名回写本地供 `build_dashboard` 重建使用；换会话 / 换机器、凭证不在本地时轮换，新明文签名会丢失、页面无法补救。此类情况**不要轮换**。
> - 「数据想更新」不需要 refresh，更不需要轮换：页面 live 取数自动拿最新值。refresh 仅在极少数需要强制重算 data_id 时用，且应 `rotate_signature:false`。

### 从旧 quant-buddy-skill 迁移凭证（升级到 view 后一次性）

公式包能力已从 `quant-buddy-skill` 迁到本 skill。**已注册的包无需重注册**——`signature` 仅注册时明文返回一次，旧凭证落盘在 `quant-buddy-skill/output/formula_packages/*.json`，把它们导入本 skill 即可继续用旧 `package_id` 取数：

```bash
# 显式指定源目录（推荐）
python scripts/formula_package.py import '{"from":"D:/.../quant-buddy-skill/output/formula_packages"}'

# 或设环境变量；或留空走「同级 quant-buddy-skill」兜底猜测
QBS_IMPORT_CRED_DIR='D:/.../quant-buddy-skill/output/formula_packages' \
    python scripts/formula_package.py import
```

`import` 纯本地操作（不需 api_key / task_id / 网络），默认不覆盖已存在凭证（传 `{"overwrite":true}` 才覆盖），返回导入 / 跳过 / 无效的明细。

## 注册参数

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `formulas` | `string[]` | ✅ | 1~100 条公式（可含中间变量），每条形如 `变量名 = 表达式`。语法同 quant-buddy-skill 的 `runMultiFormulaBatchStream`（引用数据/变量用双引号，资产名不加引号）|
| `reads` | `object[]` | ✅ | 1~20 个**对外产出**及其读取模式，见下 |
| `begin_date` | `number` | ❌ | 公式计算起始日（裸整数 `YYYYMMDD`） |
| `ttl_days` | `number` | ❌ | 有效期（天），默认 365 |
| `intents` | `string[]` | ❌ | 可选意图描述 |

### `reads[]` 元素

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `output` | `string` | ✅ | 产出标识 = 某条公式左侧变量名 |
| `read_mode` | `string` | ✅ | 读取模式，见下表 |
| `mode_params` | `object` | ❌ | 模式参数；`range_data` 必填 `lookback_days`（滚动窗口回溯天数，正整数）|

> 未列入 `reads` 的公式 = 中间变量，只算不对外。每个 `output` 只能一个 `read_mode`。

### 读取模式与取数返回的 `data` 结构（build_dashboard 据此渲染）

| read_mode | 适用 | `mode_params` | `data` 关键结构 | 建议 panel.type |
|-----------|------|---------------|----------------|----------------|
| `last_day_stats` | 2维截面 / 1维序列 | — | 2维：`last_day_stats.{date,top_values[],valid_count,...}`；1维：`last_value.{date,value}` | 2维→`table`；1维→`number` |
| `last_valid_per_asset` | 2维截面 | `max_rows`(默认8000) | `last_valid_per_asset[]`（每资产末值） | `table` |
| `range_data`（滚动窗口）| 1维序列 / 2维 | `lookback_days`✅（回溯天数，区间=`[今天-N, 今天]`）、`assets`、`max_cells`、`nan_handling`(`keep`/`fill_forward`/`drop_rows`) | `range_data.{dates[],values[],series_name,valid_count,null_count,zero_count,first_valid_date,last_valid_date}` | `line` |

> **`range_data` 是滚动窗口**：注册只给 `lookback_days`（近一年=365、近半年=180、近一季=90），取数时服务端现算成 `[今天-N, 今天]`。看板是 live 数据源，这样折线才会随时间滚动到最近，而不是停在注册当天。旧版 `start_date`+`end_date` 仍兼容（按跨度滚到今天），但别再指定绝对 `end_date`。
> `build_dashboard` 的渲染器会自动解包上述外层 key 并归一为图/表，多数情况下 panel 只需写 `output` + `type` 即可。
> `range_data` 取数返回里**附带数据质量元信息**（服务端实算，无需自己遍历 `values`）：`valid_count`（有效点数）、`null_count`（空/NaN 点数）、`zero_count`（值为 0 的点数）、`first_valid_date` / `last_valid_date`（首/末个有效值的日期）。可据此判断序列是否近期断更（`last_valid_date` 落后于今天）、是否大面积空值，再决定要不要换 `lookback_days` 或提示用户。
> `read_mode=last_value` 会被本地 preflight 阻断；单值请用 `last_day_stats`，其返回 data 内部仍可能是 `last_value.{date,value}`。

## 注册前本地 preflight

`scripts/formula_package.py register` 在读取 API key / 请求服务端前会先做本地预检，成功和失败响应都会带 `_preflight`：

- `formulas` 必须是非空字符串数组，每条必须是完整左值赋值公式。
- 支持多输出左值，如 `NAV, HOLD = 回测(...)`。
- 左值不能重复。
- `reads` 必须非空，且 `reads[].output` 必须命中公式左值。
- `read_mode` 只允许 `last_day_stats`、`last_valid_per_asset`、`range_data`。
- `read_mode=last_value` 会阻断，并提示改用 `last_day_stats`。

## 取数（SSE）

`scripts/formula_package.py query` 已封装 SSE 解析，并支持：

- `outputs: string[]`：只请求需要的产出；
- `result_mode=full`：完整原始结果；
- `result_mode=summary`：每个序列只返回最新值/日期、首值/日期、变化率、有效样本数；
- `result_mode=last_values`：只保留最新值与最新日期。

direct 流程必须显式使用 `summary`，避免在日志和回复上下文中打印完整时间数组。生成的 live 看板和 `build_dashboard` 内部仍调用完整模式做渲染与质量体检。

> **`code` 现在反映成败**：服务端 `done.code≠0`（部分产出失败）或任一产出带 `error` 时，封装返回 `code:1` 并附 `failures:[{output,error}]`；某产出失败时其 `outputs[output].error` 有值、`data` 为 null。**消费方应判 `code` 与逐产出 `error`，不要只看流是否正常结束。**（旧版本无论成败都返回 `code:0`，已修正。）

## 错误码（节选）

| code | 场景 |
|------|------|
| `REGISTER_FAILED` | 参数非法 / 公式执行失败 / 产出未生成 |
| `PARAMS_REQUIRED` | 取数缺 `package_id` 或 `signature` |
| `PACKAGE_NOT_FOUND` / `PACKAGE_EXPIRED` / `PACKAGE_INACTIVE` | 包不存在 / 过期 / 已撤销 |
| `SIGNATURE_INVALID` | 签名校验失败 |
| `OWNER_QUOTA_EXCEEDED` | 所有者配额耗尽 |

## 计费

注册按公式条数计费；取数计基础读取费，触发重算时按实际重算条数追加。**取数费用计入任务包所有者配额**，取数方不消耗自己配额、也无需 API Key。

> 端到端示例：[workflows/dashboard-end-to-end.md](../workflows/dashboard-end-to-end.md)。
