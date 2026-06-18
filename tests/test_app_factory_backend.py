"""#2 排查修复:沙箱后端经 select_backend() 按平台选,不再写死 SeatbeltExecutor。

Linux/Windows 用户(README 邀请)此前第一个任务就撞 raw FileNotFoundError(/usr/bin/sandbox-exec
不存在),而 linux.py 的 bwrap/unshare 后端现成却没接线。本测试证 build 路径走 select_backend()。
macOS 上 select_backend() 仍返回 SeatbeltExecutor,故 darwin 行为零变更(此测试用 fake 后端验证接线)。"""
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
    """select_backend() 在 macOS 返回 SeatbeltExecutor(darwin 行为不变);
    非 darwin 委托 linux.select_backend()(此处只验 darwin 分支,Linux 真后端需真机)。"""
    import argos.sandbox.executor as ex
    monkeypatch.setattr(ex.sys, "platform", "darwin")
    assert ex.select_backend() is ex.SeatbeltExecutor
