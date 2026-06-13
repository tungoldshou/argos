"""A3 条目级 undo 端到端验收测试。

覆盖:
  POST /runs/{id}/undo body={"entry_seq": N}
    - 文件还原铁证(修改文件 → entry undo → 逐字节回原样)
    - 其他文件不动
    - 新建文件 undo = 删除(文案断言)
    - 四分诚实:entry_not_found / not_file_entry / not_reversible / already_undone / no_snapshot
    - 条目 done 后再 undo → 409 already_undone
    - run 级路径回归不破(无 entry_seq 仍走 run 级快照还原)
  FileDiff 事件 → 账本条目:
    - worker 处理 file_diff 事件后落入账本,含正确 undo_token / reversible / summary
    - _seq 单调递增不撞号
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio

from argos.core.snapshot import RunSnapshot
from argos.daemon.manager import RunManager
from argos.daemon.server import DaemonHTTPServer
from argos.daemon.worker import RunWorker
from argos.ledger.builder import build_entry
from argos.ledger.entry import LedgerEntry
from argos.ledger.store import LedgerStore


# ── HTTP helpers ──────────────────────────────────────────────────────────────

async def _req(socket_path, method, path, *, session_id=None, body=None, timeout=5.0):
    from argos.daemon.client import DaemonClient
    cli = DaemonClient(socket_path, timeout=timeout)
    return await cli._request(method, path, session_id=session_id, body=body)


async def _create_session(socket_path) -> str:
    status, _, raw = await _req(socket_path, "POST", "/sessions")
    assert status == 201
    return json.loads(raw.decode())["session_id"]


async def _create_run(socket_path, sid, workspace="") -> str:
    status, _, raw = await _req(
        socket_path, "POST", "/runs",
        session_id=sid, body={"goal": "test", "workspace": workspace},
    )
    assert status == 201
    return json.loads(raw.decode())["run_id"]


# ── fixture ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def srv_env(tmp_path):
    """带 ledger_store 的真实 DaemonHTTPServer(无 loop_factory)。"""
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
        yield srv, manager, ledger_store, tmp_path
    finally:
        await srv.stop()
        manager.close()


# ── 辅助:写入文件粒度 LedgerEntry ──────────────────────────────────────────────

class _FakeReceipt:
    def __init__(self, action="file_diff"):
        self.action = action
        self.ts = time.time()
        self.sig = "dead" * 4


def _file_entry(run_id, seq, file_path, snap_path, undo_state="available") -> LedgerEntry:
    """构造一条带 file: 前缀 undo_token 的 LedgerEntry(文件粒度条目)。"""
    return LedgerEntry(
        ts=time.time(),
        run_id=run_id,
        seq=seq,
        action="file_diff",
        summary_human=f"修改了 {Path(file_path).name}(+3/-1)",
        risk="low",
        reversible="yes",
        undo_token=f"file:{file_path}",
        receipt_sig="",
        undo_state=undo_state,
    )


def _run_level_entry(run_id, seq, snap_path) -> LedgerEntry:
    """构造一条 run 级 undo_token 条目(供快照路径查找使用)。"""
    return LedgerEntry(
        ts=time.time(),
        run_id=run_id,
        seq=seq,
        action="write_file",
        summary_human="写入了 x.py",
        risk="low",
        reversible="yes",
        undo_token=str(snap_path),
        receipt_sig="",
        undo_state="available",
    )


# ── 铁证:文件还原 ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_file_undo_restores_file_byte_for_byte(srv_env):
    """铁证:条目级 undo → 文件内容逐字节回原样,其他文件不动。"""
    srv, manager, ledger_store, tmp_path = srv_env

    ws = tmp_path / "ws"
    ws.mkdir()
    original = "original content\n"
    other_original = "other file content\n"
    (ws / "report.md").write_text(original)
    (ws / "other.py").write_text(other_original)

    snap_path = tmp_path / "snap.tar"
    RunSnapshot.take(ws, snap_path)

    sid = await _create_session(srv.socket_path)
    run_id = await _create_run(srv.socket_path, sid, str(ws))

    # agent 修改文件
    (ws / "report.md").write_text("modified by agent\n")
    (ws / "other.py").write_text("also modified\n")

    # 写入两条账本条目:一条 run 级(供快照路径查找),一条文件粒度
    run_entry = _run_level_entry(run_id, 1, snap_path)
    file_entry = _file_entry(run_id, 2, str(ws / "report.md"), snap_path)
    ledger_store.append(run_entry)
    ledger_store.append(file_entry)

    # POST /undo with entry_seq=2
    status, _, raw = await _req(
        srv.socket_path, "POST", f"/runs/{run_id}/undo",
        session_id=sid, body={"entry_seq": 2},
    )
    assert status == 200, f"应返 200,实际 {status}: {raw.decode()}"
    body = json.loads(raw.decode())
    assert body["state"] == "done"
    assert body["entry_seq"] == 2
    assert not body.get("was_new_file")

    # 铁证:report.md 回原样
    assert (ws / "report.md").read_text() == original, "文件内容必须回原样"
    # 其他文件不动
    assert (ws / "other.py").read_text() == "also modified\n", "未指定文件不应被还原"

    # 账本条目 undo_state → done
    e = ledger_store.get_entry(run_id, 2)
    assert e is not None
    assert e.undo_state == "done"


@pytest.mark.asyncio
async def test_new_file_undo_deletes_file_with_honest_note(srv_env):
    """新建文件 undo = 删除;响应文案明说"此文件是任务中新建的"。"""
    srv, manager, ledger_store, tmp_path = srv_env

    ws = tmp_path / "ws"
    ws.mkdir()
    snap_path = tmp_path / "snap.tar"
    RunSnapshot.take(ws, snap_path)  # 空快照(新建文件不在其中)

    sid = await _create_session(srv.socket_path)
    run_id = await _create_run(srv.socket_path, sid, str(ws))

    # agent 新建了文件
    (ws / "new_file.py").write_text("new content")

    run_entry = _run_level_entry(run_id, 1, snap_path)
    file_entry = _file_entry(run_id, 2, str(ws / "new_file.py"), snap_path)
    ledger_store.append(run_entry)
    ledger_store.append(file_entry)

    status, _, raw = await _req(
        srv.socket_path, "POST", f"/runs/{run_id}/undo",
        session_id=sid, body={"entry_seq": 2},
    )
    assert status == 200, raw.decode()
    body = json.loads(raw.decode())
    assert body["state"] == "done"
    assert body["was_new_file"] is True
    # 文案必须说明"新建"语义
    assert "新建" in body["note"] or "删除" in body["note"]
    # 铁证:文件已被删除
    assert not (ws / "new_file.py").exists(), "新建文件 undo 后必须删除"


# ── 诚实四分(409 语义) ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_entry_not_found_returns_409(srv_env):
    """entry_seq 不存在 → 409 entry_not_found。"""
    srv, manager, ledger_store, tmp_path = srv_env

    ws = tmp_path / "ws"
    ws.mkdir()
    sid = await _create_session(srv.socket_path)
    run_id = await _create_run(srv.socket_path, sid, str(ws))

    status, _, raw = await _req(
        srv.socket_path, "POST", f"/runs/{run_id}/undo",
        session_id=sid, body={"entry_seq": 999},
    )
    assert status == 409
    body = json.loads(raw.decode())
    assert body["code"] == "entry_not_found"


@pytest.mark.asyncio
async def test_not_file_entry_returns_409(srv_env):
    """undo_token 不含 file: 前缀的条目 → 409 not_file_entry。"""
    srv, manager, ledger_store, tmp_path = srv_env

    ws = tmp_path / "ws"
    ws.mkdir()
    snap_path = tmp_path / "snap.tar"
    RunSnapshot.take(ws, snap_path)

    sid = await _create_session(srv.socket_path)
    run_id = await _create_run(srv.socket_path, sid, str(ws))

    # run 级条目(undo_token 无 file: 前缀)
    run_entry = _run_level_entry(run_id, 1, snap_path)
    ledger_store.append(run_entry)

    status, _, raw = await _req(
        srv.socket_path, "POST", f"/runs/{run_id}/undo",
        session_id=sid, body={"entry_seq": 1},
    )
    assert status == 409
    body = json.loads(raw.decode())
    assert body["code"] == "not_file_entry"


@pytest.mark.asyncio
async def test_not_reversible_returns_409(srv_env):
    """reversible != yes 的条目 → 409 not_reversible。"""
    srv, manager, ledger_store, tmp_path = srv_env

    ws = tmp_path / "ws"
    ws.mkdir()
    sid = await _create_session(srv.socket_path)
    run_id = await _create_run(srv.socket_path, sid, str(ws))

    # 不可逆条目(web_fetch)
    irreversible = LedgerEntry(
        ts=time.time(), run_id=run_id, seq=1, action="web_fetch",
        summary_human="发出了请求", risk="high",
        reversible="no", undo_token="file:/some/path",
        receipt_sig="", undo_state="impossible",
    )
    ledger_store.append(irreversible)

    status, _, raw = await _req(
        srv.socket_path, "POST", f"/runs/{run_id}/undo",
        session_id=sid, body={"entry_seq": 1},
    )
    assert status == 409
    body = json.loads(raw.decode())
    assert body["code"] == "not_reversible"


@pytest.mark.asyncio
async def test_already_undone_entry_returns_409(srv_env):
    """undo_state=done 的条目再 undo → 409 already_undone。"""
    srv, manager, ledger_store, tmp_path = srv_env

    ws = tmp_path / "ws"
    ws.mkdir()
    snap_path = tmp_path / "snap.tar"
    RunSnapshot.take(ws, snap_path)

    sid = await _create_session(srv.socket_path)
    run_id = await _create_run(srv.socket_path, sid, str(ws))

    run_entry = _run_level_entry(run_id, 1, snap_path)
    # 已经是 done 状态的文件条目
    done_entry = LedgerEntry(
        ts=time.time(), run_id=run_id, seq=2, action="file_diff",
        summary_human="修改了 foo.py", risk="low",
        reversible="yes", undo_token=f"file:{ws}/foo.py",
        receipt_sig="", undo_state="done",
    )
    ledger_store.append(run_entry)
    ledger_store.append(done_entry)

    status, _, raw = await _req(
        srv.socket_path, "POST", f"/runs/{run_id}/undo",
        session_id=sid, body={"entry_seq": 2},
    )
    assert status == 409
    body = json.loads(raw.decode())
    assert body["code"] == "already_undone"


@pytest.mark.asyncio
async def test_no_snapshot_returns_409_for_file_undo(srv_env):
    """有文件粒度条目但快照不存在 → 409 no_snapshot。"""
    srv, manager, ledger_store, tmp_path = srv_env

    ws = tmp_path / "ws"
    ws.mkdir()
    sid = await _create_session(srv.socket_path)
    run_id = await _create_run(srv.socket_path, sid, str(ws))

    # run 级条目指向不存在的快照
    nonexistent_snap = tmp_path / "ghost.tar"
    run_entry = LedgerEntry(
        ts=time.time(), run_id=run_id, seq=1, action="write_file",
        summary_human="写入了 x.py", risk="low",
        reversible="yes", undo_token=str(nonexistent_snap),
        receipt_sig="", undo_state="available",
    )
    file_entry = _file_entry(run_id, 2, str(ws / "foo.py"), nonexistent_snap)
    ledger_store.append(run_entry)
    ledger_store.append(file_entry)

    status, _, raw = await _req(
        srv.socket_path, "POST", f"/runs/{run_id}/undo",
        session_id=sid, body={"entry_seq": 2},
    )
    assert status == 409
    body = json.loads(raw.decode())
    assert body["code"] == "no_snapshot"


# ── run 级回归:无 entry_seq 仍走 run 级路径 ──────────────────────────────────

@pytest.mark.asyncio
async def test_run_level_undo_still_works_without_entry_seq(srv_env):
    """不传 entry_seq → 既有 run 级还原行为不变。"""
    srv, manager, ledger_store, tmp_path = srv_env

    ws = tmp_path / "ws"
    ws.mkdir()
    original = "run level original\n"
    (ws / "r.txt").write_text(original)

    snap_path = tmp_path / "snap.tar"
    RunSnapshot.take(ws, snap_path)

    sid = await _create_session(srv.socket_path)
    run_id = await _create_run(srv.socket_path, sid, str(ws))

    (ws / "r.txt").write_text("run level modified\n")

    # 只写 run 级条目
    entry = build_entry(
        receipt=_FakeReceipt("write_file"),
        run_id=run_id, seq=1,
        undo_token=str(snap_path),
    )
    ledger_store.append(entry)

    # POST /undo 无 entry_seq
    status, _, raw = await _req(
        srv.socket_path, "POST", f"/runs/{run_id}/undo",
        session_id=sid, body={},
    )
    assert status == 200, raw.decode()
    body = json.loads(raw.decode())
    assert body["state"] in ("done", "partial")
    assert (ws / "r.txt").read_text() == original


# ── FileDiff → 账本条目 worker 集成 ───────────────────────────────────────────

class _FileDiffLoop:
    """yield file_diff + tool_receipt + verify_verdict 的 fake loop。"""

    async def run(self, goal: str, session_id: str) -> AsyncIterator[dict]:
        yield {
            "kind": "file_diff",
            "path": "/ws/main.py",
            "added": 5,
            "removed": 2,
            "unified": "...",
        }
        yield {
            "kind": "tool_receipt",
            "step": 0,
            "receipt": {"action": "write_file", "ts": time.time(), "sig": "ab" * 32},
        }
        yield {"kind": "verify_verdict", "verdict": {"status": "passed", "reason": "ok"}}


@pytest.mark.asyncio
async def test_file_diff_event_produces_ledger_entry(tmp_path: Path):
    """FileDiff 事件 → 账本条目:action=file_diff,reversible=yes(有快照),undo_token=file:..."""
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="x", workspace=str(tmp_path / "ws"))

    ledger = LedgerStore(ledger_dir=tmp_path / "ledger")

    # 建一个假快照(文件存在即可)
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    snap_path = tmp_path / "snap.tar"
    snap = RunSnapshot.take(ws, snap_path)

    worker = RunWorker(
        run_id=rid, manager=mgr, loop_factory=lambda: _FileDiffLoop(),
        ledger_store=ledger,
        snapshot=snap,
    )
    await worker.run()

    # 检查账本:应有 file_diff 条目
    entries = ledger.replay(rid)
    file_entries = [e for e in entries if e.action == "file_diff"]
    assert len(file_entries) == 1, f"应有 1 条 file_diff 账本条目,实得 {len(file_entries)}"

    fe = file_entries[0]
    assert fe.reversible == "yes", "有快照时 file_diff 条目应 reversible=yes"
    assert fe.undo_token is not None and fe.undo_token.startswith("file:")
    assert "main.py" in fe.summary_human
    assert "+5" in fe.summary_human and "-2" in fe.summary_human

    # _seq 单调递增
    events = list(mgr.store.replay(rid))
    seqs = [e["_seq"] for e in events if "_seq" in e]
    assert seqs == sorted(seqs), f"_seq 必须单调递增: {seqs}"
    assert len(seqs) == len(set(seqs)), f"_seq 有重复: {seqs}"


@pytest.mark.asyncio
async def test_file_diff_no_snapshot_gives_unknown_reversible(tmp_path: Path):
    """无快照时 file_diff 条目 reversible=unknown,undo_token=None。"""
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="x", workspace=str(tmp_path / "ws"))
    ledger = LedgerStore(ledger_dir=tmp_path / "ledger")

    worker = RunWorker(
        run_id=rid, manager=mgr, loop_factory=lambda: _FileDiffLoop(),
        ledger_store=ledger,
        snapshot=None,   # 无快照
    )
    await worker.run()

    entries = ledger.replay(rid)
    file_entries = [e for e in entries if e.action == "file_diff"]
    assert len(file_entries) == 1

    fe = file_entries[0]
    assert fe.reversible == "unknown"
    assert fe.undo_token is None
    assert fe.undo_state == "impossible"
