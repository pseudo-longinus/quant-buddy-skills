# Recipe：下载 / 导出数据到本地 CSV

## 触发词

> "下载成 CSV"、"导出到本地"、"保存到本地"、"下载历史数据"

---

## ⛔ Skill 内执行主路径（在当前 skill 运行时必须走这条）

1. 先 `newSession`（每个新问题必做，不得跳过）。
2. 若是**单资产 + 单字段 + 时序序列**（如"贵州茅台最近 3 年每日收盘价"）：
   - 优先用 `runMultiFormulaBatchStream` 写单股序列公式（如 `茅台收盘价 = 收盘价("贵州茅台")`），从返回中拿到 `data_id`；
   - 不要先走 `confirmDataMulti("全市场每日收盘价")` 再 `取出(...)` 这种长路径，路径越长越易跑偏。
3. 调用原生 `downloadData '{"id":"<data_id>","begin_date":<YYYYMMDD>,"end_date":<YYYYMMDD>,"format":"csv"}'`。
4. `downloadData` 会自动落盘并返回 `saved_to` 路径（及 `total_rows`、`begin_date`、`end_date`）。把该路径告诉用户，任务即完成。
5. **⛔ 绝对不要**在 `downloadData` 之后调用任何写文件工具（`write_skill_file`、`Bash`、`python3 -c`、`shell` 等均不存在或不允许）。`downloadData` 已完成本地保存，无需任何后续步骤。

## ⛔ 禁止事项（直接对应 T-035 反例）

- 调用任何不存在的工具（`write_skill_file` 不是真实工具，调用必然失败，禁止重试）。
- 拿到 CSV 字符串后跳过 `downloadData`，转去 `Bash` + `python3 -c` 写文件。
- 反复 `Bash` 重试 `&&` / `;` / `python3 -c` / `ls` / `dir` —— 全部违反 Bash 白名单。

---

## 外部调试示例（仅供仓库外部 CLI 调试，LLM 在 skill 运行时不要走这里）

```bash
python scripts/call.py downloadData '{"data_id":"<data_id>","begin_date":<YYYYMMDD>,"end_date":<YYYYMMDD>}'
```

`call.py` 调用 `downloadData` 时会**自动**将 CSV 保存到 `output/<data_name>.csv`，终端输出摘要（total_rows、begin_date、saved_to），不刷屏。**此路径仅适用于命令行调试**，skill 运行时的 LLM 必须走上节「主路径」的原生工具调用。

---

## 使用限制

| 条件 | 说明 |
|------|------|
| **可下载** | 持久化一维时序：上传数据 (`provider=mydata`) 或平台数据 (`provider=guanzhao`) |
| **不可下载** | `runMultiFormulaBatchStream` 的计算结果 (`provider=dunhe`)，普通用户无 `access_dunhe` 权限 → 返回 403 |
| **替代方案** | 计算结果用 `readData(mode="range_data", start_date=..., end_date=...)` 读取完整区间数据，再自行保存为 CSV |

---

## 必须确认时间范围

数据通常从 2015 年起，直接下载或 `range_data` 读取可能返回几千行。**调用前先问用户**：

> "您需要下载哪段时间的数据？（默认：最近一年）"

- 用户给出范围 → 传 `begin_date` / `end_date`
- 用户说"所有历史" → 不传日期参数
