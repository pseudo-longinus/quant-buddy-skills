#!/usr/bin/env python3
"""Install and update optional QBS companion skills from a verified package.

The module is intentionally standard-library only so packaged QBS installations can
run it without adding dependencies. All failures are returned as structured soft
results; callers decide how to expose them without blocking market-data workflows.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, Optional, Tuple

COMPANION_NAME = "quant-buddy-view"
STATE_FILENAME = ".companion_state.json"
LOCK_FILENAME = ".companion_update.lock"
SHARED_LOCK_FILENAME = ".quant-buddy-view.update.lock"
MANAGED_MARKER = ".managed-install.json"
DEFAULT_PRESERVE = ("config.json", "config.local.json", "output", "logs")
LOCK_STALE_SECONDS = 2 * 60 * 60
DOWNLOAD_TIMEOUT_SECONDS = 300
DOWNLOAD_ATTEMPTS = 3
SEMVER_RE = re.compile(
    r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)


class CompanionError(RuntimeError):
    pass


class LockBusy(CompanionError):
    pass


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_semver(value: object) -> Optional[Tuple[Tuple[int, int, int], Tuple[str, ...]]]:
    match = SEMVER_RE.fullmatch(str(value or "").strip())
    if not match:
        return None
    return (
        (int(match.group(1)), int(match.group(2)), int(match.group(3))),
        tuple(match.group(4).split(".")) if match.group(4) else (),
    )


def _compare_identifier(left: str, right: str) -> int:
    left_numeric = left.isdigit()
    right_numeric = right.isdigit()
    if left_numeric and right_numeric:
        return (int(left) > int(right)) - (int(left) < int(right))
    if left_numeric != right_numeric:
        return -1 if left_numeric else 1
    return (left > right) - (left < right)


def compare_semver(left: object, right: object) -> int:
    """Compare SemVer values. Returns -1, 0, or 1."""
    a = _parse_semver(left)
    b = _parse_semver(right)
    if a is None or b is None:
        raise CompanionError(f"invalid semantic version: {left!r} or {right!r}")
    if a[0] != b[0]:
        return (a[0] > b[0]) - (a[0] < b[0])
    a_pre, b_pre = a[1], b[1]
    if not a_pre and not b_pre:
        return 0
    if not a_pre:
        return 1
    if not b_pre:
        return -1
    for index in range(max(len(a_pre), len(b_pre))):
        if index >= len(a_pre):
            return -1
        if index >= len(b_pre):
            return 1
        compared = _compare_identifier(a_pre[index], b_pre[index])
        if compared:
            return compared
    return 0


def read_skill_version(skill_root: Path) -> str:
    try:
        with (skill_root / "SKILL.md").open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if line.startswith("version:"):
                    return line.split(":", 1)[1].strip().strip('"\'')
    except Exception:
        return ""
    return ""


def _has_git_ancestor(path: Path) -> bool:
    current = path
    while True:
        if (current / ".git").exists():
            return True
        if current.parent == current:
            return False
        current = current.parent


def resolve_skills_root(
    qbs_root: Path,
    environ: Optional[Dict[str, str]] = None,
    canonical_root: Optional[Path] = None,
) -> Dict[str, object]:
    """Resolve the canonical directory that owns sibling skill installations.

    Explicit QBS_COMPANION_SKILLS_ROOT wins. Otherwise a real/canonical QBS path
    whose parent is named ``skills`` is preferred, which collapses Claude/Cursor
    links onto a shared ``~/.agents/skills`` target. A normal logical ``skills``
    parent is the fallback. Unknown layouts are soft-skipped rather than guessed.
    """
    env = os.environ if environ is None else environ
    logical_root = Path(qbs_root).absolute()
    explicit = str(env.get("QBS_COMPANION_SKILLS_ROOT", "") or "").strip()
    if explicit:
        explicit_path = Path(explicit)
        if not explicit_path.is_absolute():
            return {"ok": False, "reason": "QBS_COMPANION_SKILLS_ROOT must be absolute"}
        skills_root = explicit_path.resolve(strict=False)
        return {
            "ok": True,
            "source": "environment",
            "logical_qbs_root": logical_root,
            "canonical_qbs_root": (canonical_root or logical_root.resolve(strict=False)),
            "skills_root": skills_root,
            "dev_checkout": False,
        }

    canonical = (canonical_root or logical_root.resolve(strict=False))
    if canonical.parent.name.lower() == "skills":
        skills_root = canonical.parent
        source = "canonical_parent"
    elif logical_root.parent.name.lower() == "skills":
        skills_root = logical_root.parent
        source = "logical_parent"
    else:
        return {
            "ok": False,
            "reason": "cannot determine companion skills root safely",
            "logical_qbs_root": logical_root,
            "canonical_qbs_root": canonical,
        }

    return {
        "ok": True,
        "source": source,
        "logical_qbs_root": logical_root,
        "canonical_qbs_root": canonical,
        "skills_root": skills_root.resolve(strict=False),
        "dev_checkout": _has_git_ancestor(canonical),
    }


def _normalize_preserve_files(values: object) -> Tuple[str, ...]:
    raw_values: Iterable[object] = values if isinstance(values, list) else DEFAULT_PRESERVE
    normalized = []
    for value in raw_values:
        text = str(value or "").strip().replace("\\", "/")
        path = PurePosixPath(text)
        if not text or path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
            continue
        if text not in normalized:
            normalized.append(text)
    return tuple(normalized or DEFAULT_PRESERVE)


def _write_state(qbs_root: Path, payload: Dict[str, object]) -> None:
    try:
        state_path = qbs_root / "output" / STATE_FILENAME
        state_path.parent.mkdir(parents=True, exist_ok=True)
        body = {"schema_version": 1, "updated_at": int(time.time()), **payload}
        temp_path = state_path.with_name(f"{state_path.name}.{uuid.uuid4().hex}.tmp")
        temp_path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp_path, state_path)
    except Exception:
        pass


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
        raise LockBusy(f"update lock is held: {path}") from exc
    try:
        os.write(descriptor, json.dumps({"pid": os.getpid(), "ts": int(time.time())}).encode("utf-8"))
        os.close(descriptor)
        yield
    finally:
        try:
            path.unlink()
        except OSError:
            pass


def _sha512(path: Path) -> str:
    digest = hashlib.sha512()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _download(url: str, destination: Path) -> None:
    last_error = None
    for attempt in range(DOWNLOAD_ATTEMPTS):
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "quant-buddy-skill-companion-manager/1"},
            )
            with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
                with destination.open("wb") as handle:
                    shutil.copyfileobj(response, handle)
            return
        except Exception as exc:
            last_error = exc
            if attempt + 1 < DOWNLOAD_ATTEMPTS:
                time.sleep((1, 3, 7)[attempt])
    raise CompanionError(f"download failed after {DOWNLOAD_ATTEMPTS} attempts: {last_error}")


def _safe_extract(zip_path: Path, destination: Path) -> None:
    root = destination.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            relative = PurePosixPath(name)
            if relative.is_absolute() or ".." in relative.parts or (relative.parts and ":" in relative.parts[0]):
                raise CompanionError(f"unsafe zip member: {info.filename}")
            unix_mode = (info.external_attr >> 16) & 0o170000
            if unix_mode == 0o120000:
                raise CompanionError(f"zip symlink is not allowed: {info.filename}")
            target = (destination / Path(*relative.parts)).resolve()
            if target != root and root not in target.parents:
                raise CompanionError(f"zip member escapes staging: {info.filename}")
            if info.is_dir() or name.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _locate_source(staging: Path, zip_skill_path: str) -> Path:
    normalized = str(zip_skill_path or "").strip().replace("\\", "/").strip("/")
    relative = PurePosixPath(normalized)
    if not normalized or relative.is_absolute() or ".." in relative.parts:
        raise CompanionError("package.zip_skill_path is required and must be a safe relative path")
    source = staging.joinpath(*relative.parts).resolve()
    if staging.resolve() not in source.parents:
        raise CompanionError("package.zip_skill_path escapes staging")
    if not source.is_dir():
        raise CompanionError(f"package skill path not found: {normalized}")
    return source


def _copy_source(source: Path, prepared: Path) -> None:
    shutil.copytree(source, prepared, symlinks=False)


def _merge_preserved(target: Path, prepared: Path, preserve_files: Tuple[str, ...]) -> None:
    if not target.exists():
        return
    for name in preserve_files:
        source = target / name
        destination = prepared / name
        if not source.exists() and not source.is_symlink():
            continue
        if destination.exists() or destination.is_symlink():
            if destination.is_dir() and not destination.is_symlink():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        if source.is_dir() and not source.is_symlink():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)


def _write_managed_marker(prepared: Path, version: str) -> None:
    marker = {
        "schema_version": 1,
        "manager": "quant-buddy-skill",
        "channel": "companion",
        "installed_version": version,
        "source_repository": "pseudo-longinus/quant-buddy-view",
        "source_tag": f"v{version}",
    }
    (prepared / MANAGED_MARKER).write_text(
        json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _atomic_install(prepared: Path, target: Path, backup_root: Path) -> Optional[Path]:
    backup_root.mkdir(parents=True, exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if target.exists() or target.is_symlink():
        backup = backup_root / f"{COMPANION_NAME}-backup-{time.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
        os.replace(target, backup)
    try:
        os.replace(prepared, target)
    except Exception:
        if backup is not None and backup.exists() and not target.exists():
            os.replace(backup, target)
        raise
    return backup


def _policy_allows(companion: Dict[str, object]) -> Tuple[bool, str]:
    if companion.get("manager_compatible") is False:
        return False, "manager_too_old"
    if "eligible" in companion:
        return bool(companion.get("eligible")), str(companion.get("eligibility_reason") or "server_eligibility")
    policy = str(companion.get("install_policy") or "off")
    rollout = int(companion.get("rollout_percent") or 0)
    if policy == "off":
        return False, "policy_off"
    if policy == "default_on" and rollout >= 100:
        return True, "default_on_100"
    return False, "server_eligibility_missing"


def reconcile_after_qbs_check(
    companions: object,
    qbs_root: object,
    manager_version: str,
    qbs_update_required: bool = False,
    environ: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, object]]:
    """Apply the shared QBS-first companion state machine used by all clients."""
    items = companions if isinstance(companions, list) else []
    has_qbv = any(
        isinstance(item, dict) and item.get("name") == COMPANION_NAME
        for item in items
    )
    if not has_qbv:
        return None
    if qbs_update_required:
        return {
            "name": COMPANION_NAME,
            "attempted": False,
            "ok": True,
            "skipped": True,
            "reason": "qbs_update_has_priority",
            "reload_required": False,
        }
    return reconcile_companions(items, qbs_root, manager_version, environ=environ)


def reconcile_companions(
    companions: object,
    qbs_root: object,
    manager_version: str,
    environ: Optional[Dict[str, str]] = None,
) -> Dict[str, object]:
    """Reconcile QBV from a version/check companion payload.

    Returns a structured result and never raises. QBS callers may safely continue
    their business workflow when ``ok`` is false.
    """
    env = os.environ if environ is None else environ
    qbs_path = Path(qbs_root).absolute()
    force = _truthy(env.get("QBS_FORCE_COMPANION_RECONCILE"))
    base = {
        "name": COMPANION_NAME,
        "attempted": False,
        "ok": True,
        "reload_required": False,
    }
    if _truthy(env.get("QBS_DISABLE_COMPANION_INSTALL")):
        result = {**base, "skipped": True, "reason": "disabled_by_environment"}
        _write_state(qbs_path, result)
        return result
    items = companions if isinstance(companions, list) else []
    companion = next((item for item in items if isinstance(item, dict) and item.get("name") == COMPANION_NAME), None)
    if not companion:
        result = {**base, "skipped": True, "reason": "companion_not_declared"}
        _write_state(qbs_path, result)
        return result

    allowed, policy_reason = _policy_allows(companion)
    if not allowed:
        result = {**base, "skipped": True, "reason": policy_reason}
        _write_state(qbs_path, result)
        return result

    min_manager = str(companion.get("min_manager_version") or "").strip()
    try:
        if min_manager and compare_semver(manager_version, min_manager) < 0:
            result = {**base, "skipped": True, "reason": "manager_too_old", "required_manager_version": min_manager}
            _write_state(qbs_path, result)
            return result
    except CompanionError as exc:
        result = {**base, "ok": False, "skipped": True, "reason": str(exc)}
        _write_state(qbs_path, result)
        return result

    resolved = resolve_skills_root(qbs_path, env)
    if not resolved.get("ok"):
        result = {**base, "skipped": True, "reason": resolved.get("reason")}
        _write_state(qbs_path, result)
        return result
    if resolved.get("dev_checkout") and not force:
        result = {**base, "skipped": True, "reason": "development_checkout"}
        _write_state(qbs_path, result)
        return result

    skills_root = Path(resolved["skills_root"])
    target = skills_root / COMPANION_NAME
    if qbs_path == target or qbs_path in target.parents:
        result = {**base, "ok": False, "skipped": True, "reason": "unsafe_target_path"}
        _write_state(qbs_path, result)
        return result

    package = companion.get("package") if isinstance(companion.get("package"), dict) else {}
    target_version = str(package.get("required_version") or companion.get("latest_version") or "").strip()
    zip_url = str(package.get("zip_url") or "").strip()
    expected_sha = str(package.get("zip_sha512") or "").strip().lower()
    zip_skill_path = str(package.get("zip_skill_path") or "").strip()
    if not target_version or not zip_url or not re.fullmatch(r"[0-9a-f]{128}", expected_sha) or not zip_skill_path:
        result = {**base, "ok": False, "skipped": True, "reason": "invalid_companion_package"}
        _write_state(qbs_path, result)
        return result

    current_version = read_skill_version(target)
    try:
        compared = compare_semver(target_version, current_version) if current_version else 1
    except CompanionError as exc:
        result = {**base, "ok": False, "skipped": True, "reason": str(exc), "current_version": current_version}
        _write_state(qbs_path, result)
        return result
    if compared < 0:
        result = {**base, "skipped": True, "reason": "local_version_is_newer", "current_version": current_version, "target_version": target_version}
        _write_state(qbs_path, result)
        return result
    if compared == 0 and not force:
        result = {**base, "skipped": True, "reason": "already_current", "current_version": current_version, "target_version": target_version}
        _write_state(qbs_path, result)
        return result

    preserve_files = _normalize_preserve_files(companion.get("preserve_files"))
    qbs_lock = qbs_path / "output" / LOCK_FILENAME
    shared_lock = skills_root / SHARED_LOCK_FILENAME
    result = {
        **base,
        "attempted": True,
        "ok": False,
        "action": "install" if not current_version else ("reconcile" if compared == 0 else "update"),
        "current_version": current_version or None,
        "target_version": target_version,
        "skills_root": str(skills_root),
        "target_root": str(target),
    }
    try:
        with _exclusive_lock(qbs_lock), _exclusive_lock(shared_lock):
            # Re-check inside the shared lock. Another QBS/QBV updater may have
            # completed after the optimistic check above; never overwrite it
            # with the now-stale target.
            locked_current = read_skill_version(target)
            if locked_current:
                locked_compared = compare_semver(target_version, locked_current)
                if locked_compared < 0 or (locked_compared == 0 and not force):
                    result.update({
                        "attempted": False,
                        "ok": True,
                        "skipped": True,
                        "reason": "local_version_is_newer" if locked_compared < 0 else "already_current",
                        "current_version": locked_current,
                    })
                    _write_state(qbs_path, result)
                    return result

            skills_root.parent.mkdir(parents=True, exist_ok=True)
            temp_root = Path(tempfile.mkdtemp(prefix=".qbs-companion-", dir=str(skills_root.parent)))
            try:
                zip_path = temp_root / "package.zip"
                _download(zip_url, zip_path)
                actual_sha = _sha512(zip_path)
                if actual_sha != expected_sha:
                    raise CompanionError(f"zip sha512 mismatch: expected {expected_sha}, got {actual_sha}")
                staging = temp_root / "staging"
                staging.mkdir()
                _safe_extract(zip_path, staging)
                source = _locate_source(staging, zip_skill_path)
                actual_version = read_skill_version(source)
                if not actual_version or compare_semver(actual_version, target_version) != 0:
                    raise CompanionError(
                        f"package version mismatch: expected {target_version}, got {actual_version or '(missing)'}"
                    )
                prepared = temp_root / "prepared"
                _copy_source(source, prepared)
                _merge_preserved(target, prepared, preserve_files)
                _write_managed_marker(prepared, actual_version)
                backup_root = skills_root.parent / "skill-backups"
                backup = _atomic_install(prepared, target, backup_root)
                result.update({
                    "ok": True,
                    "reload_required": True,
                    "installed_version": actual_version,
                    "backup_path": str(backup) if backup else None,
                    "activation": companion.get("activation") or "next_agent_reload",
                })
            finally:
                shutil.rmtree(temp_root, ignore_errors=True)
    except LockBusy as exc:
        result.update({"attempted": False, "skipped": True, "reason": "update_lock_held", "error": str(exc)})
    except Exception as exc:
        result.update({"error": str(exc)})

    _write_state(qbs_path, result)
    return result


__all__ = [
    "COMPANION_NAME",
    "compare_semver",
    "read_skill_version",
    "resolve_skills_root",
    "reconcile_companions",
]
