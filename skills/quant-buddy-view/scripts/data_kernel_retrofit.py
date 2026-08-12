#!/usr/bin/env python3
"""Deterministically replace only a Quant Buddy data-kernel block in HTML."""

import os
import re
import sys
import urllib.error
import urllib.request

import common as C


START = "/* QB_DATA_KERNEL_START:v2 */"
END = "/* QB_DATA_KERNEL_END:v2 */"
SCRIPT_RE = re.compile(r"(?is)(<script\b[^>]*>)(.*?)(</script\s*>)")


class RetrofitError(ValueError):
    pass


def _kernel_source():
    path = os.path.join(C.SKILL_ROOT, "assets", "data-kernel.js")
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read().strip().replace("__QBV_SKILL_VERSION__", C.SKILL_VERSION or "")


def _is_legacy_kernel(body):
    fingerprints = (
        re.search(r"\bconst\s+QB\s*=\s*\(function\s*\(", body),
        re.search(r"\basync\s+function\s+queryGrant\s*\(", body),
        re.search(r"\bquery\s*,\s*queryMany\s*,\s*queryGrant\s*,\s*apiUrl\b", body),
        re.search(r"\bSKILL_VERSION\b", body),
    )
    return all(fingerprints)


def retrofit_html(html, kernel=None):
    kernel = (kernel or _kernel_source()).strip()
    marker_re = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
    marker_matches = list(marker_re.finditer(html))
    if marker_matches:
        if len(marker_matches) != 1:
            raise RetrofitError(f"data-kernel marker 命中数量异常: {len(marker_matches)}")
        match = marker_matches[0]
        return html[:match.start()] + kernel + html[match.end():], "marker-v2"

    matches = list(SCRIPT_RE.finditer(html))
    legacy = [match for match in matches if _is_legacy_kernel(match.group(2))]
    if len(legacy) != 1:
        raise RetrofitError(f"旧 data-kernel 脚本块命中数量异常: {len(legacy)}")
    match = legacy[0]
    replacement = match.group(1) + "\n" + kernel + "\n" + match.group(3)
    return html[:match.start()] + replacement + html[match.end():], "legacy-script"


def _resolve(path):
    return path if os.path.isabs(path) else os.path.join(C.SKILL_ROOT, path)


def cmd_retrofit(params):
    source = params.get("html_file") or params.get("src") or params.get("url")
    if not source:
        return {"code": 1, "message": "缺少 html_file/src/url"}
    is_url = str(source).lower().startswith(("http://", "https://"))
    if is_url and not params.get("out_file"):
        return {"code": 1, "message": "使用 url 时必须提供 out_file"}
    source_path = None if is_url else _resolve(source)
    out_file = _resolve(params.get("out_file") or source_path)
    try:
        if is_url:
            request = urllib.request.Request(source, headers={"Accept": "text/html,application/xhtml+xml"})
            with urllib.request.urlopen(request, timeout=30) as response:
                before = response.read().decode("utf-8-sig", errors="replace")
        else:
            with open(source_path, "r", encoding="utf-8-sig") as handle:
                before = handle.read()
        after, matched_by = retrofit_html(before)
    except (OSError, RetrofitError, urllib.error.URLError) as exc:
        return {"code": 1, "message": str(exc)}
    os.makedirs(os.path.dirname(out_file) or ".", exist_ok=True)
    with open(out_file, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(after)
    return {
        "code": 0,
        "out_file": out_file,
        "matched_by": matched_by,
        "changed": before != after,
        "size": len(after.encode("utf-8")),
    }


def main():
    params = C.read_params(sys.argv[1:], env_var="DKR_PARAMS")
    C.emit(cmd_retrofit(params))


if __name__ == "__main__":
    main()
