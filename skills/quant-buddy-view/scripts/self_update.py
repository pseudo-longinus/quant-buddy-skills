#!/usr/bin/env python3
"""Self-update quant-buddy-view from a verified zip package."""

import argparse
import contextlib
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
SKILL_NAME = "quant-buddy-view"
PRESERVE_NAMES = {"config.json", "config.local.json", "output", "logs", ".managed-install.json"}
MANAGED_MARKER = ".managed-install.json"
SHARED_LOCK_FILENAME = ".quant-buddy-view.update.lock"
LOCK_STALE_SECONDS = 2 * 60 * 60
REQUIRED_PATHS = [
    "SKILL.md",
    "CHANGELOG.md",
    "scripts/common.py",
    "scripts/build_dashboard.py",
    "tools",
    "templates",
    "reply-templates",
    "workflows",
    "guides",
    "assets",
]


def _json_exit(code, **payload):
    payload.setdefault("code", code)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.exit(0 if code == 0 else 1)


def _read_managed_marker(skill_root: Path) -> dict:
    try:
        payload = json.loads((skill_root / MANAGED_MARKER).read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _is_qbs_managed_install(skill_root: Path) -> bool:
    marker = _read_managed_marker(skill_root)
    return (
        marker.get("manager") == "quant-buddy-skill"
        and marker.get("channel") == "companion"
    )


@contextlib.contextmanager
def _exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.exists() and time.time() - path.stat().st_mtime > LOCK_STALE_SECONDS:
            path.unlink()
    except OSError:
        pass
    try:
        descriptor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"update lock is held: {path}") from exc
    try:
        os.write(descriptor, json.dumps({"pid": os.getpid(), "ts": int(time.time())}).encode("utf-8"))
        os.close(descriptor)
        yield
    finally:
        try:
            path.unlink()
        except OSError:
            pass


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


def _parse_version_tuple(version: str):
    if not version:
        return None
    text = str(version).strip()
    if text.startswith(("v", "V")):
        text = text[1:]
    parts = text.split(".")
    if not parts:
        return None
    nums = []
    for part in parts:
        if not re.fullmatch(r"\d+", part):
            return None
        nums.append(int(part))
    return tuple(nums)


def _is_newer_version(target_version: str, current_version: str) -> bool:
    target = _parse_version_tuple(target_version)
    current = _parse_version_tuple(current_version)
    if target is None or current is None:
        return str(target_version or "") != str(current_version or "")
    width = max(len(target), len(current))
    target = target + (0,) * (width - len(target))
    current = current + (0,) * (width - len(current))
    return target > current


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "quant-buddy-view-self-update"})
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

    direct = staging / SKILL_NAME
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
    if expected_version:
        exp_t = _parse_version_tuple(expected_version)
        act_t = _parse_version_tuple(actual_version)
        mismatch = (exp_t != act_t) if (exp_t is not None and act_t is not None) \
            else (str(expected_version).lstrip("vV") != str(actual_version).lstrip("vV"))
        if mismatch:
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


def _finalize_dedup_state(skill_root: Path, target_version: str, status: str, last_error=None) -> None:
    """写 output/.self_update_state.json，供 common.py 的「当日去重 / 失败上限」自愈。
    与触发方约定同一文件、同字段；best-effort，失败不抛。
    """
    if not target_version:
        return
    state_file = skill_root / "output" / ".self_update_state.json"
    try:
        today = time.strftime("%Y-%m-%d")
        prev = {}
        if state_file.exists():
            try:
                prev = json.loads(state_file.read_text(encoding="utf-8")) or {}
            except Exception:
                prev = {}
        same = prev.get("date") == today and prev.get("target_version") == target_version
        attempts = int(prev.get("attempts") or 0) if same else 0
        prev_status = prev.get("status") if same else None
        if status == "failed" and prev_status != "failed":
            attempts += 1
        new_state = {
            "date": today,
            "target_version": target_version,
            "attempts": attempts,
            "status": status,
            "last_error": last_error,
            "ts": int(time.time()),
        }
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps(new_state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _install(source: Path, skill_root: Path, backup_root: Path) -> Path:
    timestamp = time.strftime("%Y%m%d%H%M%S")
    backup_path = backup_root / f"{SKILL_NAME}-backup-{timestamp}"
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
    parser = argparse.ArgumentParser(description="Update quant-buddy-view from a verified zip package.")
    parser.add_argument("--version", required=True, help="Expected SKILL.md version after update")
    parser.add_argument("--sha512", default="", help="Expected SHA-512 hex digest for the zip package")
    parser.add_argument("--trust-tls", action="store_true",
                        help="Skip sha512 verification (GitHub tag source); integrity relies on HTTPS")
    parser.add_argument("--url", help="Zip package URL")
    parser.add_argument("--zip-path", help="Local zip package path")
    parser.add_argument("--zip-skill-path", default="", help="Path to skill directory inside the extracted zip")
    parser.add_argument("--skill-root", default=str(DEFAULT_SKILL_ROOT), help="Current skill root directory")
    parser.add_argument("--backup-root", default="", help="Directory outside skills/ for backups")
    parser.add_argument("--dry-run", action="store_true", help="Validate only; do not replace files")
    args = parser.parse_args()

    skill_root = Path(args.skill_root).resolve()
    if not (skill_root / "SKILL.md").exists():
        _json_exit(1, success=False, error=f"skill root does not contain SKILL.md: {skill_root}")

    # QBS companion installations have one owner. Standalone updater exits
    # successfully without touching the directory or requiring a download URL.
    if _is_qbs_managed_install(skill_root):
        _json_exit(
            0, success=True, skipped=True, reason="managed_install_owned_by_qbs",
            package_version=_read_skill_version(skill_root / "SKILL.md"),
            skill_root=str(skill_root),
        )

    sha512 = args.sha512.strip()
    if sha512:
        if not re.fullmatch(r"[0-9a-fA-F]{128}", sha512):
            _json_exit(1, success=False, error="sha512 must be a 128-character hex digest")
    elif not args.trust_tls:
        _json_exit(1, success=False, error="one of --sha512 or --trust-tls is required")
    if not args.url and not args.zip_path:
        _json_exit(1, success=False, error="one of --url or --zip-path is required")

    backup_root = Path(args.backup_root).resolve() if args.backup_root else _default_backup_root(skill_root).resolve()
    shared_lock = skill_root.parent / SHARED_LOCK_FILENAME

    try:
        with _exclusive_lock(shared_lock):
            # Re-read under the shared lock so a QBS update that won the race can
            # never be overwritten by an older standalone target.
            current_version = _read_skill_version(skill_root / "SKILL.md")
            if current_version and not _is_newer_version(args.version, current_version):
                _finalize_dedup_state(skill_root, args.version, "ok")
                _json_exit(
                    0, success=True, skipped=True,
                    reason=f"target {args.version} not newer than current {current_version}; skip to avoid downgrade.",
                    package_version=current_version, skill_root=str(skill_root),
                )

            with tempfile.TemporaryDirectory(prefix="qbv_self_update_") as tmp:
                tmpdir = Path(tmp)
                zip_path = Path(args.zip_path).resolve() if args.zip_path else tmpdir / "package.zip"
                if args.url:
                    _download(args.url, zip_path)
                if sha512:
                    actual_sha = _sha512(zip_path)
                    if actual_sha.lower() != sha512.lower():
                        raise RuntimeError(
                            f"zip sha512 mismatch: expected {sha512.lower()}, got {actual_sha.lower()}"
                        )

                staging = tmpdir / "staging"
                staging.mkdir()
                _safe_extract(zip_path, staging)
                source = _find_skill_source(staging, args.zip_skill_path)
                package_version = _validate_source(source, args.version)

                if args.dry_run:
                    _json_exit(0, success=True, dry_run=True, trust_tls=bool(not sha512),
                               package_version=package_version, source=str(source), skill_root=str(skill_root))

                backup_path = _install(source, skill_root, backup_root)
                _finalize_dedup_state(skill_root, args.version, "ok")
                _json_exit(0, success=True, package_version=package_version, skill_root=str(skill_root), backup_path=str(backup_path))
    except Exception as exc:
        _finalize_dedup_state(skill_root, args.version, "failed", last_error=str(exc))
        _json_exit(1, success=False, error=str(exc), skill_root=str(skill_root))


if __name__ == "__main__":
    main()
