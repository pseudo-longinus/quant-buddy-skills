# 系统数据名全量索引

本目录保存平台已支持的 `indexInfo` 数据名清单，由开发维护工具从 Excel 导出文件生成。它是 `presets/data_catalog.yaml` 的补充，而不是替代。

## 何时使用

- 常见行情、估值、财务字段：先查 `presets/data_catalog.yaml`。
- `data_catalog.yaml` 没有命中时，再用 `rg "关键词" presets/index_info_catalog` 搜索本目录。
- 命中候选后，公式中使用精确的 `index_title`，不要把用户口语词直接写进公式。
- 高频、已验证、对 Agent 常用的数据名，可以人工补进 `data_catalog.yaml`。

## 文件说明

- `join_quant_fa.yaml`：A 股财务/报告期字段。
- `fmp_fa.yaml`：港股/美股财务字段。
- `guanzhao_lhb.yaml`：A 股龙虎榜标签数据。
- `guanzhao.yaml`：示例/宏观/策略类数据。
- `rice_quant_fa.yaml`：A 股期权隐含波动率。
- `fmp.yaml`：GICS 行业/板块所属指数。
- `fa_jqdata.yaml`：旧 jqdata 财务字段。
- `manifest.yaml`：导入来源、记录数、sha256 和列名校验结果。

## 查询示例

```bash
rg "归母净利润" presets/index_info_catalog
rg "EBITDA" presets/index_info_catalog
rg "龙虎榜" presets/index_info_catalog
rg "GICS" presets/index_info_catalog
```

## 维护方式

不要手工编辑记录行。需要更新时，在仓库根目录运行开发维护脚本：

```bash
python dev-tools/import_index_info_catalog.py <indexInfo_*.xlsx>...
```

导入脚本位于 skill 运行时目录外，不会作为用户侧 skill 命令发布。
