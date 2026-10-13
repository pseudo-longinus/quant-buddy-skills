"""Build auditable candidate params for the A-share value-quality page.

This helper never publishes and never registers by default.  It emits the exact
formula/read contract and the build_dashboard spec so registration, local page
build, and public acceptance can be reviewed separately.
"""
import json
import sys
from pathlib import Path
from typing import Optional

TITLE = "A股盈利估值性价比 Top20"
PREFIX = "低PE高ROE_"
FORMULAS = [
    PREFIX + '条件=("A股市盈率（PE, TTM）〔估值数据〕">0)*("A股净资产收益率ROE">0)*板块(万得全A)',
    PREFIX + '排序值="低PE高ROE_条件"*("A股净资产收益率ROE"/"A股市盈率（PE, TTM）〔估值数据〕")',
    PREFIX + 'Top10掩码=取前("低PE高ROE_排序值",10)',
    PREFIX + 'Top20掩码=取前("低PE高ROE_排序值",20)',
    PREFIX + 'Next10掩码="低PE高ROE_Top20掩码"-"低PE高ROE_Top10掩码"',
    PREFIX + 'Top10Score=取前("低PE高ROE_排序值",10,返回数值)',
    PREFIX + 'Next10Score="低PE高ROE_Next10掩码"*"低PE高ROE_排序值"',
    PREFIX + 'Top10PE="低PE高ROE_Top10掩码"*"A股市盈率（PE, TTM）〔估值数据〕"',
    PREFIX + 'Next10PE="低PE高ROE_Next10掩码"*"A股市盈率（PE, TTM）〔估值数据〕"',
    PREFIX + 'Top10ROE="低PE高ROE_Top10掩码"*"A股净资产收益率ROE"',
    PREFIX + 'Next10ROE="低PE高ROE_Next10掩码"*"A股净资产收益率ROE"',
]
OUTPUTS = [PREFIX + name for name in (
    "Top10Score", "Next10Score", "Top10PE", "Next10PE", "Top10ROE", "Next10ROE"
)]


def package_params(begin_date: int = 20250101) -> dict:
    return {
        "name": "A股盈利估值性价比Top20候选",
        "formulas": FORMULAS,
        "include_description": True,
        "use_minute_data": False,
        "force_reusable_array": OUTPUTS,
        "reads": [{"output": output, "read_mode": "last_column_full",
                   "mode_params": {"max_rows": 20}} for output in OUTPUTS],
        **({"begin_date": begin_date} if begin_date else {}),
    }


def dashboard_spec(package_id: str, signature: str, endpoint: str) -> dict:
    if not package_id or not signature or not endpoint:
        raise ValueError("候选页需要package_id、signature和endpoint")
    labels = {
        PREFIX + "Top10Score": "ROE/PE Top10",
        PREFIX + "Next10Score": "ROE/PE 11-20",
        PREFIX + "Top10PE": "PE(TTM) Top10",
        PREFIX + "Next10PE": "PE(TTM) 11-20",
        PREFIX + "Top10ROE": "ROE Top10",
        PREFIX + "Next10ROE": "ROE 11-20",
        PREFIX + "排序值": "ROE/PE",
    }
    return {
        "title": TITLE,
        "subtitle": "万得全A · 正PE与正ROE · 按ROE/PE降序",
        "description": "正PE、正ROE股票按ROE/PE排序；不是低PE或高ROE硬门槛，不构成投资建议。",
        "share": {"enabled": True, "title": TITLE,
                  "subtitle": "共同完整截面 · 有效N/20 · 不是硬门槛筛选",
                  "pageType": "盈利估值性价比榜",
                  "footerNote": "比值靠前不等于质量过关；本页未过滤ST、流动性与异常值。"},
        "endpoint": endpoint,
        "package_id": package_id,
        "signature": signature,
        "packages": [{"package_id": package_id, "signature": signature}],
        "panels": [{
            "type": "table", "title": "盈利估值性价比完整榜", "span": "full",
            "outputs": OUTPUTS, "output_labels": labels,
            "columns": ["代码", "名称", PREFIX + "排序值", PREFIX + "Top10Score",
                        PREFIX + "Next10Score", PREFIX + "Top10PE", PREFIX + "Top10ROE"],
            "rank_by": PREFIX + "排序值", "rank_order": "desc", "rank_limit": 20,
            "expected_rows": 20,
            "description": "优先使用共同完整截面；不足20行时显示有效N/20，不冒充完整Top20。",
        }],
    }


def _write(path: Optional[str], value: dict):
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if path:
        Path(path).write_text(text, encoding="utf-8")
    else:
        print(text, end="")


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in {"package-params", "dashboard-spec"}:
        print(__doc__)
        return 2
    command = argv.pop(0)
    params = json.loads(argv[0][1:]) if argv and argv[0].startswith("@") else (
        json.loads(argv[0]) if argv else {})
    out = params.pop("out", None)
    if command == "package-params":
        _write(out, package_params(params.get("begin_date", 20250101)))
        return 0
    _write(out, dashboard_spec(params.get("package_id"), params.get("signature"), params.get("endpoint")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
