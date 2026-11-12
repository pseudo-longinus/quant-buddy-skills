"""Shared dependency source and publication checks for ECharts pages."""
import json
import re
from html.parser import HTMLParser
from pathlib import Path

SOURCES = [
    {"name": "cdn", "url": "https://cdn.jsdelivr.net/npm/echarts@5.6.0/dist/echarts.min.js", "timeout": 3000},
    {"name": "oss", "url": "https://quant-buddy-prod.oss-cn-hangzhou.aliyuncs.com/vendor/echarts/5.6.0/echarts.min.js", "timeout": 5000},
]
ASSETS = Path(__file__).resolve().parents[1] / "assets"


def runtime_source():
    return (ASSETS / "echarts-loader.js").read_text(encoding="utf-8-sig").replace("__CHART_SOURCES__", json.dumps(SOURCES))


class _Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.external = False
        self.scripts = []
        self.active = False

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "script":
            return
        attrs = dict(attrs)
        self.external |= bool(re.search(r"echarts", attrs.get("src") or "", re.I))
        self.active = attrs.get("type", "").lower() not in ("application/json", "application/ld+json")

    def handle_endtag(self, tag):
        if tag.lower() == "script":
            self.active = False

    def handle_data(self, data):
        if self.active:
            self.scripts.append(data)


def contract_error(html):
    parsed = _Scripts()
    parsed.feed(str(html or ""))
    js = "\n".join(parsed.scripts)
    managed = "/* QB_ECHARTS_RUNTIME_V1 */" in js
    direct_init = re.search(r"\becharts\s*\.\s*init\s*\(", js)
    uses_runtime = re.search(r"\bQBCharts\s*\.\s*(?:render|ensureLibrary|prepare)\s*\(", js)
    # Merely inserting the loader does not make a later synchronous init safe.
    # Custom drawing belongs inside QBCharts.render's draw(lib) callback.
    if parsed.external or direct_init or uses_runtime and not managed:
        return {"code": 1, "error": "ECHARTS_RUNTIME_REQUIRED", "message": (
            "ECHARTS_RUNTIME_REQUIRED: ECharts 图表必须使用 QBV 异步双源运行时；"
            "移除外部 ECharts script，通过 panel_block 或 QB_CHART_RUNTIME + QBCharts.render 接入，"
            "并提供同数据完整表格。async/defer 不能替代超时切源和降级。"
        )}
    return None
