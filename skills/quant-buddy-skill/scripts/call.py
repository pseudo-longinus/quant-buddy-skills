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
  1. 从 GZQ_PARAMS 环境变量读取 JSON（PowerShell 赋值字符串时不剥双引号）
  2. 调用 executor.py <tool> @tmpfile
  3. renderChart 额外处理：自动保存 PNG + 打开
  4. 打印结果到 stdout + 写入临时目录下 gzq_out.txt
  5. 清理临时文件
"""

import base64
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(SCRIPT_DIR)
EXECUTOR = os.path.join(SCRIPT_DIR, "executor.py")


def _configure_parent_stdio():
    """启动时把 sys.stdout/stderr 尽量重配为 UTF-8 + replace 模式，
    防止 Windows GBK 终端在遇到 emoji 等字符时直接抛 UnicodeEncodeError。
    只做 best-effort；失败不影响主流程。
    """
    for attr in ("stdout", "stderr"):
        stream = getattr(sys, attr)
        if stream is None:
            continue
        try:
            enc = getattr(stream, "encoding", None) or "utf-8"
            # 已是 utf-8 + replace，不需要重设
            if enc.lower().replace("-", "") == "utf8" and getattr(stream, "errors", None) == "replace":
                continue
            buf = getattr(stream, "buffer", None)
            if buf is not None:
                new_stream = io.TextIOWrapper(buf, encoding="utf-8", errors="replace", line_buffering=True)
                setattr(sys, attr, new_stream)
        except Exception:
            pass


def _safe_print(text: str, *, is_stderr: bool = False) -> None:
    """安全打印：先尝试正常 print；若遇到 UnicodeEncodeError，
    用当前终端编码的 replace 策略写入 buffer；
    若仍失败，至少打印一条纯 ASCII 提示，告知结果已存入 gzq_out.txt。
    """
    target = sys.stderr if is_stderr else sys.stdout
    try:
        print(text, end="", file=target)
        return
    except UnicodeEncodeError:
        pass
    # 第二层：buffer 直写 + replace
    try:
        enc = getattr(target, "encoding", None) or "utf-8"
        buf = getattr(target, "buffer", None)
        if buf is not None:
            buf.write(text.encode(enc, errors="replace"))
            buf.flush()
            return
    except Exception:
        pass
    # 第三层：纯 ASCII 提示
    out_file = os.path.join(tempfile.gettempdir(), "gzq_out.txt")
    try:
        print(
            f"[call.py] Output contains unencodable characters; "
            f"full result saved to {out_file}",
            file=target,
        )
    except Exception:
        pass


def _resolve_session_file():
    """按优先级解析 session 文件路径，支持多会话并行：
    1) QBS_SESSION_FILE 环境变量直接指定路径（最高优先级）
    2) QBS_SESSION_KEY 派生为 .session.<key>.json
    3) 默认 .session.json（向后兼容单会话场景）
    """
    explicit = os.environ.get("QBS_SESSION_FILE", "").strip()
    if explicit:
        return explicit
    key = os.environ.get("QBS_SESSION_KEY", "").strip()
    if key:
        # 仅允许字母数字、连字符、下划线，防止路径注入
        safe_key = re.sub(r"[^A-Za-z0-9_\-]", "_", key)[:64]
        return os.path.join(SKILL_ROOT, "output", f".session.{safe_key}.json")
    return os.path.join(SKILL_ROOT, "output", ".session.json")


SESSION_FILE = _resolve_session_file()


def _cleanup_stale_sessions(max_age_days: int = 7):
    """清理 output/ 下超过 max_age_days 的 .session.*.json，best-effort，失败不抛。"""
    try:
        import glob
        import time
        cutoff = time.time() - max_age_days * 86400
        for path in glob.glob(os.path.join(SKILL_ROOT, "output", ".session.*.json")):
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
            except Exception:
                pass
    except Exception:
        pass


def _read_skill_version() -> str:
    """从 SKILL.md frontmatter 读取 version 字段；读取失败时返回空字符串。"""
    skill_md = os.path.join(SKILL_ROOT, "SKILL.md")
    try:
        with open(skill_md, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("version:"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return ""


def _read_session():
    """读取当前 session 的 task_id，不存在则返回 None。"""
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("task_id")
    except Exception:
        return None


def _write_session(task_id, user_query=None):
    """持久化 task_id（和可选的 user_query）到 .session.json，同时写入当前 skill 版本。"""
    os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
    data = {"task_id": task_id, "skill_version_at_creation": _read_skill_version()}
    if user_query is not None:
        data["user_query"] = user_query
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


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
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            [sys.executable, EXECUTOR, tool_name, param_arg],
            capture_output=True, timeout=900,
            creationflags=extra_flags,
            env=env,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        # 子进程超时（900s），返回明确错误码与提示，避免向上抛出导致客户端崩溃
        msg = (
            f"[call.py] tool '{tool_name}' exceeded 900s timeout; "
            "subprocess killed. Consider splitting into smaller batches."
        )
        return 124, b"", msg.encode("utf-8")
    except KeyboardInterrupt:
        # 捕获并重试一次（处理极端情况）
        try:
            result = subprocess.run(
                [sys.executable, EXECUTOR, tool_name, param_arg],
                capture_output=True, timeout=900,
                creationflags=extra_flags,
                env=env,
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            msg = (
                f"[call.py] tool '{tool_name}' exceeded 900s timeout on retry; "
                "subprocess killed."
            )
            return 124, b"", msg.encode("utf-8")
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
    """解码 base64 保存 JPG，返回文件路径。"""
    b64_clean = b64.split(",", 1)[1] if b64.startswith("data:") else b64
    # 修复 padding（base64 长度必须是 4 的倍数）
    b64_clean += "=" * (4 - len(b64_clean) % 4)
    name = params.get("title", params.get("name", "chart"))
    name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    output_dir = os.path.join(SKILL_ROOT, "output")
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"{name}.jpg")
    img_data = base64.b64decode(b64_clean)
    try:
        from io import BytesIO
        from PIL import Image
        img = Image.open(BytesIO(img_data)).convert("RGB")
        img.save(out_path, "JPEG", quality=90)
    except ImportError:
        # Pillow 未安装时直接写原始字节（保留服务端格式）
        with open(out_path, "wb") as f:
            f.write(img_data)
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
        s = existing_dims[dim].get("score", 50)
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


def _auto_summarize_read_data(stdout_str, params):
    """readData last_column_full 模式：为布尔掩码数据注入 matched_names 平铺列表。

    触发条件：mode=last_column_full 且数据为布尔型（signature.is_bool=true 或值域仅含 0/1）。
    效果：注入 matched_count + matched_names（value=1 的命中名单），便于 LLM 直接读取，
    无需遍历 values 列表（如 5000 行只需读 matched_names 的 75 个名字）。

    零值过滤由后端 allow_zero_values 参数控制，此处不再重复过滤：
    - allow_zero_values=false（默认）：后端已过滤零值，values 仅含命中行
    - allow_zero_values=true：后端保留零值，values 含全部行，matched_names 仍仅含命中名单
    非布尔型数据原样返回，不做任何修改。
    """
    if params.get("mode") != "last_column_full":
        return stdout_str

    try:
        resp = json.loads(stdout_str)
    except (json.JSONDecodeError, ValueError):
        return stdout_str

    if resp.get("code") != 0:
        return stdout_str

    outer_data = resp.get("data", {})
    if not isinstance(outer_data, dict):
        return stdout_str

    inner_list = outer_data.get("data", [])
    if not isinstance(inner_list, list) or not inner_list:
        return stdout_str

    modified = False
    for item in inner_list:
        if not isinstance(item, dict):
            continue
        lcf = item.get("last_column_full")
        if not isinstance(lcf, dict):
            continue

        values = lcf.get("values", [])
        if not isinstance(values, list) or not values:
            continue

        # 判断是否为布尔型：优先读 signature.is_bool，其次抽样检测值域
        sig = item.get("signature") or {}
        is_bool = sig.get("is_bool", False)
        if not is_bool:
            sample = [v.get("value") for v in values[:200] if v.get("value") is not None]
            if sample and all(v in (0, 1, 0.0, 1.0) for v in sample):
                is_bool = True

        if not is_bool:
            continue

        # 布尔型：注入 matched_count + matched_names（仅统计命中=1的行）
        # values 列表本身不修改（已由后端按 allow_zero_values 控制）
        matched = [v for v in values if v.get("value") in (1, 1.0)]
        lcf["matched_count"] = len(matched)
        lcf["matched_names"] = [v.get("name", "") for v in matched if v.get("name")]
        modified = True

    if not modified:
        return stdout_str
    return json.dumps(resp, indent=2, ensure_ascii=False)


def _process_run_multi_formula_batch(stdout_str):
    """runMultiFormulaBatch 后处理：data.success=false 时把失败摘要提升到顶层。

    设计原则（方案 B）：
    - 不篡改服务端 code（保持 0），避免与服务端协议（成功 0 / 业务错误 -1）冲突
    - 不改进程 rc（HTTP 层确实成功）
    - 在顶层注入 success / errors / message，调用方只需看顶层字段即可识别失败
    - 区分「全部失败」和「部分成功」两种语义，避免部分成功结果被忽视
    """
    try:
        resp = json.loads(stdout_str)
    except (json.JSONDecodeError, ValueError):
        return stdout_str

    if resp.get("code") != 0:
        return stdout_str

    data = resp.get("data", {})
    if not isinstance(data, dict):
        return stdout_str

    # 仅在 success=false 时介入；success=true 或缺失（旧版本）时原样透传
    if data.get("success") is not False:
        return stdout_str

    errors = data.get("errors") or []
    dep = data.get("dependency_analysis") or {}
    total = data.get("total", len(errors))
    error_count = data.get("errorCount", len(errors))
    success_count = data.get("successCount", max(total - error_count, 0))

    resp["success"] = False
    resp["errors"] = [
        {
            "formula": e.get("formula"),
            "leftName": e.get("leftName"),
            "error": e.get("error"),
            "errorType": e.get("errorType"),
        }
        for e in errors
    ]

    if success_count == 0:
        resp["message"] = (
            f"runMultiFormulaBatch 全部失败（{error_count}/{total} 条），详见 errors 数组。"
        )
    else:
        resp["message"] = (
            f"runMultiFormulaBatch 部分失败（成功 {success_count}/{total}，失败 {error_count}/{total}），"
            f"成功结果仍在 data.data 中，失败详情见 errors。"
        )

    can_retry = dep.get("can_incremental_retry", False)
    if can_retry:
        resp["can_incremental_retry"] = True
        if dep.get("incremental_retry_suggestion"):
            resp["incremental_retry_suggestion"] = dep["incremental_retry_suggestion"]

    return json.dumps(resp, indent=2, ensure_ascii=False)


def _normalize_params(tool_name, params):
    """常见参数名错误自动修正，减少 LLM 调用失败率。"""
    if not isinstance(params, dict):
        return params

    # confirmMultipleAssets: assets/names/queries → intentions
    if tool_name == "confirmMultipleAssets":
        if "intentions" not in params or not params["intentions"]:
            for alias in ("assets", "names", "queries", "items"):
                if alias in params and params[alias]:
                    params["intentions"] = params.pop(alias)
                    break

    # runMultiFormulaBatch: formulas 元素必须是字符串，不能是对象
    if tool_name == "runMultiFormulaBatch" and "formulas" in params:
        fixed = []
        for item in params["formulas"]:
            if isinstance(item, str):
                fixed.append(item)
            elif isinstance(item, dict):
                # 尝试从对象中提取公式字符串
                f = item.get("formula") or item.get("expression") or item.get("value") or ""
                if f:
                    fixed.append(f)
        params["formulas"] = fixed

    return params


def main():
    _configure_parent_stdio()

    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    tool_name = sys.argv[1]

    # ── newSession：生成新 task_id 并持久化 ──────────────────────
    if tool_name == "newSession":
        new_id = str(uuid.uuid4())

        # 顺手清理超过 7 天的旧 session 文件，避免 output/ 累积垃圾
        _cleanup_stale_sessions()

        # 尝试解析 user_query 参数（用于服务端 trace 分析，失败不影响主流程）
        _raw_params = os.environ.get("GZQ_PARAMS", "").strip()
        if not _raw_params and len(sys.argv) >= 3:
            if sys.argv[2].startswith("@"):
                try:
                    with open(sys.argv[2][1:], "r", encoding="utf-8") as _f:
                        _raw_params = _f.read()
                except Exception:
                    pass
            else:
                _raw_params = " ".join(sys.argv[2:])
        _ns_params = {}
        try:
            _ns_params = json.loads(_raw_params or "{}")
        except Exception:
            pass
        user_query = _ns_params.get("user_query") or None

        # 在覆写 session 文件之前，先读取旧版本号（用于检测版本变更）
        _prev_version = None
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as _sf:
                _prev_version = json.load(_sf).get("skill_version_at_creation")
        except Exception:
            pass

        _write_session(new_id, user_query=user_query)
        _current_ver = _read_skill_version()
        _version_changed = bool(_prev_version and _prev_version != _current_ver)

        # Fire-and-forget：把原始问题上报给服务端，供 trace 分析用
        # 读取 config 获取 endpoint / api_key
        try:
            import urllib.request
            _cfg_path = os.path.join(SKILL_ROOT, "config.json")
            with open(_cfg_path, "r", encoding="utf-8") as _f:
                _cfg = json.load(_f)
            _local_cfg_path = os.path.join(SKILL_ROOT, "config.local.json")
            if os.path.exists(_local_cfg_path):
                with open(_local_cfg_path, "r", encoding="utf-8") as _f:
                    _local = json.load(_f)
                for k, v in _local.items():
                    if v not in (None, ""):
                        _cfg[k] = v
            _env_key = os.environ.get("QUANT_BUDDY_API_KEY", "").strip()
            if _env_key:
                _cfg["api_key"] = _env_key
            _endpoint = _cfg.get("endpoint", "").rstrip("/")
            _api_key = _cfg.get("api_key", "")
            _channel = _cfg.get("_channel", "")
            if _endpoint and _api_key:
                _payload = json.dumps({"task_id": new_id, "user_query": user_query},
                                      ensure_ascii=False).encode("utf-8")
                _headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {_api_key}",
                    "x-skill-version": _current_ver,
                }
                if _channel:
                    _headers["x-skill-channel"] = _channel
                _req = urllib.request.Request(
                    f"{_endpoint}/skill/session/begin",
                    data=_payload,
                    headers=_headers,
                    method="POST",
                )
                urllib.request.urlopen(_req, timeout=3)
        except Exception:
            pass  # 上报失败不影响 session 创建

        result = json.dumps({
            "code": 0,
            "task_id": new_id,
            "skill_version": _current_ver,
            "version_changed_from_last_session": _version_changed,
            "previous_skill_version": _prev_version if _version_changed else None,
            "message": (
                f"新 session 已创建（skill {_current_ver}）。"
                + (f"检测到 skill 从 {_prev_version} 升级到 {_current_ver}，"
                   "旧上下文中的工具签名/参数可能已失效，必须先重读 SKILL.md 再继续。"
                   if _version_changed else
                   "task_id 已保存到 .session.json，后续调用自动注入。")
            ),
        }, ensure_ascii=False, indent=2)
        out_file = os.path.join(tempfile.gettempdir(), "gzq_out.txt")
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(result)
        _safe_print(result)
        sys.exit(0)

    # ── 事件研究本地工具（不走 executor / 平台 API）───────────────
    if tool_name in ("webSearch", "buildEventStudy"):
        from event_study_local import bocha_web_search, build_event_study

        # 解析参数（复用与下方相同的优先级逻辑）
        _raw = os.environ.get("GZQ_PARAMS", "").strip()
        if not _raw and len(sys.argv) >= 3:
            if sys.argv[2].startswith("@"):
                with open(sys.argv[2][1:], "r", encoding="utf-8") as _f:
                    _raw = _f.read()
            else:
                _raw = " ".join(sys.argv[2:])
        if not _raw and not sys.stdin.isatty():
            _raw = sys.stdin.buffer.read().decode("utf-8", errors="replace").strip()
        _params = json.loads(_raw or "{}")

        try:
            if tool_name == "webSearch":
                _result = bocha_web_search(
                    query=_params.get("query", ""),
                    freshness_months=int(_params.get("freshness_months", 36)),
                    count=_params.get("count"),
                )
            else:
                _result = build_event_study(_params)
        except Exception as _exc:
            _result = {"code": 1, "error": str(_exc)}

        _output = json.dumps(_result, ensure_ascii=False, indent=2)
        out_file = os.path.join(tempfile.gettempdir(), "gzq_out.txt")
        with open(out_file, "w", encoding="utf-8") as _f:
            _f.write(_output)
        _safe_print(_output)
        sys.exit(0)

    # ── 版本守卫：检测旧会话与当前 skill 版本是否匹配 ─────────────
    current_version = _read_skill_version()
    if current_version:
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as _sf:
                _session_data = json.load(_sf)
            session_version = _session_data.get("skill_version_at_creation")
            if session_version is None or session_version != current_version:
                _mismatch_result = json.dumps({
                    "error": "SKILL_VERSION_MISMATCH",
                    "current_version": current_version,
                    "session_version": session_version,
                    "message": (
                        f"检测到 skill 版本不匹配（session 创建于 {session_version}，当前为 {current_version}）。"
                        "请立即调用 newSession 创建新 session，"
                        "然后强制重读 SKILL.md 及当前 workflow 后再继续。"
                    ),
                }, ensure_ascii=False, indent=2)
                out_file = os.path.join(tempfile.gettempdir(), "gzq_out.txt")
                with open(out_file, "w", encoding="utf-8") as _of:
                    _of.write(_mismatch_result)
                _safe_print(_mismatch_result)
                sys.exit(0)
        except FileNotFoundError:
            # 尚未创建过 session，不阻断（模型可能正要新建）
            pass
        except Exception:
            pass

    # ── 解析参数来源 ──────────────────────────────────────────────
    # 优先级: GZQ_PARAMS 环境变量 > @file > 命令行 argv > stdin
    raw = None
    at_file = None

    env_params = os.environ.get("GZQ_PARAMS", "").strip()
    if env_params:
        raw = env_params
    elif len(sys.argv) >= 3 and sys.argv[2].startswith("@"):
        at_file = sys.argv[2]          # @/path/to/file.json
    elif len(sys.argv) >= 3:
        raw = " ".join(sys.argv[2:])
    elif not sys.stdin.isatty():
        raw_bytes = sys.stdin.buffer.read()
        raw = raw_bytes.decode("utf-8", errors="replace").strip()

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
            # 自动修正常见参数名错误
            params = _normalize_params(tool_name, params)
            # 如果参数被修正了，需要重写文件
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(params, f, ensure_ascii=False)
            except Exception:
                pass
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

            # 自动修正常见参数名错误
            params = _normalize_params(tool_name, params)

            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="gzq_")
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(params, f, ensure_ascii=False)
            param_arg = f"@{tmp_path}"

        # ── 自动注入 session 字段（task_id、user_query）──────────────
        session_task_id = _read_session()
        _needs_rewrite = False
        if session_task_id and "task_id" not in params:
            params["task_id"] = session_task_id
            _needs_rewrite = True
        # 注入 user_query（供服务端 skill_call_logs trace 用）
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as _sf:
                _uq = json.load(_sf).get("user_query")
            if _uq and "user_query" not in params:
                params["user_query"] = _uq
                _needs_rewrite = True
        except Exception:
            pass
        if _needs_rewrite and tmp_path:
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
        # readData last_column_full 布尔掩码：注入 matched_names
        if tool_name == "readData" and rc == 0:
            stdout = _auto_summarize_read_data(stdout, params)
        # runMultiFormulaBatch：code=0 但 data.success=false 时提升 errors
        if tool_name == "runMultiFormulaBatch" and rc == 0:
            stdout = _process_run_multi_formula_batch(stdout)
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
            # GBK 终端无法打印 emoji 等字符；改用 buffer 直写并以 ? 替换不可编码字符，
            # 确保 Agent 始终能从 stdout 读到结果，不依赖回读 gzq_out.txt。
            enc = getattr(sys.stdout, 'encoding', None) or 'utf-8'
            if stdout:
                sys.stdout.buffer.write(stdout.encode(enc, errors='replace'))
                sys.stdout.buffer.flush()
            enc_err = getattr(sys.stderr, 'encoding', None) or 'utf-8'
            if stderr:
                sys.stderr.buffer.write(stderr.encode(enc_err, errors='replace'))
                sys.stderr.buffer.flush()

        sys.exit(rc)

    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


if __name__ == "__main__":
    main()
