"""P3b §6 端到端验收:真实 DaemonHTTPServer + 注入 ledger_store/snapshot。

覆盖 P3b 审查 major 问题:
  - GET /runs/{id}/ledger 对真实 server 返回条目列表(非空列表)
  - POST /runs/{id}/undo 对真实 server 还原 workspace 文件(铁证:read_text()==original)
  - _handle_undo 诚实三态:无账本→409、无快照→409、已撤销→409
  - owner-gate:observer session 尝试 undo → 403

设计:直构 DaemonHTTPServer(不走 loop_factory/components),
注入 ledger_store=LedgerStore + snapshot=RunSnapshot,手工写入 LedgerEntry,
再通过 HTTP 协议调 /undo 断言文件内容、HTTP 状态码。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio

from argos.core.snapshot import RunSnapshot
from argos.daemon.manager import RunManager
from argos.daemon.server import DaemonHTTPServer
from argos.ledger.builder import build_entry
from argos.ledger.store import LedgerStore


# ── 内部 HTTP helper(复用 test_daemon_server.py 风格)──────────────────────

async def _req(
    socket_path: Path, method: str, path: str, *,
    session_id: str | None = None,
    body: dict | None = None,
    timeout: float = 5.0,
):
    """发 HTTP 请求,返 (status, headers, body_bytes)。"""
    from argos.daemon.client import DaemonClient
    cli = DaemonClient(socket_path, timeout=timeout)
    return await cli._request(method, path, session_id=session_id, body=body)


async def _create_session(socket_path: Path) -> str:
    """建 session,首个自动成为 owner。"""
    status, _, raw = await _req(socket_path, "POST", "/sessions")
    assert status == 201
    return json.loads(raw.decode())["session_id"]


async def _create_run(socket_path: Path, sid: str, workspace: str) -> str:
    status, _, raw = await _req(
        socket_path, "POST", "/runs",
        session_id=sid, body={"goal": "test run", "workspace": workspace},
    )
    assert status == 201
    return json.loads(raw.decode())["run_id"]


# ── fixture:带 ledger_store 的真实 server ──────────────────────────────────

@pytest_asyncio.fixture
async def ledger_server(tmp_path: Path):
    """起真实 DaemonHTTPServer,注入 ledger_store;不注入 loop_factory(run 只建元数据)。"""
    runs_dir = tmp_path / "runs"
    socket_path = tmp_path / "daemon.sock"
    manager = RunManager(runs_dir=runs_dir, index_path=tmp_path / "index.json")
    ledger_dir = tmp_path / "ledger"
    ledger_store = LedgerStore(ledger_dir)
    srv = DaemonHTTPServer(
        manager=manager,
        socket_path=socket_path,
        ledger_store=ledger_store,
    )
    await srv.start()
    try:
        yield srv, manager, ledger_store
    finally:
        await srv.stop()
        manager.close()


# ── GET /runs/{id}/ledger ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_ledger_returns_entries(tmp_path: Path, ledger_server):
    """GET /ledger 对真实 server 返回之前手工写入的 LedgerEntry 条目列表。"""
    srv, manager, ledger_store = ledger_server

    # 建 run
    sid = await _create_session(srv.socket_path)
    run_id = await _create_run(srv.socket_path, sid, str(tmp_path / "ws"))

    # 手工写入两条账本条目(模拟 worker._maybe_append_ledger 触发效果)
    class _FakeReceipt:
        def __init__(self, action: str) -> None:
            self.action = action
            self.ts = 1000.0
            self.sig = "deadsig0deadsig0"

    e1 = build_entry(receipt=_FakeReceipt("write_file"), run_id=run_id, seq=1)
    e2 = build_entry(receipt=_FakeReceipt("web_fetch"), run_id=run_id, seq=2)
    ledger_store.append(e1)
    ledger_store.append(e2)

    # GET /runs/{id}/ledger
    status, _, raw = await _req(srv.socket_path, "GET", f"/runs/{run_id}/ledger",
                                  session_id=sid)
    assert status == 200
    body = json.loads(raw.decode())
    assert body["run_id"] == run_id
    entries = body["entries"]
    assert len(entries) == 2, f"期望 2 条账本条目,实际 {len(entries)}"
    actions = {e["action"] for e in entries}
    assert "write_file" in actions
    assert "web_fetch" in actions


@pytest.mark.asyncio
async def test_get_ledger_no_ledger_store_returns_empty(tmp_path: Path):
    """无 ledger_store 注入时 GET /ledger 返 200 空列表(向后兼容)。"""
    runs_dir = tmp_path / "runs"
    socket_path = tmp_path / "d.sock"
    manager = RunManager(runs_dir=runs_dir, index_path=tmp_path / "i.json")
    srv = DaemonHTTPServer(manager=manager, socket_path=socket_path)  # 不注入 ledger_store
    await srv.start()
    try:
        sid = await _create_session(socket_path)
        run_id = await _create_run(socket_path, sid, "")
        status, _, raw = await _req(socket_path, "GET", f"/runs/{run_id}/ledger",
                                     session_id=sid)
        assert status == 200
        body = json.loads(raw.decode())
        assert body["entries"] == []
    finally:
        await srv.stop()
        manager.close()


# ── POST /runs/{id}/undo — 铁证:文件内容回原样 ───────────────────────────────

@pytest.mark.asyncio
async def test_undo_restores_workspace_file(tmp_path: Path, ledger_server):
    """端到端铁证:POST /undo 后 workspace 文件内容 == original。"""
    srv, manager, ledger_store = ledger_server

    # 准备 workspace + 原始文件
    ws = tmp_path / "ws"
    ws.mkdir()
    original = "original content\n"
    (ws / "report.md").write_text(original)

    # 拍 run 起点快照
    snap_path = tmp_path / "snap.tar"
    snapshot = RunSnapshot.take(ws, snap_path)

    # 建 run(手工绑定 workspace)
    sid = await _create_session(srv.socket_path)
    run_id = await _create_run(srv.socket_path, sid, str(ws))

    # "agent 修改了文件"
    (ws / "report.md").write_text("modified by agent\n")

    # 手工写入 ledger 条目(含 undo_token 指向快照)
    class _FakeReceipt:
        def __init__(self) -> None:
            self.action = "write_file"
            self.ts = 1000.0
            self.sig = "deadsig0deadsig0"

    entry = build_entry(
        receipt=_FakeReceipt(),
        run_id=run_id,
        seq=1,
        args={"path": str(ws / "report.md")},
        undo_token=str(snap_path),
    )
    ledger_store.append(entry)

    # POST /undo
    status, _, raw = await _req(srv.socket_path, "POST", f"/runs/{run_id}/undo",
                                  session_id=sid, body={})
    assert status == 200, f"undo 应返 200,实际 {status}: {raw.decode()}"
    body = json.loads(raw.decode())
    assert body["state"] in ("done", "partial"), f"undo state 异常: {body}"

    # 铁证:文件内容回原样
    assert (ws / "report.md").read_text() == original, "undo 后文件内容必须等于 original"

    # ledger 已标记 undo_done
    assert ledger_store.is_undo_done(run_id)


# ── POST /runs/{id}/undo — 诚实三态 ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_undo_nothing_to_undo_when_no_ledger(tmp_path: Path):
    """无 ledger_store 时 POST /undo → 409 nothing_to_undo。"""
    runs_dir = tmp_path / "runs"
    socket_path = tmp_path / "d2.sock"
    manager = RunManager(runs_dir=runs_dir, index_path=tmp_path / "i2.json")
    srv = DaemonHTTPServer(manager=manager, socket_path=socket_path)
    await srv.start()
    try:
        sid = await _create_session(socket_path)
        run_id = await _create_run(socket_path, sid, "")
        status, _, raw = await _req(socket_path, "POST", f"/runs/{run_id}/undo",
                                     session_id=sid, body={})
        assert status == 409
        body = json.loads(raw.decode())
        assert body["code"] == "nothing_to_undo"
    finally:
        await srv.stop()
        manager.close()


@pytest.mark.asyncio
async def test_undo_no_snapshot_returns_409(tmp_path: Path, ledger_server):
    """有 reversible=yes 账本条目,但快照文件路径不存在 → 409 no_snapshot。

    write_file + undo_token 指向不存在路径 → reversible=yes(build_entry 只看 token 非空)
    → available 列表非空 → 走进快照路径检查 → 快照文件不存在 → 409 no_snapshot。
    """
    srv, manager, ledger_store = ledger_server

    ws = tmp_path / "ws2"
    ws.mkdir()
    sid = await _create_session(srv.socket_path)
    run_id = await _create_run(srv.socket_path, sid, str(ws))

    # undo_token 指向一个不存在的快照路径,确保 reversible=yes(build_entry 只检查非空)
    nonexistent_snap = str(tmp_path / "nonexistent_snap.tar")

    class _FakeReceipt:
        def __init__(self) -> None:
            self.action = "write_file"
            self.ts = 1000.0
            self.sig = "deadsig0deadsig0"

    entry = build_entry(
        receipt=_FakeReceipt(), run_id=run_id, seq=1, undo_token=nonexistent_snap,
    )
    assert entry.reversible == "yes", "undo_token 非空时 write_file 应 reversible=yes"
    ledger_store.append(entry)

    status, _, raw = await _req(srv.socket_path, "POST", f"/runs/{run_id}/undo",
                                  session_id=sid, body={})
    assert status == 409
    body = json.loads(raw.decode())
    assert body["code"] == "no_snapshot"


@pytest.mark.asyncio
async def test_undo_already_undone_returns_409(tmp_path: Path, ledger_server):
    """已执行 undo_complete 后再 POST /undo → 409 already_undone。"""
    srv, manager, ledger_store = ledger_server

    ws = tmp_path / "ws3"
    ws.mkdir()
    (ws / "f.txt").write_text("v1")
    snap_path = tmp_path / "snap3.tar"
    RunSnapshot.take(ws, snap_path)

    sid = await _create_session(srv.socket_path)
    run_id = await _create_run(srv.socket_path, sid, str(ws))

    class _FakeReceipt:
        def __init__(self) -> None:
            self.action = "write_file"
            self.ts = 1000.0
            self.sig = "deadsig0deadsig0"

    entry = build_entry(
        receipt=_FakeReceipt(), run_id=run_id, seq=1, undo_token=str(snap_path),
    )
    ledger_store.append(entry)
    ledger_store.undo_complete(run_id)  # 提前标记 done

    status, _, raw = await _req(srv.socket_path, "POST", f"/runs/{run_id}/undo",
                                  session_id=sid, body={})
    assert status == 409
    body = json.loads(raw.decode())
    assert body["code"] == "already_undone"


# ── owner-gate:observer 不能 undo ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_undo_requires_owner(tmp_path: Path, ledger_server):
    """observer session 尝试 POST /undo → 403 session_readonly。"""
    srv, manager, ledger_store = ledger_server

    ws = tmp_path / "ws4"
    ws.mkdir()
    sid = await _create_session(srv.socket_path)
    run_id = await _create_run(srv.socket_path, sid, str(ws))

    # 创第二个 session → observer
    observer_sid = await _create_session(srv.socket_path)

    status, _, raw = await _req(srv.socket_path, "POST", f"/runs/{run_id}/undo",
                                  session_id=observer_sid, body={})
    assert status == 403
    body = json.loads(raw.decode())
    assert body["code"] == "session_readonly"


# ── Minor-1：纯 file: 条目 run 的 SNAPSHOT_ROOT fallback ─────────────────────

@pytest.mark.asyncio
async def test_undo_file_only_run_finds_snapshot_via_snapshot_root(
    tmp_path: Path, ledger_server
):
    """Minor-1 修正：纯文件编辑 run（账本条目全是 file: 前缀）在 SNAPSHOT_ROOT 存在快照时
    应 fallback 到约定路径 run-{run_id}.tar，而不是直接返回 no_snapshot。

    步骤：
      1. 构造一条 undo_token="file:/path/to/file" 的账本条目（纯文件条目，无 run 级 token）。
      2. 在 SNAPSHOT_ROOT 放一个合法快照 run-{run_id}.tar。
      3. POST /undo → 应还原成功（200），而非 409 no_snapshot。
    """
    from argos.core.snapshot import SNAPSHOT_ROOT
    import tarfile

    srv, manager, ledger_store = ledger_server

    ws = tmp_path / "ws_file_only"
    ws.mkdir()
    target_file = ws / "output.txt"
    target_file.write_text("original content")

    sid = await _create_session(srv.socket_path)
    run_id = await _create_run(srv.socket_path, sid, str(ws))

    # 在 SNAPSHOT_ROOT 放约定路径快照（修法里的 fallback 路径）
    SNAPSHOT_ROOT.mkdir(parents=True, exist_ok=True)
    snap_path = SNAPSHOT_ROOT / f"run-{run_id}.tar"
    # 手工建 tar 含 output.txt（RunSnapshot 格式：相对路径）
    with tarfile.open(snap_path, "w") as tf:
        tf.add(target_file, arcname="output.txt")

    # 账本条目：undo_token 是 "file:" 前缀（纯文件条目，无 run 级 token）
    class _FakeReceipt:
        def __init__(self) -> None:
            self.action = "write_file"
            self.ts = 1000.0
            self.sig = "deadsig0deadsig0"

    entry = build_entry(
        receipt=_FakeReceipt(),
        run_id=run_id,
        seq=1,
        undo_token=f"file:{str(target_file)}",
    )
    assert entry.undo_token is not None
    assert entry.undo_token.startswith("file:")
    ledger_store.append(entry)

    # 修改文件内容（模拟 agent 改动）
    target_file.write_text("modified by agent")

    try:
        # POST /undo → 应走 SNAPSHOT_ROOT fallback，还原文件
        status, _, raw = await _req(
            srv.socket_path, "POST", f"/runs/{run_id}/undo",
            session_id=sid, body={},
        )
        body = json.loads(raw.decode())
        # 应 200（找到 fallback 快照），不应 409 no_snapshot
        assert status == 200, (
            f"纯 file: 条目 run 应 fallback 到 SNAPSHOT_ROOT 快照，期望 200，"
            f"实际 {status}: {body}"
        )
        assert body.get("state") in ("done", "partial"), f"undo state 异常: {body}"
    finally:
        # 清理约定路径快照，避免污染其他测试
        if snap_path.exists():
            snap_path.unlink()


@pytest.mark.asyncio
async def test_undo_file_only_run_no_snapshot_root_still_returns_no_snapshot(
    tmp_path: Path, ledger_server
):
    """Minor-1 回归：纯 file: 条目 run，SNAPSHOT_ROOT 也没有对应快照 → 仍 409 no_snapshot。"""
    from argos.core.snapshot import SNAPSHOT_ROOT

    srv, manager, ledger_store = ledger_server

    ws = tmp_path / "ws_no_snap"
    ws.mkdir()
    target_file = ws / "data.txt"
    target_file.write_text("content")

    sid = await _create_session(srv.socket_path)
    run_id = await _create_run(srv.socket_path, sid, str(ws))

    # 确保 SNAPSHOT_ROOT 里没有此 run 的快照
    candidate = SNAPSHOT_ROOT / f"run-{run_id}.tar"
    if candidate.exists():
        candidate.unlink()

    class _FakeReceipt:
        def __init__(self) -> None:
            self.action = "write_file"
            self.ts = 1000.0
            self.sig = "deadsig0deadsig0"

    entry = build_entry(
        receipt=_FakeReceipt(),
        run_id=run_id,
        seq=1,
        undo_token=f"file:{str(target_file)}",
    )
    ledger_store.append(entry)

    status, _, raw = await _req(
        srv.socket_path, "POST", f"/runs/{run_id}/undo",
        session_id=sid, body={},
    )
    body = json.loads(raw.decode())
    assert status == 409, f"无快照时应 409，实际 {status}: {body}"
    assert body["code"] == "no_snapshot"
