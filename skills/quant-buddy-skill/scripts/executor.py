#!/usr/bin/env python3
r"""
观照量化投研 Skill 执行器

Usage:
    python scripts/executor.py <tool_name> @<params_file.json>   # 推荐，跨平台安全
    python scripts/executor.py <tool_name> '<json_params>'       # 仅 bash/zsh，不含中文时可用

PowerShell（Windows）— 必须用 @file 传参，中文字符在命令行参数中会被 GBK codepage 截断：
    # Step 1: 写参数文件
    echo '{"query": "均线金叉回测", "top_k": 3}' > /tmp/p.json

    # Step 2: 调用（结果直接打印到终端，不要再管道到文件）
    python scripts/executor.py searchSimilarCases @/tmp/p.json

    # ❌ 禁止：以下两种方式均在 Windows 中文环境下必然失败
    # python scripts\executor.py searchFunctions '{"query": "回测"}'   # 中文 GBK 截断
    # echo '...' | python scripts\executor.py searchFunctions          # GBK 管道

bash/zsh:
    python scripts/executor.py searchFunctions '{"query": "回测", "top_k": 5}'
"""

import sys
import io
import json
import os
import time
import re
import urllib.request
import urllib.error
from datetime import datetime

# ── 跳过 Windows 注册表代理检测（proxy_bypass_registry 在某些 Windows 环境极慢）──
# 使用空 ProxyHandler() 完全绕过系统代理，量化 API 是内网地址无需代理
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# ── Windows 下强制 stdout/stderr 使用 UTF-8，避免服务端返回 emoji 等字符时崩溃 ──
# line_buffering=True：每次 print 立即 flush，避免 PowerShell 终端首次读到空输出。
# 必须在任何 print 调用之前设置。
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
if hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

# scripts/ 目录的上一级即 skill 包根目录，config.json 在根目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(SCRIPT_DIR)

# ────────────────────────────────────────────────
# 工具名 → HTTP 方法 + 路径 映射表
# ────────────────────────────────────────────────
TOOL_ROUTES = {
    "searchFunctions":       ("POST", "/skill/searchFunctions"),
    "searchSimilarCases":    ("POST", "/skill/searchSimilarCases"),
    "getCardFormulas":       ("POST", "/skill/getCardFormulas"),
    "confirmDataMulti":      ("POST", "/skill/confirmDataMulti"),
    "confirmMultipleAssets": ("POST", "/skill/confirmMultipleAssets"),
    "runMultiFormula":       ("POST", "/skill/runMultiFormula"),
    "readData":              ("POST", "/skill/readData"),
    "uploadData":            ("POST", "/skill/upload/preview"),   # 两阶段：先 preview
    "uploadConfirm":         ("POST", "/skill/upload/confirm"),   # 再 confirm
    "downloadData":          ("GET",  "/skill/data/{id}"),        # id 从 params 取
    "renderChart":           ("POST", "/skill/renderChart"),
    "renderKLine":           ("POST", "/skill/renderKLine"),
    "getChartSpec":          ("GET",  "/skill/chartSpec/{task_id}"),
    "reRenderChart":         ("POST", "/skill/reRenderChart"),
    "scanDimensions":        ("POST", "/skill/scanDimensions"),
}

# saveChart 不走 HTTP，本地处理 base64 → PNG
SAVE_CHART_TOOL = "saveChart"


# ────────────────────────────────────────────────
# Presets 层：零网络请求匹配常用资产/数据/函数
# ────────────────────────────────────────────────
# 策略：全量命中 → 返回合成响应；任一缺失 → fallthrough 到网络调用
# 只用 re + 字符串处理解析 YAML 子集，不引入 PyYAML 依赖

PRESETS_DIR = os.path.join(SKILL_ROOT, "presets")

def _parse_yaml_list_of_dicts(text):
    """解析 YAML 列表项（- key: value 格式），返回 [dict, ...]。
    只处理 presets 文件用到的子集：缩进 2-4 空格的 key: value，字符串值可带引号。"""
    items = []
    current = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        # 新列表项
        if stripped.startswith('- '):
            if current is not None:
                items.append(current)
            current = {}
            kv = stripped[2:].strip()
            if ':' in kv:
                k, v = kv.split(':', 1)
                current[k.strip()] = v.strip().strip('"').strip("'")
        elif current is not None and ':' in stripped:
            # 延续当前 dict 的 key: value
            k, v = stripped.split(':', 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if v.lower() == 'true':
                v = True
            elif v.lower() == 'false':
                v = False
            current[k] = v
    if current is not None:
        items.append(current)
    return items


def _load_presets_assets():
    """加载 presets/assets.yaml，返回 {name_lower: {name, code, type}} 映射"""
    fpath = os.path.join(PRESETS_DIR, "assets.yaml")
    if not os.path.exists(fpath):
        return {}
    try:
        with open(fpath, 'r', encoding='utf-8') as f:
            text = f.read()
        items = _parse_yaml_list_of_dicts(text)
        mapping = {}
        for item in items:
            name = item.get('name', '')
            if name:
                mapping[name.lower()] = item
        return mapping
    except Exception:
        return {}


def _load_presets_data_catalog():
    """加载 presets/data_catalog.yaml，返回 {index_title_lower: {index_title, dimension, is_bool}} 映射"""
    fpath = os.path.join(PRESETS_DIR, "data_catalog.yaml")
    if not os.path.exists(fpath):
        return {}
    try:
        with open(fpath, 'r', encoding='utf-8') as f:
            text = f.read()
        items = _parse_yaml_list_of_dicts(text)
        mapping = {}
        for item in items:
            title = item.get('index_title', '')
            if title:
                mapping[title.lower()] = item
        return mapping
    except Exception:
        return {}


def _load_presets_functions():
    """加载 presets/functions.yaml，返回 {title_lower: {title, format}} 映射"""
    fpath = os.path.join(PRESETS_DIR, "functions.yaml")
    if not os.path.exists(fpath):
        return {}
    try:
        with open(fpath, 'r', encoding='utf-8') as f:
            text = f.read()
        items = _parse_yaml_list_of_dicts(text)
        mapping = {}
        for item in items:
            title = item.get('title', '')
            if title:
                mapping[title.lower()] = item
        return mapping
    except Exception:
        return {}


# 延迟加载缓存（进程生命周期内只加载一次）
_presets_cache = {}

def _get_presets(kind):
    """获取指定类型的 presets 数据（首次调用时加载）"""
    if kind not in _presets_cache:
        if kind == 'assets':
            _presets_cache[kind] = _load_presets_assets()
        elif kind == 'data_catalog':
            _presets_cache[kind] = _load_presets_data_catalog()
        elif kind == 'functions':
            _presets_cache[kind] = _load_presets_functions()
    return _presets_cache.get(kind, {})


def _try_presets_confirm_assets(params):
    """尝试从 presets 匹配 confirmMultipleAssets 请求。全部命中返回合成响应，否则 None。"""
    intentions = params.get('intentions', [])
    if not intentions:
        return None
    assets = _get_presets('assets')
    if not assets:
        return None

    results = []
    for intention in intentions:
        key = intention.lower().strip()
        hit = assets.get(key)
        if not hit:
            # 尝试模糊后缀匹配（如 "沪深300" 匹配 "沪深300"）
            hit = None
            for k, v in assets.items():
                if key in k or k in key:
                    hit = v
                    break
        if not hit:
            return None  # 有一个没命中，放弃 presets，走网络
        results.append({
            "intention": intention,
            "matched": True,
            "type": hit.get('type', 'asset'),
            "name": hit.get('name', intention),
            "ticker": hit.get('code', ''),
            "alternatives": [],
            "_source": "presets"
        })

    return {"code": 0, "data": {"results": results}, "_presets": True}


def _try_presets_confirm_data(params):
    """尝试从 presets 匹配 confirmDataMulti 请求。"""
    data_desc = params.get('data_desc', '')
    if not data_desc:
        return None
    catalog = _get_presets('data_catalog')
    if not catalog:
        return None

    # data_desc 可能是字符串或列表（MCP schema 允许两种格式）
    if isinstance(data_desc, list):
        queries = [str(q).strip() for q in data_desc if str(q).strip()]
    else:
        queries = [q.strip() for q in re.split(r'[,，\s]+', data_desc) if q.strip()]
    if not queries:
        return None

    results = []
    for q in queries:
        key = q.lower()
        hit = catalog.get(key)
        if not hit:
            # 模糊匹配：查询词出现在 index_title 或 description 中
            for k, v in catalog.items():
                desc = str(v.get('description', '')).lower()
                if key in k or key in desc:
                    hit = v
                    break
        if not hit:
            return None
        results.append({
            "query": q,
            "matched": True,
            "index_info": {
                "_id": "",  # presets 没有 _id，调用方需注意
                "index_title": hit.get('index_title', q),
                "dimension": hit.get('dimension', 'two'),
                "is_bool": hit.get('is_bool', False) if isinstance(hit.get('is_bool'), bool) else str(hit.get('is_bool', '')).lower() == 'true',
                "provider": "guanzhao",
            },
            "_source": "presets"
        })

    return {"code": 0, "data": {"results": results}, "_presets": True}


def _try_presets_search_functions(params):
    """尝试从 presets 匹配 searchFunctions 请求。"""
    query = params.get('query', '').strip()
    if not query:
        return None
    funcs = _get_presets('functions')
    if not funcs:
        return None

    top_k = int(params.get('top_k', 5))
    keywords = [kw.lower().strip() for kw in re.split(r'[|,，\s/]+', query) if kw.strip()]
    if not keywords:
        return None

    # 按关键词匹配打分
    scored = []
    for title_lower, item in funcs.items():
        fmt = str(item.get('format', '')).lower()
        score = 0
        for kw in keywords:
            if kw == title_lower:
                score += 10  # 精确匹配标题
            elif kw in title_lower:
                score += 5   # 部分匹配标题
            elif kw in fmt:
                score += 2   # 匹配 format
        if score > 0:
            scored.append((score, item))

    if not scored:
        return None  # 无任何命中，走网络

    scored.sort(key=lambda x: -x[0])
    top_items = scored[:top_k]

    functions = []
    for _, item in top_items:
        functions.append({
            "name": item.get('title', ''),
            "format": item.get('format', ''),
            "_source": "presets"
        })

    return {"code": 0, "data": {"functions": functions}, "_presets": True}


# ────────────────────────────────────────────────
# 日志模块：每个 task_id 一个 JSONL 文件，存 logs/ 目录
# ────────────────────────────────────────────────

def _get_log_path(params: dict, result=None) -> str:
    """按 task_id 决定日志文件路径；无 task_id 则按日期归入 general_YYYYMMDD.jsonl

    task_id 优先从服务端响应（result）里提取——因为 task_id 是服务端生成的，
    第一次调用时请求里不带 task_id，只有响应里才有。
    回退顺序：result.task_id → result.data.task_id → params.task_id → general_日期
    """
    log_dir = os.path.join(SKILL_ROOT, "logs")
    os.makedirs(log_dir, exist_ok=True)
    task_id = ""
    # 优先从响应里取
    if isinstance(result, str):
        task_id = _extract_yaml_task_id(result)
    elif isinstance(result, dict):
        task_id = result.get("task_id", "")
        if not task_id and isinstance(result.get("data"), dict):
            task_id = result["data"].get("task_id", "")
    # 回退到请求参数里
    if not task_id and isinstance(params, dict):
        task_id = params.get("task_id", "")
    filename = f"{task_id}.jsonl" if task_id else f"general_{datetime.now().strftime('%Y%m%d')}.jsonl"
    return os.path.join(log_dir, filename)


def _sanitize_for_log(obj, _depth=0):
    """递归截断大字段，避免 base64 图片等撑爆日志文件。"""
    if _depth > 6:
        return "..."
    if isinstance(obj, str):
        # base64 图片 / 超长字符串 → 只保留前 120 字符
        return obj[:120] + "...[truncated]" if len(obj) > 120 else obj
    if isinstance(obj, dict):
        return {k: _sanitize_for_log(v, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        # 超过 20 个元素只保留前 10 + 尾部计数
        if len(obj) > 20:
            return [_sanitize_for_log(x, _depth + 1) for x in obj[:10]] + [f"... ({len(obj) - 10} more)"]
        return [_sanitize_for_log(x, _depth + 1) for x in obj]
    return obj


def _write_log(tool: str, params: dict, result, elapsed_ms: int):
    """追加一条 JSONL 记录，写失败静默忽略（不影响主流程）。

    日志路径在拿到 result 之后才决定，这样能正确用服务端返回的 task_id 命名文件。
    支持 result 为 dict（JSON）或 str（YAML 原文）。
    """
    log_path = _get_log_path(params, result)
    if isinstance(result, str):
        entry = {
            "ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "tool": tool,
            "params": _sanitize_for_log(params),
            "elapsed_ms": elapsed_ms,
            "result_code": _extract_yaml_code(result),
            "result_yaml_preview": result[:500] + ("..." if len(result) > 500 else ""),
        }
    else:
        entry = {
            "ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "tool": tool,
            "params": _sanitize_for_log(params),
            "elapsed_ms": elapsed_ms,
            "result_code": result.get("code") if isinstance(result, dict) else None,
            "result": _sanitize_for_log(result),
        }
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 日志写失败不中断主流程


def load_config():
    config_path = os.path.join(SKILL_ROOT, "config.json")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"找不到配置文件: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    # config.local.json 覆盖（优先级高于 config.json）
    local_path = os.path.join(SKILL_ROOT, "config.local.json")
    if os.path.exists(local_path):
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                local_cfg = json.load(f)
            for k, v in local_cfg.items():
                if v not in (None, ""):
                    cfg[k] = v
        except Exception:
            pass
    if not cfg.get("api_key"):
        raise ValueError("config.json / config.local.json 中 api_key 为空，请填写您的 sk-xxx 密钥")
    return cfg


def call_multipart(endpoint, api_key, path, file_path, fields=None):
    """用 multipart/form-data 上传文件，附带额外表单字段 (fields dict)。"""
    import email.mime.multipart
    import uuid
    boundary = uuid.uuid4().hex
    body_parts = []
    # 额外表单字段
    for k, v in (fields or {}).items():
        body_parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
            .encode('utf-8')
        )
    # 文件本身
    with open(file_path, 'rb') as f:
        file_bytes = f.read()
    filename = os.path.basename(file_path)
    body_parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: text/csv\r\n\r\n'
        .encode('utf-8') + file_bytes + b'\r\n'
    )
    body_parts.append(f'--{boundary}--\r\n'.encode('utf-8'))
    body = b''.join(body_parts)
    url = f"{endpoint}{path}"
    req = urllib.request.Request(
        url, data=body,
        headers={
            'Content-Type': f'multipart/form-data; boundary={boundary}',
            'Authorization': f'Bearer {api_key}',
        },
        method='POST',
    )
    with _NO_PROXY_OPENER.open(req, timeout=120) as resp:
        return json.loads(resp.read().decode('utf-8'))


def call_post(endpoint, api_key, path, params, accept_yaml=True, timeout=300):
    """发送 POST 请求。accept_yaml=True 时返回 YAML 原文(str)，否则返回 JSON(dict)。"""
    url = f"{endpoint}{path}"
    data = json.dumps(params, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Authorization": f"Bearer {api_key}",
    }
    if accept_yaml:
        headers["Accept"] = "text/yaml"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with _NO_PROXY_OPENER.open(req, timeout=timeout) as resp:
        ct = resp.headers.get("Content-Type", "")
        raw = resp.read().decode("utf-8")
        if "yaml" in ct:
            return raw   # YAML 原文，交给调用方直接输出
        return json.loads(raw)


def call_get(endpoint, api_key, path, params, timeout=60):
    """发送 GET 请求（downloadData / getChartSpec 等）"""
    # 用 params 中的值填充路径模板（支持 {id}、{task_id} 等）
    formatted_path = path.format(**params) if '{' in path else path
    _fmt = params.get("format", "")
    url = f"{endpoint}{formatted_path}"
    query_parts = []
    if _fmt:
        query_parts.append(f"format={_fmt}")
    if params.get("begin_date"):
        query_parts.append(f"begin_date={params['begin_date']}")
    if params.get("end_date"):
        query_parts.append(f"end_date={params['end_date']}")
    if query_parts:
        url += "?" + "&".join(query_parts)
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "text/yaml"},
        method="GET",
    )
    with _NO_PROXY_OPENER.open(req, timeout=timeout) as resp:
        content_type = resp.headers.get("Content-Type", "")
        raw = resp.read()
        if "text/csv" in content_type:
            return {"code": 0, "data": raw.decode("utf-8")}
        raw_str = raw.decode("utf-8")
        if "yaml" in content_type:
            return raw_str   # YAML 原文
        return json.loads(raw_str)


def upload_data(endpoint, api_key, params):
    """
    两阶段上传：
    1. 读取本地 CSV 文件
    2. POST /skill/upload/preview 获取 file_token
    3. POST /skill/upload/confirm 完成上传
    """
    file_path = params.get("file_path")
    data_name = params.get("data_name", "")
    description = params.get("description", "")
    on_conflict = params.get("on_conflict", "error")

    if not file_path:
        return {"code": 1, "message": "缺少 file_path 参数"}

    if not os.path.exists(file_path):
        return {"code": 1, "message": f"文件不存在: {file_path}"}

    if not data_name:
        data_name = os.path.splitext(os.path.basename(file_path))[0]

    # Step 1: preview — multipart/form-data（后端用 multer upload.single('file')）
    preview_result = call_multipart(endpoint, api_key, "/skill/upload/preview",
                                    file_path=file_path, fields={"data_name": data_name})

    if preview_result.get("code") != 0:
        return preview_result

    file_token = preview_result["data"]["file_token"]
    sample = preview_result["data"].get("sample_rows", [])
    name_conflict = preview_result["data"].get("name_conflict", False)

    print(f"[Preview OK] data_name={data_name}, rows={preview_result['data'].get('total_rows')}, "
          f"name_conflict={name_conflict}", file=sys.stderr)
    if sample:
        print(f"  sample: {sample[:2]}", file=sys.stderr)

    # Step 2: confirm
    confirm_result = call_post(endpoint, api_key, "/skill/upload/confirm", {
        "file_token": file_token,
        "data_name": data_name,
        "description": description,
        "on_conflict": on_conflict,
    }, accept_yaml=False)

    return confirm_result


def _decode_bytes(raw_bytes: bytes) -> str:
    """尝试多种编码解码字节流，优先 UTF-8，其次系统默认编码（应对 PowerShell GBK 管道）。"""
    for enc in ('utf-8-sig', 'utf-8'):
        try:
            return raw_bytes.decode(enc)
        except (UnicodeDecodeError, LookupError):
            pass
    # 回落系统编码（中文 Windows 通常是 gbk/cp936）
    import locale
    sys_enc = locale.getpreferredencoding(False) or 'gbk'
    try:
        return raw_bytes.decode(sys_enc)
    except (UnicodeDecodeError, LookupError):
        pass
    return raw_bytes.decode('utf-8', errors='replace')


# ── YAML 响应解析辅助（零依赖，仅用正则提取关键字段）──────────

_RE_YAML_CODE = re.compile(r'^code:\s*(-?\d+)', re.MULTILINE)
_RE_YAML_TASK_ID = re.compile(r'^task_id:\s*(\S+)', re.MULTILINE)


def _extract_yaml_code(yaml_text):
    """从 YAML 文本提取顶层 code 字段（int 或 None）。"""
    m = _RE_YAML_CODE.search(yaml_text)
    return int(m.group(1)) if m else None


def _extract_yaml_task_id(yaml_text):
    """从 YAML 文本提取顶层 task_id 字段。"""
    m = _RE_YAML_TASK_ID.search(yaml_text)
    return m.group(1).strip("'\"") if m else ""


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    tool_name = sys.argv[1]

    # 解析参数：支持三种方式
    #   1. 命令行第2个参数（JSON 字符串，bash/zsh 适用）
    #   2. 命令行第2个参数以 @ 开头（从文件读取，PowerShell 推荐方式）
    #   3. 第2个参数为 "-" 或缺省且 stdin 非 tty（从 stdin 读取，自动检测编码）
    if len(sys.argv) >= 3 and sys.argv[2] == '-':
        raw_arg = _decode_bytes(sys.stdin.buffer.read()).strip()
    elif not sys.stdin.isatty() and len(sys.argv) < 3:
        raw_arg = _decode_bytes(sys.stdin.buffer.read()).strip()
    elif len(sys.argv) >= 3:
        raw_arg = sys.argv[2]
    else:
        raw_arg = '{}'

    if raw_arg.startswith('@'):
        # 从文件读取 JSON
        json_file = raw_arg[1:]
        try:
            with open(json_file, 'r', encoding='utf-8-sig') as f:
                json_str = f.read()
            params = json.loads(json_str)
        except FileNotFoundError:
            print(json.dumps({"code": 1, "message": f"参数文件不存在: {json_file}"}, ensure_ascii=False))
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(json.dumps({"code": 1, "message": f"参数文件 JSON 解析失败: {e}"}, ensure_ascii=False))
            sys.exit(1)
    else:
        try:
            params = json.loads(raw_arg)
        except json.JSONDecodeError as e:
            print(json.dumps({
                "code": 1,
                "message": (
                    f"参数 JSON 解析失败: {e}\n"
                    "PowerShell 请用 @file 方式传参:\n"
                    "  echo '{\"key\": \"value\"}' > /tmp/p.json\n"
                    f"  python scripts/executor.py {tool_name} @/tmp/p.json"
                )
            }, ensure_ascii=False))
            sys.exit(1)

    # ── 参数规范化：自动修正常见参数名错误 ──────────────────────
    if tool_name == "confirmMultipleAssets":
        if "intentions" not in params or not params.get("intentions"):
            for alias in ("assets", "names", "queries", "items", "asset", "name"):
                if alias in params and params[alias]:
                    val = params.pop(alias)
                    params["intentions"] = [val] if isinstance(val, str) else val
                    break
    if tool_name == "runMultiFormula" and "formulas" in params:
        fixed = []
        for item in params["formulas"]:
            if isinstance(item, str):
                fixed.append(item)
            elif isinstance(item, dict):
                f = item.get("formula") or item.get("expression") or item.get("value") or ""
                if f:
                    fixed.append(f)
        # 防御性修复：模型有时对公式中的引号做双重转义（ \" → "）
        # 例如 kimi-k2.5 会生成 \\\"A股营业收入\\\" 导致 HTTP 500
        params["formulas"] = [f.replace('\\"', '"') for f in fixed]

    # ── buildEventStudy 参数校验 ──────────────────────────────
    if tool_name == "buildEventStudy":
        def _is_weekday(d):
            """简易校验：YYYYMMDD 整数是否为工作日（排除周末）"""
            try:
                from datetime import date as _date
                s = str(d)
                dt = _date(int(s[:4]), int(s[4:6]), int(s[6:8]))
                return dt.weekday() < 5  # 0=周一 ... 4=周五
            except Exception:
                return False

        # 校验 dates / group_a_dates / group_b_dates 中的周末日期
        for date_key in ("dates", "group_a_dates", "group_b_dates"):
            date_list = params.get(date_key)
            if date_list and isinstance(date_list, list):
                weekends = [d for d in date_list if not _is_weekday(d)]
                if weekends:
                    print(f"[warn] {date_key} 包含周末日期 {weekends}，事件研究要求使用交易日", file=sys.stderr)

        # compare 模式：group_a / group_b 长度一致性
        mode = params.get("mode", "single")
        if mode == "compare":
            ga = params.get("group_a_dates", [])
            gb = params.get("group_b_dates", [])
            if ga and gb and len(ga) != len(gb):
                print(f"[warn] compare 模式下 group_a_dates({len(ga)}) 与 group_b_dates({len(gb)}) 长度不一致", file=sys.stderr)

    # 特殊处理：saveChart（本地 base64 → PNG，不走 HTTP，无需配置文件）
    if tool_name == "saveChart":
        import base64
        t0 = time.time()
        b64_str = params.get("base64", "")
        name = params.get("name", "latest_chart")
        if b64_str.startswith("data:image/"):
            b64_str = b64_str.split(",", 1)[1]
        if not b64_str:
            result = {"code": 1, "message": "缺少 base64 参数"}
            _write_log(tool_name, params, result, int((time.time()-t0)*1000))
            print(json.dumps(result, ensure_ascii=False))
            sys.exit(1)
        output_dir = os.path.join(SKILL_ROOT, "output")
        os.makedirs(output_dir, exist_ok=True)
        out_path = os.path.join(output_dir, f"{name}.png")
        with open(out_path, "wb") as f:
            f.write(base64.b64decode(b64_str))
        if sys.platform == "win32":
            os.startfile(out_path)
        result = {"code": 0, "data": {"saved_to": out_path}}
        _write_log(tool_name, params, result, int((time.time()-t0)*1000))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    # 加载配置
    try:
        cfg = load_config()
    except (FileNotFoundError, ValueError) as e:
        print(json.dumps({"code": 1, "message": str(e)}, ensure_ascii=False))
        sys.exit(1)

    endpoint = cfg["endpoint"].rstrip("/")
    api_key = cfg["api_key"]

    # 特殊处理：uploadData（两阶段）
    if tool_name == "uploadData":
        t0 = time.time()
        result = upload_data(endpoint, api_key, params)
        _write_log(tool_name, params, result, int((time.time()-t0)*1000))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    # 查路由表
    if tool_name not in TOOL_ROUTES:
        known = ", ".join(TOOL_ROUTES.keys())
        print(json.dumps(
            {"code": 1, "message": f"未知工具: {tool_name}。支持的工具: {known}"},
            ensure_ascii=False
        ))
        sys.exit(1)

    method, path = TOOL_ROUTES[tool_name]
    t0 = time.time()

    # ── Presets 层：尝试本地匹配，避免网络调用 ──────────────────
    presets_result = None
    if tool_name == "confirmMultipleAssets":
        presets_result = _try_presets_confirm_assets(params)
    elif tool_name == "confirmDataMulti":
        presets_result = _try_presets_confirm_data(params)
    elif tool_name == "searchFunctions":
        presets_result = _try_presets_search_functions(params)

    if presets_result is not None:
        elapsed_ms = int((time.time() - t0) * 1000)
        print(f"[presets] {tool_name} 命中本地预设，跳过网络请求 ({elapsed_ms}ms)", file=sys.stderr)
        _write_log(tool_name, params, presets_result, elapsed_ms)
        print(json.dumps(presets_result, indent=2, ensure_ascii=False))
        sys.stdout.flush()
        return
    # ── Presets miss → 走网络 ────────────────────────────────

    try:
        if method == "GET":
            result = call_get(endpoint, api_key, path, params)
        else:
            result = call_post(endpoint, api_key, path, params)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        ct = e.headers.get("Content-Type", "") if hasattr(e, 'headers') else ""
        if "yaml" in ct:
            # 服务端返回了 YAML 格式的错误响应
            _write_log(tool_name, params, body, int((time.time()-t0)*1000))
            print(body, end="")
            sys.stdout.flush()
            sys.exit(1)
        try:
            err = json.loads(body)
        except Exception:
            err = {"message": body}
        result = {"code": e.code, "message": err.get("message", str(e))}
        # 透传服务端 error 结构（含 error.code / nextResetIn 等 429 分类信息）
        if "error" in err and isinstance(err["error"], dict):
            result["error"] = err["error"]
        if "success" in err:
            result["success"] = err["success"]
        _write_log(tool_name, params, result, int((time.time()-t0)*1000))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(1)
    except urllib.error.URLError as e:
        result = {"code": 1, "message": f"连接失败: {e.reason}。请检查 endpoint 配置: {endpoint}"}
        _write_log(tool_name, params, result, int((time.time()-t0)*1000))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(1)
    except Exception as e:
        result = {"code": 1, "message": str(e)}
        _write_log(tool_name, params, result, int((time.time()-t0)*1000))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(1)

    elapsed_ms = int((time.time() - t0) * 1000)

    # ── 认证失败：立即终止，不要重试 ──────────────────────────────
    if isinstance(result, str):
        result_code = _extract_yaml_code(result)
    else:
        result_code = result.get("code") if isinstance(result, dict) else None

    if result_code in (401, 402):
        if isinstance(result, str):
            msg_m = re.search(r'^message:\s*(.+)$', result, re.MULTILINE)
            msg = msg_m.group(1).strip().strip("'\"") if msg_m else "认证失败"
        else:
            msg = result.get("message", "认证失败")
        print(json.dumps({
            "code": result_code,
            "fatal": True,
            "message": f"[认证错误] {msg}\n请检查 config.json 中的 api_key，修复后再重试。不要继续调用其他工具。"
        }, indent=2, ensure_ascii=False))
        sys.exit(1)

    _write_log(tool_name, params, result, elapsed_ms)
    if isinstance(result, str):
        # YAML 响应：直接输出原文
        print(result, end="")
    else:
        # JSON 响应：格式化输出
        print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
