"""Internal documentation."""
from __future__ import annotations

from pathlib import Path

import pytest

from argos.tui import daemon_spawn


@pytest.mark.asyncio
async def test_spawn_uses_socket_path_flag(monkeypatch, tmp_path: Path):
    captured: dict = {}

    class _FakeProc:
        returncode = None

    async def fake_exec(*args, **kwargs):
        captured["args"] = args
        return _FakeProc()

    async def fake_probe(_p):
        return False

    monkeypatch.setattr(daemon_spawn.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(daemon_spawn, "_probe", fake_probe)
    monkeypatch.setattr(daemon_spawn, "_SPAWN_TIMEOUT", 0.03)
    monkeypatch.setattr(daemon_spawn, "_WAIT_POLL", 0.01)

    await daemon_spawn.probe_or_spawn(tmp_path / "d.sock")

    args = captured.get("args", ())
    assert "argosd" in args
    assert "--socket-path" in args, f"daemon 只认 --socket-path,实际传了 {args}"
    assert "--socket" not in args, f"旧的坏 flag --socket 仍在:{args}"
    assert "--pid-path" in args, f"TUI spawn 必须传 pid path,否则 stale cleanup 会读错 pid 文件:{args}"
    assert str(tmp_path / "daemon.pid") in args
