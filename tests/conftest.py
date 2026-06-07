"""pytest 全局夹具。"""
import pytest


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
def _neutralize_mcp_singleton(monkeypatch):
    """测试隔离:绝不让 loop._build_system 连真实 ~/.argos/mcp.json 里的 MCP server
    (那会 spawn npx、联网下包、拖慢/污染测试,且让系统提示断言不稳)。把进程内单例的
    CONFIG_PATH 指到不存在的路径 → list_tools/tools_summary 恒空。需要测真 MCP 的用例
    自己构造独立 McpManager(config_path=...),不受此影响。"""
    from pathlib import Path

    from argos_agent import mcp_native
    mcp_native.shutdown()  # 清掉可能已建的单例
    monkeypatch.setattr(mcp_native, "CONFIG_PATH", Path("/nonexistent/argos-test/mcp.json"))
    yield
    mcp_native.shutdown()
