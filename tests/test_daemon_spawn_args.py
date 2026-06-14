"""daemon spawn 用正确的 CLI flag。

bug:probe_or_spawn 拉起 argosd 时传 `--socket`,但 daemon argparse(argos/daemon/__main__.py)只认
`--socket-path` → argosd 因未知 flag argparse rc=2 立即退出 → TUI 永远落 inline fallback(打脸
README/CLAUDE 的 "daemon is the default / always-on")。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from argos.tui import daemon_spawn


@pytest.mark.asyncio
async def test_spawn_uses_socket_path_flag(monkeypatch, tmp_path: Path):
    captured: dict = {}

    class _FakeProc:
        returncode = None   # 不提前退出 → 走轮询到超时

    async def fake_exec(*args, **kwargs):
        captured["args"] = args
        return _FakeProc()

    async def fake_probe(_p):
        return False        # probe 恒失败 → 触发 spawn,且 spawn 后轮询超时返 False

    monkeypatch.setattr(daemon_spawn.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(daemon_spawn, "_probe", fake_probe)
    monkeypatch.setattr(daemon_spawn, "_SPAWN_TIMEOUT", 0.03)
    monkeypatch.setattr(daemon_spawn, "_WAIT_POLL", 0.01)

    await daemon_spawn.probe_or_spawn(tmp_path / "d.sock")

    args = captured.get("args", ())
    assert "argosd" in args
    assert "--socket-path" in args, f"daemon 只认 --socket-path,实际传了 {args}"
    assert "--socket" not in args, f"旧的坏 flag --socket 仍在:{args}"
