#!/usr/bin/env python3
"""
轻量调用封装器。通过环境变量传 JSON 参数，彻底绕过 PowerShell GBK 编码和双引号问题。
renderChart 自动保存 PNG 并打开（无需额外调 saveChart）。

用法（Claude 在终端执行）：

    方式1 —— 环境变量（推荐）：
    GZQ_PARAMS='{"query":"收盘价"}' python scripts/call.py searchFunctions

    方式2 —— @file 传参（跨平台备用）：
    python scripts/call.py searchFunctions @params.json

    方式3 —— 命令行传参（仅 bash/zsh）：
    python scripts/call.py searchFunctions '{"query":"收盘价"}'

    方式4 —— 管道传参（macOS/Linux）：
    echo '{"query":"收盘价"}' | python scripts/call.py searchFunctions

原理：
  1. 从 GZQ_PARAMS 环境变量读取 JSON
  2. 调用 executor.py <tool> @tmpfile
  3. renderChart 额外处理：自动保存 PNG + 打开
  4. 打印结果到 stdout + 写入临时目录下 gzq_out.txt
  5. 清理临时文件
"""

import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..'))
EXECUTOR = os.path.join(SCRIPT_DIR, "executor.py")
SESSION_FILE = os.path.join(SKILL_ROOT, "output", ".session.json")


def _read_session():
    """读取当前 session 的 task_id，不存在则返回 None。"""
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("task_id")
    except Exception:
        return None


def _write_session(task_id):
    """持久化 task_id 到 .session.json。"""
    os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump({"task_id": task_id}, f)


def _run_executor(tool_name, param_arg):
    """调用 executor.py，返回 (returncode, stdout_bytes, stderr_bytes)。"""
    import signal as _signal
    # Windows: 将 executor.py 放到新进程组，防止 console Ctrl+C 广播干扰子进程
    extra_flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    # 在父进程中临时忽略 SIGINT，防止 communicate() 被残留信号中断
    try:
        old_handler = _signal.signal(_signal.SIGINT, _signal.SIG_IGN)
    except (OSError, ValueError):
        old_handler = None
    try:
        result = subprocess.run(
            [sys.executable, EXECUTOR, tool_name, param_arg],
            capture_output=True, timeout=300,
            creationflags=extra_flags,
        )
        return result.returncode, result.stdout, result.stderr
    except KeyboardInterrupt:
        # 捕获并重试一次（处理极端情况）
        result = subprocess.run(
            [sys.executable, EXECUTOR, tool_name, param_arg],
            capture_output=True, timeout=300,
            creationflags=extra_flags,
        )
        return result.returncode, result.stdout, result.stderr
    finally:
        if old_handler is not None:
            try:
                _signal.signal(_signal.SIGINT, old_handler)
            except (OSError, ValueError):
                pass


def _auto_save_chart(stdout_str, params):
    """renderChart 后自动保存 PNG，返回修改后的 stdout 供打印。支持 JSON 和 YAML 两种格式。"""
    # ── JSON 模式 ──
    try:
        data = json.loads(stdout_str)
        return _save_chart_from_json(data, params)
    except (json.JSONDecodeError, ValueError):
        pass
    # ── YAML 模式 ──
    return _save_chart_from_yaml(stdout_str, params)


def _save_chart_from_json(data, params):
    """从 JSON dict 提取 base64 并保存。"""
    if data.get("code") != 0:
        return json.dumps(data, indent=2, ensure_ascii=False)
    b64 = (data.get("data") or {}).get("base64", "")
    if not b64:
        return json.dumps(data, indent=2, ensure_ascii=False)
    out_path = _save_b64_to_png(b64, params)
    data["data"]["base64"] = f"<{len(b64)} chars>"
    data["data"]["saved_to"] = out_path
    data["data"]["auto_opened"] = sys.platform == "win32"
    return json.dumps(data, indent=2, ensure_ascii=False)


def _save_chart_from_yaml(stdout_str, params):
    """从 YAML 文本提取 base64 并保存。"""
    code_m = re.search(r'^code:\s*(\d+)', stdout_str, re.MULTILINE)
    if not code_m or code_m.group(1) != '0':
        return stdout_str
    # 在 YAML 行中查找 base64 字段
    b64 = None
    for line in stdout_str.split('\n'):
        stripped = line.strip()
        if stripped.startswith('base64:'):
            b64 = stripped[len('base64:'):].strip().strip("'\"")
            break
    if not b64:
        return stdout_str
    out_path = _save_b64_to_png(b64, params)
    # 替换 YAML 中的 base64 为摘要
    replacement = f"'<{len(b64)} chars, saved to {out_path}>'"
    stdout_str = stdout_str.replace(b64, replacement, 1)
    return stdout_str


def _save_b64_to_png(b64, params):
    """解码 base64 保存 PNG，返回文件路径。"""
    b64_clean = b64.split(",", 1)[1] if b64.startswith("data:") else b64
    # 修复 padding（base64 长度必须是 4 的倍数）
    b64_clean += "=" * (4 - len(b64_clean) % 4)
    name = params.get("title", params.get("name", "chart"))
    name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    output_dir = os.path.join(SKILL_ROOT, "output")
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"{name}.png")
    with open(out_path, "wb") as f:
        f.write(base64.b64decode(b64_clean))
    if sys.platform == "win32":
        os.startfile(out_path)
    return out_path


# 维度标准顺序（用于重算 overall_score 时保持一致）
_DIM_ORDER = ["D1_估值", "D3_资金", "D4_波动率", "D5_宏观胜率",
              "D6_相关资产", "D7_技术形态", "D8_季节性", "D9_财务"]


def _score_to_signal(score):
    for lo, hi, label in [
        (80, 101, "强看多 ^^"), (65, 80, "偏多 ^"), (55, 65, "中性偏多 ->^"),
        (45, 55, "中性 ->"), (35, 45, "中性偏空 ->v"), (20, 35, "偏空 v"),
        (0,  20,  "强看空 vv"),
    ]:
        if lo <= score < hi:
            return label
    return "中性 ->"


def _local_score_from_indicators(indicators: list):
    """API 维度分 == 50 且所有 IC_IR 为 null 时，从原始指标值本地估算分维度得分。

    触发条件（全部满足）：
      1. 有 indicators 且每个 indicator 的 ic_ir 均为 None / null
      2. 至少有一个 current_value 可解析为 float（范围 [0, 1]）

    计算逻辑：
      avg = mean(current_value)  —— 适用于分位水位(0‒1)和 binary 指标(0/1)
      score = 50 + (avg - 0.5) × 60   → [20, 80]，保守斜率避免过度解读

    返回 int 或 None（None 表示不适用本地兜底）。
    """
    if not indicators:
        return None
    vals = []
    for ind in indicators:
        # 只要有任意 IC_IR 非 null，说明平台已经计算过，不走本地路径
        if ind.get("ic_ir") is not None:
            return None
        v = ind.get("current_value")
        if v is None:
            continue
        try:
            fv = float(v)
            # 只接受 [0, 1] 范围的分位/binary 值
            if 0.0 <= fv <= 1.0:
                vals.append(fv)
        except (TypeError, ValueError):
            pass
    if not vals:
        return None
    avg = sum(vals) / len(vals)
    return max(20, min(80, round(50 + (avg - 0.5) * 60)))


def _auto_save_scan_dimensions(stdout_str, params):
    """scanDimensions 后**合并写入** output/ic_data/，返回精简摘要。

    分维度调用时（dimensions=["D1_估值"] 等），新扫描的维度覆盖旧结果，
    其他维度保留，并重算 overall_score / overall_signal / top_dimension / bottom_dimension。
    全量一次性调用与单次效果相同。
    """
    try:
        resp = json.loads(stdout_str)
    except (json.JSONDecodeError, ValueError):
        return stdout_str

    if resp.get("code") != 0:
        return stdout_str

    data = resp.get("data", {})
    # 提取资产名称（优先从请求参数取，其次从响应取）
    name = ""
    if isinstance(params.get("asset"), dict):
        name = params["asset"].get("name", "")
    if not name:
        name = (data.get("stock_name") or data.get("stock")
                or data.get("asset", {}).get("name") or "unknown")

    ic_dir = os.path.join(SKILL_ROOT, "output", "ic_data")
    os.makedirs(ic_dir, exist_ok=True)
    out_path = os.path.join(ic_dir, f"{name}_dimension_ic.json")

    # ── 合并已有文件 ─────────────────────────────────────
    merged = {}
    if os.path.exists(out_path):
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                merged = json.load(f)
        except Exception:
            merged = {}

    # 顶层字段：新数据优先（dimensions 单独处理）
    for k, v in data.items():
        if k not in ("dimensions", "overall_score", "overall_signal",
                     "top_dimension", "bottom_dimension"):
            merged[k] = v

    # 合并 dimensions：只更新本次真正被计算的维度（indicators 非空），
    # 其余保留已有结果，避免后端返回全量默认值时覆盖已有好数据。
    existing_dims = merged.get("dimensions", {})
    new_dims = data.get("dimensions", {})
    computed_dims = {k: v for k, v in new_dims.items()
                     if v.get("indicators")}   # 非空 indicators = 真正计算过
    existing_dims.update(computed_dims)
    merged["dimensions"] = existing_dims

    # ── 重算综合数值 ─────────────────────────────────────
    raw_scores = []
    dim_scores = []
    for dim in _DIM_ORDER:
        if dim not in existing_dims:
            continue
        dim_data = existing_dims[dim]
        s = dim_data.get("score", 50)
        # 本地兜底：API 返回 50 且 IC_IR 全 null 时，从原始指标值重算
        if s == 50:
            local_s = _local_score_from_indicators(dim_data.get("indicators") or [])
            if local_s is not None and local_s != 50:
                s = local_s
                dim_data["score"] = s
                dim_data["signal"] = _score_to_signal(s)
                dim_data["_score_source"] = "local_fallback"
        w = 0.5 if dim == "D8_季节性" else 1.0
        dim_scores.append({"name": dim, "score": s})
        raw_scores.extend([s] * round(w * 10))

    if raw_scores:
        overall = round(sum(raw_scores) / len(raw_scores))
        merged["overall_score"] = overall
        merged["overall_signal"] = _score_to_signal(overall)
        merged["top_dimension"] = max(dim_scores, key=lambda x: x["score"])
        merged["bottom_dimension"] = min(dim_scores, key=lambda x: x["score"])

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    # ── 精简摘要（仅打印本次新扫维度） ───────────────────
    dim_summary = {}
    for dim_key in list(new_dims.keys()):
        dim_val = existing_dims.get(dim_key, {})
        if isinstance(dim_val, dict):
            dim_summary[dim_key] = {
                "score": dim_val.get("score"),
                "signal": dim_val.get("signal"),
                "indicators": [
                    {"label": ind.get("label") or ind.get("name"),
                     "current": ind.get("current_value"),
                     "ic_ir": ind.get("ic_ir")}
                    for ind in (dim_val.get("indicators") or [])[:3]
                ]
            }

    summary = {
        "code": 0,
        "data": {
            "asset": params.get("asset", {"name": name}),
            "scan_date": merged.get("scan_date"),
            "overall_score": merged.get("overall_score"),
            "overall_signal": merged.get("overall_signal"),
            "new_dimensions": sorted(new_dims.keys()),
            "file_has_dimensions": sorted(existing_dims.keys()),
            "new_dim_results": dim_summary,
            "saved_to": out_path,
            "note": (
                f"新增/更新 {len(new_dims)} 个维度，"
                f"文件已含 {len(existing_dims)}/8 个维度。"
                + ("" if len(existing_dims) >= 8 else
                   f" 剩余未扫：{sorted(set(_DIM_ORDER) - set(existing_dims.keys()))}")
            )
        },
        "task_id": resp.get("task_id")
    }
    return json.dumps(summary, indent=2, ensure_ascii=False)


def _auto_save_csv(stdout_str, params):
    """downloadData 后自动保存 CSV 到 output/，打印摘要而非原文。"""
    try:
        data = json.loads(stdout_str)
    except (json.JSONDecodeError, ValueError):
        # 后端直接返回 CSV 文本（Content-Type: text/csv）时 executor 已包一层 JSON
        return stdout_str

    if data.get("code") != 0:
        return json.dumps(data, indent=2, ensure_ascii=False)

    inner = data.get("data", {})
    # format=json 路径：inner 包含 labels/values
    # format=csv 路径：inner 是 CSV 字符串
    if isinstance(inner, str):
        # executor 把 CSV 文本放在 data 字段
        csv_text = inner
        data_name = params.get("id", "download")
        total_rows = len(csv_text.strip().split('\n')) - 1
    elif isinstance(inner, dict) and "labels" in inner:
        # json 路径：重新组装 CSV
        labels = inner.get("labels", [])
        values = inner.get("values", [])
        csv_text = "date,value\n" + "\n".join(
            f"{lbl},{'' if v is None else v}" for lbl, v in zip(labels, values)
        )
        data_name = inner.get("data_name", params.get("id", "download"))
        total_rows = len(labels)
    else:
        return json.dumps(data, indent=2, ensure_ascii=False)

    # 保存到 output/
    name = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(data_name))
    output_dir = os.path.join(SKILL_ROOT, "output")
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"{name}.csv")
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(csv_text)

    summary = {
        "code": 0,
        "data": {
            "saved_to": out_path,
            "total_rows": total_rows,
            "data_name": data_name,
        }
    }
    if isinstance(inner, dict):
        for k in ("provider", "dimension", "begin_date", "end_date"):
            if k in inner:
                summary["data"][k] = inner[k]
    return json.dumps(summary, indent=2, ensure_ascii=False)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    tool_name = sys.argv[1]

    # ── newSession：生成新 task_id 并持久化 ──────────────────────
    if tool_name == "newSession":
        new_id = str(uuid.uuid4())
        _write_session(new_id)
        result = json.dumps({"code": 0, "task_id": new_id,
                             "message": "新 session 已创建，task_id 已保存到 .session.json，后续调用自动注入"
                             }, ensure_ascii=False, indent=2)
        out_file = os.path.join(tempfile.gettempdir(), "gzq_out.txt")
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(result)
        print(result)
        sys.exit(0)

    # ── 解析参数来源 ──────────────────────────────────────────────
    # 优先级: GZQ_PARAMS 环境变量 > @file > stdin > 命令行 argv
    # GZQ_PARAMS 是 Windows PowerShell 推荐方式：
    #   GZQ_PARAMS='{"key":"value"}' python scripts/call.py <tool>
    # PowerShell 给变量赋字符串时不剥双引号，子进程继承环境变量，JSON 完整传达。
    raw = None
    at_file = None

    env_params = os.environ.get("GZQ_PARAMS", "").strip()
    if env_params:
        raw = env_params
    elif len(sys.argv) >= 3 and sys.argv[2].startswith("@"):
        at_file = sys.argv[2]          # @/path/to/file.json
    elif not sys.stdin.isatty():
        raw_bytes = sys.stdin.buffer.read()
        raw = raw_bytes.decode("utf-8", errors="replace").strip()
    elif len(sys.argv) >= 3:
        raw = " ".join(sys.argv[2:])

    if not at_file and not raw:
        raw = "{}"

    # ── 准备参数文件 ──────────────────────────────────────────────
    tmp_path = None
    params = {}
    try:
        if at_file:
            # @file：读取以解析 params（用于 renderChart 后处理），原文件直接转发
            file_path = at_file[1:]    # 去掉 @
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    params = json.load(f)
            except Exception:
                params = {}
            param_arg = at_file
        else:
            # 解析 + 写临时文件
            try:
                params = json.loads(raw)
            except json.JSONDecodeError as e:
                print(json.dumps({
                    "code": 1,
                    "message": f"JSON 解析失败: {e}\n原始输入: {raw[:200]}"
                }, ensure_ascii=False))
                sys.exit(1)

            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="gzq_")
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(params, f, ensure_ascii=False)
            param_arg = f"@{tmp_path}"

        # ── 自动注入 task_id（若 params 未提供）───────────────────
        session_task_id = _read_session()
        if session_task_id and "task_id" not in params:
            params["task_id"] = session_task_id
            # 重写临时文件（仅 tmp_path 路径，at_file 不重写）
            if tmp_path:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(params, f, ensure_ascii=False)

        # ── 调用 executor.py ──────────────────────────────────────
        rc, stdout_bytes, stderr_bytes = _run_executor(tool_name, param_arg)

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        # renderChart / renderKLine 自动保存
        if tool_name in ("renderChart", "renderKLine") and rc == 0:
            stdout = _auto_save_chart(stdout, params)

        # downloadData CSV 自动落盘 output/
        if tool_name == "downloadData" and rc == 0:
            stdout = _auto_save_csv(stdout, params)
        # scanDimensions 自动保存 JSON 到 output/ic_data/
        if tool_name == "scanDimensions" and rc == 0:
            stdout = _auto_save_scan_dimensions(stdout, params)
        # ── 从响应中捕获 task_id，更新 session（服务端生成的UUID优先）──
        if rc == 0:
            try:
                resp = json.loads(stdout)
                resp_task_id = resp.get("task_id") or (resp.get("data") or {}).get("task_id")
                if resp_task_id and resp_task_id != _read_session():
                    _write_session(resp_task_id)
            except Exception:
                pass

        # ── 始终写输出到固定文件，解决 VS Code 终端缓冲吞 stdout 的问题 ──
        # 必须在 print 之前写入，因为 print 可能因 GBK 编码崩溃（如 ✅ emoji）
        out_file = os.path.join(tempfile.gettempdir(), "gzq_out.txt")
        with open(out_file, "w", encoding="utf-8") as f:
            if stdout:
                f.write(stdout)
            if stderr:
                f.write(stderr)

        try:
            if stdout:
                print(stdout, end="")
            if stderr:
                print(stderr, end="", file=sys.stderr)
        except UnicodeEncodeError:
            # GBK 终端无法打印 emoji 等字符，忽略——结果已写入 gzq_out.txt
            pass

        sys.exit(rc)

    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


if __name__ == "__main__":
    main()
