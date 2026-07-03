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



class _FakeReceipt:
    def __init__(self, action="file_diff"):
        self.action = action
        self.ts = time.time()
        self.sig = "dead" * 4


def _file_entry(run_id, seq, file_path, snap_path, undo_state="available") -> LedgerEntry:
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



@pytest.mark.asyncio
async def test_file_undo_restores_file_byte_for_byte(srv_env):
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

    (ws / "report.md").write_text("modified by agent\n")
    (ws / "other.py").write_text("also modified\n")

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

    assert (ws / "report.md").read_text() == original, "文件内容必须回原样"
    assert (ws / "other.py").read_text() == "also modified\n", "未指定文件不应被还原"

    e = ledger_store.get_entry(run_id, 2)
    assert e is not None
    assert e.undo_state == "done"


@pytest.mark.asyncio
async def test_new_file_undo_deletes_file_with_honest_note(srv_env):
    srv, manager, ledger_store, tmp_path = srv_env

    ws = tmp_path / "ws"
    ws.mkdir()
    snap_path = tmp_path / "snap.tar"
    RunSnapshot.take(ws, snap_path)

    sid = await _create_session(srv.socket_path)
    run_id = await _create_run(srv.socket_path, sid, str(ws))

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
    assert "新建" in body["note"] or "删除" in body["note"]
    assert not (ws / "new_file.py").exists(), "新建文件 undo 后必须删除"



@pytest.mark.asyncio
async def test_entry_not_found_returns_409(srv_env):
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
    srv, manager, ledger_store, tmp_path = srv_env

    ws = tmp_path / "ws"
    ws.mkdir()
    snap_path = tmp_path / "snap.tar"
    RunSnapshot.take(ws, snap_path)

    sid = await _create_session(srv.socket_path)
    run_id = await _create_run(srv.socket_path, sid, str(ws))

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
    srv, manager, ledger_store, tmp_path = srv_env

    ws = tmp_path / "ws"
    ws.mkdir()
    sid = await _create_session(srv.socket_path)
    run_id = await _create_run(srv.socket_path, sid, str(ws))

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
    srv, manager, ledger_store, tmp_path = srv_env

    ws = tmp_path / "ws"
    ws.mkdir()
    snap_path = tmp_path / "snap.tar"
    RunSnapshot.take(ws, snap_path)

    sid = await _create_session(srv.socket_path)
    run_id = await _create_run(srv.socket_path, sid, str(ws))

    run_entry = _run_level_entry(run_id, 1, snap_path)
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
    srv, manager, ledger_store, tmp_path = srv_env

    ws = tmp_path / "ws"
    ws.mkdir()
    sid = await _create_session(srv.socket_path)
    run_id = await _create_run(srv.socket_path, sid, str(ws))

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



@pytest.mark.asyncio
async def test_run_level_undo_still_works_without_entry_seq(srv_env):
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

    entry = build_entry(
        receipt=_FakeReceipt("write_file"),
        run_id=run_id, seq=1,
        undo_token=str(snap_path),
    )
    ledger_store.append(entry)

    status, _, raw = await _req(
        srv.socket_path, "POST", f"/runs/{run_id}/undo",
        session_id=sid, body={},
    )
    assert status == 200, raw.decode()
    body = json.loads(raw.decode())
    assert body["state"] in ("done", "partial")
    assert (ws / "r.txt").read_text() == original



class _FileDiffLoop:

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
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="x", workspace=str(tmp_path / "ws"))

    ledger = LedgerStore(ledger_dir=tmp_path / "ledger")

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

    entries = ledger.replay(rid)
    file_entries = [e for e in entries if e.action == "file_diff"]
    assert len(file_entries) == 1, f"应有 1 条 file_diff 账本条目,实得 {len(file_entries)}"

    fe = file_entries[0]
    assert fe.reversible == "yes", "有快照时 file_diff 条目应 reversible=yes"
    assert fe.undo_token is not None and fe.undo_token.startswith("file:")
    assert "main.py" in fe.summary_human
    assert "+5" in fe.summary_human and "-2" in fe.summary_human

    events = list(mgr.store.replay(rid))
    seqs = [e["_seq"] for e in events if "_seq" in e]
    assert seqs == sorted(seqs), f"_seq 必须单调递增: {seqs}"
    assert len(seqs) == len(set(seqs)), f"_seq 有重复: {seqs}"


@pytest.mark.asyncio
async def test_file_diff_no_snapshot_gives_unknown_reversible(tmp_path: Path):
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="x", workspace=str(tmp_path / "ws"))
    ledger = LedgerStore(ledger_dir=tmp_path / "ledger")

    worker = RunWorker(
        run_id=rid, manager=mgr, loop_factory=lambda: _FileDiffLoop(),
        ledger_store=ledger,
        snapshot=None,
    )
    await worker.run()

    entries = ledger.replay(rid)
    file_entries = [e for e in entries if e.action == "file_diff"]
    assert len(file_entries) == 1

    fe = file_entries[0]
    assert fe.reversible == "unknown"
    assert fe.undo_token is None
    assert fe.undo_state == "impossible"
