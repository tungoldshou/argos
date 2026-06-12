"""实测修复回归钉(2026-06-12 真实场景试驾发现的两条 bug)。

bug 1:TUI 不传 --project 时 workspace 落默认目录,agent 在错误目录干活
       (用户在 ~/argos-field-test 启动,任务却跑在 ~/.argos/workspace)。
bug 2:daemon SSE 数据体 UTF-8 被客户端按 latin-1 解码,中文全 mojibake
       ("当前目录" → "å½åç®å½")。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from argos_agent.__main__ import resolve_workspace


# ── bug 1:workspace 默认 cwd ────────────────────────────────────────────────

class TestResolveWorkspace:
    def test_explicit_project_wins(self):
        assert resolve_workspace("/tmp/myproj") == "/tmp/myproj"

    def test_default_is_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert resolve_workspace(None) == str(tmp_path.resolve())

    def test_home_dir_falls_back_to_none(self, monkeypatch):
        """cwd=家目录 → 不默认(危险面护栏),走旧默认 workspace。"""
        monkeypatch.chdir(Path.home())
        assert resolve_workspace(None) is None

    def test_fs_root_falls_back_to_none(self, monkeypatch):
        monkeypatch.chdir("/")
        assert resolve_workspace(None) is None


# ── bug 2:SSE 中文 round-trip 无 mojibake ──────────────────────────────────

@pytest.mark.asyncio
async def test_sse_chinese_no_mojibake(tmp_path):
    """中文事件经 server SSE → DaemonClient.subscribe_events 解析后逐字符一致。"""
    from argos_agent.daemon.manager import RunManager
    from argos_agent.daemon.server import DaemonHTTPServer
    from argos_agent.daemon.client import DaemonClient

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
        assert "å" not in got["text"]  # latin-1 错解的特征字符
    finally:
        await srv.stop()


# ── bug 3:reap_expired 零调用 → 重启 TUI 永久 403(空壳病第四例) ─────────────

@pytest.mark.asyncio
async def test_observer_promoted_after_owner_expiry_on_next_request(tmp_path):
    """owner 过期后,observer 的下一个写请求应当场晋升通过(按需 reap)。

    修复前:reap_expired 全仓零调用,owner 永不过期 → 重启 TUI 的新 session
    永远 observer,create_run 永久 403 session_readonly。
    """
    import asyncio
    from argos_agent.daemon.manager import RunManager
    from argos_agent.daemon.server import DaemonHTTPServer
    from argos_agent.daemon.client import DaemonClient

    socket_path = tmp_path / "d.sock"
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    srv = DaemonHTTPServer(manager=mgr, socket_path=socket_path,
                           session_timeout_s=0.2)   # 快速过期便于测试
    await srv.start()
    try:
        cli = DaemonClient(socket_path)
        _o = await cli.create_session()
        owner_sid = _o["session_id"] if isinstance(_o, dict) else _o
        _n = await cli.create_session()
        obs_sid = _n["session_id"] if isinstance(_n, dict) else _n
        assert srv.sessions.get(obs_sid).role == "observer"
        # owner 心跳停止;observer 中途续命一次 —— 时间线:
        # t=0 两 session 建立 → t=0.15 observer heartbeat(续到 0.35)
        # → t=0.3 owner 已过期(0.3>0.2),observer 仍活(0.3<0.35)
        await asyncio.sleep(0.15)
        await cli.heartbeat(obs_sid)
        await asyncio.sleep(0.15)
        # observer 发写请求:按需 reap 把 owner 回收+晋升 observer → 201 而非 403
        status, _, raw = await cli._request(
            "POST", "/runs", session_id=obs_sid,
            body={"goal": "promotion probe", "workspace": str(tmp_path)},
        )
        assert status == 201, f"observer 未被晋升,仍 {status}: {raw.decode()[:120]}"
        assert srv.sessions.get(obs_sid).role == "owner"
    finally:
        await srv.stop()
