"""Task 1.1: stagnation / stuck-state detection in the act loop.

When the model emits the identical (code_block, stdout) pair >= STAGNATION_LIMIT
consecutive times, the loop breaks early and emits an Escalation.
"""
from __future__ import annotations

import pytest

from argos.core.loop import AgentLoop, LoopConfig
from argos.sandbox.backend import ExecResult
from argos.protocol.events import CodeResult, Escalation, EventBus


class _StagnatingModel:
    """Emits the same failing code block every turn to simulate stagnation."""

    def __init__(self, block: str = "print(1/0)") -> None:
        self._block = block
        self.calls = 0

    async def stream(self, messages, *, system, system_dynamic=None):
        self.calls += 1
        for ch in f"```python\n{self._block}\n```":
            yield ch


class _RotatingModel:
    """Emits a DIFFERENT code block each turn — must NOT trigger stagnation."""

    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, messages, *, system, system_dynamic=None):
        self.calls += 1
        # Each call has a unique step counter baked in → different fingerprint every time.
        for ch in f"```python\nprint({self.calls})\n```":
            yield ch


class _FixedSandbox:
    """Returns a fixed (deterministic) stdout and always fails so the model keeps looping."""

    def __init__(self, stdout: str = "err", ok: bool = False) -> None:
        self._stdout = stdout
        self._ok = ok

    def spawn(self, *, workspace, namespace, allow_workflow=True, read_only=False): ...

    def exec_code(self, code):
        return ExecResult(stdout=self._stdout, value_repr="", exc="ZeroDivisionError" if not self._ok else "")

    def close(self): ...


class _NullVerifier:
    def verify(self, verify_cmd, *, attempts=1):
        from argos.core.verify_gate import Verdict
        return Verdict.unverifiable(detail="no verifier", verify_cmd=verify_cmd, attempts=attempts)


class _FakeStore:
    def append_event(self, sid, ev): ...
    def append_message(self, sid, **kw): return "m0"


@pytest.mark.asyncio
async def test_identical_code_block_triggers_stagnation_escalation():
    """Positive: same (code, stdout) pair repeated → early stop + Escalation."""
    loop = AgentLoop(
        store=_FakeStore(), bus=EventBus(), sandbox=_FixedSandbox(),
        broker=None, model=_StagnatingModel(), verifier=_NullVerifier(),
        config=LoopConfig(verify_cmd=None, max_rounds=5, max_steps=20),
    )
    events = [ev async for ev in loop.run("do x", "s")]

    escalations = [ev for ev in events if isinstance(ev, Escalation)]
    code_results = [ev for ev in events if isinstance(ev, CodeResult)]

    # Must escalate (not run to max_steps=20)
    assert escalations, "expected an Escalation event for stagnating run"
    esc = escalations[0]
    assert "stagnant" in esc.last_failure.lower() or "stuck" in esc.last_failure.lower() or \
           "cycle" in esc.last_failure.lower(), \
        f"Escalation.last_failure should mention stagnation, got: {esc.last_failure!r}"

    # Stopped early: STAGNATION_LIMIT=2 fires on the 2nd consecutive identical failing pair.
    # fp_run reaches 1 on first failure, 2 on second → guard fires → exactly 2 code results.
    assert len(code_results) == 2, \
        f"stagnation should fire after 2nd identical failing pair, got {len(code_results)} code results"


@pytest.mark.asyncio
async def test_different_code_blocks_do_not_trigger_stagnation():
    """Negative (false-positive guard): different block each turn → no stagnation Escalation."""
    loop = AgentLoop(
        store=_FakeStore(), bus=EventBus(), sandbox=_FixedSandbox(stdout="ok", ok=True),
        broker=None, model=_RotatingModel(), verifier=_NullVerifier(),
        config=LoopConfig(verify_cmd=None, max_rounds=1, max_steps=5),
    )
    events = [ev async for ev in loop.run("do y", "s")]

    stagnation_escalations = [
        ev for ev in events
        if isinstance(ev, Escalation)
        and ("stagnant" in (ev.last_failure or "").lower()
             or "stuck" in (ev.last_failure or "").lower()
             or "cycle" in (ev.last_failure or "").lower())
    ]
    assert not stagnation_escalations, \
        f"rotating blocks must NOT trigger stagnation, got {stagnation_escalations}"


@pytest.mark.asyncio
async def test_rotating_blocks_with_failing_sandbox_do_not_trigger_stagnation():
    """Negative (accumulation path guard): different blocks each turn WITH failing sandbox →
    no stagnation Escalation. Proves different fingerprints do NOT accumulate even when
    ok=False, so the counter can only grow on truly identical (code, stdout) pairs."""
    loop = AgentLoop(
        store=_FakeStore(), bus=EventBus(), sandbox=_FixedSandbox(stdout="err", ok=False),
        broker=None, model=_RotatingModel(), verifier=_NullVerifier(),
        config=LoopConfig(verify_cmd=None, max_rounds=1, max_steps=5),
    )
    events = [ev async for ev in loop.run("do z", "s")]

    stagnation_escalations = [
        ev for ev in events
        if isinstance(ev, Escalation)
        and ("stagnant" in (ev.last_failure or "").lower()
             or "stuck" in (ev.last_failure or "").lower()
             or "cycle" in (ev.last_failure or "").lower())
    ]
    assert not stagnation_escalations, (
        f"rotating blocks with failing sandbox must NOT trigger stagnation, "
        f"got {stagnation_escalations}"
    )


@pytest.mark.asyncio
async def test_success_resets_stagnation_counter():
    """Counter-reset invariant: a successful execution resets fp_run to 0.

    Sequence: fail-A, success-B, fail-A, fail-A → stagnation fires on the 4th call
    (the THIRD fail-A), NOT on the 2nd (the success between the two fail-A runs resets
    the counter). Proves the ``not result.ok`` reset semantics in the stagnation guard.
    """

    class _SequenceModel:
        """Emits a scripted sequence of code blocks."""
        # block_A always fails; block_B always succeeds (different code + sandbox keyed on it)
        BLOCK_A = "raise RuntimeError('fail')"
        BLOCK_B = "x = 1  # success"
        _seq = [BLOCK_A, BLOCK_B, BLOCK_A, BLOCK_A]  # 4 calls

        def __init__(self):
            self.calls = 0

        async def stream(self, messages, *, system, system_dynamic=None):
            block = self._seq[self.calls % len(self._seq)]
            self.calls += 1
            for ch in f"```python\n{block}\n```":
                yield ch

    class _SequenceSandbox:
        """Fails for raise RuntimeError blocks, succeeds for x = 1 blocks."""
        def spawn(self, *, workspace, namespace, allow_workflow=True, read_only=False): ...
        def exec_code(self, code):
            if "raise" in code:
                return ExecResult(stdout="err", value_repr="", exc="RuntimeError")
            return ExecResult(stdout="ok", value_repr="", exc="")
        def close(self): ...

    loop = AgentLoop(
        store=_FakeStore(), bus=EventBus(), sandbox=_SequenceSandbox(),
        broker=None, model=_SequenceModel(), verifier=_NullVerifier(),
        config=LoopConfig(verify_cmd=None, max_rounds=1, max_steps=20),
    )
    events = [ev async for ev in loop.run("do seq", "s")]

    stagnation_escalations = [
        ev for ev in events
        if isinstance(ev, Escalation)
        and ("stagnant" in (ev.last_failure or "").lower()
             or "stuck" in (ev.last_failure or "").lower()
             or "cycle" in (ev.last_failure or "").lower())
    ]
    code_results = [ev for ev in events if isinstance(ev, CodeResult)]

    # Must escalate eventually (on the 4th call / 3rd fail-A)
    assert stagnation_escalations, "expected stagnation Escalation after success resets counter"
    # The success between the two fail-A pairs resets fp_run → guard cannot fire on the
    # 2nd fail-A; it fires only on the 2nd *consecutive* fail-A (after the reset).
    # Calls: fail-A(1), success-B(2), fail-A(3), fail-A(4) → fires after call 4 → 4 CodeResults.
    assert len(code_results) == 4, (
        f"stagnation should fire after 4 steps (not 2 — success resets counter), "
        f"got {len(code_results)}"
    )
