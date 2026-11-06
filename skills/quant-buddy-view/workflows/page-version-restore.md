# 聊天恢复历史版本

用户明确说“回退 V1 / 恢复 V1”即进入版本操作，不重新计算、不近似重建、不走研究失败降级。继续当前宿主 task/turn，目标是上下文中的原 page_id；不新建替代页。

本轮恢复意图也约束普通建页、Compose、计划修订和发布入口；误用这些入口返回 `ROLLBACK_WORKFLOW_REQUIRED` 并转向 `versions`。即使模型继续旧研究，普通发布收据也不能作为本轮恢复成功的证据；缺少恢复收据时不触发研究收尾，不复用旧研究答复。

1. `versions` 读取当前版本与历史列表，保存 `current_version_id`。`V1` 是编号 1，不是列表顺序或用户消息的第一轮。
   原始问题明确 V1 时，即使 V1 是占位页也不能自行改选 V2；自动默认选项不算用户修改目标。可以说明目标内容或等待用户新消息，不能替换目标后宣称完成。`rollback` 会在写入和复用已确认 journal 前核对原始目标，不一致返回 `ROLLBACK_TARGET_CONFLICT`。
2. `version` 传 `page_id` 和 `version:"V1"`，查看目标元信息及预检；加 `task_id, download:true` 将历史正文校验 hash 后下载到本轮私有目录，按返回的 `html_file` 核对内容。签名预览地址不进入工具输出。检查权限、对象和运行凭证；目标不存在、凭证撤销或权限不足时说明具体阻断，不 force、不重新注册来改变历史绑定。
3. `rollback` 沿用同一 task/turn，传目标版本及步骤 1 的 `expected_current_version_id`。默认恢复正文、运行绑定及页面元信息，保留当前标签。可指定稳定 `operation_id`；省略时按 task/turn/page/target/base 生成。同轮重复执行复用 journal，不产生第二次写入。
4. 超时或响应不确定时先读历史，只有 task、目标来源、base+1 版本序号及 hash 一致才认领结果。查不到不能证明没写入；返回 `ROLLBACK_OUTCOME_UNKNOWN`，不自动重发。换 operation_id 不能绕过保护。
5. 写入成功后比对历史目标的 hash、运行绑定和元信息，核对恢复来源，在原公开 URL 执行桌面、390px、320px 浏览器验收，核对文档 hash；最后重读当前版本，防止验收期间又发生更新。
6. 仅 `written:true, verified:true` 才报告成功，并说明“原链接恢复为 V1 内容，新增历史版本 Vn”。已写入未验收须分别说明。导出器按本轮恢复收据返回 `operation:rollback`，不继承旧研究计划的完整性标签，也不触发宿主方法页收尾。
   发布收据同时记录 `restored_version_id`、`restored_version_no`，区分目标旧版本与新增恢复版本；宿主必须核对原始请求与恢复来源，缺少来源证据不能确认成功。

示例 `rollback.json`（版本 ID 来自本次只读查询）：

```json
{
  "task_id": "task_current",
  "turn_id": "turn_current",
  "page_id": "page_owned",
  "version": "V1",
  "expected_current_version_id": "spv_current",
  "change_note": "按用户要求恢复 V1"
}
```

预览 URL 是短时私有签名，只用于核验。最终交付仍用原公开链接；不得把签名或历史正文凭证复制进回复、日志或交接文档。
