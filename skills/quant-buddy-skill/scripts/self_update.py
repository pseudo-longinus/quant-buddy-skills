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


DOWNLOAD_TIMEOUT = 300          # 单次下载超时：5 分钟
DOWNLOAD_MAX_ATTEMPTS = 3       # 至少重试 3 次
DOWNLOAD_BACKOFF_BASE = 2       # 退避基数（秒）：1s, 2s, 4s ...


def _download_once(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "quant-buddy-skill-self-update"})
    with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp, dest.open("wb") as out:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)


def _download(url: str, dest: Path) -> None:
    """带退避重试的下载：单次 5min 超时，至少尝试 DOWNLOAD_MAX_ATTEMPTS 次。
    每次失败按 1s/2s/4s 退避；全部失败时抛出最后一次异常，错误信息含尝试次数与原因类别。
    """
    last_exc = None
    for attempt in range(1, DOWNLOAD_MAX_ATTEMPTS + 1):
        try:
            _download_once(url, dest)
            return
        except Exception as exc:  # noqa: BLE001 - 统一重试所有可恢复网络错误
            last_exc = exc
            try:
                if dest.exists():
                    dest.unlink()
            except OSError:
                pass
            if attempt < DOWNLOAD_MAX_ATTEMPTS:
                time.sleep(DOWNLOAD_BACKOFF_BASE ** (attempt - 1))
    raise RuntimeError(
        f"download failed after {DOWNLOAD_MAX_ATTEMPTS} attempts: "
        f"{type(last_exc).__name__}: {last_exc}"
    )


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


# 随版本更新的“代码/文档”顶层项；其余（output/logs/config*）跨版本保留、绝不换名
PRESERVE_FROM_SWAP = {"config.json", "config.local.json", "output", "logs", "__pycache__"}
STAGING_DIRNAME = ".staging"
LOCK_DIRNAME = ".self_update.lock"
LOCK_STALE_SECONDS = 1800  # 锁超过 30min 视为残留，可抢占


def _acquire_lock(skill_root: Path):
    """用 output/.self_update.lock 目录做并发互斥锁（mkdir 原子）。
    返回锁路径；获取失败抛 RuntimeError。检测并抢占明显残留的旧锁。
    """
    output_dir = skill_root / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    lock_path = output_dir / LOCK_DIRNAME
    try:
        lock_path.mkdir()
        return lock_path
    except FileExistsError:
        try:
            age = time.time() - lock_path.stat().st_mtime
            if age > LOCK_STALE_SECONDS:
                shutil.rmtree(lock_path, ignore_errors=True)
                lock_path.mkdir()
                return lock_path
        except Exception:
            pass
        raise RuntimeError("another self_update is in progress (lock held)")


def _release_lock(lock_path: Path):
    try:
        shutil.rmtree(lock_path, ignore_errors=True)
    except Exception:
        pass


def _atomic_swap_item(staged_item: Path, target: Path, trash_dir: Path) -> None:
    """同卷原子换名：把已就位的 staged_item 换成 target。
    - target 不存在：直接 os.replace（原子创建）
    - target 是文件/链接：os.replace 原子覆盖
    - target 是目录：旧目录先移入 trash，再放新目录
    Windows 对“有打开句柄/正在执行”的目录换名可能失败，调用方需保证更新时段无并发执行。
    """
    if not target.exists():
        os.replace(staged_item, target)
        return
    if target.is_file() or target.is_symlink():
        os.replace(staged_item, target)
        return
    trash_target = trash_dir / target.name
    os.replace(target, trash_target)
    try:
        os.replace(staged_item, target)
    except Exception:
        os.replace(trash_target, target)
        raise


def _install(source: Path, skill_root: Path, backup_root: Path) -> Path:
    """方案 X 原子安装：
      1) 文件锁互斥；
      2) 备份当前安装（沿用旧逻辑，供审计/手工回滚）；
      3) 新版各顶层“代码/文档”项先拷到 output/.staging/<item>（同卷）；
      4) 逐项用 os.replace 原子换名换入 skill_root，旧项移入 .trash；
      5) 全部成功后清 .trash / .staging；任一步失败则从 .trash 回滚已换项。
    config*/output/logs 全程不参与换名，原地保留。
    """
    lock_path = _acquire_lock(skill_root)
    timestamp = time.strftime("%Y%m%d%H%M%S")
    backup_path = backup_root / f"quant-buddy-skill-backup-{timestamp}"
    backup_root.mkdir(parents=True, exist_ok=True)

    output_dir = skill_root / "output"
    staging_root = output_dir / STAGING_DIRNAME / timestamp
    trash_root = output_dir / STAGING_DIRNAME / f"{timestamp}.trash"
    swapped = []  # [(target, trash_path_or_None)] 供失败回滚

    try:
        # 备份（best-effort，失败不阻断主流程）
        try:
            _copytree(skill_root, backup_path)
        except Exception:
            pass

        # 计算要换入的顶层项（排除保留态）
        items = [it for it in source.iterdir() if it.name not in PRESERVE_FROM_SWAP]

        # 全部先拷到 staging（同卷，保证后续 os.replace 原子）
        if staging_root.exists():
            shutil.rmtree(staging_root, ignore_errors=True)
        staging_root.mkdir(parents=True, exist_ok=True)
        trash_root.mkdir(parents=True, exist_ok=True)
        for it in items:
            dst = staging_root / it.name
            if it.is_dir() and not it.is_symlink():
                shutil.copytree(it, dst)
            else:
                shutil.copy2(it, dst)

        # 逐项原子换名
        for it in items:
            target = skill_root / it.name
            staged = staging_root / it.name
            had_target = target.exists()
            _atomic_swap_item(staged, target, trash_root)
            swapped.append((target, (trash_root / it.name) if had_target else None))

        # 成功：清理 trash / staging
        shutil.rmtree(trash_root, ignore_errors=True)
        shutil.rmtree(staging_root, ignore_errors=True)
        return backup_path

    except Exception:
        # 回滚已换入的项：把 trash 里的旧项换回来
        for target, trash_old in reversed(swapped):
            try:
                if trash_old is not None and trash_old.exists():
                    if target.exists():
                        if target.is_dir() and not target.is_symlink():
                            shutil.rmtree(target, ignore_errors=True)
                        else:
                            target.unlink()
                    os.replace(trash_old, target)
                else:
                    # 原本不存在的新项：删除以恢复原状
                    if target.exists():
                        if target.is_dir() and not target.is_symlink():
                            shutil.rmtree(target, ignore_errors=True)
                        else:
                            target.unlink()
            except Exception:
                pass
        shutil.rmtree(trash_root, ignore_errors=True)
        shutil.rmtree(staging_root, ignore_errors=True)
        raise
    finally:
        _release_lock(lock_path)



def _finalize_dedup_state(skill_root: Path, target_version: str, status: str, last_error=None):
    """更新 output/.self_update_state.json，让 call.py 的“当日去重/软锁”自愈：
    后台更新结束（ok/failed）后清除 in_progress，避免同日其他进程被永久软锁。
    与 call.py._self_update_mark 写同一文件、同一字段约定；best-effort，失败不抛。
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
    current_version = _read_skill_version(skill_root / "SKILL.md")
    if current_version and not _is_newer_version(args.version, current_version):
        _finalize_dedup_state(skill_root, args.version, "ok")
        _json_exit(
            0,
            success=True,
            skipped=True,
            reason=f"target version {args.version} is not newer than current {current_version}; skip self_update to avoid downgrade.",
            package_version=current_version,
            skill_root=str(skill_root),
        )

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
            _finalize_dedup_state(skill_root, args.version, "ok")
            _json_exit(0, success=True, package_version=package_version, skill_root=str(skill_root), backup_path=str(backup_path))
        except Exception as exc:
            _finalize_dedup_state(skill_root, args.version, "failed", last_error=str(exc))
            _json_exit(1, success=False, error=str(exc), skill_root=str(skill_root))


if __name__ == "__main__":
    main()
