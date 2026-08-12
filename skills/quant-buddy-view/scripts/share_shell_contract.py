#!/usr/bin/env python3
"""Share Shell version contract and canonical artifact hashing."""

from __future__ import annotations

import hashlib
import json
import pathlib
import re

SKILL_ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTRACT_PATH = SKILL_ROOT / "assets" / "share-shell" / "contract.json"
MARKERS = ("CSS", "HEADER", "RESEARCH_WAREHOUSE", "FOOTER", "MODAL", "JS")


def load_contract(path: pathlib.Path = CONTRACT_PATH):
    contract = json.loads(path.read_text(encoding="utf-8"))
    version = str(contract.get("version") or "").strip()
    revision = int(contract.get("revision") or 0)
    capabilities = [str(item).strip() for item in contract.get("required_capabilities", []) if str(item).strip()]
    if not version or revision <= 0 or not capabilities:
        raise ValueError("Share Shell contract 缺少有效 version/revision/required_capabilities")
    return {"version": version, "revision": revision, "required_capabilities": capabilities}


def canonical_share_shell_artifact(html: str) -> str:
    text = str(html or "").replace("\r\n", "\n").replace("\r", "\n")
    sections = []
    for name in MARKERS:
        start = f"<!-- QB_SHELL_{name}_START -->"
        end = f"<!-- QB_SHELL_{name}_END -->"
        if text.count(start) != 1 or text.count(end) != 1:
            raise ValueError(f"{name} marker 必须各命中 1 次")
        match = re.search(re.escape(start) + r"([\s\S]*?)" + re.escape(end), text)
        if not match:
            raise ValueError(f"无法提取 {name} marker 区块")
        body = "\n".join(line.rstrip() for line in match.group(1).strip().split("\n"))
        sections.append(f"{start}\n{body}\n{end}")
    return "\n".join(sections) + "\n"


def share_shell_artifact_hash(html: str) -> str:
    canonical = canonical_share_shell_artifact(html).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
