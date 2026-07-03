from __future__ import annotations

import time
from pathlib import Path
from typing import AsyncIterator

import pytest

from argos.daemon.manager import RunManager
from argos.daemon.worker import RunWorker
from argos.ledger.store import LedgerStore


class _ReceiptLoop:

    async def run(self, goal: str, session_id: str) -> AsyncIterator[dict]:
        for i in range(3):
            yield {"kind": "token_delta", "text": f"t{i}", "step": i}
            yield {
                "kind": "tool_receipt",
                "step": i,
                "receipt": {"action": "write_file", "ts": time.time(), "sig": "ab" * 32},
            }
        yield {"kind": "verify_verdict", "verdict": {"status": "passed", "reason": "fake"}}


@pytest.mark.asyncio
async def test_ledger_entry_seq_monotonic_and_unique(tmp_path: Path):
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="x", workspace=str(tmp_path))
    ledger = LedgerStore(ledger_dir=tmp_path / "ledger")
    worker = RunWorker(
        run_id=rid, manager=mgr, loop_factory=lambda: _ReceiptLoop(),
        ledger_store=ledger,
    )
    await worker.run()

    events = list(mgr.store.replay(rid))
    seqs = [e["_seq"] for e in events if "_seq" in e]
    kinds = [e.get("kind") for e in events]
    assert kinds.count("ledger_entry") == 3, f"应有 3 条 ledger_entry,实得 {kinds}"
    assert seqs == sorted(seqs), f"_seq 必须单调递增: {seqs}"
    assert len(seqs) == len(set(seqs)), f"_seq 出现重复(since=N 续传会跳/重事件): {seqs}"
    assert mgr.get_run(rid).last_event_seq == max(seqs)
