"""pytest 全局夹具。"""
from __future__ import annotations

import shutil
import sys

import pytest

from argos.sandbox import executor as _executor_mod
from argos.sandbox.linux import _AVAILABLE_BACKEND as _LINUX_BACKEND


def current_sandbox_backend() -> str | None:
    """返回当前平台可用的沙箱后端名;都没有则 None(不假装有)。

    - darwin + /usr/bin/sandbox-exec 在 → "seatbelt"
    - linux + bwrap 在 → "bwrap"
    - linux + 仅 unshare 在 → "unshare"
    - 其他或工具不在 → None
    """
    if sys.platform == "darwin":
        if shutil.which("sandbox-exec") or _executor_mod.SeatbeltExecutor is not None:
            # macOS 上 sandbox-exec 总是系统自带;Seatbelt 仍可用
            return "seatbelt"
        return None
    if sys.platform == "linux":
        return _LINUX_BACKEND  # bwrap / unshare / None
    return None


def require_sandbox_backend() -> str:
    """返回当前沙箱后端名;无后端则 pytest.skip 并说明原因(供 fixture / test 入口用)。"""
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
    """共享守卫 fixture:无沙箱后端时自动 skip(并把后端名递给测试方便断言)。

    用法:
        def test_x(requires_sandbox):
            backend = requires_sandbox
            ...真跑...

    纯单元测试(presets/config/prune/jsonl)不要装这个 fixture —— 它们不真开沙箱。
    """
    return require_sandbox_backend()


@pytest.fixture(autouse=True)
def _shorten_unix_socket_paths(monkeypatch):
    """macOS 的 AF_UNIX `sun_path` 上限是 104 字节;pytest 的 `tmp_path` 落在
    `/var/folders/.../pytest-of-<user>/pytest-N/<长测试名>0/` 下,拼上 `daemon.sock`
    常常 >104 → daemon server bind / client connect 直接 `OSError: AF_UNIX path too long`。

    这里把**超长**的 unix socket 路径透明映射到 `/tmp` 下一个短路径(按原路径确定性哈希,
    所以 server bind 与 client connect 拿到的是同一个短路径,能接上)。只改 socket 文件的
    落点,不碰任何被测逻辑/断言;路径本就够短时是 no-op,正常机器上行为不变。
    """
    import asyncio
    import hashlib
    import os

    real_start = asyncio.start_unix_server
    real_open = asyncio.open_unix_connection
    created: set[str] = set()
    LIMIT = 100  # 留余量,稳在 104 以内

    def _short(path):
        if path is None:
            return path
        s = str(path)
        if len(s) < LIMIT:
            return path
        h = hashlib.sha1(s.encode()).hexdigest()[:16]
        short = f"/tmp/ags-{h}.sock"  # 短且确定:同一原路径恒映射到同一短路径
        created.add(short)
        return short

    async def _start_wrap(cb, path=None, *args, **kwargs):
        sp = _short(path)
        if sp is not path and sp is not None:
            # 我们改写了路径 → bind 前确保干净,避免上次残留导致 EADDRINUSE
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
def _force_numbered_setup_menu(monkeypatch):
    """测试环境强制 `argos setup` 向导走编号输入回退,绝不进 termios raw 模式 ——
    即便 `pytest -s` 下 stdin 是真终端,也不会卡住等待键盘(_arrow_select 见此 env 即抛 _NotATTY)。"""
    monkeypatch.setenv("ARGOS_NO_ARROW_SELECT", "1")


@pytest.fixture(autouse=True)
def _reset_skills_registry():
    """测试隔离:每个测试前后清空 skills_runtime 单例注册表。

    _SKILLS 是模块级 dict,不同测试文件在同一 xdist worker 进程内顺序跑时会互相污染
    (例如 test_skills_registry 注册 "verify" 后未清除,下一个测试再注册同名 → ValueError)。
    autouse=True:无需各测试显式调用 _reset_registry()。
    """
    try:
        from argos.skills_runtime import _reset_registry as _rr
        _rr()
        yield
        _rr()
    except ImportError:
        yield


@pytest.fixture(autouse=True)
def _reset_permissions_config(tmp_path, monkeypatch):
    """测试隔离:permissions.config 单例 + CONFIG_PATH 双重隔离。

    两个坑(Phase 1 让"always"真持久化后双双显形):
      1) _config 模块级缓存:有的测试 monkeypatch CONFIG_PATH 后调 reload_config(),把单例换成
         tmp 配置(可能含 run_command/^pytest allow),monkeypatch 只回滚路径不回滚单例 → 污染下一个
         测试(默认 gate / get_config 会误把 pytest 命令 soft_allow 成 approve)。
      2) 真实 ~/.argos/permissions.json:走"always"审批的测试(如 daemon p3 circuit)若不隔离
         CONFIG_PATH,会把 action_b/run_workflow 等测试动作真写进用户的配置文件。
    把 CONFIG_PATH 指到本测试独占的 tmp 文件(默认不存在 → 读空配置),既杜绝读真实配置、也杜绝
    写脏用户文件。需要测真持久化的用例自己 monkeypatch CONFIG_PATH 到自备 tmp(在 fixture 之后生效,
    覆盖此默认)。"""
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
    """测试隔离:绝不让 loop._build_system 连真实 ~/.argos/mcp.json 里的 MCP server
    (那会 spawn npx、联网下包、拖慢/污染测试,且让系统提示断言不稳)。把进程内单例的
    CONFIG_PATH 指到不存在的路径 → list_tools/tools_summary 恒空。需要测真 MCP 的用例
    自己构造独立 McpManager(config_path=...),不受此影响。"""
    from pathlib import Path

    from argos import mcp_native
    mcp_native.shutdown()  # 清掉可能已建的单例
    monkeypatch.setattr(mcp_native, "CONFIG_PATH", Path("/nonexistent/argos-test/mcp.json"))
    yield
    mcp_native.shutdown()


@pytest.fixture(autouse=True)
def _no_real_daemon(monkeypatch):
    """测试隔离铁律(实测 2026-06-12):pytest 绝不许探测/连接用户真实 daemon。

    真 daemon 在跑时,TUI Pilot 测试会经 _setup_daemon_mode 连上用户内核
    (建 session、被 observer 403、甚至可能建真 run)。ARGOS_NO_DAEMON=1 强制
    inline;ARGOS_DAEMON_SOCKET 指向不存在路径作双保险。显式测 daemon 路径的
    测试自己起独立 server + 显式 socket,不受影响。"""
    monkeypatch.setenv("ARGOS_NO_DAEMON", "1")
    monkeypatch.setenv("ARGOS_DAEMON_SOCKET", "/nonexistent/argos-test/daemon.sock")
