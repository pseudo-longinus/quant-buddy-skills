# Recipe：下载数据到本地 CSV

## 触发词

> "把数据下载成 CSV"、"导出到本地"、"下载历史数据"

---

## 调用方式

```bash
python scripts/call.py downloadData '{"data_id":"<data_id>","begin_date":<YYYYMMDD>,"end_date":<YYYYMMDD>}'
```

`call.py` 调用 `downloadData` 时会**自动**将 CSV 保存到 `output/<data_name>.csv`，终端输出摘要（total_rows、begin_date、saved_to），不刷屏。

---

## 使用限制

| 条件 | 说明 |
|------|------|
| **可下载** | 持久化一维时序：上传数据 (`provider=mydata`) 或平台数据 (`provider=guanzhao`) |
| **不可下载** | `runMultiFormulaBatch` 的计算结果 (`provider=dunhe`)，普通用户无 `access_dunhe` 权限 → 返回 403 |
| **替代方案** | 计算结果用 `readData(mode="range_data", start_date=..., end_date=...)` 读取完整区间数据，再自行保存为 CSV |

---

## 必须确认时间范围

数据通常从 2015 年起，直接下载或 `range_data` 读取可能返回几千行。**调用前先问用户**：

> "您需要下载哪段时间的数据？（默认：最近一年）"

- 用户给出范围 → 传 `begin_date` / `end_date`
- 用户说"所有历史" → 不传日期参数
