# 故障排查

> 汇总所有场景（量化选股、渲染图表、数据下载）的常见错误与解决方式。

---

## 公式 / 变量

| 问题现象 | 可能原因 | 处理方式 |
|----------|----------|----------|
| `公式变量未找到` | 同一批公式 task_id 不一致 | 确保所有公式用同一个 task_id |
| `函数不存在` / 函数名报错 | 案例原文笔误，或抄写时引入差异 | 用 `searchFunctions` 找正确函数名 |
| `数据名不存在` | 公式中名称与 confirmDataMulti 的 index_title 不一致 | 以 index_title 为准 |
| `公式格式检测失败：MA(dataid(...),N)` | 平台**无 `MA()` 函数** | 简单均线用 `平均("数据名", N)`；指数均线用 `ema("数据名", N)` |
| `函数不存在：取出最后值` | 该函数不存在于平台 | 替代：① `取前(数据, n, 返回数值)` 获取截面 TopN；② `readData(mode=last_day_stats)` 获取最新截面 |
| PE 选股包含亏损股 | 未过滤负 PE | 加 `("PE">0)` 条件 |
| 多因子选股数为 0 | 非季报日截面财务数据为空 | ① 检查结束日期是否临近季报日；② 用 `readData(mode=last_day_stats)`；③ 调整至最近季报日（3/31、6/30、9/30、12/31） |

---

## 工具参数

| 问题现象 | 可能原因 | 处理方式 |
|----------|----------|----------|
| `参数 xxx 必填` / `400` | 参数名错误 | 读对应 `tools/<tool>.md` 确认正确字段名 |
| `readData` 返回 400 | 参数名用了 `variable_names` | 改为 `ids` 数组 |
| `match_quality=low` | searchSimilarCases 未找到好模板 | 调整 query 关键词，**最多重试 1 次** |
| confirmDataMulti 返回 404 | 查询的是单资产价格，不是平台聚合数据 | 用 `收盘价(资产名)` 函数，无需 confirmDataMulti |
| 本地资产库未命中 | intentions 用了前缀格式如 `CMX-铜` | **优先方案**：先 `grep "铜" presets/assets_db/future.yaml` 拿到规范 name（如 `CMX-铜` / `沪铜主力合约`）直接用；**处理**：未唯一命中时停止并说明需要更明确的资产名称或代码，不再远程兜底 |

---

## 图表渲染

| 问题现象 | 可能原因 | 处理方式 |
|----------|----------|----------|
| renderChart 图中无曲线 | 数据为二维，renderChart 仅支持一维 | 确保公式输出一维时序 |
| `参数 lines 必须是非空数组` | 误用了 `variable_names` 参数 | 改为 `lines: [{id, name}]`，id 来自 runMultiFormulaBatch 的 `_id` |
| K线图报 `必须包含 open_id/high_id/low_id/close_id` | candlestick 参数缺少必填字段 | 传入完整 4 个 ID；或改用 `renderKLine` |
| K线图日期对不齐 / 数据缺失 | OHLC 4 个 data ID 来自不同 task_id | 确保在同一个 runMultiFormulaBatch 中计算 |
| renderKLine 报 ticker 不存在 | ticker 格式错误 | 使用 `SH`/`SZ` 前缀格式如 `SH600519` |
| renderKLine indicators 无效 | 指标名拼写错误 | 参照 `tools/render_kline.md` 支持列表，全小写 |
| 图表不知道在哪里 | 未找到输出文件 | `call.py` 已自动保存到 `output/` 并打开 |

---

## 认证 / 网络

| 问题现象 | 可能原因 | 处理方式 |
|----------|----------|----------|
| `401 Unauthorized` | api_key 无效或过期 | **立即停止**，提示用户重新认证 |
| `402 Quota` | 配额耗尽 | **立即停止**，提示用户等待恢复或次日重置 |
| 终端命令无输出 | 终端缓冲 stdout | `call.py` 已写 `/tmp/gzq_out.txt`，用 `cat /tmp/gzq_out.txt` 读取 |

## 业务错误（HTTP 200 + success: false）

部分错误走 HTTP 200 返回，通过 `success: false` + `error` 对象区分：

```json
{"code": -1, "success": false, "error": {"message": "参数 ids 必须是非空数组"}}
```

| 判断方式 | 说明 |
|----------|------|
| `success === false` 或 `code !== 0` | 均可判定为错误 |
| `error.message` | 错误描述 |

> 业务错误与 429 配额超限使用相同的 `{ success: false, error: { message } }` 结构。
> 429/503 的 `error` 中额外包含 `code`（语义化字符串）和恢复时间字段。
> 调用方应先检查 HTTP status（429/503），再检查 body 的 `success` / `code`。

---

## 配额限流（429 错误码）

| 错误码 | 含义 | 处理方式 |
|--------|------|----------|
| `WINDOW_QUOTA_EXCEEDED` | 窗口 RU 已耗尽 | **停止调用**，告知用户等待时间（`error.nextResetIn` 秒后最早一批恢复） |
| `DAILY_QUOTA_EXCEEDED` | 今日 RU 已耗尽 | **停止调用**，告知用户次日 00:00 重置（`error.resetIn` 秒） |
| `DAILY_SCAN_EXCEEDED` | IC 扫描今日次数已满 | **停止调用**，告知用户次日 00:00 重置（free=2次/天，plus=10次/天）（`error.resetIn` 秒） |
| `RATE_LIMIT_EXCEEDED` | 每分钟请求过于频繁 | **静默等待** `error.retryAfter` 秒后重试，不暴露给用户 |
| `CONCURRENT_LIMIT` | 有计算任务正在执行 | **静默等待** `error.retryAfter` 秒后重试，不暴露给用户 |
| `SERVICE_OVERLOADED` | 系统熔断（503） | **静默等待** `error.retryAfter` 秒后重试 1 次；若仍失败则告知用户"系统繁忙，请稍后重试" |

---

## 数据下载

| 问题现象 | 可能原因 | 处理方式 |
|----------|----------|----------|
| downloadData 返回 403 | 计算结果 `provider=dunhe`，无权限 | 改用 `readData(mode="range_data", start_date=..., end_date=...)` |
| 下载到全量历史几千行 | 未传 begin_date | 调用前先问用户要哪段时间 |
| 上传数据 NaN 率高 | CSV 列标题缺少交易所后缀 | 改为 `600519.SH` 格式 |

---

## 版本不匹配（SKILL_VERSION_MISMATCH / 服务端要求升级）

| 问题现象 | 类型 | 处理方式 |
|----------|------|----------|
| 工具返回 `"error": "SKILL_VERSION_MISMATCH"` | 本地 session 与本地 SKILL.md 不一致 | 按 SKILL.md 硬规则 #8 (A)：`newSession` + 重读 SKILL.md / workflow / tools，重跑任务 |
| 工具返回 message 含 `[QBS:SKILL_UPDATE_REQUIRED]` / 『skill 版本过低』 | 服务端要求版本高于本地 | **第一步走 Python Zip**：先检查 `scripts/self_update.py` 是否存在——存在则 cd 到 SKILL_ROOT 执行 `python_zip_cmd` 字段命令；不存在则自行编写内联 Python 脚本（urllib 下载 → sha512 校验 → zipfile/shutil 解压 → 保留 config.json → 覆盖 SKILL_ROOT）；Python 本身不可用时再按 `npx update` → `npx add` 顺序处理；成功后重读 SKILL.md / CHANGELOG 最新 5 条 / workflow / tools，再 `newSession` 重跑 |
| `npx skills update` 成功 | 已安装老用户更新成功 | 重读 SKILL.md 确认版本，再 `newSession` 重跑 |
| `update` 报 `not installed` / `skill not found` | 用户从未安装过本 skill | 改用 `npx skills add pseudo-longinus/quant-buddy-skills -g --all`；安装完成后，新 SKILL_ROOT 为输出中标注的路径（通常 `~\.agents\skills\quant-buddy-skill`）；**若该路径与原始 SKILL_ROOT 不同，必须先读取原始 SKILL_ROOT/config.json 的 api_key 并写入新 SKILL_ROOT/config.json（保持其他字段不变），防止 API Key 因路径变更丢失**；完成后重读 SKILL.md，再 `newSession` 重跑 |
| `update` / `add` 报 `command not found` / 无 Node/npx | Node 工具链不可用 | 若 message 协议块含 `python_zip_available=true`、`zip_url`、`zip_sha512`，进入 Python Zip Fallback |
| `update` / `add` 报 `EACCES` / `EPERM` / symlink 权限 / 网络错误 | npx 更新链路不可用 | 进入 Python Zip Fallback；不要继续追加 `--copy` 或反复重试 npx |
| Python Zip 的 SHA-512 不一致 | 下载包损坏或非服务端记录版本 | 放弃该 zip 包并提示重试，禁止解压或替换正式 skill 目录 |
| Python Zip 内 `SKILL.md` 版本不等于 `required_version` | 下载包版本错误 | 放弃该 zip 包并输出原始错误 |
| `newSession` 返回的 `skill_version` 旧于服务端提示版本 | 服务端要求版本高于本地 | 同「服务端要求升级」流程 |
| 所有更新路径均失败 | 用户环境问题 | 把原始错误整段交给用户；**禁止**改本地版本号字符串或 session 文件凑数 |

> ⚠️ **P0 红线**：任何情况下都禁止用编辑工具修改 `SKILL.md` / `config.json` / `scripts/*.py` / `CHANGELOG.md` 中的 `version` 字段，或改写 `.session.json` 的 `skill_version_at_creation` 来"伪装版本一致"。这是欺骗式自愈，本地工具签名仍是旧的，下一次调用必然继续报错；服务端审计日志也会记录真实上报版本，伪造无效。
