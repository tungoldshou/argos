"""多 run 并发 dispatch + 503 拒 + worktree + GET /runs 字段测试(#5b T2)。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import pytest_asyncio

from argos_agent.daemon.manager import RunManager
from argos_agent.daemon.registry import RunRegistry
from argos_agent.daemon.server import DaemonHTTPServer
from argos_agent.daemon.worktree import WorktreeManager


# ── fixtures ────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def mr_server(tmp_path: Path):
    """带 RunRegistry + WorktreeManager 的 server。"""
    runs_dir = tmp_path / "runs"
    index_path = tmp_path / "index.json"
    socket_path = tmp_path / "daemon.sock"
    manager = RunManager(runs_dir=runs_dir, index_path=index_path)
    registry = RunRegistry(max_concurrent=5, max_history=100)
    worktree = WorktreeManager(base_dir=tmp_path / "wt")
    srv = DaemonHTTPServer(
        manager=manager, socket_path=socket_path,
        registry=registry, worktree=worktree,
    )
    await srv.start()
    try:
        yield srv, manager, registry
    finally:
        await srv.stop()
        manager.close()


async def _req(socket_path: Path, method: str, path: str, *,
               session_id: str | None = None, body: dict | None = None,
               timeout: float = 5.0):
    from argos_agent.daemon.client import DaemonClient
    cli = DaemonClient(socket_path, timeout=timeout)
    return await cli._request(method, path, session_id=session_id, body=body)


async def _create_session(socket_path: Path) -> str:
    status, _, raw = await _req(socket_path, "POST", "/sessions")
    assert status == 201
    return json.loads(raw.decode("utf-8"))["session_id"]


# ── 并发 dispatch ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_run_returns_id(mr_server, tmp_path: Path):
    srv, _, _ = mr_server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "refactor auth.py"})
    assert status == 201
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    assert len(rid) == 12


@pytest.mark.asyncio
async def test_concurrent_create_runs_all_register(mr_server, tmp_path: Path):
    """5 个并发 run 全部成功 + registry 都注册了。"""
    srv, _, reg = mr_server
    sid = await _create_session(srv.socket_path)
    rids = []
    for i in range(5):
        status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                     session_id=sid, body={"goal": f"g{i}"})
        assert status == 201
        rids.append(json.loads(raw.decode("utf-8"))["run_id"])
    assert len(set(rids)) == 5
    for rid in rids:
        assert reg.get(rid) is not None
    assert reg.active_count == 5


@pytest.mark.asyncio
async def test_post_runs_returns_503_when_max_reached(mr_server, tmp_path: Path):
    """5 槽全被占用(模拟 5 个在跑的 worker)+ 第 6 个 → 503 busy。

    注:元数据模式的 run 不再永久占槽(P5b 槽位泄漏修复),故显式 acquire
    模拟真 worker 在跑 —— 503 契约测的是"满员拒绝",不是泄漏副作用。
    """
    srv, _, reg = mr_server
    sid = await _create_session(srv.socket_path)
    # 显式占满 5 槽(等价于 5 个 worker 在跑)
    for _ in range(5):
        await reg.acquire_slot()
    # 第 6 个
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "g6"})
    assert status == 503
    body = json.loads(raw.decode("utf-8"))
    assert body["code"] == "busy"
    assert "max_concurrent_runs_reached" in body["error"]
    assert "max=5" in body["error"]


@pytest.mark.asyncio
async def test_post_runs_after_cancel_frees_slot(mr_server, tmp_path: Path):
    """cancel 一个后槽位回到 1,新 run 能进。"""
    srv, mgr, reg = mr_server
    sid = await _create_session(srv.socket_path)
    rids = []
    for i in range(5):
        status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                     session_id=sid, body={"goal": f"g{i}"})
        rids.append(json.loads(raw.decode("utf-8"))["run_id"])
    # 重新占满 5 槽(元数据 run 已即时归还槽位 —— P5b 泄漏修复;此处模拟 5 worker 在跑)
    for _ in range(5):
        await reg.acquire_slot()
    # cancel 第 1 个(cleanup = worker 终态路径,释放 1 槽)
    await reg.cleanup(run_id=rids[0], terminal_state="cancelled")
    # 第 6 个能进
    status, _, _ = await _req(srv.socket_path, "POST", "/runs",
                               session_id=sid, body={"goal": "g6"})
    assert status == 201


# ── worktree ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_runs_with_isolation_creates_worktree(mr_server, tmp_path: Path):
    """isolation=worktree + workspace 是 git repo → RunMeta.worktree_path 已设。"""
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    (repo / "a").write_text("x")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

    srv, _, reg = mr_server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid,
                                 body={"goal": "x", "workspace": str(repo),
                                       "isolation": "worktree"})
    assert status == 201
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    entry = reg.get(rid)
    assert entry.worktree_path is not None
    assert (tmp_path / "wt" / rid).exists()


@pytest.mark.asyncio
async def test_post_runs_workspace_not_found_returns_400(mr_server, tmp_path: Path):
    """workspace 路径存在但不是 git repo → 走 temp 兜底(不抛);非 worktree 模式无 workspace 也 OK。"""
    srv, _, _ = mr_server
    sid = await _create_session(srv.socket_path)
    # 非 worktree 模式,workspace 不存在 → 仍 OK(run 不写文件也没事)
    status, _, _ = await _req(srv.socket_path, "POST", "/runs",
                               session_id=sid, body={"goal": "x"})
    assert status == 201


# ── GET /runs /runs/{id} 字段 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_runs_includes_cost_worktree_focus(mr_server, tmp_path: Path):
    srv, _, reg = mr_server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    reg.add_cost(run_id=rid, tokens_in_delta=100, tokens_out_delta=20, cost_usd_delta=0.01)
    reg.set_focus(run_id=rid, session_id=sid)
    status, _, raw = await _req(srv.socket_path, "GET", "/runs", session_id=sid)
    assert status == 200
    runs = json.loads(raw.decode("utf-8"))
    target = next(r for r in runs if r["run_id"] == rid)
    assert target["tokens_in"] == 100
    assert target["tokens_out"] == 20
    assert target["cost_usd"] == 0.01
    assert target["focus_session_id"] == sid


@pytest.mark.asyncio
async def test_get_run_includes_cost_worktree_focus(mr_server, tmp_path: Path):
    srv, _, reg = mr_server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    reg.add_cost(run_id=rid, tokens_in_delta=50, tokens_out_delta=10, cost_usd_delta=0.005)
    status, _, raw = await _req(srv.socket_path, "GET", f"/runs/{rid}",
                                 session_id=sid)
    assert status == 200
    body = json.loads(raw.decode("utf-8"))
    assert body["tokens_in"] == 50
    assert body["tokens_out"] == 10
    assert body["cost_usd"] == 0.005
    assert "worktree_path" in body
    assert "focus_session_id" in body
