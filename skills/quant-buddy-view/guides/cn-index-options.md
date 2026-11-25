# 国内股指及ETF期权槽位页面

用户要求展示下列股指或ETF的期权槽位行情、IV、持仓量或成交额时读取。`国内期货期权-*` 存放日频槽位行情。股指期权的数据列分别为沪深300主连（IF.CFE / IO）、上证50主连（IH.CFE / HO）、中证1000主连（IM.CFE / MO），括号后半部分是期权品种代码，不是数据列ticker。ETF期权数据列为南方中证500ETF（SH510500）、华夏科创50ETF（SH588000）、易方达创业板ETF（SZ159915）。

## 数据通道

1. 沿正常Trace、QBS先答、模板或自建流程处理。QBS已有本轮计算胶囊时复用；没有时通过bridge按QBS `workflows/cn-index-options.md` 查询精确数据标题与实际资产维度，先区分ETF现货、ETF期权和股指期权，再取对应数据；例如 `SH510500` 的现货K线不能用作该ETF的期权槽位行情。
2. 行情目录提供 E1/E2 × ATM-CALL/ATM-PUT/25C/25P × 收盘价/隐含波动率/持仓量/成交额32个字段。只验证用户所需槽位、字段和时间范围；标题例如 `国内期货期权-E1-25C-隐含波动率`，各标的实际缺口以查询为准。
3. 使用QBS已验证的完整公式合同登记Formula Package，再按原有收据、资源归属、首次取数及发布验收合同绑定页面；不能将这些目录字段当作 `fast_query` 白名单，也不能用 `kind:option_contracts` 取得行情。
4. `option_contracts`只读取具体合约映射，当前未开放上述股指和ETF的具体合约映射。若用户还要合约代码、行权价、到期日或换约，保留可交付的行情模块，单独说明映射缺口，不能编造合约或因为该限制删除行情。
5. 期权槽位 1 分钟行情及分钟 `self_iv`/`self_delta` 使用 `fast_query_option_minute` Data Grant（`kind: "fast_query_option_minute"`，详见 `tools/data_grant.md`），先通过 QBS `fast_query_option_minute` 实测出数再注册；若后台尚未开放股指/ETF 分钟会返回 `UPSTREAM_UNDERLYING_NOT_YET_SUPPORTED`，如实披露缺口，不用现货分钟代替。
6. 完整期权链合约列表/T 型报价截面使用 `option_chain` Data Grant（底层 `query_option_chain`，行内自带同日 `slots` 槽位标识，ETF 自动带名称/除权系列/乘数）；具体期权合约或局部期权链分钟走势/日内波动率微笑使用 `option_chain_minute` Data Grant（底层 `fast_query_option_chain_minute`，16 列自带 `expiration`/`strike`/`option_type`，超阈值自动 CSV）。长期活页优先冻结 `date_mode: "current_trade_day"` + `expiry_ranks` + `atm_strike_steps`，避免合约到期或标的大幅波动后数据失效。

## 页面口径

- 按 [研究与数据合同](research-data-contract.md#解释数据口径与用途)，在相关图表旁说明每个槽位显示按规则选出的代表合约，适合比较同口径日频 IV 或活跃度。标明实际标的、E1/E2、槽位、字段日期和单位；self-IV 原始小数 0.25 展示为 25%。数据列使用主连维度不等于股指期权以期货合约为法律标的。
- E1/E2不等于期货主力/次主力；拼接价格变化不等于持有同一合约的收益。
- 按标的称“股指期权槽位行情”或“ETF期权槽位行情”。期权分钟行情需另行验证，不能用ETF现货分钟数据代替。全链须有全部请求到期月、行权价和认购/认沽覆盖证据，32个目录字段不是全合约清单。
- 保留真实缺值和日期，发布可用模块并说明缺口；不能因映射接口拒绝或某槽无值，扩大为该类期权数据不可用。
