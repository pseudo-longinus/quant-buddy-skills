# publish_workflow — Manifest 驱动的 fork 发布器

新 fork 默认使用 `publish_workflow_v2`。`fork_prepare` 已生成完整 plan，Agent 不再手写 packages、grants、Marker 或完整 workflow JSON。

## 新 fork 调用

先创建目标页，再把目标 `page_id` 作为 `target_page_id` 传给 `fork_prepare`：

```powershell
python scripts/static_page.py fork_prepare '@D:\temp\fork-prepare.json'
```

命令生成：

- `*.fork.html`：脱敏工作 HTML；
- `*.fork-manifest-v2.json`：私有运行合同与 Marker 绑定；
- `*.fork-review.json`：Agent 审查接口；
- `*.publish-plan.json`：发布参数骨架。

Agent只编辑 `*.fork.html` 和 `*.fork-review.json`。审查文件只填写主资产确认、目标同业槽位、复杂跨资产公式和允许的 Grant 资产范围，不添加来源 ID/signature、Marker、reads 或完整 Grant payload。

直接执行返回的 `publish_command`：

```powershell
python scripts/publish_workflow.py '@D:\path\page.publish-plan.json'
```

> **`publish-plan.json` 按设计不含凭证（credential-free）**：这个文件里没有 `api_key`。如果这次任务的
> `page_id` 是用调用方自带的 api_key（比如 Playground 场景，而不是 `config.json` 里的默认 key）建的，
> 必须让 `publish_command` 这次调用也拿到同一个 key，否则 `publish_workflow.py` 会退回 `config.json`
> 的默认身份注册/发布，服务端会报 `无权操作他人的页面`。**不要**为此设置 `QUANT_BUDDY_API_KEY` 环境
> 变量——它只在 `config.json` 也为空时才生效，`config.json` 已有默认 key 时设它不会有任何效果（这是
> 已经复现过两次的真实故障模式）。正确做法二选一：
> 1. 设置环境变量 `QBV_API_KEY=<本次 key>` 后再执行 `publish_command`（推荐，不用改 plan 文件）；
> 2. 或者把 `api_key` 合并进这次调用的顶层参数（如果不是走 `@file`，直接在 JSON 里加一个
>    `"api_key"` 字段）。
> 两种方式效果一致：`scripts/common.py::configure_trace_context()` 全程保留这个覆盖，
> `publish_workflow.py` 内部多次切换 task_id 上下文也不会把它冲掉。

`fork_manifest_v2` 存在时，手工传入 `packages`、`grants` 或 runtime markers 会返回：

```text
MANUAL_RUNTIME_BINDINGS_FORBIDDEN
```

## 固定执行顺序

所有下列结构检查均发生在第一次网络写入之前：

1. 读取 manifest、review 和脱敏 HTML；检查 review 完整性。
2. 检查来源凭证残留、runtime role、Marker 数量与全局唯一性。
3. 从同一 package 合同检查公式左值、reads、required outputs 和 `begin_date`。
4. 检查水位语义：PE/PB 水位输出必须使用带明确正整数窗口的 `排序水位` 或 `数值水位` 公式；fork 可继承来源模板已经声明且能通过 QBS 的窗口口径，不强制改成固定250日。
5. 检查 Grant 仅修改声明的资产范围；`kind/query_type/fields/dimensions/window_days/result_mode` 及 CSV/inline 合同默认继承。改变非资产合同必须填写 `contract_change_reason`。
6. 以假凭证执行 Card Runtime `structure-only` 预检。图片空 `src` 规则保持现状。
7. 用 canonical package 合同调用 `validate_package_set`；用 canonical `kind + payload` 调用 `validate_grant_set`。 严格数据回复模板会在此阶段复用公式验证返回的 `data_id`，按相同 `read_mode/mode_params` 每批最多10个调用 `readData`；Grant直接压缩验证响应。单批失败只记录 warning，不重算公式、不重查 package/grant。
8. 每个 runtime role 只注册一次，并把一个注册结果扇出到页面/Card的全部 Marker。
9. 上传 manifest 声明的图片，写 prepared HTML，单次调用 `publish_verified`。

Manifest 中 package 明确保留两层合同：`source_contract.formulas/nodes` 是模板详情接口原始结构，`target_registration_contract.formulas/reads/begin_date` 是新公式包的请求结构。发布器只从后者派生验证与注册；来源 `nodes[].data_id` 不得进入目标请求。`fork-review.json` 仍只投影公式语义与只读输出摘要。

最终验证/注册使用的 Package合同只有一个：

```json
{"formulas": [], "reads": [], "begin_date": 20150101}
```

验证请求取其中的 `formulas + begin_date`，注册请求使用同一完整合同。Grant只有一个 `kind + payload` 合同；验证收据与注册前都检查同一 SHA256 fingerprint。

`validate_grant_set` 映射：

| Grant kind | quant-buddy-skill 工具 |
|---|---|
| `fast_query` | `fast_query` |
| `stock_profile` | `stockProfile` |
| `composition_select` | `selectByComposition` |

## 图片

`images[]` 仍由 `fork_prepare` 从来源托管图片生成。发布器在网络调用前检查本地文件、类型、大小和 Marker；Card Runtime 结构预检时临时替换为 data URI。发布到目标 `page_id` 后再写入同页 WebP URL。本次升级没有放宽或新增图片门禁。

## 输出与耗时

CLI stdout只返回阶段摘要、package/grant/image 数量、耗时和完整报告路径。完整逐角色结果写入 `output/publish_reports/`。

耗时至少包含：

- `manifest_preflight_ms`
- `package_validation_ms`
- `grant_validation_ms`
- `reply_evidence_ms`（含公式结果补读与本地投影/落盘）
- `package_registration_ms`
- `grant_registration_ms`
- `image_upload_ms`
- `browser_validation_ms`
- `publish_ms`
- `public_smoke_ms`

任一预检失败时，QBS、注册、图片上传和发布均不会被调用。注册失败后的幂等/checkpoint不属于本版本。

## v1兼容

已准备的 `fork_manifest_v1` 和旧式 workflow JSON继续走原分支；新 `fork_prepare` 只生成 v2。不要把 v1任务人工改写成半套 v2。
