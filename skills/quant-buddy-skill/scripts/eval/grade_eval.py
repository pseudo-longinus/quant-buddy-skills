#!/usr/bin/env python3
"""
Guanzhao-Quant-Skill Agent Eval 评分脚本

用法:
  python scripts/grade_eval.py --iteration 1
  python scripts/grade_eval.py --iteration 1 --eval-name low-pe-selection

依赖: 无（Python 标准库）
"""

import json
import argparse
from pathlib import Path
import re
from typing import Dict, List, Optional

SKILL_ROOT = Path(__file__).parent.parent
WORKSPACE = SKILL_ROOT / "eval-workspace"
EVALS_JSON = SKILL_ROOT / "evals" / "evals.json"


def load_evals() -> Dict:
    """加载测试用例定义"""
    if not EVALS_JSON.exists():
        raise FileNotFoundError(f"找不到 {EVALS_JSON}，请先创建测试用例")
    with open(EVALS_JSON, 'r', encoding='utf-8') as f:
        return json.load(f)


def check_file_contains(output_dir: Path, pattern: str) -> Optional[Dict]:
    """检查输出目录中是否有文件包含指定模式"""
    outputs = output_dir / "outputs"
    if not outputs.exists():
        return {"passed": False, "evidence": f"输出目录不存在: {outputs}"}
    
    # 扫描所有文本文件
    for ext in ['*.txt', '*.json', '*.csv', '*.md']:
        for file in outputs.rglob(ext):
            try:
                content = file.read_text(encoding='utf-8')
                if re.search(pattern, content, re.IGNORECASE):
                    return {
                        "passed": True, 
                        "evidence": f"在 {file.name} 中找到匹配: {pattern}"
                    }
            except Exception as e:
                continue
    
    return {"passed": False, "evidence": f"未找到包含 '{pattern}' 的文件"}


def check_file_exists(output_dir: Path, pattern: str) -> Optional[Dict]:
    """检查输出目录中是否存在匹配的文件"""
    outputs = output_dir / "outputs"
    if not outputs.exists():
        return {"passed": False, "evidence": f"输出目录不存在: {outputs}"}
    
    matching_files = list(outputs.rglob(pattern))
    if matching_files:
        return {
            "passed": True,
            "evidence": f"找到文件: {', '.join(f.name for f in matching_files)}"
        }
    return {"passed": False, "evidence": f"未找到匹配 '{pattern}' 的文件"}


def check_tool_called(output_dir: Path, tool_name: str) -> Optional[Dict]:
    """检查是否调用了指定工具（通过 transcript.txt）"""
    transcript = output_dir / "transcript.txt"
    if not transcript.exists():
        # 如果没有 transcript，尝试从其他文件推断
        return {"passed": None, "evidence": f"缺少 transcript.txt，无法确认工具调用"}
    
    content = transcript.read_text(encoding='utf-8')
    if tool_name.lower() in content.lower():
        return {"passed": True, "evidence": f"在 transcript 中找到 {tool_name} 调用"}
    return {"passed": False, "evidence": f"在 transcript 中未找到 {tool_name} 调用"}


def check_json_field(output_dir: Path, file_pattern: str, field_path: str) -> Optional[Dict]:
    """检查 JSON 文件中是否存在指定字段"""
    outputs = output_dir / "outputs"
    if not outputs.exists():
        return {"passed": False, "evidence": f"输出目录不存在: {outputs}"}
    
    for json_file in outputs.rglob(file_pattern):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 解析字段路径（如 "data.series[0].name"）
            keys = field_path.split('.')
            current = data
            for key in keys:
                if '[' in key:
                    # 处理数组索引
                    key_name, idx = key.rstrip(']').split('[')
                    current = current[key_name][int(idx)]
                else:
                    current = current[key]
            
            return {
                "passed": True,
                "evidence": f"在 {json_file.name} 中找到字段 {field_path} = {current}"
            }
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            continue
    
    return {"passed": False, "evidence": f"未找到包含字段 '{field_path}' 的 JSON 文件"}


def check_assertion(assertion_text: str, output_dir: Path, eval_name: str) -> Dict:
    """
    检查单个断言是否通过
    
    支持的断言模式：
    - "调用了 XXX" → 检查 transcript.txt
    - "公式中包含 XXX" → 检查文件内容
    - "返回了 XXX" → 检查文件内容
    - "图表包含 X 条系列" → 检查 JSON 结构
    - "文件存在: XXX" → 检查文件是否存在
    """
    
    # 模式1: 工具调用检查
    if "调用了" in assertion_text:
        tool_match = re.search(r'调用了\s+(\w+)', assertion_text)
        if tool_match:
            tool_name = tool_match.group(1)
            return check_tool_called(output_dir, tool_name)
    
    # 模式2: 内容包含检查
    if any(keyword in assertion_text for keyword in ["公式中包含", "包含", "返回了"]):
        # 提取关键词
        patterns = [
            r'包含[^"]*["""](.*?)["""]',
            r'包含\s+(\w+)',
            r'返回了\s+(.+?)(?:，|$)',
        ]
        for pattern in patterns:
            match = re.search(pattern, assertion_text)
            if match:
                keyword = match.group(1)
                return check_file_contains(output_dir, keyword)
    
    # 模式3: 数量范围检查
    if "数量" in assertion_text and "之间" in assertion_text:
        range_match = re.search(r'(\d+)-(\d+)', assertion_text)
        if range_match:
            min_count, max_count = map(int, range_match.groups())
            # 尝试从结果文件中提取行数
            count_result = check_file_contains(output_dir, r'\d{6}\.(SZ|SH)')
            if count_result.get("passed"):
                outputs = output_dir / "outputs"
                for file in outputs.rglob("*.json"):
                    try:
                        with open(file, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        if isinstance(data, list):
                            actual_count = len(data)
                            if min_count <= actual_count <= max_count:
                                return {
                                    "passed": True, 
                                    "evidence": f"返回 {actual_count} 条数据，在 {min_count}-{max_count} 范围内"
                                }
                            else:
                                return {
                                    "passed": False,
                                    "evidence": f"返回 {actual_count} 条数据，不在 {min_count}-{max_count} 范围内"
                                }
                    except:
                        continue
    
    # 模式4: 图表系列数量检查
    if "图表包含" in assertion_text and "系列" in assertion_text:
        series_match = re.search(r'(\d+)\s*条系列', assertion_text)
        if series_match:
            expected_series = int(series_match.group(1))
            # 检查图表 spec JSON
            for json_file in (output_dir / "outputs").rglob("*chart*.json"):
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    if 'series' in data:
                        actual_series = len(data['series'])
                        if actual_series >= expected_series:
                            return {
                                "passed": True,
                                "evidence": f"图表包含 {actual_series} 条系列（≥{expected_series}）"
                            }
                except:
                    continue
    
    # 模式5: 结论检查（定性）
    if "给出了" in assertion_text and "结论" in assertion_text:
        # 检查是否有文本输出
        outputs = output_dir / "outputs"
        for file in outputs.rglob("*.txt"):
            content = file.read_text(encoding='utf-8')
            if any(keyword in content for keyword in ["收益", "更高", "表现", "优于"]):
                return {"passed": True, "evidence": f"在 {file.name} 中找到结论性表述"}
        return {"passed": None, "evidence": "需要人工检查是否给出了明确结论"}
    
    # 默认：无法自动判断
    return {
        "passed": None, 
        "evidence": f"断言模式未识别，需要人工检查: {assertion_text}"
    }


def grade_eval(iteration: int, eval_dir: Path, eval_id: int) -> Optional[Dict]:
    """对单个测试用例评分"""
    
    # 查找对应的 eval 定义
    evals_data = load_evals()
    eval_def = next((e for e in evals_data['evals'] if e['id'] == eval_id), None)
    if not eval_def:
        print(f"⚠️  跳过 {eval_dir.name}: 找不到 ID={eval_id} 的 eval 定义")
        return None
    
    assertions = eval_def.get('expectations', [])
    if not assertions:
        print(f"⚠️  跳过 {eval_dir.name}: 没有定义断言")
        return None
    
    results = []
    output_dir = eval_dir / "with_skill"
    
    if not output_dir.exists():
        print(f"❌ {eval_dir.name}: 输出目录不存在")
        return None
    
    # 检查每个断言
    for assertion in assertions:
        result = check_assertion(assertion, output_dir, eval_dir.name)
        results.append({
            "text": assertion,
            "passed": result["passed"],
            "evidence": result["evidence"]
        })
    
    # 保存评分结果
    grading = {
        "eval_id": eval_id,
        "eval_name": eval_dir.name,
        "expectations": results
    }
    grading_file = output_dir / "grading.json"
    with open(grading_file, 'w', encoding='utf-8') as f:
        json.dump(grading, f, indent=2, ensure_ascii=False)
    
    # 统计通过率
    passed_count = sum(1 for r in results if r["passed"] is True)
    failed_count = sum(1 for r in results if r["passed"] is False)
    unknown_count = sum(1 for r in results if r["passed"] is None)
    total_count = len(results)
    
    status_icon = "✅" if passed_count == total_count else "⚠️" if unknown_count > 0 else "❌"
    print(f"{status_icon} {eval_dir.name}: {passed_count}/{total_count} 通过, {failed_count} 失败, {unknown_count} 需人工")
    
    return grading


def generate_benchmark(iteration: int) -> Dict:
    """生成 benchmark.json 聚合报告"""
    iter_dir = WORKSPACE / f"iteration-{iteration}"
    if not iter_dir.exists():
        raise FileNotFoundError(f"迭代目录不存在: {iter_dir}")
    
    eval_dirs = sorted([d for d in iter_dir.iterdir() if d.is_dir()])
    
    results = []
    total_passed = 0
    total_assertions = 0
    
    for eval_dir in eval_dirs:
        grading_file = eval_dir / "with_skill" / "grading.json"
        if not grading_file.exists():
            continue
        
        with open(grading_file, 'r', encoding='utf-8') as f:
            grading = json.load(f)
        
        expectations = grading.get('expectations', [])
        passed = sum(1 for e in expectations if e.get('passed') is True)
        failed = sum(1 for e in expectations if e.get('passed') is False)
        unknown = sum(1 for e in expectations if e.get('passed') is None)
        total = len(expectations)
        
        pass_rate = passed / total if total > 0 else 0
        
        results.append({
            "eval_id": grading.get('eval_id', 0),
            "eval_name": eval_dir.name,
            "pass_rate": round(pass_rate, 3),
            "passed": passed,
            "failed": failed,
            "unknown": unknown,
            "total": total
        })
        
        total_passed += passed
        total_assertions += total
    
    overall_pass_rate = total_passed / total_assertions if total_assertions > 0 else 0
    
    benchmark = {
        "skill_name": "guanzhao-quant-skill",
        "iteration": iteration,
        "overall_pass_rate": round(overall_pass_rate, 3),
        "total_passed": total_passed,
        "total_assertions": total_assertions,
        "results": results
    }
    
    benchmark_file = iter_dir / "benchmark.json"
    with open(benchmark_file, 'w', encoding='utf-8') as f:
        json.dump(benchmark, f, indent=2, ensure_ascii=False)
    
    return benchmark


def print_benchmark_summary(benchmark: Dict):
    """打印 benchmark 摘要"""
    print("\n" + "="*60)
    print(f"📊 Benchmark Summary - Iteration {benchmark['iteration']}")
    print("="*60)
    print(f"总体通过率: {benchmark['overall_pass_rate']:.1%} ({benchmark['total_passed']}/{benchmark['total_assertions']})")
    print()
    
    for result in benchmark['results']:
        status = "✅" if result['pass_rate'] == 1.0 else "⚠️" if result['unknown'] > 0 else "❌"
        print(f"{status} {result['eval_name']:30s} | {result['pass_rate']:5.1%} ({result['passed']}/{result['total']})")
    
    print("="*60)
    
    # 评级
    pass_rate = benchmark['overall_pass_rate']
    if pass_rate >= 0.85:
        grade = "🟢 PASS - 可推向市场"
    elif pass_rate >= 0.70:
        grade = "🟡 MARGINAL - 继续改进"
    else:
        grade = "🔴 FAIL - 需要重大改进"
    
    print(f"评级: {grade}")
    print("="*60)


def main():
    parser = argparse.ArgumentParser(description="Guanzhao-Quant-Skill Agent Eval 评分")
    parser.add_argument('--iteration', type=int, default=1, help='迭代轮次')
    parser.add_argument('--eval-name', type=str, help='只评分指定的测试用例（目录名）')
    args = parser.parse_args()
    
    iter_dir = WORKSPACE / f"iteration-{args.iteration}"
    if not iter_dir.exists():
        print(f"❌ 迭代目录不存在: {iter_dir}")
        print(f"请先运行测试用例，并将结果保存到该目录")
        return
    
    print(f"🔍 开始评分 Iteration {args.iteration}")
    print(f"工作目录: {iter_dir}")
    print()
    
    # 加载 eval 定义，建立名称到 ID 的映射
    evals_data = load_evals()
    eval_name_to_id = {}
    for eval_def in evals_data['evals']:
        # 根据 expected_output 生成目录名（简化版）
        name = eval_def.get('expected_output', f"eval-{eval_def['id']}")[:30].replace(' ', '-')
        eval_name_to_id[name] = eval_def['id']
    
    # 获取要评分的测试用例目录
    if args.eval_name:
        eval_dirs = [iter_dir / args.eval_name]
        if not eval_dirs[0].exists():
            print(f"❌ 测试用例目录不存在: {eval_dirs[0]}")
            return
    else:
        eval_dirs = sorted([d for d in iter_dir.iterdir() if d.is_dir()])
    
    # 对每个测试用例评分
    for eval_dir in eval_dirs:
        # 尝试从目录名推断 eval_id
        eval_id = eval_name_to_id.get(eval_dir.name)
        if eval_id is None:
            # 如果推断失败，尝试从 eval_metadata.json 读取
            metadata_file = eval_dir / "eval_metadata.json"
            if metadata_file.exists():
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                eval_id = metadata.get('eval_id')
        
        if eval_id is None:
            print(f"⚠️  跳过 {eval_dir.name}: 无法确定 eval_id")
            continue
        
        grade_eval(args.iteration, eval_dir, eval_id)
    
    # 生成 benchmark
    print()
    benchmark = generate_benchmark(args.iteration)
    print_benchmark_summary(benchmark)
    print()
    print(f"✅ Benchmark 已保存到: {iter_dir / 'benchmark.json'}")


if __name__ == '__main__':
    main()
