# query_kline — 日K线数据与技术指标

`POST /skill/queryKLine`，需API Key。用单个asset查询，返回可直接绘图的日频OHLCV与已计算指标，不返回图片。不需要先跑公式。

```json
{"asset":"贵州茅台","limit_candles":120,"indicators":["ma5","ma20","boll","macd","rsi","volma5"]}
```

- `asset`必填，单个名称、简称或代码字符串，长度不超过100字符。复用fast_query的assets数据库匹配：如贵州茅台、茅台、600519、600519.SH、SH600519；港美股支持已有港股代码归一化、英文裸代码等逻辑，匹配与行情覆盖以实际返回为准。不能传assets数组。旧ticker参数仅兼容标准代码，与asset互斥；新调用统一传asset。
- `begin_date`可选，合法整数YYYYMMDD，表示显示起始下界；不晚于当前业务日期。
- `limit_candles`默认120，整数1～2000。先按begin_date过滤，再取最近N根；不传begin_date适合持续滚动窗口。
- `indicators`默认[]，字符串数组，服务端统一小写去重；最多32个不同指标。支持maN/volmaN（N=1..250）、boll(20,2)、macd(12,26,9)、rsi(14)、volume。没有ema/kdj/boll20别名。
- 仅日频；不传end_date/period/adjust/fields/title/width/show_volume等参数。分钟、周/月线或多资产沿对应专用工具，不用本接口偷换频率。

基础OHLCV为2RU，仅volume仍2RU；存在任意计算指标后整次3RU，多个指标不累加。快捷查询与后续授权注册是两次调用，分别计费；授权注册仅校验窗口和指标，不试跑股票；发布前QBS/QBV按页面当前资产验证取数。

调用：`python scripts/call.py query_kline @params.json`，沿用当前task_id/turn_id。平台已有同名原生工具时直接调用。

响应data含schema_version:1、标准ticker、asset_resolution:{asset,ticker}、period:1d、labels、open/high/low/close/volume、indicators、indicator_data、data_points、first_date/last_date、fetched_at、warmup_days、warnings。asset_resolution记录本次输入与解析代码，用于核对名称查询；所有列按同一日期轴对齐、等长；日期为YYYYMMDD字符串。

指标输出：maN/volmaN同名；boll→boll_mid/boll_up/boll_dn；macd→macd_dif/macd_dea/macd_bar，bar=2×(DIF−DEA)；rsi同名。indicator_data各列在完整计算后统一四舍五入到最多3位小数，返回数值而非字符串，不补末尾零；原始OHLCV保持原值，快捷查询和授权取数相同。预热段不返回，历史不足时返回null和INSUFFICIENT_HISTORY，不能补0或宣称指标完整。零成交量有效，缺失量为null。

业务首答使用实际first_date/last_date/data_points及末日close和所选指标值，注明日频与数据警告。fetched_at是拉取时间，last_date不保证已收盘或盘中实时；未返回单位、币种或复权口径时如实说明未核验。

普通日K线活页继续 [K线快路径](../workflows/kline-page-fast-path.md)：先答，再交给QBV注册kind=query_kline，payload只保留begin_date/limit_candles/indicators，禁止ticker和asset。注册/重新校验各3RU且不查股票，页面queryDataGrant为0RU；取数提交grant_id/signature/asset，资产由页面URL、选择控件或当前业务状态提供，同一授权可以换资产。只固定窗口和指标；新增指标仍须重新验证并注册，保持原page_id更新。只有明确只要图片时才用renderKLine。
