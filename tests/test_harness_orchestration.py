"""harness L1-L5 编排(契约 §9;spec §3.3):阶段门不可跳 + verify gate 三态 + escalation + 回执核验。"""
import pytest

from argos_agent.tui.events import EventBus, PhaseChange, VerifyVerdict, Escalation
from argos_agent.core.types import Verdict
from argos_agent.core.verify_gate import Verifier
from argos_agent.tools.receipts import ReceiptSigner
from argos_agent.core.harness import Harness, PHASE_ORDER
from argos_agent import runtime


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
    # 跳过 verify 直接 report → 拒绝(阶段门不可跳,spec §3.3 L3)
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
    v3 = await h.run_verify_gate("pytest -q test_bad.py", attempt=3)  # 超 max_rounds
    assert v3.status == "failed"
    # 超上限 → 投 Escalation(诚实卡住),不假装完成
    escs = [e for e in bus.seen if isinstance(e, Escalation)]
    assert len(escs) == 1
    assert escs[0].attempts == 3
    assert "pytest" in escs[0].last_failure or "exit_code" in escs[0].last_failure


@pytest.mark.asyncio
async def test_verify_gate_no_cmd_completes_honestly_no_escalation(in_project):
    """HONESTY CORRECTION:没配 verify_cmd 的无测任务 → verdict=unverifiable,但属于诚实
    非阻塞完成 —— Harness 不 bounce/escalate(无测任务必须能收尾),报告诚实标'未机检验证'。"""
    bus = _RecordingBus()
    h = _harness(bus)
    # 即便 attempt 远超 max_rounds,无 verify_cmd 也绝不 escalate(它本就没有可修的失败)。
    verdict = await h.run_verify_gate(None, attempt=99)
    assert verdict.status == "unverifiable"   # 诚实:没真的机检过
    assert verdict.verify_cmd is None
    assert h.is_honest_completion(verdict, verify_cmd=None) is True
    assert any(isinstance(e, VerifyVerdict) for e in bus.seen)
    assert not any(isinstance(e, Escalation) for e in bus.seen)


@pytest.mark.asyncio
async def test_verify_gate_configured_cmd_unverifiable_is_not_honest_completion(in_project):
    """对照:配了 verify_cmd 却 unverifiable(篡改/超时)→ 真问题,不算诚实完成。"""
    bus = _RecordingBus()
    h = _harness(bus)
    # 用 Verdict.unverifiable 直接构造一个"配了 cmd 但篡改"的裁决,验证判据。
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


# ── Phase 4 #2: 倒退 + 非 plan 首次进入 防护 ─────────────────────────────────

@pytest.mark.asyncio
async def test_enter_phase_backward_raises():
    """倒退(从 act 回 plan)必须抛 ValueError。"""
    bus = _RecordingBus()
    h = _harness(bus)
    await h.enter_phase("plan", actions=0)
    await h.enter_phase("act", actions=1)
    with pytest.raises(ValueError, match="倒退"):
        await h.enter_phase("plan", actions=0)


@pytest.mark.asyncio
async def test_enter_phase_first_must_be_plan():
    """首次 enter_phase 非 plan 必须抛 ValueError。"""
    bus = _RecordingBus()
    h = _harness(bus)
    with pytest.raises(ValueError, match="plan"):
        await h.enter_phase("act", actions=0)


@pytest.mark.asyncio
async def test_full_plan_act_verify_report_still_works(in_project):
    """正常 plan→act→verify→report 序列不应抛异常。"""
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
