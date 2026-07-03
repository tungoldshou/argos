"""Internal documentation."""
from __future__ import annotations

import argos.app_factory as af
from argos.approval import ApprovalLevel
from argos.sandbox.egress import EgressPolicy
from argos.tools.receipts import ReceiptSigner


def test_make_gate_broker_sandbox_uses_select_backend(monkeypatch, tmp_path):
    created: dict = {}

    class _FakeBackend:
        def __init__(self, *, broker_handler):
            created["broker_handler"] = broker_handler

    monkeypatch.setattr(af, "select_backend", lambda: _FakeBackend)
    gate, broker, sandbox = af._make_gate_broker_sandbox(
        approval_level=ApprovalLevel.AUTO,
        perm_config=None,
        perm_audit=None,
        egress=EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set()),
        signer=ReceiptSigner(key=b"k"),
        workspace=tmp_path,
    )
    assert isinstance(sandbox, _FakeBackend), "沙箱应由 select_backend() 选出的后端构造,而非写死"
    assert created.get("broker_handler") is not None, "broker_handler 应传给选出的后端"


def test_select_backend_returns_seatbelt_on_darwin(monkeypatch):
    """Internal documentation."""
    import argos.sandbox.executor as ex
    monkeypatch.setattr(ex.sys, "platform", "darwin")
    assert ex.select_backend() is ex.SeatbeltExecutor
