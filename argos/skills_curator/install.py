"""Internal documentation."""
from __future__ import annotations

import hashlib
import os
import shutil
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import yaml

from argos.i18n import t
from argos.skills_curator import index as _index_mod
from argos.skills_curator.capabilities import parse_frontmatter, validate_skill_meta
from argos.skills_curator.index import (
    BUILTIN_NAMES,
    IndexEntry,
    IndexFetchError,
    fetch_remote,
    load_cache,
)

MAX_SKILL_BYTES = 100 * 1024
_SIZE_DRIFT_TOL = 0.2  # 20%


@dataclass(frozen=True, slots=True)
class InstallResult:
    name: str
    path: Path
    sha256: str
    capabilities: tuple[str, ...]
    smoke: str | None
    warnings: tuple[str, ...] = ()


class InstallError(RuntimeError):
    """Internal documentation."""


def _is_builtin_protected(name: str) -> bool:
    return name in BUILTIN_NAMES


def download_skill(entry: IndexEntry, *, timeout: float = 10.0) -> bytes:
    if not entry.skill_md_url.startswith("https://"):
        raise InstallError(f"insecure_url: {entry.skill_md_url} must be https")
    try:
        with urllib.request.urlopen(entry.skill_md_url, timeout=timeout) as r:
            data = r.read()
    except (urllib.error.URLError, TimeoutError) as e:
        raise InstallError(
            f"network_error: {entry.skill_md_url}: {type(e).__name__}: {e}"
        ) from e
    if len(data) > MAX_SKILL_BYTES:
        raise InstallError(
            f"too_large: {len(data)} bytes > {MAX_SKILL_BYTES} (max skill size)"
        )
    return data


def verify_sha256(content: bytes, expected: str) -> str:
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected.lower():
        raise InstallError(
            f"sha_mismatch: expected={expected[:16]}... actual={actual[:16]}..."
        )
    return actual


def check_size_drift(content: bytes, declared: int, *, tol: float = _SIZE_DRIFT_TOL) -> str | None:
    if declared <= 0:
        return None
    ratio = abs(len(content) - declared) / declared
    if ratio > tol:
        return (
            f"size_drift: declared={declared} got={len(content)} "
            f"(drift {ratio*100:.0f}% > {tol*100:.0f}%)"
        )
    return None


def _ensure_enabled_false(content: bytes) -> bytes:
    """Internal documentation."""
    text = content.decode("utf-8")
    try:
        meta = parse_frontmatter(text)
    except ValueError:
        return content
    meta["enabled"] = False
    parts = text.split("---", 2)
    body = parts[2].lstrip("\n") if len(parts) >= 3 else ""
    new = "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + "---\n" + body
    return new.encode("utf-8")


def _network_user_confirmed(name: str) -> bool:
    """Internal documentation."""
    return os.environ.get("ARGOS_SKILLS_NETWORK_OK") == "1"


def backup_to_trash(skill_dir: Path, *, base_dir: Path) -> Path:
    """Internal documentation."""
    trash_dir = base_dir / ".trash" / f"{skill_dir.name}-{int(time.time())}"
    trash_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(skill_dir), str(trash_dir))
    return trash_dir


def install(name: str, *, base_dir: Path | None = None,
            run_smoke: bool = True) -> InstallResult:
    """Internal documentation."""
    if _is_builtin_protected(name):
        raise InstallError(
            f"protected_skill: {name!r} is builtin and cannot be overridden"
        )

    cache = load_cache(base_dir=base_dir)
    if cache is None:
        try:
            cache = fetch_remote()
        except IndexFetchError as e:
            raise InstallError(f"index_unavailable: {e}") from e
    entry = cache.find(name)
    if entry is None:
        raise InstallError(f"not_in_index: {name!r} (run `argos skills refresh`)")

    content = download_skill(entry)
    actual_sha = verify_sha256(content, entry.sha256)
    warnings: list[str] = []
    drift = check_size_drift(content, entry.size_bytes)
    if drift:
        warnings.append(drift)

    try:
        meta = parse_frontmatter(content.decode("utf-8"))
    except ValueError as e:
        raise InstallError(f"frontmatter_invalid: {e}") from e
    errs = validate_skill_meta(meta, name=name)
    if errs:
        raise InstallError(f"frontmatter_invalid: {'; '.join(errs)}")

    if "network" in entry.capabilities and not _network_user_confirmed(name):
        raise InstallError(t("skill.install_network_confirm_required", name=name))

    root = base_dir or _index_mod._skills_root()
    target_dir = root / name
    target_file = target_dir / "SKILL.md"

    if target_dir.exists():
        backup_to_trash(target_dir, base_dir=root)

    target_dir.mkdir(parents=True, exist_ok=True)
    final_content = _ensure_enabled_false(content)
    tmp = target_dir / "SKILL.md.tmp"
    tmp.write_bytes(final_content)
    tmp.replace(target_file)  # atomic

    smoke: str | None = None
    if run_smoke:
        try:
            from argos.skills_curator.smoke import run_smoke_test
            smoke = run_smoke_test(name, target_dir)
        except Exception as e:  # noqa: BLE001
            smoke = f"smoke_error: {type(e).__name__}: {e}"
            warnings.append(f"smoke test raised: {smoke}")

    return InstallResult(
        name=name,
        path=target_file,
        sha256=actual_sha,
        capabilities=entry.capabilities,
        smoke=smoke,
        warnings=tuple(warnings),
    )


__all__ = [
    "InstallError",
    "InstallResult",
    "MAX_SKILL_BYTES",
    "backup_to_trash",
    "check_size_drift",
    "download_skill",
    "install",
    "verify_sha256",
]
