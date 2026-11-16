# query_kline — 动态资产的日K线授权

授权结构参照asset_info：注册只保存窗口和技术指标，不保存ticker/asset。页面每次从当前业务状态取得asset，再以同一grant_id/signature查询。切换股票无需重注册。

## 注册合同与验证样例

```json
{
  "task_id":"当前任务",
  "user_query":"用户原话",
  "grants":[{
    "name":"kline",
    "asset":"SH600519",
    "contract":{
      "kind":"query_kline",
      "payload":{"limit_candles":120,"indicators":["ma5","ma20","boll","macd","rsi","volma5"]}
    }
  }]
}
```

将以上传给qbs_bridge.py validate_grant_set。外层asset是本轮验证样例，支持名称、简称、数字代码、带市场代码或标准ticker，与fast_query assets匹配规则一致。验证时以asset调用QBS快捷查询，并核对返回的asset_resolution和标准ticker，用于回复证据与快照；asset不写入注册payload、不参与授权合同指纹。成功后按返回的registration_params_file/registration_command登记，注册参数只含kind和规则。样例资产可从用户请求或本轮QBS已确认的数据/资产解析结果中取得，不能凭空编造。

payload允许为空对象或仅包含begin_date、limit_candles、indicators，禁止ticker/asset。begin_date为可选整数YYYYMMDD；根数默认120，1..2000；最多32个不同指标，支持maN/volmaN（1..250）、boll、macd、rsi、volume。单资产日频；不传end_date/period/adjust等未实现参数。

注册和refresh只做规则校验，不解析资产、不拉股票数据。实际行情是否可用须由独立验证或页面取数确认；不能把“授权注册成功”当作某只股票已有行情。保留既有首答、计划、路由和公开验收流程。

## 页面取数

```json
{"grant_id":"dg_...","signature":"...","asset":"贵州茅台"}
```

queryDataGrant只接受这三个字段。asset为单个名称或代码（非空字符串、最多100字符），沿asset_info的数据库确认能力解析为标准ticker。每次可以换资产，窗口和指标不可覆写。源未覆盖的资产按实际错误说明，不保证所有可识别资产都有日线。

响应data仍为schema_version=1的labels、OHLCV与indicator_data，所有列同轴等长；data.ticker是本次实际查询资产。缓存按本次标准ticker与固定规则区分，别名可复用同一资产缓存，不同资产不串数据。

快捷query_kline使用asset，例如{"asset":"贵州茅台"}；旧ticker参数仅保留标准代码兼容，不能与asset同时传。基础2RU、含任意计算指标整次3RU，仅volume仍2RU。授权注册/refresh各3RU，页面queryDataGrant为0RU。注册内部没有额外快捷查询账单；窗口/指标改变需重注册，换资产不需要。

## build_dashboard的页面资产源

```json
{
  "type":"candlestick",
  "grant_id":"dg_...",
  "asset":"SH600519",
  "asset_source":{"query_param":"asset"},
  "overlay_source":"grant",
  "open":"open","high":"high","low":"low","close":"close","volume":"volume",
  "overlays":["ma5","ma20","boll_up","boll_mid","boll_dn"],
  "volume_overlays":["volma5"],
  "x_range":{"start_date":"实际first_date"}
}
```

asset是页面默认值和构建时的验证资产，不是授权范围。asset_source可选，且只选一种：

- query_param：每次刷新读取当前URL的对应参数；缺省/空值回退到页面asset。URL带asset=SZ000001即可查看另一资产。
- selector：例如{"selector":"#asset-select"}，读取当前输入/选择控件的value；change事件刷新，空值回退到默认asset。自定义布局需真实提供该控件。

同一授权可绑定多个面板或多只资产。相同资产/来源共用输出，不同资产/来源分配独立输出；快速切换时旧响应不会覆盖新选择。主图和MACD/RSI等副图使用同一asset/asset_source，保证同源。

MA/BOLL在价格主图，成交量均线用volume_overlays绑定成交量轴；MACD的DIF/DEA用line、bar用bar，RSI用line。窗口内全null的指标不能填0冒充绘图成功。日期、单位、复权口径和预热不足提示沿原规则核验。

## 自定义页面和CLI

```javascript
const out = await QB.queryGrant({
  endpoint, grant_id, signature,
  asset: () => document.querySelector('#asset-select').value
});
```

asset也可直接传当前业务状态中的字符串；可由页面参数、页面资产上下文或选择控件得到。内核在每次调用开始时取得一次资产值，用于这次请求及其重试。绘图时使用返回data.ticker核对当前资产。

自定义HTML在发布验收时，还应声明可读取的默认来源JSON，例如：

```html
<script type="application/json" data-qb-query-assets>
[{"grant_id":"dg_...","signature":"...","asset":"SH600519"}]
</script>
```

这只是页面默认数据源声明，不会写入授权；运行时仍可传另一asset。标准build_dashboard会在BOOT中自动保留此信息。发布前的凭证核验逐个带入声明的默认asset，不会因缺少固定ticker而失败，也不能凭声明直接跳过真实取数。

CLI：data_grant.py query的参数中增加asset。通过materialize_snapshot恢复动态K线快照时也要显式传当前asset；快照记录该次资产与数据哈希，不能将一只股票的样例当作另一只的证据。

合同内部版本为2，返回数据schema_version仍为1。旧版本1固定ticker授权不会自动升级为跨资产能力，需要重新登记。有效期、撤销和轮换沿用原机制；本类型不接asset_info的LLM内容或收费，只复用其资产随请求传入的结构。
