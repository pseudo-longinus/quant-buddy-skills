# 单资产多指标活页快路径

> **唯一适用范围**：一个已明确资产 + 2～4 个 `fast_query(window)` 标准历史字段 + 用户明确要求“放在一张图里 / 画成一张图 / 同图比较”。典型问题：“把贵州茅台最近一年的股价、成交量和市盈率变化放在一张图里”。
>
> 这不是 K 线请求。只有用户明确说“K 线 / 蜡烛图 / OHLC”才进入 `render-kline.md`。

## 顶部硬闸门

命中本流程后，本 Turn **只读本文件，不得读取 `quant-standard.md`、`render-kline.md` 或 `render-chart.md`**。本流程已有完整参数和恢复规则，不得为了“更全面”扩大文档范围。

不得调用 `searchFunctions`、`searchSimilarCases`、`confirmDataMulti`、`runMultiFormulaBatchStream` 或 `readData`。不得调用 `renderChart`；不得调用 `renderKLine`。字段已由 `fast_query` 返回时立即停止取数，禁止重复计算。

## 固定执行序列

1. 用一次 `Grep` 在资产库确认唯一资产代码；未命中或跨市场同名时按 `SKILL.md` 资产规则处理，不猜测。
2. 本 Session 首轮调用 `newSession`；追问调用 `beginTurn`。之后才能调用平台工具。
3. **先执行路由**，不要等静态图或公式计算：

```powershell
python scripts/live_page_routing.py route --user-query "用户本轮原话"
```

4. 只有返回 `create` 才继续本快路径。若为 `none/suggest`，按路由结果正常回答，不准备页面 Job。
5. 调用一次 `fast_query`：

```json
{
  "assets": ["资产库确认后的代码或唯一名称"],
  "query_type": "window",
  "fields": ["用户要求的 2～4 个标准字段"],
  "window_days": 250,
  "user_query": "用户本轮原话"
}
```

时间口径：一年默认 250 个交易日；半年 120；三个月 60；用户给 N 日则用 N（1～2500）。不要传 `result_mode`。

6. 若返回 `mode:"csv"`，把 `csv_fields[].csv_url` 按原顺序交给受控脚本；`--labels` 必须对应 `csv_fields[].intent`。**无需预建目录**，脚本会安全创建 `--output` 的父目录；禁止额外调用 `mkdir`：

```powershell
python scripts/fetch_fastquery_csv.py "<csv_url1>" "<csv_url2>" "<csv_url3>" --labels "收盘价,成交量,市盈率" --full --output "output/_working/<task_id>/main-series.json"
```

stdout 是紧凑 receipt；完整序列已写入 artifact，不要再读取整份 artifact 回模型上下文。直接使用 receipt 的 `series_summaries`（首值、末值、区间涨跌、极值）、字段统计和 `pairwise_analysis` 支持 QBS 首答；禁止再用 `curl`、`Invoke-WebRequest`、`read_skill_file` 或其它方式读取 CSV/artifact。

7. 一次命令生成 computation capsule、Handoff 和幂等 Job：

```powershell
python scripts/live_page_routing.py prepare-fast-query-page --task-id "<task_id>" --turn-id "<turn_id>" --user-query "用户本轮原话" --source-skill-version "<当前 SKILL.md version>" --asset-id "<资产代码>" --asset-name "<资产名称>" --fields "收盘价,成交量,市盈率" --window-days 250 --artifact-file "output/_working/<task_id>/main-series.json"
```

有真实 `source_skill_id` 时增加 `--source-skill-id`；不知道就省略，禁止猜测。命令返回的 `handoff_file`、`qbv_job_id`、`should_spawn` 是唯一交接依据。

**终止性规则**：`prepare-fast-query-page` 返回 `code=0` 后，capsule、Handoff 和 Job 已全部生成。此后只允许二选一：调用一次内部委派，或调用一次 `mark-delegation-unavailable`；然后立即基于既有 receipt 给出 QBS 首答。**禁止再次执行 `handoff`、`prepare` 或第二次 `prepare-fast-query-page`，也不得再调用任何取数、下载或文件读取工具**；不得把 `qbv_job_id` 当作 Handoff JSON 输入。

8. `should_spawn=true` 时，使用宿主真实提供的内部委派能力把该 Handoff 交给独立 QBV SOP；只等待接受回执，不等待页面完成。用户可见表述只能说“正在后台生成可交互页面”，不要说“新开一个子 Agent”。若宿主无委派能力或调用失败，执行：

```powershell
python scripts/live_page_routing.py mark-delegation-unavailable --qbv-job-id "<qbv_job_id>"
```

该命令把 Job 写为 `failed + DELEGATION_UNAVAILABLE + retryable=true`；QBS 首答照常发送，且不得对用户声称页面正在生成。
9. QBS 首答必须回答用户的分析问题：给出区间、价格/估值变化、相关系数与方向一致率的谨慎解释。**禁止**写“价格主要由估值驱动”“PE 导致股价变化”等因果结论；PE 指标通常包含价格项，高相关可能带有定义上的机械关系，必须明确写出“同步不等于因果，不能据此判断驱动因素”。页面完成后由终态消息补公开链接。

## Inline 返回的窄恢复

若 `fast_query` 未进入 CSV 模式而直接返回列式序列：只允许用 `write_skill_file` 将本次 `results` 原样写到 `output/_working/<task_id>/main-series.json`，然后执行同一个 `prepare-fast-query-page` 命令。不得为了制造 CSV 或图表改走公式引擎。

## 工具预算

| 类型 | 上限 |
|---|---:|
| Skill/workflow Read | 2（`SKILL.md` + 本文件） |
| 资产 Grep | 1（只允许未命中时补 1 次） |
| Session/Turn 工具 | 1 |
| 路由 Bash | 1 |
| `fast_query` | 1 |
| CSV artifact Bash 或 `write_skill_file` | 1 |
| `prepare-fast-query-page` Bash | 1 |
| 内部委派 | 1 |
| **目标总调用** | **8～10** |

任何一步成功后不得重复调用同角色工具。`fast_query` 只有明确返回字段失败时才允许对失败字段做一次降级；否则超预算即停止扩张并基于已有结果回答。
