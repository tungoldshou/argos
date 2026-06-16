"""2d 接线铁证:_on_propose_gui_verify 登记 + _run_gui_probe_verdict 三态映射。
object.__new__ 绕过 AgentLoop 重型 __init__(两方法只用 _gui_prober/_verify_cmd/_harness/_fail_count)。"""
from __future__ import annotations

import pytest

from argos.core.loop import AgentLoop
from argos.verify.gui_probe import GuiProbeResult


class _FakeProber:
    def __init__(self, result):
        self._r = result
    def probe(self, expected_text, **kw):
        return self._r


class _FakeBus:
    def __init__(self):
        self.emitted = []
    async def emit(self, ev):
        self.emitted.append(ev)


class _FakeHarness:
    def __init__(self):
        self.bus = _FakeBus()


def _loop(gui_prober=None, verify_cmd=None) -> AgentLoop:
    loop = object.__new__(AgentLoop)
    loop._gui_prober = gui_prober            # type: ignore[attr-defined]
    loop._verify_cmd = verify_cmd            # type: ignore[attr-defined]
    loop._pending_gui_expected_text = ""     # type: ignore[attr-defined]
    loop._harness = _FakeHarness()           # type: ignore[attr-defined]
    loop._fail_count = 0                     # type: ignore[attr-defined]
    return loop


# ── _on_propose_gui_verify:登记 ──────────────────────────────────────────
def test_registers_expected_text():
    loop = _loop(gui_prober=_FakeProber(None))
    assert loop._on_propose_gui_verify("expected_text='Login OK'") is True
    assert loop._pending_gui_expected_text == "Login OK"


def test_ignored_without_prober():
    loop = _loop(gui_prober=None)            # computer use 未开 → GUI lane 跳过
    assert loop._on_propose_gui_verify("expected_text='X'") is False
    assert loop._pending_gui_expected_text == ""


def test_ignored_when_verify_cmd_set():
    loop = _loop(gui_prober=_FakeProber(None), verify_cmd="pytest -q")
    assert loop._on_propose_gui_verify("expected_text='X'") is False   # 显式命令优先


def test_ignored_without_expected_text():
    loop = _loop(gui_prober=_FakeProber(None))
    assert loop._on_propose_gui_verify("") is False


# ── _run_gui_probe_verdict:三态映射 ──────────────────────────────────────
@pytest.mark.asyncio
async def test_verdict_passed_when_found():
    loop = _loop(gui_prober=_FakeProber(GuiProbeResult(found=True, text_excerpt="…Login OK…")))
    v = await loop._run_gui_probe_verdict("Login OK", attempt=1)
    assert v.status == "passed"
    assert loop._harness.bus.emitted          # 投了 VerifyVerdict


@pytest.mark.asyncio
async def test_verdict_failed_when_absent():
    loop = _loop(gui_prober=_FakeProber(GuiProbeResult(found=False, error="")))
    v = await loop._run_gui_probe_verdict("Login OK", attempt=1)
    assert v.status == "failed"               # 屏上明确没有 → failed(真实证据)


@pytest.mark.asyncio
async def test_verdict_unverifiable_on_error():
    loop = _loop(gui_prober=_FakeProber(GuiProbeResult(found=False, error="OCR 不可用")))
    v = await loop._run_gui_probe_verdict("Login OK", attempt=1)
    assert v.status == "unverifiable"         # OCR/截图不可用 → 诚实 unverifiable
