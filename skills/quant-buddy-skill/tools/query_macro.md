# query_macro — 宏观及一维时序指标快捷查询

> 通过指标简称（`index_short_title`）或 `indexinfo_id` 直接读取 `indexInfoCore` 宏观经济、利率汇率、大宗商品现货及全球股指等一维时序指标，**仅返回原始值**，无需先走 `confirmDataMulti` + `runMultiFormulaBatchStream`。

## 端点

`POST /skill/queryMacro`

## 适用场景

- 查单个或多个宏观指标的最新值或历史某个时点快照（`mode: "snapshot"`），例如：`中国CPI同比`、`中国PPI同比`、`中采PMI`、`中国10年国债收益`、`美国PCE同比`、`WTI原油连续`、`标普500`。
- 查一个或多个宏观指标在指定日期区间内的连续原始时间序列（`mode: "series"`）。
- 需要对宏观指标做剪刀差、相关性、自定义组合或回测等**二次公式计算**时，改走 `runMultiFormulaBatchStream`；仅导出 CSV 时也可对 `macro_indicators.yaml` 中的 `id` 直接调用 `downloadData`。
- 活页/看板需要免 Key 持续读取宏观数据时，支持通过 QBV Data Grant（`kind: "query_macro"`）注册数据授权。

## 参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `indicators` | string[] | ✅ | — | 指标名称（优先使用 `presets/index_info_catalog/macro_indicators.yaml` 中的精确 `index_title`）或 24 位 hex `id`，单次 1~50 个 |
| `mode` | string | ❌ | `"snapshot"` | `"snapshot"`（最新或 `as_of_date` 截至时点快照）/ `"series"`（日期区间连续序列） |
| `as_of_date` | number \| string | ❌ | — | 仅 `snapshot` 有效；截至日期，支持 `YYYYMMDD` 或 `YYYY-MM-DD`。不传时取最新有效值 |
| `start_date` | number \| string | `series` 必填 | — | 起始日期，支持 `YYYYMMDD` 或 `YYYY-MM-DD` |
| `end_date` | number \| string | ❌ | 当天 | 结束日期，支持 `YYYYMMDD` 或 `YYYY-MM-DD` |
| `nan_handling` | string | ❌ | `"keep"` | 仅 `series` 有效：`"keep"`（保留 `null`）/ `"fill_forward"`（向前填充） |
| `decimal_places` | number | ❌ | `4` | 保留小数位，0~10 的整数 |
| `task_id` | string | ❌ | 自动注入 | 任务 ID |

## 返回格式

> **频率与日期说明**：不同宏观指标发布频率不同（GDP 季频、CPI/PPI/社融月频、库存周频、国债/汇率/股指日频）。`snapshot` 模式按 `as_of_date` 对每个指标独立向前回溯取最后一个有效观测值，并在每条结果中返回其真实观测日期 `date`；接口**仅返回原始值**，不自动计算上期值或环比/同比变化量。

### `mode = "snapshot"`

```json
{
  "code": 0,
  "data": {
    "mode": "snapshot",
    "as_of_date": 20261127,
    "results": {
      "中国CPI同比": {
        "id": "66122a4fcc1471d4a418bb5e",
        "index_short_title": "中国CPI同比",
        "index_title": "中国:CPI:当月同比",
        "timezone": "Asia/Shanghai",
        "date": 20261031,
        "value": 0.3
      },
      "中国10年国债收益": {
        "id": "66122a4fcc1471d4a418bb69",
        "index_short_title": "中国10年国债收益",
        "index_title": "中国:中债国债到期收益率:10年",
        "timezone": "Asia/Shanghai",
        "date": 20261126,
        "value": 2.15
      }
    },
    "meta": {
      "requested_count": 2,
      "resolved_count": 2,
      "returned_count": 2,
      "elapsed_ms": 42
    }
  }
}
```

### `mode = "series"`

```json
{
  "code": 0,
  "data": {
    "mode": "series",
    "start_date": 20260101,
    "end_date": 20261127,
    "nan_handling": "keep",
    "results": {
      "中国CPI同比": {
        "id": "66122a4fcc1471d4a418bb5e",
        "index_short_title": "中国CPI同比",
        "index_title": "中国:CPI:当月同比",
        "timezone": "Asia/Shanghai",
        "dates": [20260131, 20260228],
        "values": [0.5, 0.4],
        "count": 2,
        "is_truncated": false
      }
    },
    "meta": {
      "requested_count": 1,
      "resolved_count": 1,
      "returned_count": 1,
      "elapsed_ms": 58
    }
  }
}
```

部分指标未命中或区间无有效数据时，已命中的指标仍正常返回，未命中项记录在 `indicator_errors[]` 中（`INDICATOR_NOT_FOUND` / `DATA_UNAVAILABLE`）。

## 调用示例

```bash
# 1) 最新多指标宏观快照（Windows PowerShell 使用 @file 传参）
python scripts/executor.py queryMacro @/tmp/macro_snapshot.json
# /tmp/macro_snapshot.json:
# {"indicators": ["中国CPI同比", "中国PPI同比", "中采PMI", "中国10年国债收益"], "mode": "snapshot"}

# 2) 历史某个时点的宏观快照
python scripts/executor.py queryMacro @/tmp/macro_asof.json
# {"indicators": ["中国CPI同比", "中国PPI同比"], "mode": "snapshot", "as_of_date": 20251231}

# 3) 区间连续原始序列
python scripts/executor.py queryMacro @/tmp/macro_series.json
# {"indicators": ["中国CPI同比", "中国PPI同比"], "mode": "series", "start_date": 20240101, "end_date": 20261127}
```
