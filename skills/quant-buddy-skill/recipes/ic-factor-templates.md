# IC 因子公式模板

> 来源：`workflows/quant-standard.md` Step 2 手动因子构建
> 通常由 `scanDimensions` 脚本自动完成，仅在需要**自定义指标**或脚本不可用时手动使用

---

## 基础数据（所有因子前置）

```python
B_Close = 收盘价(X)         # X = 目标资产名（来自 confirmMultipleAssets 的 name）
B_Ind   = 收盘价(Ind)       # Ind = 行业指数名
B_Mkt   = 收盘价(Mkt)       # Mkt = 大盘指数（如 万得全A 或 沪深300）
```

---

## D1 估值

```python
B_PE      = "A股市盈率（PE, TTM）〔估值数据〕" * 取出(X的代码)
B_PB      = "A股市净率（PB）〔估值数据〕" * 取出(X的代码)
B_PE_Rank = 数值水位("B_PE", 250)
B_PB_Rank = 数值水位("B_PB", 250)
```

> PE 必须使用 TTM 口径（`A股市盈率（PE, TTM）〔估值数据〕`）

---

## D3 资金

```python
B_AllAmt    = 按天求和("全市场每日成交额")
B_Amt       = "全市场每日成交额" * 取出(X的代码)
B_AmtRatio  = "B_Amt" / "B_AllAmt"
B_AmtRank   = 数值水位("B_AmtRatio", 250)
B_Short     = "A股融券空头持仓比例" * 取出(X的代码)
B_ShortRank = 数值水位("B_Short", 250)
B_Fund      = "A股持股市值占基金股票投资市值比" * 取出(X的代码)
B_FundRank  = 数值水位("B_Fund", 250)
```

---

## D4 波动率 / 风险

```python
B_PrevClose = 前几天("B_Close", 1)
B_High      = 最高价(X)
B_Low       = 最低价(X)
B_TR  = 比较取大("B_High"-"B_Low", 比较取大(绝对值("B_High"-"B_PrevClose"), 绝对值("B_Low"-"B_PrevClose")))
B_ATR = 平均("B_TR", 14)
```

---

## D5 宏观 / 大盘环境

```python
B_Mkt_MA60  = 平均("B_Mkt", 60)
B_Mkt_Above = ("B_Mkt" > "B_Mkt_MA60")
```

---

## D7 技术形态

```python
# 均线
B_MA10 = 平均("B_Close", 10)
B_MA20 = 平均("B_Close", 20)
B_MA60 = 平均("B_Close", 60)

# MACD
B_EMA12     = EMA("B_Close", 12)
B_EMA26     = EMA("B_Close", 26)
B_MACD      = "B_EMA12" - "B_EMA26"
B_Signal    = EMA("B_MACD", 9)
B_MACD_Hist = "B_MACD" - "B_Signal"

# 布林带
B_SD20  = 标准差("B_Close", 20)
B_BollZ = ("B_Close" - "B_MA20") / "B_SD20"
```

---

## D9 财务

```python
B_Profit_Raw = 报告期转发布日("A股净利润同比增长率：单季〔财务指标〕")
B_Profit_F   = 缺失填充("B_Profit_Raw" * 取出(X的代码))
```

---

## 收益率 / 位置（跨维度通用）

```python
B_Ret20       = 涨跌幅("B_Close", 20)
B_IndRet20    = 涨跌幅("B_Ind", 20)
B_Alpha20     = "B_Ret20" - "B_IndRet20"
B_Ret20_Next  = 前几天(涨跌幅("B_Close", 20), -20)   # 未来20日收益（IC计算目标）

B_PriceRank   = 数值水位("B_Close", 250)
B_RS          = "B_Close" / "B_Ind"
B_RS_Rank     = 数值水位("B_RS", 250)
```

---

## IC 计算公式

```python
# 内联写法（推荐，无跨变量依赖）
PE_IC = 相关系数(前几天(数值水位("B_PE", 250), 20), 涨跌幅(收盘价(X), 20), 250)

# 引用写法（同一 task_id 内）
B_PE_Rank = 数值水位("B_PE", 250)
PE_IC     = 相关系数(前几天("B_PE_Rank", 20), 涨跌幅("B_Close", 20), 250)
```

> 不同 task_id 之间不能引用变量——newSession 后旧 session 的变量全部丢失
