#!/usr/bin/env python3
"""Self-update quant-buddy-skill from a verified zip package."""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SKILL_ROOT = SCRIPT_DIR.parent
PRESERVE_NAMES = {"config.json", "config.local.json", "output", "logs"}
REQUIRED_PATHS = [
    "SKILL.md",
    "CHANGELOG.md",
    "scripts/call.py",
    "scripts/executor.py",
    "workflows",
    "tools",
]


def _json_exit(code, **payload):
    payload.setdefault("code", code)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.exit(0 if code == 0 else 1)


def _read_skill_version(skill_md: Path) -> str:
    try:
        with skill_md.open("r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("version:"):
                    return stripped.split(":", 1)[1].strip().strip('"\'')
    except OSError:
        pass
    return ""


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "quant-buddy-skill-self-update"})
    with urllib.request.urlopen(req, timeout=60) as resp, dest.open("wb") as out:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)


def _sha512(path: Path) -> str:
    h = hashlib.sha512()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_unsafe_zip_name(name: str) -> bool:
    if not name or "\x00" in name:
        return True
    posix = PurePosixPath(name)
    win = PureWindowsPath(name)
    if posix.is_absolute() or win.is_absolute() or win.drive:
        return True
    return any(part == ".." for part in posix.parts) or any(part == ".." for part in win.parts)


def _safe_extract(zip_path: Path, dest: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"zip contains corrupt member: {bad}")
        for info in zf.infolist():
            if _is_unsafe_zip_name(info.filename):
                raise RuntimeError(f"unsafe zip member path: {info.filename}")
        zf.extractall(dest)


def _find_skill_source(staging: Path, zip_skill_path: str) -> Path:
    if zip_skill_path:
        source = staging / zip_skill_path
        if source.exists():
            return source
        raise RuntimeError(f"zip skill path not found: {zip_skill_path}")

    direct = staging / "quant-buddy-skill"
    if direct.exists():
        return direct

    candidates = []
    for path in staging.rglob("SKILL.md"):
        candidates.append(path.parent)
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise RuntimeError("cannot locate SKILL.md in zip")
    raise RuntimeError("multiple SKILL.md files found; pass --zip-skill-path")


def _validate_source(source: Path, expected_version: str) -> str:
    for rel in REQUIRED_PATHS:
        path = source / rel
        if not path.exists():
            raise RuntimeError(f"required path missing from package: {rel}")

    actual_version = _read_skill_version(source / "SKILL.md")
    if not actual_version:
        raise RuntimeError("cannot read version from package SKILL.md")
    if expected_version and actual_version != expected_version:
        raise RuntimeError(f"package version mismatch: expected {expected_version}, got {actual_version}")
    return actual_version


def _default_backup_root(skill_root: Path) -> Path:
    parent = skill_root.parent
    if parent.name == "skills":
        return parent.parent
    return parent / "skill-backups"


def _copytree(src: Path, dst: Path) -> None:
    def ignore(_dir, names):
        return {name for name in names if name in {"output", "logs", "__pycache__"}}

    shutil.copytree(src, dst, ignore=ignore)


def _clear_installation(skill_root: Path) -> None:
    for item in skill_root.iterdir():
        if item.name in PRESERVE_NAMES:
            continue
        if item.is_dir() and not item.is_symlink():
            shutil.rmtree(item)
        else:
            item.unlink()


def _copy_source(source: Path, skill_root: Path) -> None:
    for item in source.iterdir():
        if item.name in {"config.local.json", "output", "logs", "__pycache__"}:
            continue
        target = skill_root / item.name
        if item.is_dir() and not item.is_symlink():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def _restore_config(skill_root: Path, configs: dict) -> None:
    for name, data in configs.items():
        if data is not None:
            (skill_root / name).write_bytes(data)
    config_json = skill_root / "config.json"
    template = skill_root / "config.json.template"
    if configs.get("config.json") is None and not config_json.exists() and template.exists():
        shutil.copy2(template, config_json)


def _rollback(skill_root: Path, backup_path: Path, configs: dict) -> None:
    if not backup_path.exists():
        return
    _clear_installation(skill_root)
    _copy_source(backup_path, skill_root)
    _restore_config(skill_root, configs)


def _install(source: Path, skill_root: Path, backup_root: Path) -> Path:
    timestamp = time.strftime("%Y%m%d%H%M%S")
    backup_path = backup_root / f"quant-buddy-skill-backup-{timestamp}"
    backup_root.mkdir(parents=True, exist_ok=True)
    configs = {}
    for name in ("config.json", "config.local.json"):
        path = skill_root / name
        configs[name] = path.read_bytes() if path.exists() else None

    _copytree(skill_root, backup_path)
    try:
        _clear_installation(skill_root)
        _copy_source(source, skill_root)
        _restore_config(skill_root, configs)
    except Exception:
        _rollback(skill_root, backup_path, configs)
        raise
    return backup_path


def main():
    parser = argparse.ArgumentParser(description="Update quant-buddy-skill from a verified zip package.")
    parser.add_argument("--version", required=True, help="Expected SKILL.md version after update")
    parser.add_argument("--sha512", required=True, help="Expected SHA-512 hex digest for the zip package")
    parser.add_argument("--url", help="Zip package URL")
    parser.add_argument("--zip-path", help="Local zip package path")
    parser.add_argument("--zip-skill-path", default="", help="Path to skill directory inside the extracted zip")
    parser.add_argument("--skill-root", default=str(DEFAULT_SKILL_ROOT), help="Current skill root directory")
    parser.add_argument("--backup-root", default="", help="Directory outside skills/ for backups")
    parser.add_argument("--dry-run", action="store_true", help="Validate only; do not replace files")
    args = parser.parse_args()

    if not re.fullmatch(r"[0-9a-fA-F]{128}", args.sha512.strip()):
        _json_exit(1, success=False, error="sha512 must be a 128-character hex digest")
    if not args.url and not args.zip_path:
        _json_exit(1, success=False, error="one of --url or --zip-path is required")

    skill_root = Path(args.skill_root).resolve()
    if not (skill_root / "SKILL.md").exists():
        _json_exit(1, success=False, error=f"skill root does not contain SKILL.md: {skill_root}")
    backup_root = Path(args.backup_root).resolve() if args.backup_root else _default_backup_root(skill_root).resolve()

    with tempfile.TemporaryDirectory(prefix="qbs_self_update_") as tmp:
        tmpdir = Path(tmp)
        zip_path = Path(args.zip_path).resolve() if args.zip_path else tmpdir / "package.zip"
        try:
            if args.url:
                _download(args.url, zip_path)
            actual_sha = _sha512(zip_path)
            if actual_sha.lower() != args.sha512.lower():
                _json_exit(1, success=False, error="zip sha512 mismatch", expected=args.sha512.lower(), actual=actual_sha.lower())

            staging = tmpdir / "staging"
            staging.mkdir()
            _safe_extract(zip_path, staging)
            source = _find_skill_source(staging, args.zip_skill_path)
            package_version = _validate_source(source, args.version)

            if args.dry_run:
                _json_exit(0, success=True, dry_run=True, package_version=package_version, source=str(source), skill_root=str(skill_root))

            backup_path = _install(source, skill_root, backup_root)
            _json_exit(0, success=True, package_version=package_version, skill_root=str(skill_root), backup_path=str(backup_path))
        except Exception as exc:
            _json_exit(1, success=False, error=str(exc), skill_root=str(skill_root))


if __name__ == "__main__":
    main()
