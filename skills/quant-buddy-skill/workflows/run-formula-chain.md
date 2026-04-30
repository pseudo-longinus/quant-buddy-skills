# Leaf Workflow — 直接运行用户给定的公式链文件

> **场景**：用户提供一个本地文件（`.md` / `.txt` / `.json`），里面已写好编号公式链，要求"直接运行 / 跑一遍 / 执行"文件里的全部公式，并按最末公式的语义给出最终结果。
>
> **核心约束**：本场景最容易触发"自写 driver 脚本"反模式（heredoc + subprocess 循环驱动多批）。SKILL.md 硬规则 #2 已明文禁止。本 workflow 给出**唯一合规路径**。

---

## ⛔ 反模式（违规即失败）

下列写法**全部禁止**，无论公式数量多少、依赖多复杂：

```bash
# ❌ heredoc 包 subprocess 多批循环
python - <<'PY'
for start in range(0, len(formulas), 20):
    subprocess.run(['python','scripts/call.py','runMultiFormulaBatch', ...])
PY

# ❌ python -c 包装
python -c "import subprocess; [subprocess.run([...]) for b in batches]"

# ❌ node -e + execSync
node -e "require('child_process').execSync('python scripts/call.py runMultiFormulaBatch ...')"
```

**根本原因**：每多套一层解释器/subprocess，就多一处 session 漂移、stdout 阻塞、TMP 路径错乱、配额误算的可能。call.py 的兜底地位**只允许一层**：`shell → call.py`。

---

## ✅ 合规执行路径

### Step 1：读公式链文件

用 `read_file` 读取用户给定路径的全部内容（一次读完，禁止 limit）。

### Step 2：LLM 在推理中解析公式数组

不写解析脚本。提取每行编号公式（典型形式 `^\s*\d+\.\s*(.+)$`），形成 `formulas: string[]`。

> 文件可能不止"编号 + 公式"一种格式（也可能是 yaml/json 列表、或带注释的 markdown 块）。识别格式由 LLM 在推理中完成，不要为此写脚本。

### Step 3：LLM 在推理中生成 `force_reusable_array`

按 SKILL.md 硬规则 #2 + `global-rules.md` §13 三问法判定每条：

1. 左侧变量是否会被 `readData` 或最终业务步骤读取？
2. 是否会被**后续 batch / 后续 `runMultiFormulaBatch` 调用 / 用户后续追问**引用？
3. 此刻是否能确定它"以后再不会被读"？

任一答"会/不能确定" → 把变量名**写进** `force_reusable_array`；只有完全确定"仅本批后续公式用、再无人引用" → 不要写进数组。

**末批内仅 readData 读取的最终输出变量必须写进数组**（通常是末条公式，如 `*_Top10`、`*_Result`、`*_Final`）；末批内的 `*_Score`、`*_Ratio` 等中间量仍按三问法判断，不因在末批而自动写入。**禁止全列**（列出本批全部变量名 = 规则退化，与未传等价）。

### Step 4：切批 + 落盘 batch JSON

按本 skill 的单批上限（**10 条/批**，服务端硬上限同为 10）切分。用 `create_file` 把每批落盘到 `output/tmp_batches/batch_K.json`：

```json
{
  "formulas": ["...", "..."],
  "force_reusable_array": ["变量名1", "变量名2"],
  "use_minute_data": true
}
```

跨批数组联动：组装第 K 批的 `force_reusable_array` 前，先扫描第 `K+1..N` 批的右侧引用，凡被后续引用的本批左侧变量必须写入。

### Step 5：逐批发起独立 shell 调用

**每批一条独立的 `run_in_terminal` 调用**，前一批返回后再发起下一批：

```bash
cd <SKILL_ROOT> && GZQ_PARAMS="$(cat output/tmp_batches/batch_K.json)" python scripts/call.py runMultiFormulaBatch
```

**禁止**：
- 用 `&&` 把多批拼到一条命令里
- 写 python/node 脚本一次跑完所有批
- 用 `for` 循环（shell 或 inline 脚本）驱动多批
- 上一批还没返回就发起下一批

### Step 6：取最终输出

末批返回后，从返回 JSON 的 `data.data[]` 里找到**用户最终关心变量**（通常是末条公式的左侧）的 `index_info._id`，再发起一次 `readData`：

```bash
cd <SKILL_ROOT> && GZQ_PARAMS='{"ids":["<_id>"],"mode":"last_column_full"}' python scripts/call.py readData
```

按用户问法解析返回（取前 N、阈值筛选、等等），输出数据结论。

---

## 失败处理

| 现象 | 处理 |
|---|---|
| 某批返回 `code=-1` | 读返回的 `errors` 数组，定位失败公式；不重试整批，先报告错误位置 |
| `SKILL_VERSION_MISMATCH` | 按 SKILL.md 硬规则 #8 (A) 自愈（newSession + 重读文档 + 重跑） |
| 服务端要求 skill 升级（响应里有 `npx skills update` 提示） | 按 SKILL.md 硬规则 #8 (B) 自愈（运行 `npx skills update pseudo-longinus/quant-buddy-skills -y` + 重读 + newSession + 重跑），**禁止改本地版本号字符串** |
| 配额超限 | 按 SKILL.md 全局 429 处理表 |
| stdout 截断 | Linux/macOS：`cat /tmp/gzq_out.txt`；Windows PowerShell：`Get-Content "$env:TEMP\gzq_out.txt" -Encoding UTF8`；或用返回的 task_id 查询 |
| stdout 完全为空（exit code=0）| 先查 `%TEMP%\gzq_out.txt`（UTF-8）；再查 `quant-buddy-skill/logs/<task_id>.jsonl`；只要其中有 `code=0`、`success:true`、`index_info._id`，即可直接进入 `readData`，无需重跑 |
| 某批**超时 / 报错被动拆分** | 不得沿用失败批次的 `force_reusable_array` 或全列兏底；必须重新对拆分后的每个子批逐条过三问法；特别注意：原批内的引用在拆分后变成跨批引用的变量，必须在对应子批重新写入数组 |

---

## 多轮追加公式（场景 B）前置检查 SOP

收到第 2 轮（或后续轮）追加公式时，在发起 `runMultiFormulaBatch` 之前执行以下检查：

1. 扫描新公式的右侧，列出所有引用了前批左侧变量的依赖项；
2. 对照历史 batch 的 `force_reusable_array`，查看这些依赖变量是否已列入；
3. 若发现有依赖变量在历史 batch 中未列入：
   - **有修正接口时**：先调 `markReusable` / `updateForceReusable`，再继续执行新公式；
   - **无修正接口时**：在终态答案中**显式说明**「变量 X 在首批未保活，本次需重新计算前置链（#N1 ~ #N2）」，并先补跑这些前置公式（把这些变量名都写进 `force_reusable_array`），再跑新公式；**禁止默默依赖缓存兏底**。

---

## 最终回答合同

第一句必须是数据结论，按用户问法直接给出（资产名 + 数值 / 表格 / 名单 / 等等）。

禁止：「已成功执行 N 条公式」「按照 workflow Step 1/2/3」「让我来分批执行」等过程话术。
