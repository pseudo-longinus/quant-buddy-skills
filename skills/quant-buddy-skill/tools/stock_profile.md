# stockProfile — 个股指标画像

> **实际工具名：`stockProfile`**。禁止调用 `stock_profile` / `getStockProfile` / `stockProfileQuery` 等名称变体。

一次调用返回单只股票在评级表系统中的预计算指标画像。数据来自后端 `smartstock_indicator_latest` 集合，按维度分组返回最新值、上一期值、日期和单位。本工具是纯 DB 查询，不执行自定义公式，不做 IC 扫描。

## 适用 / 不适用

| 适用 | 不适用 |
|---|---|
| 分析一下 XX 个股 | 最新价、PE、ROE 等单字段快查 → `fast_query` |
| 个股画像、指标概览 | 最近 N 日序列 / 窗口统计 → `fast_query` |
| 估值、财务、资金、波动率、走势综合看一下 | 多股票批量比较、选股、回测、自定义公式 → 对应量化 workflow |
| 单只股票全维度预计算指标概览 | IC / 预测力 / 哪个维度有效 → `scanDimensions` |
| 最新值 + 上一期值对比 | 投资建议、目标价、价格预测 → safe-fail |

## 参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `asset` | ✅ | 资产名称或代码，如 `贵州茅台` / `600519.SH` / `苹果` / `AAPL` / `小米` / `01810.HK` |
| `user_query` | ✅ | 用户原始问题，用于 trace；调用时携带原文 |
| `task_id` | 自动注入 | 当前 session 的 task_id，由调用层注入，不需要手写 |

调用示例：

```json
{
  "asset": "贵州茅台",
  "user_query": "分析一下贵州茅台这只股票"
}
```

## 返回结构

响应经过压缩：维度内统一的 `latest_date`、`unit` 提升到维度层级；同一基础指标的衍生变体（百分位、builder 变体等）折叠到 `variants` 子对象；数值已按精度 round，不返回 `data_id` 和 `decimals`。

```text
code: 0
task_id
data:
  asset:
    code / name / ticker
  computed_at
  indicators_count
  dimensions:
    维度名:
      latest_date          ← 维度内统一时出现，省略则看各指标自身
      unit                 ← 维度内统一时出现
      indicators:
        base_id:
          name
          latest_value
          latest_date      ← 与维度层不同时出现
          unit             ← 与维度层不同时出现
          previous_value   ← period_change 类指标
          previous_date    ← period_change 类指标
          variants:        ← 有衍生变体时出现
            suffix:
              value
              date         ← 与父指标不同时出现
              pre_value    ← period_change 类变体
              pre_date     ← 与父指标不同时出现
```

### 维度层字段

| 字段 | 说明 |
|---|---|
| `latest_date` | 维度内所有指标日期一致时提升到此层（YYYYMMDD） |
| `unit` | 维度内所有指标单位一致时提升到此层（倍、%、元、港元、美元） |

### 指标字段（`indicators[base_id]`）

| 字段 | 说明 |
|---|---|
| `name` | 指标展示名 |
| `latest_value` | 最新值（已 round） |
| `latest_date` | 最新值日期（YYYYMMDD），与维度层一致时省略；财务指标可能是报告期 |
| `unit` | 单位，与维度层一致时省略 |
| `previous_value` | 上一期值，仅 `period_change` 类指标 |
| `previous_date` | 上一期日期（YYYYMMDD），仅 `period_change` 类指标 |
| `variants` | 衍生变体子对象，key 为变体后缀（如 `pctrank:1Y`、`quarter_yoy`、`ret:20`） |

### 变体字段（`variants[suffix]`）

| 字段 | 说明 |
|---|---|
| `value` | 该变体最新值 |
| `date` | 日期（YYYYMMDD），仅当与父指标 `latest_date` 不同时出现 |
| `pre_value` | 上一期值，仅 `period_change` 类变体 |
| `pre_date` | 上一期日期，仅当与父指标 `previous_date` 不同时出现 |

## 维度口径

| 维度 | 常见指标 |
|---|---|
| 估值 | `pe_ttm`、`pb_ratio`、`ps_ttm`、`dividend_yield` 及百分位（A股/港股/美股均覆盖） |
| 财务分析 | 毛利率、净利率、营业利润率、收入增速、ROE、ROIC、经营现金流等及 builder 变体（`:quarter_yoy`/`:ttm_level`/`:annual_yoy` 等） |
| 资金流向 | 成交额占比、换手均线、卖空比例、基金持仓等 |
| 波动率 | 年化波动率、标准差及百分位 |
| 宏观胜率背景 | 行业估值、情绪、换手等背景指标 |
| 资产走势 | `close_price` 及 `:ret:20/60/120/250` |
| 其他 | 新增但尚未映射到固定维度的指标 |

## 日内刷新注意

`close_price` 支持分钟级刷新。若后端 `realtime_value` 存在且 `realtime_computed_at` 距今小于 2 小时，返回的 `latest_value` 可能是分钟刷新值；否则是日频管线值。其他指标始终使用日频管线值。

回答时不要自行判断是否实时，除非返回字段能直接证明。可表述为“接口返回的最新值为……”。

## 错误处理

| 返回情况 | 处理 |
|---|---|
| `TASK_ID_REQUIRED` | 当前 session 异常；重新 `newSession` 后再试 |
| `ASSET_REQUIRED` | 参数缺失，修正为只传一个明确资产 |
| `ASSET_NOT_FOUND` | 告知资产无法识别，不用相似股票替代 |
| `indicators_count = 0` 或 `warnings` | 告知该资产暂无预计算指标数据，不改用模型常识补写 |
| 某维度 `indicators` 为空 | 说明该维度本轮无返回指标，跳过该维度 |
| HTTP 500 / 网络错误 | 受控失败，不改用外部网页或训练知识猜测 |

## 输出规则

1. 首句直接给指标画像结论，不说”已成功获取”。
2. 只引用返回的维度和指标，不补写未返回字段。
3. 对用户关注的维度优先展开；未明确关注时按”资产走势 → 估值 → 财务分析 → 资金流向 → 波动率 → 宏观胜率背景”排序。
4. 每个指标尽量包含：指标名、最新值、日期、上一期值。日期和单位可能在维度层级，注意合并读取。
5. `variants` 中的变体按需展开：用户问估值时展开百分位，问财务时展开 yoy/qoq/ttm 等口径。不必列出全部变体。
6. 不提供买卖建议、目标价或后市价格预测。