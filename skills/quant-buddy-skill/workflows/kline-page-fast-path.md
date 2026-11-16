# K线活页快路径（QBS → QBV）

适用于单资产日K线/蜡烛图/OHLC/开高低收活页。先读 [query_kline](../tools/query_kline.md)。分钟和多资产沿相应专用工具；只有明确只要PNG/图片时进入旧的renderKLine流程。

## 数据与首答

1. 确认用户的单个资产名称、简称或代码和窗口；可直接使用asset，由服务端按fast_query相同规则解析。
2. 调用query_kline，例如 `{"asset":"贵州茅台","limit_candles":120,"indicators":["ma5","ma20","macd"]}`。核对返回的标准ticker与asset_resolution。取得同轴OHLCV和服务端指标，无需逐字段fast_query或自写MA公式。普通日K线活页不调用图片型renderKLine。
3. 核对实际first_date、last_date、data_points、末日收盘价与指标值，保留warnings。均线/BOLL/MACD/RSI预热已由服务端处理；历史不足的null不能补0。
4. 发送本轮完整业务首答：资产、实际窗口、日频、所选指标及其周期、最新值和限制。单位/复权未返回时说明未核验，不能用请求起点或今天冒充实际数据日期。

基础OHLCV/仅volume为2RU；含任意计算指标整次3RU。一次选择多个指标不会按条累加。

## 活页交接

沿answer-first的 `prepare-validated-page` 生成Capsule/Handoff/Job：kline角色的contract为 `{"kind":"query_kline","payload":{"limit_candles":120,"indicators":["ma5","ma20","macd"]}}`，data或artifact_file保存本轮真实结构化结果；page_intent.primary_visualization为candlestick。不得改用只接受fast_query格式的prepare-fast-query-page来包装新响应。ticker/asset/task_id/turn_id不塞进授权payload。资产放在asset_resolution、本轮数据或页面asset中；QBV验证时用外层asset作为样例，它不参与注册合同。

QBV按其 `tools/query_kline.md` 使用validate_grant_set验证该合同并生成注册参数，再登记kind=query_kline；合同只含窗口和指标，样例asset在合同外，注册与refresh不取数。已由QBV验证的合同和收据沿用，不重复验证同一个未改动合同。授权注册与重新校验各3RU，页面凭grant_id/signature取数0RU。

QBV candlestick面板直接绑定这一份Grant：

```json
{"type":"candlestick","grant_id":"dg_...","asset":"SH600519","asset_source":{"query_param":"asset"},"overlay_source":"grant","open":"open","high":"high","low":"low","close":"close","volume":"volume","overlays":["ma5","ma20"],"x_range":{"start_date":"实际first_date"}}
```

overlays只填已请求且有效的价格指标；BOLL用boll_up/boll_mid/boll_dn，volma使用volume_overlays绑定成交量轴，MACD/RSI用同源副图。构建与公开验收核对同一Grant的实际日期、OHLCV和指标后补真实链接。

## 同页追加指标

用户说“加MA20”时，将ma20纳入query_kline指标列表重新查询核对，先说明真实值、区间和口径，再交QBV验证并注册新合同，以原page_id更新原页。页面不能通过queryDataGrant参数自行增加授权外指标。纯标题、颜色、布局维护沿现有同页维护规则，无需重新查数。

同一query_kline Grant内的指标列使用 `overlay_source:"grant"`，避免将ma20等列名误识别为独立公式包产出；历史跨来源公式overlays继续沿原规则。

切换资产时沿用同一grant_id/signature，每次queryDataGrant传asset（名称或代码）；页面默认asset不属于授权范围。仅修改指标/窗口时需重新注册。
