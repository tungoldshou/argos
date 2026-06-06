"""Self-update 通知(仅查不下载,spec §2.5)。

启动时 background check GitHub latest release:
- 缓存 7 天(读 mtime 判定,无需解析文件)
- 缓存新鲜 → 跳过,不调网络
- 缓存陈旧 → 调 GitHub API,比较版本号
- 网络/JSON 失败 → 静默 None,启动不卡
- 静默更新缓存(网络成功时)

不下载(用户拍)。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx


MAX_CACHE_AGE_DAYS = 7
DEFAULT_TIMEOUT = 5  # 秒


def _is_cache_fresh(cache_path: Path, *, max_age_days: int = MAX_CACHE_AGE_DAYS) -> bool:
    """缓存文件存在 且 mtime 在 max_age_days 内 → True。"""
    if not cache_path.exists():
        return False
    age_seconds = time.time() - cache_path.stat().st_mtime
    return age_seconds < max_age_days * 86400


def _is_newer(remote: str, current: str) -> bool:
    """remote > current 用 packaging.version 严格比较(PEP 440)。"""
    from packaging.version import Version, InvalidVersion
    try:
        return Version(remote) > Version(current)
    except InvalidVersion:
        # 兜底:字符串字典序(够 MVP,失败不抛)
        return remote > current


def _check_for_update(
    latest_url: str,
    current_version: str,
    cache_path: Path,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    force: bool = False,
) -> str | None:
    """启动时调。返新版版本号(无新版/失败 → None)。

    force=True 跳过缓存(用于 `argos self-update` 主动命令)。
    """
    if not force and _is_cache_fresh(cache_path):
        return None
    try:
        resp = httpx.get(latest_url, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except Exception:  # noqa: BLE001 — 网络/JSON/超时全部静默(spec §3)
        return None
    tag = (data.get("tag_name") or "").lstrip("v").strip()
    if not tag:
        return None
    # 网络成功才刷缓存(失败保留旧 mtime,下次再试)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.touch()
    except OSError:
        pass  # 缓存写不进不算致命(spec §3 静默)
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
    """便捷包装:固定用 GitHub Releases API URL。

    Returns:新版 tag(去掉 'v' 前缀)或 None。
    """
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    return _check_for_update(
        latest_url=url,
        current_version=current_version,
        cache_path=cache_path,
        force=force,
    )
