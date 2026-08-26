#!/usr/bin/env python3
r"""
公式任务包（Formula Package）客户端 —— 注册一组公式为任务包，凭包凭证流式取数。

对接接口文档：docs/formulaPackage 相关文档/对外接口文档.md
工具说明文档：tools/formula_package.md

两段式使用：
  1. 注册（需 API Key）：提交一组 formulas + 各产出读取模式，服务端执行校验后
     返回 package_id + signature（signature 仅此一次明文返回，请妥善保存）。
  2. 取数（无需 API Key）：凭 package_id + signature 拉取数据，SSE 流式返回，
     底层数据更新后自动重算，永远返回最新结果。

子命令：
    register  注册任务包（读 config.json 的 api_key + endpoint）
    query     取数（无需 api_key，凭 package_id + signature）
    list      列出我的任务包（需 api_key）
    revoke    撤销任务包（需 api_key）
    refresh   强制刷新/轮换签名（需 api_key）
    import    从 quant-buddy-skill 的凭证目录导入已注册包（纯本地，无需 api_key/会话）

参数传递（规避 PowerShell GBK 截断中文）：
    优先级：FP_PARAMS 环境变量 > @file > 命令行 JSON > stdin

用法示例：
    # 注册（推荐用 @file 传中文公式，Windows 必须）
    python scripts/formula_package.py register @params.json

    # 取数（package_id + signature 即可，不需要 api_key）
    FP_PARAMS='{"package_id":"pkg_xxx","signature":"a1b2..."}' \
        python scripts/formula_package.py query

    # 管理
    python scripts/formula_package.py list '{"page":1,"page_size":20}'
    python scripts/formula_package.py revoke '{"package_id":"pkg_xxx"}'
    python scripts/formula_package.py refresh '{"package_id":"pkg_xxx","rotate_signature":true}'

    # 从旧 quant-buddy-skill 迁移凭证（升级到 view 后一次性，无需重注册）：
    #   显式指定源目录（推荐）
    python scripts/formula_package.py import '{"from":"D:/.../quant-buddy-skill/output/formula_packages"}'
    #   或设环境变量 QBS_IMPORT_CRED_DIR；或留空走同级 quant-buddy-skill 兜底猜测
    QBS_IMPORT_CRED_DIR='D:/.../quant-buddy-skill/output/formula_packages' \
        python scripts/formula_package.py import

输出：
    结果打印到 stdout（UTF-8），并写入临时目录下 fp_out.txt（防终端缓冲吞输出）。
    register / query 成功时，包凭证额外落盘到 output/formula_packages/<package_id>.json，
    方便后续取数与 build_dashboard 引用（signature 服务端不可再取出，本地不存丢失即不可恢复）。

认证：register/list/revoke/refresh 凭 config.json 的 api_key（Bearer）认身份；query 以 package_id + signature
为能力凭证，CLI 本地有 api_key 时会可选附带用于审计归因，浏览器无 Key 取数仍兼容。活页任务通过参数复用 trace_context.py begin 返回的 task_id，
公共 headers() 会自动透传 x-task-id 供后端聚合调用链。
"""

import json
import os
import re
import sys
from pathlib import Path
import urllib.error
import urllib.request

import common as C

SKILL_ROOT = C.SKILL_ROOT

# 公式包接口前缀固定带 /skill（服务端 router 同时挂在 / 与 /skill，endpoint 带不带 /skill 均可解析）
_PATH = {
    "register": "/skill/registerFormulaPackage",
    "query":    "/skill/queryFormulaPackage",
    "list":     "/skill/listFormulaPackages",
    "revoke":   "/skill/revokeFormulaPackage",
    "refresh":  "/skill/refreshFormulaPackage",
}

# 取数（SSE）可能等待服务端重算，给足超时
_QUERY_TIMEOUT = 1800
_DEFAULT_TIMEOUT = 600
_ALLOWED_READ_MODES = {"last_day_stats", "last_valid_per_asset", "range_data"}
_ASSIGN_RE = re.compile(r"(?<![<>=!])=(?!=)")


def _config(require_key):
    """加载 endpoint(+api_key)。query 子命令 require_key=False（取数无需 api_key）。"""
    cfg = C.load_config_require_key() if require_key else C.load_config()
    return C.endpoint_of(cfg), cfg.get("api_key", "")


def _save_credential(reg):
    """注册/轮换成功后把 package_id + signature 落盘，供后续取数 / 看板引用。"""
    pkg = reg.get("package_id")
    sig = reg.get("signature")
    if not pkg or not sig:
        return None
    out_dir = os.path.join(SKILL_ROOT, "output", "formula_packages")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{pkg}.json")
    record = {
        "package_id": pkg,
        "signature": sig,
        "outputs": reg.get("outputs"),
        "expires_at": reg.get("expires_at"),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    return path


def load_credential(package_id):
    """从本地凭证目录读取 {package_id, signature, outputs, ...}，不存在返回 None。"""
    cred = os.path.join(SKILL_ROOT, "output", "formula_packages", f"{package_id}.json")
    if os.path.exists(cred):
        try:
            with open(cred, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def _split_left_values(formula):
    m = _ASSIGN_RE.search(formula)
    if not m:
        return []
    left = formula[:m.start()].strip()
    return [x.strip() for x in re.split(r"[,，]", left) if x.strip()]


def _preflight_register_params(params):
    """Local register preflight for cheap shape errors before auth/network."""
    errors = []
    warnings = []
    formulas = params.get("formulas")
    reads = params.get("reads")
    left_values = []
    seen = {}

    if not isinstance(formulas, list) or not formulas:
        errors.append("formulas 必须是非空字符串数组")
    else:
        if len(formulas) > 100:
            errors.append(f"单包公式数 ≤ 100，当前 {len(formulas)}")
        for i, formula in enumerate(formulas):
            if not isinstance(formula, str):
                errors.append(f"formulas[{i}] 必须是字符串，当前是 {type(formula).__name__}")
                continue
            text = formula.strip()
            if not text:
                errors.append(f"formulas[{i}] 不能为空字符串")
                continue
            if not _ASSIGN_RE.search(text):
                errors.append(f"formulas[{i}] 缺少左值赋值：每条公式必须形如 `变量名 = 表达式`")
                continue
            lefts = _split_left_values(text)
            if not lefts:
                errors.append(f"formulas[{i}] 左值为空：每条公式必须形如 `变量名 = 表达式`")
                continue
            assignment = _ASSIGN_RE.search(text)
            right = text[assignment.end():].strip() if assignment else ""
            for left in lefts:
                if left in seen:
                    errors.append(f"公式左值重复：`{left}` 同时出现在 formulas[{seen[left]}] 和 formulas[{i}]")
                else:
                    seen[left] = i
                    left_values.append(left)
                if left.lower().endswith("_pctile"):
                    alias = re.fullmatch(r'["\']([^"\']+)["\']', right)
                    if alias and not alias.group(1).lower().endswith("_pctile"):
                        errors.append(
                            f"`{left}` 是历史分位输出，不能直接别名到 `{alias.group(1)}`；"
                            "请使用带明确窗口的历史水位公式（如排序水位或数值水位）并先通过 QBS 验证"
                        )

    if not isinstance(reads, list) or not reads:
        errors.append("reads 必须是非空数组")
    else:
        if len(reads) > 20:
            errors.append(f"单包对外产出数 ≤ 20，当前 {len(reads)}")
        for i, read in enumerate(reads):
            if not isinstance(read, dict):
                errors.append(f"reads[{i}] 必须是对象，包含 output/read_mode")
                continue
            output = read.get("output")
            mode = read.get("read_mode")
            if not isinstance(output, str) or not output.strip():
                errors.append(f"reads[{i}].output 必须是非空字符串")
            elif left_values and output.strip() not in seen:
                errors.append(
                    f"reads[{i}].output `{output}` 未命中公式左值；可用左值：{', '.join(left_values)}"
                )
            if mode == "last_value":
                errors.append("read_mode=last_value 已废弃/不支持，请改用 last_day_stats")
            elif mode not in _ALLOWED_READ_MODES:
                errors.append(
                    f"reads[{i}].read_mode `{mode}` 不支持；只允许 "
                    f"{', '.join(sorted(_ALLOWED_READ_MODES))}"
                )

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "left_values": left_values,
        "allowed_read_modes": sorted(_ALLOWED_READ_MODES),
    }


# ────────────────────────────────────────────────
# 子命令
# ────────────────────────────────────────────────

def cmd_register(params):
    preflight = _preflight_register_params(params)
    if not preflight["ok"]:
        return {
            "code": 1,
            "error": "PREFLIGHT_FAILED",
            "message": "公式任务包注册参数预检失败",
            "_preflight": preflight,
        }
    endpoint, api_key = _config(require_key=True)
    formulas = params.get("formulas")
    reads = params.get("reads")
    body = {"formulas": formulas, "reads": reads}
    for k in ("intents", "begin_date", "ttl_days"):
        if params.get(k) is not None:
            body[k] = params[k]
    reg = C.http_json("POST", C.api_url(endpoint, _PATH["register"]),
                      C.headers(api_key), body, timeout=_DEFAULT_TIMEOUT)
    if isinstance(reg, dict):
        reg["_preflight"] = preflight
    if reg.get("code") == 0 and reg.get("package_id"):
        saved = _save_credential(reg)
        if saved:
            reg["_saved_credential"] = saved
    return reg


def query_package(endpoint, package_id, signature, outputs=None, api_key=""):
    """取数核心：逐条 SSE → 组装为 {code, outputs, progress, done}。供 build_dashboard 复用。"""
    request_body = {"package_id": package_id, "signature": signature}
    if isinstance(outputs, list) and outputs:
        request_body["outputs"] = outputs
    body = json.dumps(request_body).encode("utf-8")
    req = urllib.request.Request(C.api_url(endpoint, _PATH["query"]), data=body,
                                 headers=C.headers(api_key, accept="text/event-stream"),
                                 method="POST")
    outputs = {}
    progress = []
    done = None
    err = None
    try:
        resp = C._NO_PROXY_OPENER.open(req, timeout=_QUERY_TIMEOUT)
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"code": e.code, "success": False,
                    "error": {"message": getattr(e, "reason", str(e))}}
    except Exception as e:
        return {"code": 1, "success": False, "error": {"message": str(e)}}

    event_type, data_buf = None, []
    with resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            if line == "":
                if event_type and data_buf:
                    try:
                        payload = json.loads("\n".join(data_buf))
                    except json.JSONDecodeError:
                        payload = {"raw": "\n".join(data_buf)}
                    if event_type == "result":
                        outputs[payload.get("output")] = {
                            "read_mode": payload.get("read_mode"),
                            "data_id": payload.get("data_id"),
                            "data": payload.get("data"),
                            "error": payload.get("error"),   # 失败产出带 error 而非 data，透出别丢
                        }
                        _e = payload.get("error")
                        sys.stderr.write(f"  {'✗' if _e else '✓'} {payload.get('output')} "
                                         f"({payload.get('read_mode')})" + (f" — {_e}" if _e else "") + "\n")
                        sys.stderr.flush()
                    elif event_type == "progress":
                        progress.append(payload)
                        sys.stderr.write(f"  … recomputing {payload.get('node')} "
                                         f"{payload.get('done')}/{payload.get('total')}\n")
                        sys.stderr.flush()
                    elif event_type == "done":
                        done = payload
                    elif event_type == "error":
                        err = payload
                event_type, data_buf = None, []
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                data_buf.append(line[5:].lstrip())

    if err is not None:
        return {"code": 1, "success": False, "error": err,
                "outputs": outputs, "progress": progress}
    # 信号透传：done.code≠0（服务端判部分产出失败）或存在带 error 的产出 → 整体判失败。
    # 此前这里硬编码 code:0，把服务端的失败信号丢在 done 字段里，build_dashboard 永远看到成功。
    done_code = (done or {}).get("code", 0)
    failed = [o for o, v in outputs.items() if v.get("error")]
    code = 1 if (done_code not in (0, None) or failed) else 0
    failures = (done or {}).get("failures") or (
        [{"output": o, "error": outputs[o].get("error")} for o in failed] or None)
    ret = {"code": code, "success": code == 0, "package_id": package_id,
           "outputs": outputs, "progress": progress, "done": done}
    if failures:
        ret["failures"] = failures
    return ret


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _unwrap_read_data(data):
    current = data
    while isinstance(current, dict):
        nested = None
        for key in ("range_data", "last_value", "last_day_stats", "last_valid_per_asset"):
            if isinstance(current.get(key), (dict, list)):
                nested = current[key]
                break
        if nested is None:
            break
        current = nested
    return current


def _series_summary(values, dates=None, name=None):
    dates = dates if isinstance(dates, list) else []
    valid = [(idx, float(value)) for idx, value in enumerate(values or []) if _is_number(value)]
    if not valid:
        return {"name": name, "first_value": None, "latest_value": None, "first_date": None,
                "latest_date": None, "change_rate_pct": None, "valid_sample_count": 0}
    first_idx, first_value = valid[0]
    last_idx, latest_value = valid[-1]
    change = None if first_value == 0 else (latest_value / first_value - 1) * 100
    return {
        "name": name,
        "first_value": first_value,
        "latest_value": latest_value,
        "first_date": dates[first_idx] if first_idx < len(dates) else None,
        "latest_date": dates[last_idx] if last_idx < len(dates) else None,
        "change_rate_pct": change,
        "valid_sample_count": len(valid),
    }


def summarize_output_data(data):
    """把公式包输出压成无原始时间数组的首尾/变化/样本摘要。"""
    data = _unwrap_read_data(data)
    if isinstance(data, dict):
        dates = data.get("dates") if isinstance(data.get("dates"), list) else []
        values = data.get("values")
        if isinstance(values, list):
            if values and all(_is_number(item) or item is None for item in values):
                return _series_summary(values, dates)
            if values and all(isinstance(item, list) for item in values):
                names = data.get("series_names") or data.get("names") or []
                return {
                    "series": [
                        _series_summary(series, dates, names[idx] if idx < len(names) else f"series_{idx + 1}")
                        for idx, series in enumerate(values)
                    ]
                }
        if _is_number(data.get("value")):
            value = float(data["value"])
            date = data.get("date") or data.get("trade_date") or data.get("computed_at")
            return {
                "first_value": value,
                "latest_value": value,
                "first_date": date,
                "latest_date": date,
                "change_rate_pct": 0.0,
                "valid_sample_count": 1,
            }
        for collection_key in ("records", "items", "top_values"):
            records = data.get(collection_key)
            if isinstance(records, list):
                summarized = summarize_output_data(records)
                if summarized:
                    return summarized
        numeric_fields = {key: float(value) for key, value in data.items() if _is_number(value)}
        return {
            "latest_date": data.get("date") or data.get("trade_date") or data.get("computed_at"),
            "latest_values": numeric_fields,
            "valid_sample_count": len(numeric_fields),
        }
    if isinstance(data, list):
        series = {}
        dates = []
        for item in data:
            if not isinstance(item, dict):
                continue
            dates.append(item.get("date") or item.get("trade_date") or item.get("computed_at"))
            row_index = len(dates) - 1
            for values in series.values():
                values.append(None)
            for key, value in item.items():
                if _is_number(value):
                    if key not in series:
                        series[key] = [None] * row_index + [value]
                    else:
                        series[key][-1] = value
        if series:
            summaries = [_series_summary(values, dates, name) for name, values in series.items()]
            return summaries[0] if len(summaries) == 1 else {"series": summaries}
        return {"latest_value": None, "latest_date": None, "valid_sample_count": 0}
    if _is_number(data):
        value = float(data)
        return {"first_value": value, "latest_value": value, "first_date": None,
                "latest_date": None, "change_rate_pct": 0.0, "valid_sample_count": 1}
    return {"latest_value": None, "latest_date": None, "valid_sample_count": 0}


def _compact_query_result(result, result_mode):
    if result_mode == "full" or not isinstance(result, dict):
        return result
    compact = {key: value for key, value in result.items() if key not in ("outputs", "progress")}
    compact["result_mode"] = result_mode
    compact["progress_count"] = len(result.get("progress") or [])
    compact_outputs = {}
    for name, item in (result.get("outputs") or {}).items():
        summary = summarize_output_data(item.get("data"))
        if result_mode == "last_values":
            if isinstance(summary.get("series"), list):
                summary = {
                    "series": [
                        {"name": row.get("name"), "latest_value": row.get("latest_value"), "latest_date": row.get("latest_date")}
                        for row in summary["series"]
                    ]
                }
            else:
                summary = {key: summary.get(key) for key in ("latest_value", "latest_date", "latest_values") if key in summary}
        compact_outputs[name] = {
            "read_mode": item.get("read_mode"),
            "data_id": item.get("data_id"),
            "summary": summary,
            "error": item.get("error"),
        }
    compact["outputs"] = compact_outputs
    return compact


def cmd_query(params):
    """取数：无需 api_key，凭 package_id + signature（signature 可由本地凭证补全）。"""
    endpoint, api_key = _config(require_key=False)
    pkg = params.get("package_id")
    sig = params.get("signature")
    if pkg and not sig:
        cred = load_credential(pkg)
        if cred:
            sig = cred.get("signature")
    if not pkg or not sig:
        return {"code": 1, "message": "query 需要 package_id + signature（signature 可由本地凭证补全）"}
    outputs = params.get("outputs")
    if outputs is not None and (not isinstance(outputs, list) or not all(isinstance(item, str) and item.strip() for item in outputs)):
        return {"code": 1, "message": "outputs 必须是非空字符串数组"}
    result_mode = str(params.get("result_mode") or ("summary" if params.get("direct") else "full")).strip().lower()
    if result_mode not in ("full", "summary", "last_values"):
        return {"code": 1, "message": "result_mode 只允许 full / summary / last_values"}
    return _compact_query_result(query_package(endpoint, pkg, sig, outputs=outputs, api_key=api_key), result_mode)


def _resolve_import_dir(params):
    """凭证导入源目录：显式参数 > 环境变量 > 共享活动 QBS resolver。"""
    explicit = (params.get("from") or params.get("import_from") or params.get("dir") or "").strip()
    if explicit:
        return explicit, "params"
    env_dir = os.environ.get("QBS_IMPORT_CRED_DIR", "").strip()
    if env_dir:
        return env_dir, "env(QBS_IMPORT_CRED_DIR)"
    resolution = C.resolve_qbs_skill_root()
    root = resolution.get("root")
    if root is not None:
        return os.path.join(str(root), "output", "formula_packages"), "default(resolved qbs skill)"
    call_script = resolution.get("call_script")
    guess_root = call_script.parent.parent if call_script else Path(SKILL_ROOT).parent / "quant-buddy-skill"
    return os.path.join(str(guess_root), "output", "formula_packages"), "default(unresolved qbs skill)"


def cmd_import(params):
    """从 quant-buddy-skill 的凭证目录一次性导入已注册包的 {package_id, signature, ...}。

    纯本地操作（不需 api_key / task_id / 网络）：把源目录下的 *.json 拷进本 skill 的
    output/formula_packages/，使老用户迁移到 view 后无需重注册即可凭旧 package_id 取数。
    默认不覆盖已存在凭证（传 overwrite=true 才覆盖）。
    """
    src_dir, src_kind = _resolve_import_dir(params)
    if not os.path.isdir(src_dir):
        return {"code": 1, "error": "IMPORT_DIR_NOT_FOUND",
                "message": (f"凭证源目录不存在：{src_dir}（来源：{src_kind}）。"
                            "请用 `{\"from\":\"<skill>/output/formula_packages\"}` 显式指定，"
                            "或设置环境变量 QBS_IMPORT_CRED_DIR。"),
                "source_dir": src_dir}

    overwrite = bool(params.get("overwrite", False))
    dst_dir = os.path.join(SKILL_ROOT, "output", "formula_packages")
    os.makedirs(dst_dir, exist_ok=True)

    imported, skipped, invalid = [], [], []
    for name in sorted(os.listdir(src_dir)):
        if not name.endswith(".json"):
            continue
        src_path = os.path.join(src_dir, name)
        try:
            with open(src_path, "r", encoding="utf-8") as f:
                rec = json.load(f)
        except Exception as e:
            invalid.append({"file": name, "reason": f"读取/解析失败: {e}"})
            continue
        if not (rec.get("package_id") and rec.get("signature")):
            invalid.append({"file": name, "reason": "缺少 package_id 或 signature"})
            continue
        dst_path = os.path.join(dst_dir, name)
        if os.path.exists(dst_path) and not overwrite:
            skipped.append(rec.get("package_id") or name)
            continue
        with open(dst_path, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=2)
        imported.append(rec.get("package_id") or name)

    return {
        "code": 0,
        "source_dir": src_dir,
        "source_kind": src_kind,
        "dest_dir": dst_dir,
        "imported": imported,
        "skipped_existing": skipped,
        "invalid": invalid,
        "message": (
            f"已从 {src_kind} 导入 {len(imported)} 个凭证"
            + (f"，跳过 {len(skipped)} 个已存在（传 overwrite=true 可覆盖）" if skipped else "")
            + (f"，{len(invalid)} 个无效" if invalid else "")
            + "。现在可直接用 query 凭旧 package_id 取数。"
        ),
    }


def cmd_list(params):
    import urllib.parse as _up
    endpoint, api_key = _config(require_key=True)
    page = params.get("page", 1)
    page_size = params.get("page_size", 20)
    qs_pairs = [("page", page), ("page_size", page_size)]
    url = C.api_url(endpoint, _PATH["list"]) + "?" + _up.urlencode(qs_pairs)
    return C.http_json("GET", url, C.headers(api_key))


def cmd_revoke(params):
    endpoint, api_key = _config(require_key=True)
    if not params.get("package_id"):
        return {"code": 1, "message": "revoke 需要 package_id"}
    body = {"package_id": params["package_id"]}
    return C.http_json("POST", C.api_url(endpoint, _PATH["revoke"]), C.headers(api_key), body)


def cmd_refresh(params):
    endpoint, api_key = _config(require_key=True)
    if not params.get("package_id"):
        return {"code": 1, "message": "refresh 需要 package_id"}
    body = {"package_id": params["package_id"],
            "rotate_signature": bool(params.get("rotate_signature", False))}
    res = C.http_json("POST", C.api_url(endpoint, _PATH["refresh"]), C.headers(api_key), body)
    rotated = bool(params.get("rotate_signature", False))
    if res.get("code") == 0 and res.get("signature"):
        cred = os.path.join(SKILL_ROOT, "output", "formula_packages",
                            f"{params['package_id']}.json")
        cred_updated = False
        if os.path.exists(cred):
            try:
                with open(cred, "r", encoding="utf-8") as f:
                    rec = json.load(f)
                rec["signature"] = res["signature"]
                with open(cred, "w", encoding="utf-8") as f:
                    json.dump(rec, f, ensure_ascii=False, indent=2)
                res["_credential_updated"] = cred
                cred_updated = True
            except Exception:
                pass
        # 轮换成功后打醒目善后提醒：新签名已生效，所有内嵌旧签名的已发布页面此刻已失效，
        # 必须重建 + static_page update 每一个页面把新签名同步进去，否则它们取数会报 SIGNATURE_INVALID。
        if rotated:
            warn = ("⚠️ 签名已轮换，旧签名此刻已失效：所有内嵌该包旧签名的已发布页面现在取数会报 "
                    "SIGNATURE_INVALID。必须立即用新签名重建 HTML 并 static_page update 覆盖每一个页面（同 "
                    "page_id、链接不变）。新签名只此一次明文返回、服务端不可再取出，务必落库/记录。")
            if not cred_updated:
                warn += ("｜本地无该包凭证 output/formula_packages/{}.json，脚本未能回写新签名——"
                         "请手动保存上面的 signature，否则 build_dashboard 无法重建。").format(params["package_id"])
            res["_rotate_warning"] = warn
    return res


_COMMANDS = {
    "register": cmd_register,
    "query": cmd_query,
    "list": cmd_list,
    "revoke": cmd_revoke,
    "refresh": cmd_refresh,
    "import": cmd_import,
}

def main():
    # 注：common 在 import 时已把 stdout/stderr 重配为 UTF-8，无需重复包裹
    if len(sys.argv) < 2 or sys.argv[1] not in _COMMANDS:
        C.emit({"code": 1, "message": f"用法: formula_package.py <{'|'.join(_COMMANDS)}> [params]",
                "doc": (__doc__ or "").strip()[:400]}, out_name="fp_out.txt")
        sys.exit(1)
    cmd = sys.argv[1]
    params = C.read_params(sys.argv[2:], env_var="FP_PARAMS")

    try:
        result = _COMMANDS[cmd](params)
    except (FileNotFoundError, ValueError) as e:
        result = {"code": 1, "message": str(e)}
    C.emit(result, out_name="fp_out.txt")
    sys.exit(0 if (isinstance(result, dict) and result.get("code") == 0) else 1)


if __name__ == "__main__":
    main()
