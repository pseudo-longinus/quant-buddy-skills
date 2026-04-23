# 环境依赖说明

本文档描述运行 `quant-buddy-skill` 及其子场景所需的环境配置。

---

## Python

- **版本要求**：Python 3.8+（推荐 3.11）
- **核心功能**：仅依赖标准库，无需额外 `pip install`
- **Windows 推荐启动方式**：所有涉及中文路径的脚本加 `-X utf8` 标志

```bash
python -X utf8 scripts/call.py <工具名>
```

---

## API Key 配置

首次使用需在 skill 根目录执行：

```bash
python scripts/auth/setup.py
```

安装向导会将 `api_key` 写入根目录下的 `config.json`。

若你需要保留私有配置或覆盖默认端点，请使用 `config.local.json`；该文件仅供本地使用，不应打包或提交。

若出现 `401 Unauthorized` 或 `402 Quota`，重新运行上述命令，或手动更新 `config.json` 中的 `api_key`。

---

## 可选 Bocha 搜索能力

仅部分 Web 搜索辅助场景需要博查凭证；核心行情、财务、选股、回测能力不依赖该凭证。

可选配置方式（任一即可）：

- 环境变量 `BOCHA_API_KEY`
- `config.local.json` 中手动添加 `bocha_api_key`
- `config.json` 中手动添加 `bocha_api_key`

---

## 运行时输出目录

- `output/.session.json`：当前 session 的 task_id
- `output/ic_data/`：IC 扫描结果（若 workflow 触发相关能力）
- 其他 `csv / png / json / html`：运行过程中的临时或交付产物

---

## readData 批量限制

`readData` 单次调用最多传入 **10 个 data_id**。如需读取更多结果，拆分多次调用。

---

## 终端注意事项

- 终端缓冲可能导致长输出不完整显示，`call.py` 会额外写入系统临时目录下的 `gzq_out.txt`
- 若需排查，可在系统临时目录中查看该文件内容
