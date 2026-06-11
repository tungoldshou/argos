"""P3b 回归钉:ledger_entry 与主事件流共用同一单调 _seq 序列,无重复无撞号。

历史 bug 两连:① ledger 事件复用当前 event_seq(与 tool_receipt 同号,since=N 续传跳事件);
② 修成 event_seq + ledger_seq 偏移(与后续常规事件撞号,换个姿势破坏游标)。
正解:ledger 事件从主计数器领号。本测把"全流 _seq 严格单调递增且唯一"钉成断言。
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import AsyncIterator

import pytest

from argos_agent.daemon.manager import RunManager
from argos_agent.daemon.worker import RunWorker
from argos_agent.ledger.store import LedgerStore


class _ReceiptLoop:
    """yield 多个 tool_receipt(触发 ledger 落账)与普通事件交错的 fake loop。"""

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
    # 账本事件真的混进了主流
    kinds = [e.get("kind") for e in events]
    assert kinds.count("ledger_entry") == 3, f"应有 3 条 ledger_entry,实得 {kinds}"
    # 铁律:严格单调递增(蕴含唯一) —— 任何撞号/回退都立刻红
    assert seqs == sorted(seqs), f"_seq 必须单调递增: {seqs}"
    assert len(seqs) == len(set(seqs)), f"_seq 出现重复(since=N 续传会跳/重事件): {seqs}"
    # index 游标与最大 _seq 一致(断线重连从正确位置续)
    assert mgr.get_run(rid).last_event_seq == max(seqs)
