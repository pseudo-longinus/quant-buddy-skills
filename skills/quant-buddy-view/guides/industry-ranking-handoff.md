# 行业排名：一次验证，原合同交接

行业范围、窗口和排序口径按用户问题确定；先查数并回复，再建页。普通无建页意图的QBS行业查询不因本指南触发建页。

1. 先用 `qbs_bridge.py validate_package_set` 查询并验证完整公式合同，替代“先run一遍，再改写公式重复validate”。`packages:[{name,formulas,reads,begin_date}]`；完整截面用 `reads:[{"output":"实际输出名","read_mode":"last_column_full","mode_params":{"max_rows":100,"allow_zero_values":true}}]`，不只保留前后几行。函数和字段来自QBS目录，不能猜名称。
2. 从成功的 `validation_outputs` 取真实data_id，必要时一次readData核对日期、31行业覆盖和数值，发送完整业务首答。已经有同合同完整结果则直接复用。日涨跌的当前截面不改成最近一分钟收益，分钟参数按实际请求与证据保留。
3. 首答后才查templates、决定direct/fork/unmatched、创建或复用首链。行业排名不能继承单股票数据合同；可借鉴样式时保留Compose及研究来源门禁。
4. 注册只执行验证返回的 `registration_command` / `registration_params_file`，不重写公式、reads、日期、task或指纹。`registration_capability=unsupported_minute_package` 时停止该注册路径，不能删分钟标志或改日频来绕过。
5. 原样交接注册收据、角色与页面ID，按已选模式构建和公开验收。遇到宿主明确不支持执行计划/Compose命令时记录能力阻断，不猜命令别名、不换另一脚本绕过限制；保留首答并报告页面未完成。

注册参数文件只是本次已验证合同的可执行副本，不代表已注册、已建页或首答已经送达。完整截面随合同保留，显示TopN时保持原始正负号。
