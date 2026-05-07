#!/usr/bin/env python3
"""
观照量化 API —— Python 可编程接口

供业务 Skill 的脚本 import 使用，底层走 executor.py REST API，不依赖 MCP 协议。
所有工具名、参数格式、认证、session 管理均复用 quant-buddy-skill 的基础设施。

用法：
    import sys
    sys.path.insert(0, r"/path/to/quant-buddy-skill/scripts")
    from quant_api import QuantAPI

    api = QuantAPI()                  # 自动定位 skill root
    api.new_session()                 # 初始化 session（每个任务调一次）
    r = api.run_multi_formula(formulas=["X=收盘价(贵州茅台)"], begin_date=20160101)
    ids = api.extract_obj_ids(r)      # {"X": "60f..."}
    d = api.read_data(ids=list(ids.values()), mode="smart_sample")

依赖：仅 Python 标准库（json, os, re, sys, uuid）。
"""

import json
import os
import re
import sys
import uuid

__all__ = ["QuantAPI"]

# 本文件所在目录 = quant-buddy-skill/scripts/
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_SKILL_ROOT = os.path.dirname(_SCRIPT_DIR)


def _read_skill_version(skill_root: str = _SKILL_ROOT) -> str:
    """从 SKILL.md frontmatter 读取 version 字段；读取失败时返回空字符串。"""
    skill_md = os.path.join(skill_root, "SKILL.md")
    try:
        with open(skill_md, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("version:"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return ""


def _resolve_session_file(skill_root: str) -> str:
    """按优先级解析 session 文件路径，支持多会话并行：
    1) QBS_SESSION_FILE 环境变量直接指定路径
    2) QBS_SESSION_KEY 派生为 .session.<key>.json
    3) 默认 .session.json（向后兼容）
    """
    explicit = os.environ.get("QBS_SESSION_FILE", "").strip()
    if explicit:
        return explicit
    key = os.environ.get("QBS_SESSION_KEY", "").strip()
    if key:
        safe_key = re.sub(r"[^A-Za-z0-9_\-]", "_", key)[:64]
        return os.path.join(skill_root, "output", f".session.{safe_key}.json")
    return os.path.join(skill_root, "output", ".session.json")


class QuantAPI:
    """观照量化平台的同步 Python 客户端。

    Parameters
    ----------
    skill_root : str, optional
        quant-buddy-skill 的根目录，默认自动检测（本文件上两级）。
    timeout : int
        每次 API 调用的最大等待秒数，默认 300。
    """

    def __init__(self, skill_root=None, timeout=300):
        self.skill_root = skill_root or _SKILL_ROOT
        self.timeout = timeout
        self._scripts_dir = os.path.join(self.skill_root, "scripts")
        self._session_file = _resolve_session_file(self.skill_root)
        # in-memory task_id：一旦初始化后不再从文件重读，避免并发写入导致跨批次 task_id 漂移
        self._task_id: str = ""
        # 配额累积器：跨工具调用累计本 session 消耗的 RU
        self._session_ru_cost: int = 0
        self._last_quota: dict = {}

        if not os.path.isdir(self._scripts_dir):
            raise FileNotFoundError(
                f"找不到 scripts 目录: {self._scripts_dir}\n"
                f"请确认 skill_root 指向 quant-buddy-skill 根目录"
            )

    # ────────────────────────────────────────────
    # Session 文件读写（与 call.py 共用同一个 .session.json）
    # ────────────────────────────────────────────

    def _read_session(self) -> str:
        try:
            with open(self._session_file, "r", encoding="utf-8") as f:
                return json.load(f).get("task_id", "")
        except Exception:
            return ""

    def _write_session(self, task_id: str, user_query: str = None):
        self._task_id = task_id          # 同步更新内存，保证同一进程内一致
        os.makedirs(os.path.dirname(self._session_file), exist_ok=True)
        data = {"task_id": task_id, "skill_version_at_creation": _read_skill_version(self.skill_root)}
        if user_query is not None:
            data["user_query"] = user_query
        with open(self._session_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    # ────────────────────────────────────────────
    # 底层调用（直接 HTTP，不走 subprocess）
    # ────────────────────────────────────────────

    def _call(self, tool_name: str, params: dict = None) -> dict:
        """直接调用 executor.py 的 HTTP 函数，跳过 call.py / subprocess 两层开销。

        返回 dict（JSON 响应）。出错时抛出 RuntimeError。
        """
        import uuid as _uuid
        params = dict(params or {})

        # ── newSession：本地生成 UUID，不需要 HTTP ──────────────────
        if tool_name == "newSession":
            new_id = str(_uuid.uuid4())
            # 覆写前先读旧版本号
            _prev_ver = None
            try:
                with open(self._session_file, "r", encoding="utf-8") as _sf:
                    _prev_ver = json.load(_sf).get("skill_version_at_creation")
            except Exception:
                pass
            self._write_session(new_id, user_query=params.get("user_query"))   # 同时更新内存 + 文件
            _cur_ver = _read_skill_version(self.skill_root)
            _changed = bool(_prev_ver and _prev_ver != _cur_ver)
            return {
                "code": 0,
                "task_id": new_id,
                "skill_version": _cur_ver,
                "version_changed_from_last_session": _changed,
                "previous_skill_version": _prev_ver if _changed else None,
                "message": (
                    f"新 session 已创建（skill {_cur_ver}）。"
                    + (f"检测到 skill 从 {_prev_ver} 升级到 {_cur_ver}，"
                       "必须先重读 SKILL.md 再继续。"
                       if _changed else
                       "task_id 已保存到 .session.json。")
                ),
            }

        # ── 版本守卫：检测旧会话与当前 skill 版本是否匹配 ─────────────
        _cur_ver = _read_skill_version(self.skill_root)
        if _cur_ver:
            try:
                with open(self._session_file, "r", encoding="utf-8") as _sf:
                    _session_ver = json.load(_sf).get("skill_version_at_creation")
                if _session_ver is None or _session_ver != _cur_ver:
                    raise RuntimeError(
                        f"SKILL_VERSION_MISMATCH: session 创建于 {_session_ver}，"
                        f"当前为 {_cur_ver}。请调用 newSession 并重读 SKILL.md 后再继续。"
                    )
            except FileNotFoundError:
                pass  # 尚未创建 session，不阻断

        # ── 注入 task_id（优先用内存缓存，避免文件被并发覆盖导致跨批次漂移）──
        if "task_id" not in params:
            # 首次调用：内存为空时才读文件，读后缓存到内存
            if not self._task_id:
                self._task_id = self._read_session()
            if self._task_id:
                params["task_id"] = self._task_id

        # ── 确保 executor 在 sys.path 里，然后 import ───────────────
        if self._scripts_dir not in sys.path:
            sys.path.insert(0, self._scripts_dir)
        import executor as _ex  # noqa: PLC0415

        if tool_name not in _ex.TOOL_ROUTES:
            raise RuntimeError(f"未知工具: {tool_name}，可用: {list(_ex.TOOL_ROUTES)}")

        cfg = _ex.load_config()
        method, path = _ex.TOOL_ROUTES[tool_name]

        try:
            if method == "GET":
                raw = _ex.call_get(cfg["endpoint"], cfg["api_key"], path, params,
                                   timeout=self.timeout)
            else:
                raw = _ex.call_post(cfg["endpoint"], cfg["api_key"], path, params,
                                    timeout=self.timeout)
        except Exception as e:
            raise RuntimeError(f"HTTP 调用失败 [{tool_name}]: {e}") from e

        # call_post 在服务端返回 YAML 时给回字符串，统一转 dict
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                code_m = re.search(r"^code:\s*(-?\d+)", raw, re.MULTILINE)
                if code_m:
                    return {"code": int(code_m.group(1)), "_raw_yaml": raw}
                return {"code": -1, "_raw": raw[:2000]}

        # 服务端有时在响应里带新的 task_id：
        #   - 只更新文件（供 call.py / 外部工具读取）
        #   - 不覆盖 self._task_id 内存——内存 task_id 是本次扫描 8 个批次的"组号"，
        #     中途被服务端改掉会导致跨批次变量引用失效（"公式变量未找到"）
        if isinstance(raw, dict) and raw.get("code") == 0:
            _data = raw.get("data")
            resp_tid = raw.get("task_id") or ((_data if isinstance(_data, dict) else {}).get("task_id"))
            if resp_tid and resp_tid != self._task_id:
                # 只写文件，不动内存
                os.makedirs(os.path.dirname(self._session_file), exist_ok=True)
                with open(self._session_file, "w", encoding="utf-8") as _f:
                    json.dump({"task_id": resp_tid}, _f)

        # ── 配额累积器：提取 _quota，累加 session 级总消耗 ──────────
        if isinstance(raw, dict) and "_quota" in raw:
            quota = raw["_quota"]
            self._session_ru_cost += quota.get("cost", 0)
            self._last_quota = dict(quota)
            # 注入 session_total_cost，方便模型从最后一次结果直接读取
            raw["_quota"]["session_total_cost"] = self._session_ru_cost

        return raw

    @staticmethod
    def _unwrap(r: dict) -> dict:
        """将 {"code": 0, "data": {inner}} 展开为 inner dict。

        后端 REST 响应总是包裹在 {"code": X, "data": {...}} 中，
        而业务代码（ic_scan_dimensions.py 等）直接用 .get("data") / .get("errors")
        访问内层字段。通过此展开保持向下兼容。
        """
        if isinstance(r, dict) and "code" in r and "data" in r:
            inner = r.get("data")
            if isinstance(inner, dict):
                return inner
        return r

    # ────────────────────────────────────────────
    # Session 管理
    # ────────────────────────────────────────────

    def new_session(self) -> str:
        """初始化新 session，返回 task_id。每个独立任务开始时调一次。"""
        r = self._call("newSession")
        task_id = r.get("task_id", "")
        if not task_id:
            raise RuntimeError(f"newSession 未返回 task_id: {r}")
        return task_id

    # ────────────────────────────────────────────
    # 核心工具（与 SKILL.md 工具表一一对应）
    # ────────────────────────────────────────────

    def search_functions(self, query: str, top_k: int = 3) -> dict:
        """搜索平台函数。"""
        return self._call("searchFunctions", {"query": query, "top_k": top_k})

    def search_similar_cases(self, query: str) -> dict:
        """向量搜索相似案例（fallback 用途）。"""
        return self._call("searchSimilarCases", {"query": query})

    def get_card_formulas(self, card_ids: list) -> dict:
        """按卡片 ID 批量获取公式。"""
        return self._call("getCardFormulas", {"card_ids": card_ids})

    def confirm_data_multi(self, data_desc: str) -> dict:
        """确认平台数据项。data_desc 是逗号分隔字符串，如 "换手率,市盈率"。"""
        return self._call("confirmDataMulti", {"data_desc": data_desc})

    def run_multi_formula(self, formulas: list, begin_date: int = None,
                          include_description: bool = False, **kwargs) -> dict:
        """执行公式批次。

        Parameters
        ----------
        formulas : list[str]
            公式数组，如 ["X=收盘价(贵州茅台)", "Y=涨跌幅(\"X\",20)"]
        begin_date : int, optional
            起始日期 YYYYMMDD，如 20160101
        include_description : bool
            是否在返回中包含数据描述，默认 False
        """
        params = {"formulas": formulas, "include_description": include_description}
        if begin_date:
            params["begin_date"] = begin_date
        params.update(kwargs)
        return self._unwrap(self._call("runMultiFormulaBatch", params))

    def refresh_snapshot_time(self, task_id: str = None) -> dict:
        """强制刷新指定 session 的分钟数据截止时间。"""
        task_id = task_id or self._task_id or self._read_session()
        if not task_id:
            raise ValueError(
                "refresh_snapshot_time 需要 task_id：请先调用 new_session()，"
                "或显式传入 task_id 参数。"
            )
        return self._unwrap(self._call("refreshSnapshotTime", {"task_id": task_id}))

    def read_data(self, ids: list, mode: str = "smart_sample",
                  sample_points: int = None, **kwargs) -> dict:
        """读取数据。

        Parameters
        ----------
        ids : list[str]
            data_id 数组（来自 run_multi_formula 返回的 _id）
        mode : str
            smart_sample / last_day_stats / signature / precheck
        sample_points : int, optional
            采样点数（mode=smart_sample 时有效）
        """
        params = {"ids": ids, "mode": mode}
        if sample_points:
            params["sample_points"] = sample_points
        params.update(kwargs)
        return self._unwrap(self._call("readData", params))

    def scan_dimensions(self, asset: dict, industry: str = None,
                        dimensions=None, begin_date: int = 20160101, **kwargs) -> dict:
        """\u4e5d\u7ef4\u5ea6 IC \u626b\u63cf\u3002

        Parameters
        ----------
        asset : dict
            {"name": "\u4e2d\u63a7\u6280\u672f", "code": "688777.SH"}
        industry : str, optional
            \u884c\u4e1a\u6307\u6570\u540d\uff0c\u5982 "\u81ea\u52a8\u5316\u8bbe\u5907\uff08\u7533\u4e07\uff09"
        dimensions : list or "all", optional
            \u6307\u5b9a\u7ef4\u5ea6\u5217\u8868\uff0c\u5982 ["D1_\u4f30\u503c","D7_\u6280\u672f\u5f62\u6001"]\uff0c\u9ed8\u8ba4 None \u5373\u5168\u91cf
        begin_date : int, optional
            \u5386\u53f2\u8d77\u59cb\u65e5 YYYYMMDD\uff0c\u9ed8\u8ba4 20160101
        """
        params = {"asset": asset, "begin_date": begin_date}
        if industry:
            params["industry"] = industry
        if dimensions is not None:
            params["dimensions"] = dimensions
        params.update(kwargs)
        return self._call("scanDimensions", params)

    def render_chart(self, lines: list, title: str, **kwargs) -> dict:
        """渲染图表，自动保存 PNG 到 output/。

        Parameters
        ----------
        lines : list[dict]
            如 [{"id": "data_id", "name": "图例名"}]
        title : str
            图表标题
        """
        params = {"lines": lines, "title": title}
        params.update(kwargs)
        return self._call("renderChart", params)

    def render_kline(self, ticker: str, begin_date: int, title: str = "",
                     indicators: list = None, **kwargs) -> dict:
        """K线图快捷渲染。"""
        params = {"ticker": ticker, "begin_date": begin_date}
        if title:
            params["title"] = title
        if indicators:
            params["indicators"] = indicators
        params.update(kwargs)
        return self._call("renderKLine", params)

    def download_data(self, data_id: str, begin_date: int = None,
                      end_date: int = None, **kwargs) -> dict:
        """下载数据为 CSV（自动保存到 output/）。"""
        params = {"id": data_id}
        if begin_date:
            params["begin_date"] = begin_date
        if end_date:
            params["end_date"] = end_date
        params.update(kwargs)
        return self._call("downloadData", params)

    # ────────────────────────────────────────────
    # 数据提取工具（纯本地，不调 API）
    # ────────────────────────────────────────────

    @staticmethod
    def extract_obj_ids(formula_result: dict) -> dict:
        """从 run_multi_formula 结果中提取 {leftName: obj_id} 映射。

        这是最常用的后处理步骤——公式执行后需要拿到 data_id 才能 read_data。
        """
        id_map = {}
        if not isinstance(formula_result, dict):
            return id_map
        for item in (formula_result.get("data") or []):
            if not isinstance(item, dict):
                continue
            left_name = item.get("leftName") or item.get("index_title") or ""
            obj_id = None
            if isinstance(item.get("index_info"), dict):
                obj_id = item["index_info"].get("_id") or item["index_info"].get("id")
            if not obj_id:
                obj_id = item.get("_id") or item.get("id") or item.get("index_id")
            if obj_id and left_name:
                id_map[left_name] = obj_id
        return id_map

    @staticmethod
    def extract_sample_values(item: dict):
        """从 read_data 返回的单条 item 中提取 (values, dates) 列表。

        支持多种后端返回格式：sample_points / values / samples.values。
        """
        raw = []
        for key in ("sample_points", "values"):
            candidate = item.get(key)
            if isinstance(candidate, list) and len(candidate) > 0:
                raw = candidate
                break
        if not raw:
            samples = item.get("samples")
            if isinstance(samples, dict):
                raw = samples.get("values", [])
            elif isinstance(samples, list):
                raw = samples

        values, dates = [], []
        for sp in raw:
            if isinstance(sp, dict):
                v = sp.get("value") if "value" in sp else (sp.get("v") if "v" in sp else sp.get("y"))
                d = sp.get("date") if "date" in sp else (sp.get("x") if "x" in sp else sp.get("time"))
            else:
                v, d = sp, None
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            values.append(fv)
            dates.append(d)
        return values, dates

    @staticmethod
    def extract_latest_value(item: dict):
        """从 read_data 返回的单条 item 中获取最新值。"""
        lp = item.get("latest_point")
        if isinstance(lp, dict) and "value" in lp:
            try:
                return float(lp["value"])
            except (TypeError, ValueError):
                pass
        return None
