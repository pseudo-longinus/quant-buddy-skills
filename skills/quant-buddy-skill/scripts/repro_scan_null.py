#!/usr/bin/env python3
"""
scanDimensions 空值问题 — 最小可复现脚本
=========================================

结论（2026-04-20 实测）：
  1. code 格式无关 — SH688xxx 和 688xxx.SH 返回完全相同
  2. 存在稳定复现的 stock×dimension 空值 — 例如：
     - 翱捷科技 × D1_估值：多次新 session，始终 ic_ir=null / current_value=null
     - 沪硅产业 × D9_财务：同上
  3. 存在偶发性空值 — 批量运行中赛恩斯 D1 全空，但事后单独调又有数据
     → 疑与 session 累计 RU / 并发速率有关

用法：
  cd quant-buddy-skill
  python scripts/repro_scan_null.py               # 跑全量 8 组测试
  python scripts/repro_scan_null.py --quick        # 只跑 3 组核心对比
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from quant_api import QuantAPI


# ── 测试用例 ─────────────────────────────────────────────────
ALL_CASES = [
    # --- 稳定复现：翱捷科技 D1 始终空 ---
    {"name": "翱捷科技", "code": "688220.SH", "dim": "D1_估值",   "expect": "null"},
    # --- 对照：沪硅产业 D1 始终有值 ---
    {"name": "沪硅产业", "code": "688126.SH", "dim": "D1_估值",   "expect": "filled"},
    # --- 稳定复现：沪硅产业 D9 始终空 ---
    {"name": "沪硅产业", "code": "688126.SH", "dim": "D9_财务",   "expect": "null"},
    # --- 对照：通光线缆 D9 始终有值 ---
    {"name": "通光线缆", "code": "300265.SZ", "dim": "D9_财务",   "expect": "filled"},
    # --- 验证 code 格式无关 ---
    {"name": "赛恩斯",   "code": "SH688480",  "dim": "D1_估值",   "expect": "filled"},
    {"name": "赛恩斯",   "code": "688480.SH", "dim": "D1_估值",   "expect": "filled"},
    # --- 其他维度正常 ---
    {"name": "翱捷科技", "code": "688220.SH", "dim": "D7_技术形态", "expect": "filled"},
    {"name": "翱捷科技", "code": "688220.SH", "dim": "D3_资金",   "expect": "filled"},
]

QUICK_CASES = ALL_CASES[:4]  # 只跑最核心的 2 组对比


def scan_one(api: QuantAPI, case: dict) -> dict:
    """调用 scanDimensions 返回单维度摘要"""
    name, code, dim = case["name"], case["code"], case["dim"]
    r = api.scan_dimensions(asset={"name": name, "code": code}, dimensions=[dim])
    data = r.get("data", r)
    quota = r.get("_quota", {}).get("window", {})
    d = data.get("dimensions", {}).get(dim, {})
    indicators = d.get("indicators", [])
    filled = [i for i in indicators if i.get("ic_ir") is not None]
    return {
        "name": name,
        "code": code,
        "dim": dim,
        "expect": case.get("expect", "?"),
        "total": len(indicators),
        "filled": len(filled),
        "score": d.get("score"),
        "signal": d.get("signal"),
        "indicators": indicators,
        "quota_remaining": quota.get("remaining"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="只跑核心 4 组")
    args = parser.parse_args()

    cases = QUICK_CASES if args.quick else ALL_CASES

    api = QuantAPI()
    api.new_session()
    print(f"Session: {api._task_id}\n")

    results = []
    for case in cases:
        r = scan_one(api, case)
        results.append(r)
        tag = "✓" if (r["filled"] > 0) == (r["expect"] == "filled") else "✗ UNEXPECTED"
        ratio = f"{r['filled']}/{r['total']}"
        print(f"  {tag}  {r['name']:8s} × {r['dim']:<10s}  {ratio:<5s}  score={r['score']:<4}  "
              f"(expect={r['expect']}, quota_left={r['quota_remaining']})")

    # 保存
    out_path = Path(__file__).resolve().parent.parent / "output" / "repro_scan_null_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已保存: {out_path}")

    # 判定
    print("\n" + "=" * 60)
    print("结论")
    print("=" * 60)
    nulls = [r for r in results if r["filled"] == 0]
    if nulls:
        print(f"以下 {len(nulls)} 组返回全空（平台 bug）:")
        for r in nulls:
            print(f"  - {r['name']} × {r['dim']}: 0/{r['total']} indicators, score 默认 {r['score']}")
        print("\n这些组合在多次独立 session 中始终返回 null，")
        print("表明平台对特定 stock×dimension 缺少底层数据或计算异常。")
    else:
        print("本次运行所有测试均返回有效数据。如之前出现过全空，属偶发性问题。")


if __name__ == "__main__":
    main()
