# 受限回复合同纠错

仅维护误配合同：原始问题明确为股票筛选、原合同由发布元数据自动推断为 `single_stock_deep_dive_v1`，且没有单股证据绑定。普通单股缺证据继续补证，不使用本入口。

先在当前任务/轮次的 Trace 上下文运行：

```bash
python scripts/static_page.py repair_reply_contract @repair-params.json
```

参数仅接受：

```json
{
  "task_id": "task_xxx",
  "turn_id": "turn_xxx",
  "page_id": "page_xxx",
  "expected_contract_sha256": "调用方记录的64位旧合同SHA256",
  "execute": false
}
```

默认预览；核对结果后显式 `execute:true` 才更新任务侧绑定。不能传模板、正文或任意路径。需具备可读的当前任务计划、原始问题、自动推断来源、封存合同、已确认写入及公开验收记录。工具只读回页面元信息，确认 page_id、版本和 HTML hash 与原回执相同；缺证、跨轮、显式/继承模板、过期合同、页面变化或已完成任务均阻断并返回具体错误。

执行在任务锁内生成新合同，保留原合同，切换 `reply-validate.json` 与交付状态中的合同hash。`receipts/reply-contract-repairs/<旧hash>/` 保存旧合同、校验参数、状态备份和原因审计；原页面、Grant、版本及聊天正文不变。执行本身不代表回复完成：按返回 `next_action` 读取新合同、填写真实业务答复，运行现有 `validate_agent_reply.py @参数文件`，只有 `valid:true` 才完成任务。筛选答复应说明范围、条件、候选名单、日期与限制。

重复执行同一成功纠错返回 `reused:true`，仍核验当前页面版本。文件写失败回滚状态和指针；若进程被强制终止而审计停在 `prepared`，返回 `REPLY_REPAIR_INTERRUPTED` 并保留备份，维护人员核对后处理，不自动重试覆盖。锁只协调共享任务目录的本地执行者，不宣称服务端跨接口事务。

自动推断普通“筛选”及“在股票池中找出类似股票”优先使用已有 `generic_live_page_delivery_v1`；显式模板及来源模板继承优先级不变。缺少单股证据不会触发自动换合同。本次上线不批量修复历史任务，历史正文和正式任务状态恢复另行安排。
