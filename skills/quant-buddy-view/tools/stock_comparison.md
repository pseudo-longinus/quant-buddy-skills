# stock_comparison — 扩展原生股票收盘价图

`scripts/stock_comparison.py` 专用于 `stock_analysis_instance_v1` 页面增加沪深300等基准序列。它不会创建第二个图表 renderer，而是把 Formula Package 查询、双 Y 轴渲染和数据表列并入页面原生的 `load/render/table` 生命周期。

## 为什么不能用 panel_block

这类页面的 `#priceChart` 已由原生 stock runtime 管理。若再用 `build_dashboard.py emit="panel_block"` 指向同一容器，会形成两个异步 owner：Formula Package panel 可能先画出双线，原生 Data Grant 随后完成时会清空容器并重建单线图，最终表现为图表闪现后消失或基准线丢失。

因此合同固定为：

- `#priceChart` 始终只有原生 stock runtime 一个 owner；
- 通用 `panel_block` 遇到该组合返回 `STOCK_CHART_OWNER_CONFLICT`；
- 基准序列必须通过本脚本扩展原生生命周期。

## 调用

```powershell
python scripts/stock_comparison.py apply @stock-comparison.json
```

参数示例：

```json
{
  "html_file": "C:/path/source.html",
  "out_file": "C:/path/source.stock-comparison.html",
  "package_id": "pkg_xxx",
  "signature": "由本地凭证补全时可省略",
  "benchmark_output": "HS300_CLOSE",
  "benchmark_name": "沪深300",
  "benchmark_unit": "点",
  "primary_name": "收盘价"
}
```

| 字段 | 必填 | 说明 |
|---|---:|---|
| `html_file` / `html` | 是 | 原始 `stock_analysis_instance_v1` 页面；二选一 |
| `out_file` | 条件必填 | 传 `html` 时必填；传 `html_file` 时默认生成同目录 `.stock-comparison.html` |
| `package_id` | 是 | 已注册 Formula Package |
| `signature` | 否 | 缺省时按 `package_id` 从本地公式包凭证读取；不会写入 CLI 返回 |
| `benchmark_output` | 是 | 包内基准序列 output，例如 `HS300_CLOSE` |
| `benchmark_name` | 否 | 图例和表头名称，默认使用 output |
| `benchmark_unit` | 否 | 右轴单位，默认“点” |
| `primary_name` | 否 | 左轴主序列名称，默认“收盘价” |
| `endpoint` | 否 | Formula Package 查询端点，默认使用 QBV 配置 |

## 兼容与失败关闭

脚本只支持当前已知的 `stock_analysis_instance_v1` runtime，并要求每个补丁 seam 精确命中一次。版本不符、seam 缺失/重复、ECharts CDN 不是恰好一份、凭证或 output 缺失时都会失败，并且不会写入部分目标文件。

重复执行是幂等的：配置会更新为本次参数，runtime marker `QBV_STOCK_COMPARISON_RUNTIME:v1` 保持一份。基准点按 data-kernel 的正式 `{d,v}` 合同读取，并用 `QB.fmtDate(p.d)` 归一化日频日期，与 Data Grant 的日期轴对齐。

## 验收

本地和公网都必须运行真实浏览器验证：

```powershell
node scripts/verify_page.mjs C:/path/source.stock-comparison.html --profile fork-local --require-browser
node scripts/verify_page.mjs https://pages.quantbuddy.cn/pages/.../page_xxx.html --profile public-smoke --require-browser
```

通过条件包括：

- runtime pending 归零后再经过稳定窗口，图表实例和最终 canvas 仍存在；
- 主序列与基准序列都有有效点，并存在足够共同交易日；
- 基准线使用右侧 Y 轴，页面有双 Y 轴；
- 数据表包含主序列与基准列；
- 桌面、390px、320px 无关键横向溢出；
- 无核心控制台错误。

更新已发布页面时继续使用原 `page_id` 和原 `task_id` 执行 `static_page.py update`，不得创建替代页面。
