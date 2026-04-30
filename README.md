# quant-buddy-skills

A股、港股、美股量化分析 Agent Skill，支持实时行情、财务数据查询、选股、因子计算、策略回测等。遵循 [Agent Skills 规范](https://agentskills.io/specification)，可通过 `npx skills` 一键安装到本地 IDE。

官网：[https://www.quantbuddy.cn](https://www.quantbuddy.cn)

## Skills

| Skill | 描述 |
|-------|------|
| quant-buddy-skill | 查询 A 股、港股、美股的行情、估值、财务数据；支持选股筛选、因子计算、策略回测、净值对比、图表渲染 |

## 安装

### npx（推荐）

```bash
# 首次安装（新用户）——一次装到全局所有检测到的 Agent（Claude Code、Cursor、Copilot 等）
npx skills add pseudo-longinus/quant-buddy-skills -g --all

# 版本更新（已安装过的老用户）
npx skills update pseudo-longinus/quant-buddy-skills -y
```

> **Windows 用户**：若安装时报 symlink / 权限错，命令末尾追加 `--copy` 重试：
> ```bash
> npx skills add pseudo-longinus/quant-buddy-skills -g --all --copy
> ```
>
> 不知道当前装在哪，运行 `npx skills list -g --json` 可查。

安装时会提示选择目标 IDE（Claude Code、GitHub Copilot、Cursor、Windsurf 等），以及全局安装或项目级安装。

### 手动安装

**Claude Code**

```bash
git clone https://github.com/pseudo-longinus/quant-buddy-skills.git
cp -r quant-buddy-skills/skills/quant-buddy-skill ~/.claude/skills/
```

**GitHub Copilot**

```bash
cp -r quant-buddy-skills/skills/quant-buddy-skill ~/.copilot/skills/
```

**Cursor / Windsurf / 其他**

参考 [npx skills 支持的 IDE 列表](https://www.npmjs.com/package/skills#supported-agents)，将 `skills/quant-buddy-skill/` 目录复制到对应路径。

## 配置

安装后，首次使用前需要配置 API Key：

1. 前往官网 [https://www.quantbuddy.cn](https://www.quantbuddy.cn) 注册并获取 API Key
2. 编辑 skill 目录下的 `config.json`，将 `api_key` 字段填入你的 Key
3. 或者在 skill 激活后按照认证向导完成手机号登录

## 数据覆盖范围

| 市场 | 行情 | 估值（PE/PB/市值） | 财务数据 |
|------|------|-------------------|---------|
| A 股（沪深主板/创业板/科创板/北交所） | ✅ | ✅ | ✅ |
| 港股 | ✅ | ❌ | ❌ |
| 美股（NASDAQ / NYSE / AMEX） | ✅ | ❌ | ❌ |
| 主要宽基指数（沪深300、中证500等） | ✅ | ✅ | — |

## 联系作者

<p align="center">
  <img src="assets/wechat_qr.jpg" width="180" alt="微信二维码" />
  <br/>
  <sub>扫码添加微信，欢迎交流量化投研</sub>
</p>

## License

MIT
