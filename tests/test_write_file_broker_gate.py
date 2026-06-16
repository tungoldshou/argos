"""item 3:write_file/edit_file 经 broker gate-only —— hard-path 系统路径拒 / 密钥 fail-closed /
签回执 / 返回放行哨兵;真正落盘留在沙箱子进程(wrapper 在 child 内写)。无 broker 命名空间无写工具。"""
from __future__ import annotations

import pytest

from argos.approval import ApprovalGate, ApprovalLevel
from argos.sandbox.broker import CapabilityBroker
from argos.sandbox.egress import EgressPolicy
from argos.tools import build_child_namespace, files
from argos.tools.receipts import ReceiptSigner

_AWS = "AKIAIOSFODNN7EXAMPLE"   # AWS 示例 access-key(密钥检测命中)


@pytest.fixture(autouse=True)
def _reset_perms(tmp_path, monkeypatch):
    from argos.permissions import config as _cfg, audit as _audit
    from argos.permissions import _reset_config, _reset_audit
    monkeypatch.setattr(_cfg, "CONFIG_PATH", tmp_path / "perm.json")
    monkeypatch.setattr(_audit, "AUDIT_DIR", tmp_path / "audit")
    _reset_config(); _reset_audit()
    yield
    _reset_config(); _reset_audit()


def _broker(level=ApprovalLevel.CONFIRM, workspace=None):
    gate = ApprovalGate(level=level)
    if workspace is not None:
        gate.set_workspace(str(workspace))
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    return CapabilityBroker(gate=gate, egress=egress,
                            signer=ReceiptSigner(key=b"k"), workspace=workspace)


# ── evaluate_sync(broker 用它做同步 gate-only 决策)──────────────────────────
def test_evaluate_sync_system_path_denied():
    m = ApprovalGate(ApprovalLevel.AUTO).evaluate_sync("write_file", {"path": "/etc/passwd", "content": "x"})
    assert m is not None and m.decision == "deny"


def test_evaluate_sync_secret_flagged():
    m = ApprovalGate(ApprovalLevel.AUTO).evaluate_sync("write_file", {"path": "a.py", "content": _AWS})
    assert m is not None and m.secret_pattern is not None


# ── broker request()(异步桥路径)gate-only ─────────────────────────────────
@pytest.mark.asyncio
async def test_request_write_system_path_denied():
    br = _broker(level=ApprovalLevel.AUTO)
    v = await br.request("write_file", {"path": "/etc/shadow", "content": "x"})
    assert ("/etc/" in str(v)) or ("拒绝" in str(v))
    assert br.last_receipt is None                       # hard-path 拒不签回执


@pytest.mark.asyncio
async def test_request_write_workspace_auto_applies_with_receipt(tmp_path):
    """CONFIRM 档普通工作区写:gate-only 自动放行(不阻塞)→ 哨兵 + 签回执(Codex 式自动应用)。"""
    br = _broker(level=ApprovalLevel.CONFIRM, workspace=tmp_path)
    v = await br.request("write_file", {"path": "a.py", "content": "print(1)"})
    assert v == files.WRITE_APPROVED_SENTINEL
    assert br.last_receipt is not None and br.last_receipt.action == "write_file"


@pytest.mark.asyncio
async def test_request_write_secret_denied():
    br = _broker(level=ApprovalLevel.AUTO)
    v = await br.request("write_file", {"path": "a.py", "content": _AWS})
    assert "密钥" in str(v)
    assert br.last_receipt is None                       # 密钥 fail-closed,不签回执


# ── broker execute_sync()(无 host_loop 回退路径)gate-only ─────────────────
def test_execute_sync_write_sentinel(tmp_path):
    br = _broker(level=ApprovalLevel.AUTO, workspace=tmp_path)
    v, code = br.execute_sync("write_file", {"path": "a.py", "content": "ok"})
    assert v == files.WRITE_APPROVED_SENTINEL and code == 0
    assert br.last_receipt is not None


def test_execute_sync_write_system_path_denied():
    br = _broker(level=ApprovalLevel.AUTO)
    v, code = br.execute_sync("write_file", {"path": "/etc/passwd", "content": "x"})
    assert code == 1 and br.last_receipt is None


# ── child wrapper:收到哨兵才在子进程内真正落盘 ─────────────────────────────
def test_wrapper_writes_on_sentinel(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "WORKSPACE", tmp_path.resolve())

    class _Ok:
        def request(self, action, args):
            return files.WRITE_APPROVED_SENTINEL

    ns = build_child_namespace(_Ok())
    assert "write_file" in ns
    assert "已写入" in ns["write_file"]("a.txt", "hello")
    assert (tmp_path / "a.txt").read_text() == "hello"


def test_wrapper_denied_no_write(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "WORKSPACE", tmp_path.resolve())

    class _Deny:
        def request(self, action, args):
            return "用户拒绝该写入(系统路径)。"

    ns = build_child_namespace(_Deny())
    out = ns["write_file"]("a.txt", "hello")
    assert "拒绝" in out and not (tmp_path / "a.txt").exists()


def test_edit_wrapper_passes_new_as_content(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "WORKSPACE", tmp_path.resolve())
    files.write_file("a.py", "old")
    seen: dict = {}

    class _Spy:
        def request(self, action, args):
            seen.update(args)
            return files.WRITE_APPROVED_SENTINEL

    ns = build_child_namespace(_Spy())
    ns["edit_file"]("a.py", "old", "newval")
    assert seen.get("content") == "newval"               # 密钥检测能看到替换后的新文本
    assert (tmp_path / "a.py").read_text() == "newval"


def test_no_broker_namespace_has_no_write_tools():
    """无 broker(纯沙箱)= 无写工具(诚实 fail-closed:不能治理就不给写),只读工具仍在。"""
    ns = build_child_namespace(None)
    assert "write_file" not in ns and "edit_file" not in ns
    assert "read_file" in ns and "search_files" in ns
