# refresh_snapshot_time — 强制刷新分钟数据截止时间

## 端点

`POST /skill/refreshSnapshotTime`

## 参数

| 参数 | 类型 | 必填（HTTP 层） | 说明 |
|------|------|------|------|
| `task_id` | string | ✅ | 当前 session 的 task_id |

> **调用方注意**：通过 `scripts/call.py` 调用时，`task_id` 会从 `output/.session.json` **自动注入**，**LLM/调用方传 `{}` 即可**（与 `runMultiFormulaBatch` 等其他工具一致）。仅在脱离 call.py 直接打 HTTP 时才需手动带 task_id。

## 调用场景

同一天同一 session 内，多次执行盘中公式且需要推进分钟数据截止时间时，先调用本工具，再调用 `runMultiFormulaBatch`。

**通过 call.py 的标准调用（推荐）**：

```bash
python scripts/call.py refreshSnapshotTime '{}'
```

**等价的底层 HTTP payload**（call.py 自动补好 task_id）：

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

## 返回

```json
{
  "code": 0,
  "data": {
    "snapshot_time": 202604271345
  },
  "task_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

## 注意事项

- `snapshot_time` 是 **12 位整数，格式为 YYYYMMDDHHMM**（如 `202604271345` 表示 2026-04-27 13:45），**不是** Unix 时间戳
- 本工具会强制获取并覆盖该 session 当天的快照时间
- ⛔ 不要向 `runMultiFormulaBatch` 传 `refresh_snapshot_time`；该参数已移除
