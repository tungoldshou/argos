"""Internal documentation."""
from __future__ import annotations

import os

os.environ.setdefault("ARGOS_LANG", "zh")

os.environ.setdefault("ARGOS_SANDBOX", "1")

import shutil
import sys

import pytest

from argos.sandbox import executor as _executor_mod
from argos.sandbox.linux import _AVAILABLE_BACKEND as _LINUX_BACKEND


def current_sandbox_backend() -> str | None:
    """Internal documentation."""
    if sys.platform == "darwin":
        if shutil.which("sandbox-exec") or _executor_mod.SeatbeltExecutor is not None:
            return "seatbelt"
        return None
    if sys.platform == "linux":
        return _LINUX_BACKEND  # bwrap / unshare / None
    return None


def require_sandbox_backend() -> str:
    """Internal documentation."""
    backend = current_sandbox_backend()
    if backend is None:
        platform = sys.platform
        if platform == "linux":
            reason = (
                "无可用 Linux 沙箱后端(bwrap / unshare 都不在 PATH);"
                "装 bwrap 或 unshare 后重试,或在该 CI 上跑"
            )
        elif platform == "darwin":
            reason = "macOS 上 /usr/bin/sandbox-exec 不在(罕见)"
        else:
            reason = f"Argos 沙箱暂不支持 {platform!r}"
        pytest.skip(reason)
    return backend


@pytest.fixture
def requires_sandbox() -> str:
    """Internal documentation."""
    return require_sandbox_backend()


@pytest.fixture(autouse=True)
def _shorten_unix_socket_paths(monkeypatch):
    """Internal documentation."""
    import asyncio
    import hashlib
    import os

    real_start = asyncio.start_unix_server
    real_open = asyncio.open_unix_connection
    created: set[str] = set()
    LIMIT = 100

    def _short(path):
        if path is None:
            return path
        s = str(path)
        if len(s) < LIMIT:
            return path
        h = hashlib.sha1(s.encode()).hexdigest()[:16]
        short = f"/tmp/ags-{h}.sock"
        created.add(short)
        return short

    async def _start_wrap(cb, path=None, *args, **kwargs):
        sp = _short(path)
        if sp is not path and sp is not None:
            try:
                os.unlink(sp)
            except OSError:
                pass
        return await real_start(cb, sp, *args, **kwargs)

    async def _open_wrap(path=None, *args, **kwargs):
        return await real_open(_short(path), *args, **kwargs)

    monkeypatch.setattr(asyncio, "start_unix_server", _start_wrap)
    monkeypatch.setattr(asyncio, "open_unix_connection", _open_wrap)
    yield
    for p in created:
        try:
            os.unlink(p)
        except OSError:
            pass


@pytest.fixture(autouse=True)
def _isolate_argos_config_dir(tmp_path, monkeypatch):
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path / ".argos"))


@pytest.fixture(autouse=True)
def _force_numbered_setup_menu(monkeypatch):
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_NO_ARROW_SELECT", "1")


@pytest.fixture(autouse=True)
def _reset_skills_registry():
    """Internal documentation."""
    try:
        from argos.skills_runtime import _reset_registry as _rr
        _rr()
        yield
        _rr()
    except ImportError:
        yield


@pytest.fixture(autouse=True)
def _reset_permissions_config(tmp_path, monkeypatch):
    """Internal documentation."""
    try:
        from argos.permissions import config as _pcfg
        monkeypatch.setattr(_pcfg, "CONFIG_PATH", tmp_path / "permissions.json", raising=False)
        _pcfg._reset_config()
        yield
        _pcfg._reset_config()
    except ImportError:
        yield


@pytest.fixture(autouse=True)
def _neutralize_mcp_singleton(monkeypatch):
    """Internal documentation."""
    from pathlib import Path

    from argos import mcp_native
    mcp_native.shutdown()
    monkeypatch.setattr(mcp_native, "CONFIG_PATH", Path("/nonexistent/argos-test/mcp.json"))
    yield
    mcp_native.shutdown()


@pytest.fixture(autouse=True)
def _no_real_daemon(monkeypatch):
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_NO_DAEMON", "1")
    monkeypatch.setenv("ARGOS_DAEMON_SOCKET", "/nonexistent/argos-test/daemon.sock")
