# upload_data — 上传自有因子数据

> 将本地 CSV 格式的一维时序数据（如自研因子、宏观指标）上传到平台，上传后可在公式中直接引用。
> `executor.py` 的 `uploadData` 工具自动处理两阶段（preview + confirm），无需手动调用两次。

## 端点

- **第一阶段（Preview）**：`POST /skill/upload/preview`
- **第二阶段（Confirm）**：`POST /skill/upload/confirm`

（使用 `executor.py uploadData` 时自动完成两阶段）

## CSV 格式要求

```csv
date,value
20240101,1.23
20240102,1.45
20240103,1.67
```

- 必须有 2 列：第一列日期（`YYYYMMDD` 格式整数），第二列数值
- 编码：UTF-8 或 GBK（自动检测）
- 文件名即为数据名（可用 `data_name` 参数覆盖）

## 参数（executor.py uploadData）

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file_path` | string | ✅ | 本地 CSV 文件绝对路径 |
| `data_name` | string | ❌ | 数据名称，默认取文件名（不含扩展名） |
| `description` | string | ❌ | 数据描述 |
| `on_conflict` | string | ❌ | 同名冲突处理：`error`（默认，报错）/ `overwrite`（覆盖）/ `rename`（自动重命名） |

## 返回

```json
{
  "code": 0,
  "data": {
    "index_id": "60a1b2c3d4e5f6a7b8c9d0e1",
    "data_name": "我的动量因子.csv",
    "rows_written": 1250,
    "message": "上传成功"
  }
}
```

- `index_id`：上传后的数据ID，可用于 `downloadData` 或 `readData`
- 上传成功后可通过 `confirmDataMulti` 按数据名查找到该数据

## 调用示例

```bash
# 基础上传
python scripts/executor.py uploadData '{
  "file_path": "C:/data/momentum_factor.csv",
  "data_name": "20日动量因子",
  "description": "过去20个交易日收益率"
}'

# 覆盖同名数据
python scripts/executor.py uploadData '{
  "file_path": "C:/data/my_factor.csv",
  "data_name": "我的因子",
  "on_conflict": "overwrite"
}'

# 自动重命名（避免覆盖）
python scripts/executor.py uploadData '{
  "file_path": "C:/data/my_factor.csv",
  "on_conflict": "rename"
}'
```

## 上传后在公式中使用

```bash
# 先确认数据名（获取 index_title）
python scripts/executor.py confirmDataMulti '{"data_desc": "我的动量因子"}'

# 在公式中引用（用 index_title）
python scripts/executor.py runMultiFormula '{
  "formulas": [
    "MyFactor=\"我的动量因子.csv\"",
    "Signal=(\"MyFactor\">0)*板块(万得全A)*\"非ST\""
  ],
  "task_id": "uuid-xxx"
}'
```

## 注意事项

- 上传依赖后端 Celery Worker 异步处理，正常 2-10 秒内完成（超过 20s 超时报错）
- `provider` 自动设为 `mydata`，只有上传者本人可查看/下载
- 数据名在系统中以 `.csv` 后缀存储（`我的因子` → `我的因子.csv`）
- 单次上传建议不超过 10MB

## 手动两阶段上传（高级用法）

如需在 preview 后检查数据再决定是否 confirm：

```bash
# 第一步：预览
python scripts/executor.py uploadData '{"file_path": "data.csv", "data_name": "测试"}' 
# → 只传 preview 参数时手动处理

# 第二步：确认（使用 preview 返回的 file_token）
python scripts/executor.py uploadConfirm '{
  "file_token": "abc123:1709000000:sig...",
  "data_name": "测试",
  "on_conflict": "error"
}'
```
