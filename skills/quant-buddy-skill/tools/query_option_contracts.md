# query_option_contracts — 美股期权槽位对应合约

开发接入：须部署配套 skill_server 路由及 dataServer Celery worker 后使用；不代表已发布。

POST /skill/queryOptionContracts。查询当前存储的历史选约映射，不查询完整期权链，不重新选券，不前填或复权。

## 何时调用
用户问对应合约、换约/换月，或要解释IV/价格/持仓量跳变时显式调用。
单纯读取IV数值不强制调用；资产输入复用既有多字段匹配，不强制用户提供市场后缀。查询日期必须与行情实际日期一致。

## 参数
- asset：必填，单个资产名称、简称或代码，如苹果、Apple、AAPL、AAPL.O；复用既有name/short_names/ticker/code匹配。仅支持部分美股标的期权，识别资产后再判断支持范围。
- 兼容旧ticker参数作为asset别名，二者只传一个；Celery内部仍使用解析后的标准ticker。
- start_date/end_date：均必填，YYYYMMDD整数/字符串或YYYY-MM-DD；按选约生效日；含首尾最多366自然日。查单日传相同值；不支持0、latest、自然日偏移。
- slots：省略查八槽，或1～8个不重复值：E1/E2分别搭配ATM-CALL、ATM-PUT、25C、25P。不得传ATM_CALL。
- mode：daily默认返回逐日映射；changes返回OCC换约记录及区间首条基准，基准行标记is_baseline=true且不重复。

示例：
~~~json
{"asset":"苹果","slots":["E1-25C"],"start_date":20260901,"end_date":20261008,"mode":"changes"}
~~~

## 解释结果
- data只有ticker、records；records每行扁平：trade_date、slot、contract、expiration、strike、call_put、changed、previous_date、previous_contract、previous_expiration、previous_strike。
- trade_date为生效日；contract直接是OCC代码字符串，没有内层contract对象。
- changed只表示OCC是否变化，无前序时null；previous_date是前一条记录日期，不保证相邻交易日。缺失日不前填。
- changes保留区间首条基准；首条本来是换约行时不再重复。仅规则/来源/分段变化不作为对外换约。
- 正常不返回warnings或notes。确有无映射记录或日期衔接缺口时才返回简短notes字符串数组。
- dataServer直接用skill_server已确认ticker查询underlying_ticker，不做额外资产确认。
- 无映射返回空records及notes，不等于没有上市期权。身份存在不代表行情已更新；只查询assignment与前序记录，不执行槽位行情、真实合约行情或checkpoint附加检查。
- strike保留Decimal字符串。源映射仍做完整内部校验，但审计字段不默认暴露，不增加detail模式。
- 当前历史修订、未核验正式交易日历、不含合约规格属于固定口径，不逐次警告。

前序到期日和行权价取自真实前序映射，无前序或旧worker未提供时为null，不解析合约代码推测。

## 错误
HTTP 400 / error.category=input：按error.parameter和error.usage修正，不原样重试。
404 ASSET_NOT_FOUND：尝试名称、简称或代码。新dataServer按标准ticker直查，无选约记录返回成功空records，不做历史空ticker回填或双向映射确认。OPTION_MAPPING_NOT_FOUND / OPTION_MAPPING_AMBIGUOUS仅兼容旧worker错误。
502数据/返回合同异常不猜结果。503暂不可用；504排队/执行/回传超时，后台任务不一定取消，不立即重复提交。
新旧部署未同步导致404/未知工具时停止，不试猜工具变体。
