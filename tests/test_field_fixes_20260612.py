"""Internal documentation."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from argos.__main__ import resolve_workspace



class TestResolveWorkspace:
    def test_explicit_project_wins(self):
        assert resolve_workspace("/tmp/myproj") == "/tmp/myproj"

    def test_default_is_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert resolve_workspace(None) == str(tmp_path.resolve())

    def test_home_dir_falls_back_to_none(self, monkeypatch):
        """Internal documentation."""
        monkeypatch.chdir(Path.home())
        assert resolve_workspace(None) is None

    def test_fs_root_falls_back_to_none(self, monkeypatch):
        monkeypatch.chdir("/")
        assert resolve_workspace(None) is None



@pytest.mark.asyncio
async def test_sse_chinese_no_mojibake(tmp_path):
    """Internal documentation."""
    from argos.daemon.manager import RunManager
    from argos.daemon.server import DaemonHTTPServer
    from argos.daemon.client import DaemonClient

    socket_path = tmp_path / "d.sock"
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    srv = DaemonHTTPServer(manager=mgr, socket_path=socket_path)
    await srv.start()
    try:
        cli = DaemonClient(socket_path)
        _sid_raw = await cli.create_session()
        sid = _sid_raw["session_id"] if isinstance(_sid_raw, dict) else _sid_raw
        rid = await mgr.create_run(goal="中文目标:整理会议记录", workspace=str(tmp_path))
        zh = "查看当前目录内容:会议记录已整理到 meetings 子文件夹 ✓"
        mgr.store.append(rid, {"kind": "token_delta", "text": zh, "_seq": 1})

        got: dict | None = None
        async for ev in cli.subscribe_events(rid, sid, since=0):
            if ev.get("kind") == "token_delta":
                got = ev
                break
        assert got is not None, "应收到 token_delta 事件"
        assert got["text"] == zh, f"中文 mojibake 回归: {got['text']!r}"
        assert "å" not in got["text"]
    finally:
        await srv.stop()



@pytest.mark.asyncio
async def test_observer_promoted_after_owner_expiry_on_next_request(tmp_path):
    """Internal documentation."""
    import asyncio
    from argos.daemon.manager import RunManager
    from argos.daemon.server import DaemonHTTPServer
    from argos.daemon.client import DaemonClient

    socket_path = tmp_path / "d.sock"
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    srv = DaemonHTTPServer(manager=mgr, socket_path=socket_path,
                           session_timeout_s=0.2)
    await srv.start()
    try:
        cli = DaemonClient(socket_path)
        _o = await cli.create_session()
        owner_sid = _o["session_id"] if isinstance(_o, dict) else _o
        _n = await cli.create_session()
        obs_sid = _n["session_id"] if isinstance(_n, dict) else _n
        assert srv.sessions.get(obs_sid).role == "observer"
        await asyncio.sleep(0.15)
        await cli.heartbeat(obs_sid)
        await asyncio.sleep(0.15)
        status, _, raw = await cli._request(
            "POST", "/runs", session_id=obs_sid,
            body={"goal": "promotion probe", "workspace": str(tmp_path)},
        )
        assert status == 201, f"observer 未被晋升,仍 {status}: {raw.decode()[:120]}"
        assert srv.sessions.get(obs_sid).role == "owner"
    finally:
        await srv.stop()
