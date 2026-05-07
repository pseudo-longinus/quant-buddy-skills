# download_data — 下载数据

> 通过数据ID下载一维时序数据，支持 CSV 文件格式和 JSON 格式返回。CSV 结果自动保存到 `output/` 目录。

## 端点

`GET /skill/data/:id?format=<csv|json>&begin_date=YYYYMMDD&end_date=YYYYMMDD`

## 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | ✅ | 数据ID（`indexInfo` 的 `_id`，来自 `runMultiFormulaBatch` / `confirmDataMulti` / `uploadData`） |
| `format` | string | ❌ | `csv`（默认）或 `json`（结构化数据） |
| `begin_date` | integer | ❌ | 开始日期 YYYYMMDD（含），不传则从数据最早日期起 |
| `end_date` | integer | ❌ | 结束日期 YYYYMMDD（含），不传则到数据最新日期止 |
| `task_id` | string | ❌ | 任务ID（UUID） |

## 返回（format=json）

```json
{
  "code": 0,
  "data": {
    "data_name": "我的动量因子.csv",
    "provider": "mydata",
    "dimension": "one-row",
    "total_rows": 250,
    "begin_date": 20250303,
    "end_date": 20260228,
    "labels": [20150104, 20150105, 20150106],
    "values": [0.0123, -0.0045, 0.0087]
  }
}
```

## 返回（format=csv，call.py 自动保存）

`call.py` 调用后自动保存到 `output/<data_name>.csv`，终端打印摘要：

```json
{
  "code": 0,
  "data": {
    "saved_to": "output/贵州茅台收盘价.csv",
    "total_rows": 250,
    "data_name": "贵州茅台收盘价",
    "begin_date": 20250303,
    "end_date": 20260228
  }
}
```

## 调用示例

```bash
# 下载最近一年，CSV 自动保存到 output/
python scripts/call.py downloadData '{"id": "60a1b2c3d4e5f6a7b8c9d0e1", "format": "csv", "begin_date": 20250303}'

# JSON 格式（获取结构化数据）
python scripts/call.py downloadData '{"id": "60a1b2c3d4e5f6a7b8c9d0e1", "format": "json", "begin_date": 20250303}'
```

## 权限说明

| provider | 访问条件 |
|----------|----------|
| `mydata` | 只能下载自己上传的数据 |
| `guanzhao` | 所有 API Key 用户均可访问 |
| `dunhe` | 需要后台开通 `access_dunhe` 权限 |

## 注意事项

- 仅支持**一维时序数据**（dimension=one-row）。公式计算的二维矩阵结果（如选股信号）请用 `readData` 读取
- `runMultiFormulaBatch` 的计算结果 provider 通常为 `dunhe`，普通 Skill 用户无 `access_dunhe` 权限，**会返回 403**；需读取公式计算结果请改用 `readData(mode="range_data", start_date=..., end_date=...)`
- `begin_date` / `end_date` 在服务端做裁剪，CSV 只含该区间的行
- `call.py` 下载后自动保存到 `output/` 并打印摘要，无需手动处理 CSV 文本
- 返回的 `labels` 为 YYYYMMDD 整数数组，`values` 为对应数值数组
