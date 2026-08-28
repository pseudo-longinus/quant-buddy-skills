# Workflow · 解读既有 QuantBuddy 活页

适用于用户提供 `pages.quantbuddy.cn/pages/...` 的既有 QuantBuddy 活页 URL，并要求“解读 / 分析当前活页 / 看看这页数据”。这是只读分析，不是建页、改页或范式复用。

```bash
python scripts/static_page.py interpret '{"url":"https://pages.quantbuddy.cn/pages/<owner>/<page_id>.html"}'
```

只调用一次 `interpret`。它调用 `getPageDetail?need_data=true`，由服务端鉴权后在原页面详情中附加 `interpretation_bundle`（公式包与 Data Grant 的当前结果）；不会下载 HTML，也不会返回或记录 signature。

随后直接基于 `data.page_context`、`data.packages`、`data.grants`、`data.interpretation_bundle.runtime_data` 和 `data.interpretation_bundle.warnings` 完成回答：先给一句话结论，再解释关键指标及变化、风险或异常，最后给出 3 个可继续追问的方向。用户自定义的解读要求优先于该默认结构。

若任一 `data.interpretation_bundle.runtime_data.grants[].data.mode` 为 `"csv"`，其 `csv_fields[].csv_url` 是可返回的临时下载链接。不要把链接当成已读取的数据：在任何计算前立即运行一次 `python scripts/static_page.py interpret_csv '{}'`。该命令读取紧邻上一条 `interpret` 的结果，下载并校验 CSV，保留 `csv_url`，并将数据补成 `results[].fields[].series`；若 `csv_hydration.failures` 非空，如实说明该字段不可用。不得重跑 `interpret`、另行调用数据接口或把签名 URL 交给用户。

不得调用 `trace_context.py`、`templates`、`template`、`direct_deliver`、`new_page`、fork、`download`、浏览器或文本搜索来处理此场景；不得创建、更新或发布页面。若返回错误或 `warnings`，如实说明缺失的数据源，不能用 HTML 或凭证提取作为降级路径。
