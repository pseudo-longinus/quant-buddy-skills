# query_option_contracts — 美股及国内商品期权槽位合约

`POST /skill/queryOptionContracts`。只读 assignment 与必要同表前序，不重选、不前填，不附加行情检查。
国内功能需部署新增dataServer任务及配套skill_server；Skill更新不等于服务上线。

## 何时调用

查询槽位当前对应合约、空槽或最近换约，解释拼接IV/价格/持仓量跳变时使用。
仅查IV数值不强制附加本工具；不能把拼接价变化当作持有同一合约的收益。

## 参数

- `asset` 必填，单个名称、简称或代码，如 苹果、AAPL、螺纹钢、RB、RB.SHF，按既有多字段匹配，不强制后缀。
  国内按商品品种查询，不接受具体月份期货合约；股指期权暂未开放。歧义时按候选代码修正。
- `query_type` 必填：snapshot/window。
- `slots` 可选，省略全部八槽；1～8个不重复值：E1/E2搭配ATM-CALL、ATM-PUT、25C、25P，不传ATM_CALL。
  E1/E2遵循存储选约规则，不等于期货主力/次主力。
- snapshot禁止lookback_days/mode，每槽最多一条最新已生效记录；国内请求槽来自同日完整批次。
- window必须提供整数lookback_days:1～366，按自然日包含市场截止日期，不是交易日；mode默认daily，也可changes。
- task_id是可选追踪信息，不要求用户提供。

```json
{"asset":"螺纹钢","slots":["E1-ATM-CALL","E1-25P"],"query_type":"snapshot"}
```

```json
{"asset":"RB.SHF","slots":["E1-ATM-CALL"],"query_type":"window","lookback_days":90,"mode":"changes"}
```

美股以America/New_York当地今天为截止日；国内使用北京时间及已开始交易时段所属交易日，
有夜盘品种在夜盘开始后按下一交易日归属，节假日和无夜盘品种按交易日历及品种配置判断。
窗口起始日=截止日减N−1个自然日。公开query_type/lookback_days由skill_server转换，
各市场Celery任务仅接收ticker/start_date/end_date/slots/mode；不新增检查任务。

## 简洁结果

`data={ticker,records,notes?}`，国内另有product_id。美股保留十一项扁平字段：
trade_date/slot/contract/expiration/strike/call_put/changed/previous_date/previous_contract/previous_expiration/previous_strike。
国内增加decision_date、underlying_contract、status，仅empty行附empty_reason。

- trade_date是实际生效日，decision_date是决策日；T+1指下一交易日。不能把旧记录日期改为今天。
- underlying_contract来自真实合约规格，不用选约锚点代替、不从合约代码猜测。
- status=empty是成功查询到的空槽；合约及其规格为null，按empty_reason说明。不能跳过它找旧active合约。
- changed表示与同槽真实前序比较，无前序为null。国内active↔empty也计为变化，empty→empty不计。
  previous_date非null而previous_contract为null，表示前序为空槽；所有前序字段null表示无前序。
- changes保留窗口每槽首条基准，额外保留时is_baseline=true；日期无记录不前填。
- strike为精确十进制字符串；正常不展示审计树或固定warnings。空records不代表市场没有期权。
- 映射不代表close/IV已更新或合约仍可交易；当前修订映射不保证等同于某次历史矩阵发布批次。

## 活页持续更新

QBV使用kind:option_contracts，payload沿用公开参数。先通过bridge验证真实数据再注册，网页只嵌入grant_id/signature。
授权冻结标准品种、市场、槽位及窗口规则，取数时重新解析日期；无需公式包。
按每行真实trade_date展示，与旧行情对应时使用同日映射，不把最新snapshot合约贴到历史行情。
QBV标准合约表支持空槽、真实标的及空槽原因；实际刷新失败按已有流程保留上次有效内容并提示。
详见QBV tools/data_grant.md。

## 错误

- 400按error.parameter/error.usage修正，不原样重试；月份期货合约改用品种，歧义资产使用候选代码。
- 502是上游身份、批次或协议异常，不能补旧批次或猜测结果。
- 503可能是服务不可用、品种元数据或交易日历覆盖不足；联系维护者，不自行造交易日历。
- 504包含排队/执行/回传超时，后台任务可能还在执行，不立即重复提交。
- 未知工具/接口说明配套尚不可用，停止并如实说明。
