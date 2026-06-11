"""build_entry:三态推断 + 人话 + receipt 字段映射测试。"""
from __future__ import annotations

import pytest
from argos_agent.ledger.builder import build_entry


class _FakeReceipt:
    def __init__(self, action: str, ts: float = 1000.0, sig: str = "abc123abc123abc1") -> None:
        self.action = action
        self.ts = ts
        self.sig = sig


class TestBuildEntryReversible:
    def test_write_file_with_snapshot_is_reversible_yes(self, tmp_path):
        snap = tmp_path / "snap.tar"
        snap.touch()
        e = build_entry(receipt=_FakeReceipt("write_file"),
                        run_id="r1", seq=1, undo_token=str(snap))
        assert e.reversible == "yes"
        assert e.undo_state == "available"
        assert e.undo_token == str(snap)

    def test_write_file_without_snapshot_is_unknown(self):
        e = build_entry(receipt=_FakeReceipt("write_file"),
                        run_id="r1", seq=1, undo_token=None)
        assert e.reversible == "unknown"
        assert e.undo_state == "impossible"
        assert e.undo_token is None

    def test_web_fetch_is_irreversible(self):
        e = build_entry(receipt=_FakeReceipt("web_fetch"),
                        run_id="r1", seq=2)
        assert e.reversible == "no"
        assert e.undo_state == "impossible"
        assert e.undo_token is None

    def test_browser_navigate_is_irreversible(self):
        e = build_entry(receipt=_FakeReceipt("browser_navigate"),
                        run_id="r1", seq=3)
        assert e.reversible == "no"
        assert e.undo_state == "impossible"

    def test_run_shell_is_unknown(self):
        e = build_entry(receipt=_FakeReceipt("run_shell"),
                        run_id="r1", seq=4)
        assert e.reversible == "unknown"
        assert e.undo_state == "impossible"

    def test_edit_file_reversible_with_token(self, tmp_path):
        snap = tmp_path / "s.tar"
        snap.touch()
        e = build_entry(receipt=_FakeReceipt("edit_file"),
                        run_id="r1", seq=5, undo_token=str(snap))
        assert e.reversible == "yes"
        assert e.undo_state == "available"


class TestBuildEntryFields:
    def test_run_id_and_seq(self):
        e = build_entry(receipt=_FakeReceipt("read_file"),
                        run_id="myrun", seq=7)
        assert e.run_id == "myrun"
        assert e.seq == 7

    def test_receipt_sig_truncated(self):
        e = build_entry(receipt=_FakeReceipt("read_file", sig="a" * 64),
                        run_id="r1", seq=1)
        assert len(e.receipt_sig) == 16
        assert e.receipt_sig == "a" * 16

    def test_ts_from_receipt(self):
        e = build_entry(receipt=_FakeReceipt("write_file", ts=9999.5),
                        run_id="r1", seq=1)
        assert e.ts == 9999.5

    def test_summary_human_not_empty(self):
        e = build_entry(receipt=_FakeReceipt("write_file"),
                        run_id="r1", seq=1,
                        args={"path": "out.txt"})
        assert e.summary_human
        assert len(e.summary_human) > 0

    def test_network_risk_high(self):
        e = build_entry(receipt=_FakeReceipt("web_fetch"),
                        run_id="r1", seq=1)
        assert e.risk == "high"

    def test_shell_risk_medium(self):
        e = build_entry(receipt=_FakeReceipt("run_shell"),
                        run_id="r1", seq=1)
        assert e.risk == "medium"

    def test_file_risk_low(self):
        e = build_entry(receipt=_FakeReceipt("write_file"),
                        run_id="r1", seq=1)
        assert e.risk == "low"


class TestBuildEntryIrreversibleNoToken:
    """不可逆动作的 undo_token 必须为 None(即使调用方传了 undo_token)。"""
    def test_irreversible_undo_token_forced_none(self):
        e = build_entry(receipt=_FakeReceipt("web_fetch"),
                        run_id="r1", seq=1,
                        undo_token="/some/path")
        assert e.undo_token is None
