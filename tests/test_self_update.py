"""self-update 4 场景:缓存新鲜跳过 / 陈旧+新版 / 陈旧+无新版 / 网络失败静默。

纯函数 _check_for_update(latest_url, current_version, cache_path, force=False) -> str | None
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from argos_agent.core.updater import _check_for_update, _is_cache_fresh, _is_newer


# ---------- 单元:cache 判定 ----------
def test_cache_fresh_within_7_days(tmp_path: Path):
    cache = tmp_path / ".last_update_check"
    cache.touch()
    # mtime = now → 新鲜
    assert _is_cache_fresh(cache, max_age_days=7) is True


def test_cache_stale_after_7_days(tmp_path: Path):
    cache = tmp_path / ".last_update_check"
    cache.touch()
    # 把 mtime 拨到 8 天前
    eight_days_ago = time.time() - 8 * 86400
    import os
    os.utime(cache, (eight_days_ago, eight_days_ago))
    assert _is_cache_fresh(cache, max_age_days=7) is False


def test_cache_missing_is_stale(tmp_path: Path):
    cache = tmp_path / ".nope"
    assert _is_cache_fresh(cache, max_age_days=7) is False


# ---------- 单元:版本比较 ----------
def test_is_newer_basic():
    assert _is_newer("0.2.0", "0.1.0") is True
    assert _is_newer("0.1.0", "0.1.0") is False
    assert _is_newer("0.1.0", "0.2.0") is False
    assert _is_newer("0.2.0", "0.2.0") is False


# ---------- 集成:_check_for_update ----------
LATEST_URL = "https://api.github.com/repos/foo/bar/releases/latest"


def test_check_skips_when_cache_fresh(tmp_path: Path):
    cache = tmp_path / ".last_update_check"
    cache.touch()  # 新鲜
    result = _check_for_update(
        latest_url=LATEST_URL,
        current_version="0.1.0",
        cache_path=cache,
    )
    assert result is None
    # 不应调网络
    # (mock 网络层若被调会失败——见下)


def test_check_returns_newer_version(tmp_path: Path):
    cache = tmp_path / ".last_update_check"
    # cache 陈旧(8 天前)
    eight_days_ago = time.time() - 8 * 86400
    cache.touch()
    import os
    os.utime(cache, (eight_days_ago, eight_days_ago))
    payload = json.dumps({"tag_name": "v0.2.0", "body": "release notes"}).encode()
    with patch("argos_agent.core.updater.httpx.get") as mock_get:
        mock_get.return_value = type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: json.loads(payload), "content": payload})()
        result = _check_for_update(LATEST_URL, "0.1.0", cache)
    assert result == "0.2.0"
    # 缓存被刷新
    assert cache.exists()


def test_check_returns_none_when_no_newer(tmp_path: Path):
    cache = tmp_path / ".last_update_check"
    cache.touch()  # 不在 fresh 范围
    # 把 mtime 拨到 8 天前
    eight_days_ago = time.time() - 8 * 86400
    import os
    os.utime(cache, (eight_days_ago, eight_days_ago))
    payload = json.dumps({"tag_name": "v0.1.0", "body": ""}).encode()
    with patch("argos_agent.core.updater.httpx.get") as mock_get:
        mock_get.return_value = type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: json.loads(payload), "content": payload})()
        result = _check_for_update(LATEST_URL, "0.1.0", cache)
    assert result is None


def test_check_returns_none_on_network_failure(tmp_path: Path):
    cache = tmp_path / ".last_update_check"
    cache.touch()
    eight_days_ago = time.time() - 8 * 86400
    import os
    os.utime(cache, (eight_days_ago, eight_days_ago))
    with patch("argos_agent.core.updater.httpx.get", side_effect=Exception("network down")):
        result = _check_for_update(LATEST_URL, "0.1.0", cache)
    assert result is None  # 静默
    # 网络失败不刷缓存(下次再试)
    # 缓存 mtime 应仍为 8 天前
    import os
    assert os.path.getmtime(cache) == eight_days_ago


def test_check_skips_when_no_httpx_call_when_cache_fresh(tmp_path: Path):
    """缓存新鲜 → 不调 httpx(用 mock 显式断言)。"""
    cache = tmp_path / ".last_update_check"
    cache.touch()  # fresh
    with patch("argos_agent.core.updater.httpx.get") as mock_get:
        _check_for_update(LATEST_URL, "0.1.0", cache)
        mock_get.assert_not_called()
