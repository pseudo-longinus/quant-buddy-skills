# 行业涨跌幅排名活页快路径

> **唯一适用范围**：用户明确要求申万一级行业/行业板块最近 N 个交易日涨跌幅排名，并且要求“图、排名图、柱状图、可视化”。典型问题：“做一张申万一级行业最近20个交易日涨跌幅排名图，我想快速看看哪些行业最强、哪些行业最弱。”

## 顶部硬闸门

命中本流程后，本 Turn **只读 `SKILL.md` 与本文件**。不得读取 `global-rules.md`、`quant-standard.md`、`recipes/industry-aggregation.md`、案例库或函数文档；本文件已包含完整公式与恢复规则。

不得调用 `searchFunctions`、`searchSimilarCases`、`getCardFormulas`、`confirmDataMulti`。不得调用 `renderChart`、`renderKLine` 或先生成 PNG；页面主图由 QBV 使用已物化结果生成。

## 固定执行序列

1. 在任何平台工具前，先执行活页路由：

```powershell
python scripts/live_page_routing.py route --user-query "用户本轮原话"
```

只有 `route=create` 才继续本流程；`none/suggest` 按路由结果回到 QBS。

2. 本 Session 首轮调用一次 `newSession`；追问调用一次 `beginTurn`。保存返回的 `task_id/turn_id`，不重复初始化。

3. 只执行以下一条公式。把 `N` 替换为用户要求的交易日数；“最近一个月”默认 N=20：

```text
行业近N日涨跌幅=成分平均汇总(涨跌幅("全市场每日收盘价",N),"申万资产所属指数")
```

调用 `runMultiFormulaBatchStream` 时：

- `formulas` 只含这一条；
- `force_reusable_array` 传 `['行业近N日涨跌幅']`；
- `begin_date` 使用当前年份 1 月 1 日；若当前日期早于 2 月 15 日，使用上一年 10 月 1 日；
- `include_description=true`；
- 不为“更全面”扩大计算区间或增加第二条公式。

4. 批次成功后，**只使用 `results[0].indexinfo_id` 作为 data_id**。`expression_id` 不是 `readData` 的数据 ID，禁止读取它。只调用一次：

```json
{
  "ids": ["results[0].indexinfo_id"],
  "mode": "last_column_full",
  "task_id": "当前 task_id"
}
```

若返回 31 个左右行业，直接排序并回答。行业名称必须原样复用；值乘 100 后显示百分比。口径必须写成：**“个股近 N 日区间收益按申万一级行业做成分股算术平均”**，不得写成指数本身的累计涨幅。

5. `readData` 成功后，直接调用一次低自由度准备命令；不要创建中间 JSON：

```powershell
python scripts/live_page_routing.py prepare-industry-ranking-page --data-id "<indexinfo_id>" --index-title "行业近N日涨跌幅" --window-days N --asset-count 31 --as-of-date "<readData 返回 YYYYMMDD>"
```

命令会从当前 QBS Session 自动补齐 `task_id/turn_id/user_query/source_skill_version`，并一次性生成 computation capsule、Handoff 和幂等 QBV Job。它同时携带：

- 已物化 `data_id`，供 QBV 只做一次 `readData`；
- 固定行业聚合公式，供页面注册实时刷新合同；
- 横向排名柱状图、正红负绿、零轴、排序、hover 和口径展示要求。

**终止性规则**：命令 `code=0` 后禁止再次执行 `handoff`、`prepare`、`prepare-validated-page` 或第二次页面准备；也禁止再调用 `renderChart`。

6. `should_spawn=true` 时，使用宿主真实提供的内部委派能力把返回的 `handoff_file` 与 `qbv_job_id` 交给独立 QBV SOP，只等待接受回执，不等待页面完成。用户可见表述只能说“正在后台生成可交互页面”，不要说“新开一个子 Agent”。

若当前测试宿主没有内部委派工具，必须执行：

```powershell
python scripts/live_page_routing.py mark-delegation-unavailable --qbv-job-id "<qbv_job_id>"
```

此失败只影响页面旁路，不影响 QBS 排名答案；不得假称页面正在生成。

## QBS 首答

首答立即给出：

- 数据日期与计算口径；
- 最强 3～5 个行业；
- 最弱 3～5 个行业；
- 全部行业表格可按篇幅保留或压缩；
- 只做强弱与分化描述，不添加未经数据验证的政策、资金或宏观归因。

## 工具预算

| 类型 | 上限 |
|---|---:|
| Skill/workflow Read | 2（`SKILL.md` + 本文件） |
| 路由 Bash | 1 |
| Session/Turn | 1 |
| `runMultiFormulaBatchStream` | 1 |
| `readData` | 1 |
| 页面准备 Bash | 1 |
| 内部委派或失败终态 Bash | 1 |
| **目标总调用** | **7～8** |

任何成功角色不得重复调用。目标是 QBS 先快速回答，QBV 只消费现有 `data_id`，绝不重跑相同公式。
