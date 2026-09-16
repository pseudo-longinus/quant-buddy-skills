# 已验证资源恢复与交付状态（0.6.76）

## 包级证明

`validate_package_set` 对 1..20 条单批及多批统一返回包级收据。合同规范化为 `{formulas, reads, begin_date}`，保留顺序，缺省 reads 为 `[]`，缺省日期为 20150101。读取输出必须存在，读取模式必须合法。QBS 原始批次收据只读保留；包级收据记录子文件路径与 SHA-256。

已有完整包级证明继续使用。缺少原始完整合同的旧单批证明不得猜补 reads 或日期、不得篡改原件；重新提供可核验的原合同和子证据，否则拒绝登记。旧公式数组仍可用，但其空 reads 不能证明带额外 reads 的包。

## bind_runtime_route

```json
{"task_id":"current-task","turn_id":"current-turn","plan_hash":"current-plan-hash"}
```

调用 `python scripts/static_page.py bind_runtime_route @params.json`。目标范围与运行角色默认读取当前执行计划，也可显式传入完全匹配的 `target_scope`、`runtime_roles`。角色必须引用当前任务已登记的 package/grant ID、验证收据及合同指纹。

工具检查任务/轮次、收据哈希、登记凭据有效性、完整合同及必需输出，然后返回 `route_receipt_file`。单资产、多资产、全市场均使用同一入口；市场不要求 asset。仅组合已有证据，不计算、不登记新包。

Compose 草稿的 `draft_ready=false` 表示已保存但不能构建。`COMPOSE_ROUTE_REQUIRED` 保持兼容，通过结构化 reasons 区分缺路由、收据集合、合同、身份和凭据错误；执行返回的 bind 下一步，不能原样重试 Compose。唯一匹配路由复用；歧义需明确选择。

## 快照与实时要求

快照入口将查询响应投影为业务输出，仅删除明确的传输字段 `outputs.*.data.signature`，保留日期和数值。未知秘密字段仍拒绝。生成快照不会改变 `require_live_data=true`，不能静默以快照交付实时任务。

## Host 只读状态导出

`python scripts/export_delivery.py --task-id TASK --turn-id TURN` 输出单个 JSON，包含白名单身份、status、page_id、result_url、progress_url、version_no、failure_stage 和 error_code。不会取 API key、联网或写状态。仅当前轮次、已发布版本及回复验收都通过时返回 succeeded；无证据或旧版兼容路径返回 unknown。stdout 不与 stderr 合并。

Host 应从受保护安装模板执行导出器，禁止执行用户工作目录中可改写的同名脚本。外部前端需要单独适配 delivery；执行 completed 不等于页面发布成功。

## 部署后单独恢复（本地修复不执行）

1. 确认 QBV/QBS/后端部署版本，验证模板中导出器及任务临时存储路径一致。
2. 核验原任务第二轮页面和原公式包有效性、原合同/子收据，不创建替代资产或重复计算。
3. 在同一页面、当前有效 task/turn 和计划下绑定匹配路由；过期凭据按受控更新流程处理，不能伪造通过。
4. 构建候选并预检、发布、检查公开页实际取数/版本、执行回复验收。
5. 核验 delivery 成品字段；线上日期按实际交易日检查，股票数量不要求永久为历史 12 只。
