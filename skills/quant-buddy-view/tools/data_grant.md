# data_grant — 数据授权（把一次直取数请求钉死成签名凭证 → 页面免 key 取数）

> 脚本 `scripts/data_grant.py` 已可用；`build_dashboard` 与 `assets/data-kernel.js` 已支持 grant 面板。服务端设计见 `skill_server/docs/dataGrant相关文档/数据授权-技术设计文档.md`（v0.2）。

> 把一次 `fastQuery` / `fastQueryMinute` / `stockProfile` / `selectByComposition` 请求在注册时**钉死**，得到 `grant_id` + `signature`；之后**无需 API Key**，页面凭这两个凭证就能反复取数。底层数据更新后，取数永远拿最新结果（钉死的是"查什么"，不是"某天的值"）。
>
> 与公式任务包（`formula_package`）的关系：**同一套签名免 key 心智**。公式包钉死的是"一组公式 + 读取模式"；数据授权钉死的是"一次平台直取数请求"。**算出来的指标用公式包；平台白名单直取的行情/估值/画像/维度分 TopN 用数据授权**（取舍见 SKILL.md「数据授权 vs 公式包」）。

## 四种 kind

| kind | 底层接口 | 钉死内容 | 页面拿到 |
|------|---------|---------|---------|
| `fast_query` | fastQuery | 一次快查请求（assets/query_type/fields…），字段须命中平台白名单 | 值 / 序列 |
| `fast_query_minute` | fastQueryMinute | `{ asset, fields }`，单资产，字段限 OHLCVA；无历史/区间参数 | 共享 `dates` + 列式 `fields` 分钟数据 |
| `stock_profile` | stockProfile | `{ asset, dimensions }` | 个股画像卡 |
| `composition_select` | selectByComposition | 一次按权重选股/筛选请求（mode/universe/composition/screens/top_n…），indicator_id 须为已上线维度分 | TopN 榜单表 |

## 端点（对齐公式包）

| 操作 | 方法 + 路径 | 认证 |
|------|-------------|------|
| 注册 | `POST /skill/registerDataGrant` | `Authorization: Bearer <api_key>` |
| 取数 | `POST /skill/queryDataGrant` | `grant_id`+`signature` 必需；API Key 可选（CLI 有 Key 时附带用于审计归因，普通 JSON） |
| 列表 | `GET /skill/listDataGrants?page=&page_size=` | Bearer |
| 撤销 | `POST /skill/revokeDataGrant` | Bearer |
| 刷新 | `POST /skill/refreshDataGrant` | Bearer |

> `endpoint` / `api_key` 读 `config.json`（与 `formula_package.py` / `static_page.py` 共用同一 endpoint）。`signature` 仅在**注册响应中明文返回一次**，服务端不可再取出；脚本会自动落盘到 `output/data_grants/<grant_id>.json` 以防丢失（与公式包凭证同款）。

## 调用方式（与 formula_package.py 同款 CLI）

```bash
# 注册（凭 config.json 的 api_key 认身份，无需会话）
python scripts/data_grant.py register @params.json

# 取数（只需 grant_id，signature 可由本地凭证自动补全）
DG_PARAMS='{"grant_id":"dg_xxx"}' python scripts/data_grant.py query

# 管理
python scripts/data_grant.py list   '{"page":1,"page_size":20}'
python scripts/data_grant.py revoke  '{"grant_id":"dg_xxx"}'
python scripts/data_grant.py refresh '{"grant_id":"dg_xxx","rotate_signature":true}'
```

## 注册参数

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `kind` | `string` | ✅ | `fast_query` / `fast_query_minute` / `stock_profile` / `composition_select` |
| `payload` | `object` | ✅ | 冻结的完整请求体，形状随 kind（见下） |
| `ttl_days` | `number` | ❌ | 有效期（天），默认 365 |
| `task_id` / `user_query` | `string` | ❌ | 随 audit 落库 |

### payload 按 kind

```jsonc
// fast_query —— 字段必须命中平台白名单（否则注册拒 FIELD_NOT_WHITELISTED）
{ "assets": ["600519.SH"], "query_type": "snapshot", "fields": ["收盘价","涨跌幅"] }

// fast_query_minute —— 单资产、当前盘中或最近完整交易日；字段会规范为 open/high/low/close/volume/amount
{ "asset": "600519.SH", "fields": ["收盘价", "最高价", "成交量"] }

// stock_profile
{ "asset": "600519.SH", "dimensions": ["估值","财务质量"] }

// composition_select —— indicator_id 必须是已上线维度分（否则注册拒 INDICATOR_NOT_FOUND）
{ "mode": "score", "universe": { "asset_scope": "A股" },
  "composition": [{ "indicator_id": "ind_a_share_momentum_reversal", "weight": 1 }],
  "top_n": 10, "with_breakdown": true }
```

## 注册响应

```jsonc
{ "code": 0, "grant_id": "dg_xxx", "signature": "<明文仅此一次>", "kind": "fast_query",
  "whitelist_fields": ["收盘价","涨跌幅"], "whitelist_indicators": [], "expires_at": "2027-06-17T..." }
```

## 取数返回（与在线接口同构，build_dashboard/data-kernel 据此渲染）

- `fast_query`：与在线 fastQuery 同构的值/序列结构。
- `fast_query_minute`：`data.dates` 为共享分钟时间轴，`data.fields.<field>` 为同索引值数组；自定义活页直接按该列式结构渲染。
- `stock_profile`：与在线 stockProfile 同构的画像卡结构。
- `composition_select`：TopN 表（排名/名称/代码/score）+ `composition_used` + `last_date`。

外层统一带 `grant_id`；失败返回 `code:1` 并附错误。

当 FastQuery 数据点超过服务端阈值时，`queryDataGrant` 会返回 `mode:"csv"` 和当次生成的
`csv_fields[].csv_url`。页面仍先调用 `queryDataGrant`，随后由内联 `data-kernel` 下载 CSV 并
hydrate 为 `results[].fields[].series`；刷新时重新请求 Grant 获取新 URL，不缓存或持久化
presigned URL。生产环境优先返回 `https://pages.quantbuddy.cn/exports/...`，与活页同源，
无需 OSS CORS。页面下载仍固定 `credentials:"omit"`、`cache:"no-store"`，访问能力完全由
presigned URL 控制；如果兼容期仍返回 OSS 跨域地址，则 Bucket 必须额外允许无 Cookie 的
`GET/HEAD` CORS。

旧页升级只替换内核，不改页面业务脚本：

```bash
DKR_PARAMS='{"html_file":"old.html","out_file":"old-new.html"}' python scripts/data_kernel_retrofit.py
# 也可用公开 url 读取，但 url 模式必须显式给 out_file
```

工具优先匹配新 `QB_DATA_KERNEL_START/END` marker；没有 marker 时只接受唯一一个同时包含
`const QB`、`queryGrant`、公开 API 返回表和 `SKILL_VERSION` 的旧脚本块。

## 硬门槛与约束

- **先验证再注册**：注册任何 grant 前，必须先在 **quant-buddy-skill** 用 api-key 跑通对应接口（fastQuery / stockProfile / selectByComposition），确认命中/出数，再回本技能注册。不要凭空注册未验证的请求。
- **免 key 执行强制 `access_dunhe=false`**：数据授权页面绝不返回付费/敦和数据；只放行平台白名单字段与已上线维度分。
- **不让页面改参数**（本期）：grant 是钉死式，页面只能原样重放；交互式选股/选字段是二期作用域子集模式。
- **signature 是凭证**：不要打印到面向最终用户的对话里；它会写进公开页面 HTML 供实时取数，发布前确认可接受。丢失即不可恢复，可 `refresh` 轮换。

## 错误码（节选）

| code | 场景 |
|------|------|
| `FIELD_NOT_WHITELISTED` | fast_query 字段未命中平台白名单 |
| `INDICATOR_NOT_FOUND` | composition_select 的 indicator_id 未在服务端可用指标库命中 |
| `INVALID_PAYLOAD` | payload 形状/参数非法 |
| `PARAMS_REQUIRED` | 取数缺 `grant_id` 或 `signature` |
| `GRANT_NOT_FOUND` / `GRANT_EXPIRED` / `GRANT_INACTIVE` | grant 不存在 / 过期 / 已撤销 |
| `SIGNATURE_INVALID` | 签名校验失败 |
| `OWNER_QUOTA_EXCEEDED` / `RATE_LIMITED` | 所有者配额耗尽 / 触发限流 |

## 计费

注册计 `register_data_grant`；取数计 `QUERY_RU`，**费用计入 grant 所有者配额**，取数方不消耗自己配额、也无需 API Key。
