"""Internal documentation."""
import pytest

from argos.tui.events import EventBus, PhaseChange, VerifyVerdict, Escalation
from argos.core.types import Verdict
from argos.core.verify_gate import Verifier
from argos.tools.receipts import ReceiptSigner
from argos.core.harness import Harness, PHASE_ORDER
from argos import runtime


class _RecordingBus(EventBus):
    def __init__(self):
        super().__init__()
        self.seen = []

    async def emit(self, ev):
        self.seen.append(ev)
        await super().emit(ev)


@pytest.fixture
def in_project(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    tok = runtime.use_project(str(proj))
    yield proj
    runtime.reset(tok)


def _harness(bus):
    return Harness(verifier=Verifier(max_rounds=2), signer=ReceiptSigner(key=b"k"), bus=bus)


@pytest.mark.asyncio
async def test_phase_order_cannot_skip():
    bus = _RecordingBus()
    h = _harness(bus)
    await h.enter_phase("plan", actions=0)
    await h.enter_phase("act", actions=1)
    with pytest.raises(ValueError):
        await h.enter_phase("report", actions=2)


@pytest.mark.asyncio
async def test_phase_change_events_emitted():
    bus = _RecordingBus()
    h = _harness(bus)
    await h.enter_phase("plan", actions=0)
    await h.enter_phase("act", actions=3)
    phases = [e for e in bus.seen if isinstance(e, PhaseChange)]
    assert [p.phase for p in phases] == ["plan", "act"]
    assert phases[1].actions == 3


@pytest.mark.asyncio
async def test_verify_gate_passed_no_escalation(in_project):
    (in_project / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    bus = _RecordingBus()
    h = _harness(bus)
    verdict = await h.run_verify_gate("pytest -q test_ok.py", attempt=1)
    assert verdict.status == "passed"
    assert any(isinstance(e, VerifyVerdict) for e in bus.seen)
    assert not any(isinstance(e, Escalation) for e in bus.seen)


@pytest.mark.asyncio
async def test_verify_gate_escalates_after_max_rounds(in_project):
    (in_project / "test_bad.py").write_text("def test_bad():\n    assert False\n")
    bus = _RecordingBus()
    h = _harness(bus)  # max_rounds=2
    v1 = await h.run_verify_gate("pytest -q test_bad.py", attempt=1)
    assert v1.status == "failed"
    v2 = await h.run_verify_gate("pytest -q test_bad.py", attempt=2)
    assert v2.status == "failed"
    v3 = await h.run_verify_gate("pytest -q test_bad.py", attempt=3)
    assert v3.status == "failed"
    escs = [e for e in bus.seen if isinstance(e, Escalation)]
    assert len(escs) == 1
    assert escs[0].attempts == 3
    assert "pytest" in escs[0].last_failure or "exit_code" in escs[0].last_failure


@pytest.mark.asyncio
async def test_verify_gate_no_cmd_completes_honestly_no_escalation(in_project):
    """Internal documentation."""
    bus = _RecordingBus()
    h = _harness(bus)
    verdict = await h.run_verify_gate(None, attempt=99)
    assert verdict.status == "unverifiable"
    assert verdict.verify_cmd is None
    assert h.is_honest_completion(verdict, verify_cmd=None) is True
    assert any(isinstance(e, VerifyVerdict) for e in bus.seen)
    assert not any(isinstance(e, Escalation) for e in bus.seen)


@pytest.mark.asyncio
async def test_verify_gate_configured_cmd_unverifiable_is_not_honest_completion(in_project):
    """Internal documentation."""
    bus = _RecordingBus()
    h = _harness(bus)
    tampered_verdict = Verdict.unverifiable(
        detail="受保护测试被改", tampered=["test_guard.py"], attempts=1,
    )
    assert h.is_honest_completion(tampered_verdict, verify_cmd="pytest -q") is False


@pytest.mark.asyncio
async def test_accept_receipt_rejects_forgery():
    bus = _RecordingBus()
    h = _harness(bus)
    good = h.signer.sign(action="run_command", args={"command": "ls"}, result="ok", exit_code=0)
    assert h.accept_receipt(good) is True
    import dataclasses
    forged = dataclasses.replace(good, sig="0" * 64)
    assert h.accept_receipt(forged) is False


def test_phase_order_constant():
    assert PHASE_ORDER == ["plan", "act", "verify", "report"]



@pytest.mark.asyncio
async def test_enter_phase_backward_raises():
    """Internal documentation."""
    bus = _RecordingBus()
    h = _harness(bus)
    await h.enter_phase("plan", actions=0)
    await h.enter_phase("act", actions=1)
    with pytest.raises(ValueError, match="倒退"):
        await h.enter_phase("plan", actions=0)


@pytest.mark.asyncio
async def test_enter_phase_first_must_be_plan():
    """Internal documentation."""
    bus = _RecordingBus()
    h = _harness(bus)
    with pytest.raises(ValueError, match="plan"):
        await h.enter_phase("act", actions=0)


@pytest.mark.asyncio
async def test_full_plan_act_verify_report_still_works(in_project):
    """Internal documentation."""
    (in_project / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    bus = _RecordingBus()
    h = _harness(bus)
    await h.enter_phase("plan", actions=0)
    await h.enter_phase("act", actions=1)
    await h.enter_phase("verify", actions=2)
    verdict = await h.run_verify_gate("pytest -q test_ok.py", attempt=1)
    assert verdict.status == "passed"
    await h.enter_phase("report", actions=3)
    phases = [e.phase for e in bus.seen if isinstance(e, PhaseChange)]
    assert phases == ["plan", "act", "verify", "report"]
