"""Internal documentation."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx


MAX_CACHE_AGE_DAYS = 7
DEFAULT_TIMEOUT = 5


def _is_cache_fresh(cache_path: Path, *, max_age_days: int = MAX_CACHE_AGE_DAYS) -> bool:
    """Internal documentation."""
    if not cache_path.exists():
        return False
    age_seconds = time.time() - cache_path.stat().st_mtime
    return age_seconds < max_age_days * 86400


def _is_newer(remote: str, current: str) -> bool:
    """Internal documentation."""
    from packaging.version import Version, InvalidVersion
    try:
        return Version(remote) > Version(current)
    except InvalidVersion:
        return remote > current


def _check_for_update(
    latest_url: str,
    current_version: str,
    cache_path: Path,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    force: bool = False,
) -> str | None:
    """Internal documentation."""
    if not force and _is_cache_fresh(cache_path):
        return None
    try:
        resp = httpx.get(latest_url, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except Exception:  # noqa: BLE001
        return None
    tag = (data.get("tag_name") or "").lstrip("v").strip()
    if not tag:
        return None
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.touch()
    except OSError:
        pass
    if _is_newer(tag, current_version):
        return tag
    return None


def check_github_release(
    *,
    repo: str = "tungoldshou/argos",
    current_version: str,
    cache_path: Path,
    force: bool = False,
) -> str | None:
    """Internal documentation."""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    return _check_for_update(
        latest_url=url,
        current_version=current_version,
        cache_path=cache_path,
        force=force,
    )
