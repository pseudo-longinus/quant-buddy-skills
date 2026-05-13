# resumeJob — 续传查询 deferred 后台任务

> 用于在 `runMultiFormulaBatchStream` 返回 `status:"deferred"` 后，重新连接 SSE 流查看任务进度并获取最终结果。

## 使用场景

当 `runMultiFormulaBatchStream` 以 `execution_profile:"research_24h"` 提交任务，或服务端自动将任务升级为后台队列模式时，会立即返回：

```json
{
  "status": "deferred",
  "task_id": "...",
  "trace_id": "...",
  "job_id": "...",
  "message": "研究任务已进入后台队列，可稍后恢复查看进度"
}
```

此时调用 `resumeJob` 即可续传，等待并获取完整结果（与 `runMultiFormulaBatchStream` 同步模式返回结构完全一致）。

## 调用方式

```bash
GZQ_PARAMS='{"task_id":"<task_id>","trace_id":"<trace_id>"}' python scripts/call.py resumeJob
```

## 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `task_id` | string | ✅ | 来自 deferred 响应的 `task_id` |
| `trace_id` | string | ✅ | 来自 deferred 响应的 `trace_id` |
| `since` | string | ❌ | 上次断连时的 `last_event_id`（默认 `"0"`，从头重放） |

## 返回结构

任务完成时返回与 `runMultiFormulaBatchStream` 同步模式完全一致的结构：

```json
{
  "status": "ok",
  "summary": { "total": N, "success": N, "failed": 0, "skipped": 0 },
  "results": [ ... ]
}
```

任务仍在队列中（未完成）时会阻塞等待，直到收到 `done` 事件或超时（最长 30 分钟）。

## 错误情况

| 情况 | 返回 |
|------|------|
| 缺少 `task_id` 或 `trace_id` | `code:-1, error.code:"MISSING_PARAMS"` |
| SSE 流中断且 3 次重连均失败 | `code:-1, error.code:"STREAM_INTERRUPTED"`，`partial.last_event_id` 可用于下次 `since` 参数 |

## 注意事项

- `resumeJob` 不额外扣 RU；任务提交接受后断线不退款
- 实时进度（每条公式完成）会打印到 stderr，与 `runMultiFormulaBatchStream` 体验一致
- 如果任务已完成，SSE 流会从 `since=0` 重放所有历史事件并返回 `done` 结果
