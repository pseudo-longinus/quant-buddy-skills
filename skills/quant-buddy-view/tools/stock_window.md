# stock_window — legacy 单股页滚动时间窗口

用于 `stock_analysis_instance_v1` 旧版单股页。页面没有 `QBV_RENDER_JS_START/END`，`chart_edit.py set_window` 返回 `LEGACY_PAGE / NO_RENDER_JS_MARKER` 时，不要手写或执行 `output/*.py` 补丁；使用本受控转换器。

```powershell
python scripts/stock_window.py apply @output/stock-window.json
```

参数：

```json
{
  "html_file": "output/pages/page_xxx.original.html",
  "out_file": "output/pages/page_xxx.stock-window.html",
  "lookback_days": 365,
  "label": "最近一年",
  "task_id": "task_xxx"
}
```

也可用 `start_date:"YYYY-MM-DD"` 代替 `lookback_days`。脚本只接受 `stock_analysis_instance_v1`，按固定 runtime seam 失败关闭；它会把折线、柱图、数据表和技术图裁剪到同一滚动窗口，并保留原 Data Grant、Card Runtime、Share Shell 与页面身份。

脚本只生成本地 HTML，不发布。成功后必须按顺序执行：

```powershell
node scripts/verify_page.mjs output/pages/page_xxx.stock-window.html --require-browser
python scripts/static_page.py update @output/update-page.json
node scripts/verify_page.mjs https://pages.quantbuddy.cn/pages/.../page_xxx.html --require-browser --card-runtime
```

`update-page.json` 必须携带原 `page_id`、本轮 `task_id` 和上述 `html_file`。不得创建新页面，不得在本地转换成功后停止。
