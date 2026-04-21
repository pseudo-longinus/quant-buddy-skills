# 环境依赖说明

本文档描述运行 `guanzhao-quant-skill` 及其子场景所需的环境配置。

---

## Python

- **版本要求**：Python 3.6+（推荐 3.11）
- **核心功能**：仅依赖标准库，无需额外 `pip install`
- **Windows 推荐启动方式**：所有涉及中文路径的脚本加 `-X utf8` 标志

```bash
python -X utf8 scripts/call.py <工具名>
```

---

## API Key 配置

首次使用需配置观昭量化 API Key：

```bash
python guanzhao-quant-skill/scripts/setup.py
```

按提示粘贴 Key 后，自动写入 `scripts/.auth.json`，后续无需重复配置。

若出现 `401 Unauthorized` 或 `402 Quota`，重新运行上述命令更新 Key。

---

## IC 扫描数据输出目录

`ic_scan_dimensions.py` 脚本输出 JSON 到：

```
asset-investment-quiz/scripts/ic_data/{股票名}_dimension_ic.json
```

目录不存在时脚本会自动创建。

---

## readData 批量限制

`readData` 单次调用最多传入 **10 个 data_id**。如需读取更多结果，拆分多次调用。

---

## 终端注意事项

- 终端缓冲可能导致长输出不显示，`call.py` 自动写 `/tmp/gzq_out.txt`
- 查看方式：`cat /tmp/gzq_out.txt`
