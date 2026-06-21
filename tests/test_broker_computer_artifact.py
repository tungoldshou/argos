"""2b.1:broker 执行 computer_screenshot 后 stash 截图工件(path, size),供 loop 取去挂图像;
take_computer_artifact 取后清空;非截图动作不 stash。OS 层用 fake ComputerExecutor(无需真屏幕)。"""
from __future__ import annotations

from argos.approval import ApprovalGate, ApprovalLevel
from argos.sandbox.broker import CapabilityBroker
from argos.sandbox.egress import EgressPolicy
from argos.tools.receipts import ReceiptSigner


def _broker():
    gate = ApprovalGate(level=ApprovalLevel.AUTO)
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    return CapabilityBroker(gate=gate, egress=egress, signer=ReceiptSigner(key=b"k"))


class _FakeResult:
    def __init__(self, ok, detail, artifact_path=None, size=None):
        self.ok = ok
        self.detail = detail
        self.artifact_path = artifact_path
        self.size = size


def _patch_executor(monkeypatch, result):
    from argos.perception import executor as _ex
    class _FakeExec:
        def dispatch(self, ca):
            return result
    # broker 现以 ComputerExecutor(auto_detect_scale=True) 构造(Retina 缩放惰性探测)→ fake 接受 **kw。
    monkeypatch.setattr(_ex, "ComputerExecutor", lambda **kw: _FakeExec())


def test_screenshot_stashes_artifact(monkeypatch):
    _patch_executor(monkeypatch, _FakeResult(True, "截图已保存", "/tmp/shot.png", (120, 80)))
    br = _broker()
    value, code = br.execute_sync("computer_screenshot", {})
    assert "截图" in str(value) and code == 0
    art = br.take_computer_artifact()
    assert art == ("/tmp/shot.png", (120, 80))
    assert br.take_computer_artifact() is None   # 取后清空


def test_non_screenshot_action_does_not_stash(monkeypatch):
    _patch_executor(monkeypatch, _FakeResult(True, "点击 (10,20) 成功", artifact_path=None))
    br = _broker()
    br.execute_sync("computer_click", {"x": 10, "y": 20})
    assert br.take_computer_artifact() is None   # 非截图不 stash


def test_failed_screenshot_does_not_stash(monkeypatch):
    _patch_executor(monkeypatch, _FakeResult(False, "截图失败(exit 1)", "/tmp/x.png", (0, 0)))
    br = _broker()
    br.execute_sync("computer_screenshot", {})
    assert br.take_computer_artifact() is None   # 失败不 stash(无可信工件)
