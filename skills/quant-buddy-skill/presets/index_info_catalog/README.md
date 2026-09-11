# 系统数据名全量索引

本目录保存平台已支持的数据名，是 `presets/data_catalog.yaml` 的补充。

## 何时使用

- 常见行情、估值、财务字段先查 `presets/data_catalog.yaml`。
- 未命中时，用 `rg "关键词" presets/index_info_catalog` 搜索本目录。
- 公式中使用精确的 `index_title`，不要把用户口语词或分类名写进公式。
- 高频、已验证的数据名可由维护人员补进 `data_catalog.yaml`。

## 业务分类

- `a_share_financials.yaml`：A 股财务及报告期字段。
- `global_financials.yaml`：港股、美股财务字段。
- `a_share_trading_labels.yaml`：A 股龙虎榜标签数据。
- `macro_strategy.yaml`：示例、宏观及策略类数据。
- `a_share_option_iv.yaml`：A 股期权隐含波动率。
- `global_classification.yaml`：GICS 行业、板块所属指数。
- `manifest.yaml`：业务分类文件清单和记录数。

分类仅用于检索组织，不代表数据的原创归属。不要手工修改记录；维护流程及真实来源记录保存在用户侧 Skill 目录之外。
