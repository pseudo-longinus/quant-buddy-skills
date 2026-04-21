# 手动运行 Agent Eval 测试指南

因为当前环境下无法自动化调用 Claude with Skill，我们采用**手动执行 + 自动评分**的方式。

## 执行步骤

### Step 1: 准备工作

确保已创建：
- `evals/evals.json` ✓
- `evals/files/sample_factor.csv` ✓

### Step 2: 逐个运行测试用例（在 Claude Code/Chat 中）

在 Claude 对话中，逐个输入以下 Prompt（确保加载了 guanzhao-quant-skill）：

#### 测试用例 1: 低PE选股
```
帮我选出当前市场上市盈率最低的20%股票

【重要】请将所有生成的文件（公式、数据、图表）保存到：
d:\liangye\.claude\skills\guanzhao-quant-skill\eval-workspace\iteration-1\low-pe-selection\with_skill\outputs\
```

执行完后，在该目录下应该有：
- `formula.txt` 或类似文件（包含生成的公式）
- `result.json` 或 `result.csv`（股票列表）
- （可选）图表文件

#### 测试用例 2: 均线交叉策略回测
```
回测一个策略：5日均线上穿20日均线时买入，跌破时卖出，看看过去3年表现

【重要】请将所有生成的文件保存到：
d:\liangye\.claude\skills\guanzhao-quant-skill\eval-workspace\iteration-1\ma-crossover-backtest\with_skill\outputs\
```

期望输出：
- 净值曲线图表（PNG 或 interactive_url）
- 策略公式
- 回测数据

#### 测试用例 3: 多策略对比
```
帮我对比一下低PE策略和沪深300指数，哪个收益更高

【重要】请将所有生成的文件保存到：
d:\liangye\.claude\skills\guanzhao-quant-skill\eval-workspace\iteration-1\multi-strategy-comparison\with_skill\outputs\
```

期望输出：
- 双曲线对比图表
- 量化指标（收益率、夏普等）

#### 测试用例 4: 因子上传
```
我有一个因子数据文件（d:\liangye\.claude\skills\guanzhao-quant-skill\evals\files\sample_factor.csv），
帮我上传并看看它的分布

【重要】请将所有生成的文件保存到：
d:\liangye\.claude\skills\guanzhao-quant-skill\eval-workspace\iteration-1\factor-upload\with_skill\outputs\
```

期望输出：
- 上传成功的确认信息（index_title）
- 因子分布图表

#### 测试用例 5: 相似案例搜索
```
有没有类似的研究案例：用财务指标做选股

【重要】请将搜索结果保存到：
d:\liangye\.claude\skills\guanzhao-quant-skill\eval-workspace\iteration-1\similar-cases-search\with_skill\outputs\result.json
```

期望输出：
- JSON 格式的案例列表

### Step 3: 手动记录执行信息

在每个测试用例的目录下，创建 `transcript.txt`，记录：
- 使用了哪些工具（按顺序）
- 每个工具的参数
- 是否遇到错误

例如：
```
# low-pe-selection 执行记录

1. 调用工具：confirmDataMulti
   - 查询：全市场数据
   - 结果：index_title = "万得全A"

2. 调用工具：searchFunctions
   - 查询：市盈率
   - 结果：找到 PE(MRQ)

3. 调用工具：runMultiFormula
   - 公式：SORT(PE(MRQ), True, 0.2)
   - 结果：task_id = "xxx"

4. 调用工具：readData
   - task_id：xxx
   - 结果：返回 800 只股票

5. 是否有图表：否（选股类不需要图表）
```

### Step 4: 运行评分脚本

```powershell
cd d:\liangye\.claude\skills\guanzhao-quant-skill
python scripts/grade_eval.py --iteration 1
```

脚本会：
- 扫描 `eval-workspace/iteration-1/` 下的所有测试目录
- 检查每个断言是否满足
- 生成 `benchmark.json`

### Step 5: 查看结果

```powershell
# 查看总体评分
Get-Content eval-workspace\iteration-1\benchmark.json | ConvertFrom-Json | ConvertTo-Json -Depth 10

# 查看单个测试用例的评分
Get-Content eval-workspace\iteration-1\low-pe-selection\with_skill\grading.json | ConvertFrom-Json | ConvertTo-Json -Depth 10
```

---

## 评分标准

每个断言会被标记为：
- ✅ **passed: true** - 断言通过
- ❌ **passed: false** - 断言失败
- ⚠️ **passed: null** - 无法自动判断（需要人工检查）

目标：**总体通过率 ≥ 85%**

---

## 如果某个测试用例失败了...

1. 查看 `transcript.txt`，定位失败原因：
   - 是否漏掉了某个工具？
   - 参数是否错误？
   - 是否返回了 API 错误？

2. 根据失败原因，改进 `SKILL.md`：
   - 添加更强的指令（如"MUST", "REQUIRED"）
   - 提供更清晰的示例
   - 添加错误处理提示

3. 运行 Iteration 2，重新测试

---

## 快速检查清单

运行前确认：
- [ ] `evals/evals.json` 已创建
- [ ] `evals/files/sample_factor.csv` 已创建
- [ ] Claude 已加载 guanzhao-quant-skill
- [ ] `scripts/grade_eval.py` 已准备好

运行后确认：
- [ ] 所有测试用例目录都有 `outputs/` 文件夹
- [ ] 每个目录都有 `transcript.txt` 记录工具调用
- [ ] `benchmark.json` 已生成
- [ ] 通过率 ≥ 85%

如果通过率低于 85%，需要进行 Iteration 2。
