# formula_package — 公式任务包（注册一组公式 → 凭包凭证取数）

> 把一组公式注册成一个「任务包」，得到 `package_id` + `signature`；之后**无需 API Key**，
> 凭这两个凭证就能反复取数。底层数据更新后服务端自动重算，取数永远拿最新结果。
> 适合给**前端页面 / 第三方**做只读数据接入（如本地 HTML 直接渲染）。
>
> ⚠️ 本工具**不是**平台原生 MCP 工具，通过本地脚本 `scripts/formula_package.py` 调用，
> 走的是公式包专用 REST 端点（`/skill/registerFormulaPackage` 等），与 `runMultiFormulaBatchStream`
> 的执行/计费池**不同**。何时用它 vs 用 `runMultiFormulaBatchStream` 见文末「选型」。

## 端点

| 操作 | 方法 + 路径 | 认证 |
|------|-------------|------|
| 注册 | `POST /skill/registerFormulaPackage` | `Authorization: Bearer <api_key>` |
| 取数 | `POST /skill/queryFormulaPackage` | **无需**，凭 `package_id`+`signature`（SSE 流式） |
| 列表 | `GET /skill/listFormulaPackages?page=&page_size=` | Bearer |
| 撤销 | `POST /skill/revokeFormulaPackage` | Bearer |
| 刷新 | `POST /skill/refreshFormulaPackage` | Bearer |

> `endpoint` / `api_key` 读 `config.json`（与其它工具同源）。`signature` 仅在**注册响应中明文返回一次**，
> 服务端不可再取出；脚本会自动落盘到 `output/formula_packages/<package_id>.json` 以防丢失。

## 调用方式（本地脚本，参数传递与 call.py 同款，避免 PowerShell GBK 截断）

```bash
# 注册（Windows 用 @file 传中文公式）
python scripts/formula_package.py register @params.json

# 取数（只需 package_id，signature 可由本地凭证自动补全）
FP_PARAMS='{"package_id":"pkg_xxx"}' python scripts/formula_package.py query

# 管理
python scripts/formula_package.py list   '{"page":1,"page_size":20}'
python scripts/formula_package.py revoke '{"package_id":"pkg_xxx"}'
python scripts/formula_package.py refresh '{"package_id":"pkg_xxx","rotate_signature":true}'
```

## 注册参数

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `formulas` | `string[]` | ✅ | 1~100 条公式（可含中间变量），每条形如 `变量名 = 表达式`。语法同 `runMultiFormulaBatchStream`（引用数据/变量用双引号，资产名不加引号）|
| `reads` | `object[]` | ✅ | 1~20 个**对外产出**及其读取模式，见下 |
| `begin_date` | `number` | ❌ | 公式计算起始日（裸整数 `YYYYMMDD`） |
| `ttl_days` | `number` | ❌ | 有效期（天），默认 365 |
| `intents` | `string[]` | ❌ | 可选意图描述，透传给执行引擎 |

### `reads[]` 元素

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `output` | `string` | ✅ | 产出标识 = 某条公式左侧变量名（如 `AG_ret = ...` 的 `AG_ret`）|
| `read_mode` | `string` | ✅ | 该产出读取模式，见下表 |
| `mode_params` | `object` | ❌ | 模式参数；`range_data` 必填 `start_date`、`end_date` |

> - 未列入 `reads` 的公式 = 中间变量，只计算不对外。
> - **每个 `output` 只能指定一个 `read_mode`**；同一产出写两条会导致注册失败。
> - 不同产出可用不同模式与参数。

### 读取模式与 `result.data` 结构

| read_mode | 适用 | `mode_params` | 取数返回的 `data` 关键字段 |
|-----------|------|---------------|---------------------------|
| `last_day_stats` | 截面（2维）/ 单序列（1维）皆可 | — | 2维：`last_day_stats.{date,top_values[],valid_count,coverage_rate,...}`；**1维序列：`last_value.{date,value}`** |
| `last_valid_per_asset` | 2维截面 | `max_rows`（默认8000） | 每个资产最后一个有效值（跨市场对齐） |
| `range_data` | 1维序列 / 2维 | `start_date`✅、`end_date`✅、`assets`、`max_cells`、`nan_handling`(`keep`/`fill_forward`/`drop_rows`) | `range_data.{dates[],values[],series_name}`（非交易日为 `null`）|

## 取数（SSE）

`POST /skill/queryFormulaPackage`，body 仅 `{package_id, signature}`，永远返回 `text/event-stream`：

| event | 含义 |
|-------|------|
| `result` | 单个产出数据（每产出一条）：`{output, read_mode, data_id, data}` |
| `progress` | 重算进度（仅数据陈旧时出现） |
| `done` | 全部完成：`{code,stale,recomputed,summary}` |
| `error` | 出错并关闭流：`{code,message}` |

`scripts/formula_package.py query` 已封装 SSE 解析，返回组装好的
`{code, outputs:{<output>:{read_mode,data_id,data}}, progress, done}`。

**浏览器直连**（取数无需 api_key、已支持跨域，用 `fetch` 读流，**勿用 `EventSource`**）：
见 `recipes/formula-package.md` 的 HTML 示例与对外接口文档 §3。

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

## 选型：何时用公式包 vs `runMultiFormulaBatchStream`

| 用公式包（本工具） | 用 `runMultiFormulaBatchStream` |
|--------------------|-------------------------------|
| 要把一组结果做成**长期、可重复、对外只读**的取数接口（前端页面、看板、第三方接入）| 一次性问答 / 即时计算，会话内拿到 `data_id` 即用 `readData` |
| 取数方**不该持有 api_key**（如浏览器本地 HTML 直连）| 调用方在本 skill 内、已有 session 与 api_key |
| 需要「数据更新→自动重算→永远最新」的语义 | 手动重跑公式即可 |

> 详见对外接口文档：`docs/formulaPackage 相关文档/对外接口文档.md`；端到端示例：`recipes/formula-package.md`。
