# 页面形态骨架（bespoke templates）

可复制的 bespoke 页面骨架。不是在线模板接口（那部分见 [templates/README.md](../../templates/README.md)），
也不含真实数据凭证；复制后按对应指南替换内容并编译。

| 骨架 | 用途 | 指南 |
| --- | --- | --- |
| `commodity-factor-watch-v1.html` | 「N 因子观察台 / 涨跌怎么看」类页面：结论前置 hero、N 因子卡、分组图表、口径折叠；参考实现为原油六因子 | [guides/factor-watch-pages.md](../../guides/factor-watch-pages.md) |

编译：`python scripts/compile_bespoke_page.py @params.json`（替换 CONFIG 三件套与图表 panel_block 后）。
验收：`node scripts/verify_page.mjs <html> --profile self-built --require-browser`，因子页自动附加结构硬门槛。
