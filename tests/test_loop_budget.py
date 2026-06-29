"""Task 1.2: hard cost/token circuit-breaker on LoopConfig.

When accumulated input tokens exceed max_tokens_in (or accumulated cost exceeds
max_cost_usd), the loop breaks early and emits an Escalation before max_steps.
When both ceilings are None (default), behavior is identical to before.

Token counting mechanism: after every model call the loop reads
``model.last_usage["input_tokens"]`` and adds it to ``self._tok_in``.
We expose this by giving FakeModel a settable ``last_usage`` dict.
"""
from __future__ import annotations

import pytest

from argos.core.loop import AgentLoop, LoopConfig
from argos.sandbox.backend import ExecResult
from argos.protocol.events import CodeResult, Escalation, EventBus


# ── shared fakes ─────────────────────────────────────────────────────────────

class _FakeStore:
    def append_event(self, sid, ev): ...
    def append_message(self, sid, **kw): return "m0"


class _NullVerifier:
    def verify(self, verify_cmd, *, attempts=1):
        from argos.core.verify_gate import Verdict
        return Verdict.unverifiable(detail="no verifier", verify_cmd=verify_cmd, attempts=attempts)


class _OkSandbox:
    """Always succeeds so the loop doesn't stop for unrelated reasons."""
    def spawn(self, *, workspace, namespace, allow_workflow=True, read_only=False): ...
    def exec_code(self, code):
        return ExecResult(stdout="ok", value_repr="", exc="")
    def close(self): ...


class _TokenBurningModel:
    """Reports ``tokens_per_call`` input tokens each step, emits a no-op code block
    so the loop keeps iterating until the budget check fires."""

    def __init__(self, tokens_per_call: int = 20) -> None:
        self.tokens_per_call = tokens_per_call
        self.calls = 0
        # last_usage is read by the loop after every stream() call
        self.last_usage: dict = {}

    async def stream(self, messages, *, system, system_dynamic=None):
        self.calls += 1
        self.last_usage = {"input_tokens": self.tokens_per_call, "output_tokens": 1}
        # Emit a simple harmless code block so the loop has something to execute
        code = f"x = {self.calls}  # step {self.calls}"
        for ch in f"```python\n{code}\n```":
            yield ch


class _PricedTokenBurningModel(_TokenBurningModel):
    """Same as above but also sets a `tier` with a known model name so cost_of
    returns a real USD figure (used by the cost-ceiling test)."""

    def __init__(self, tokens_per_call: int = 1000) -> None:
        super().__init__(tokens_per_call)
        # Build a minimal tier object that satisfies the model_name lookup in the loop
        from argos.core.models import ModelTier
        self.tier = ModelTier(
            name="default",
            model="claude-sonnet-4-6",  # present in PRICING ($3/M in)
            base_url="https://api.anthropic.com/v1",
            max_tokens=4096,
            context_window=200_000,
            multimodal=False,
        )

    async def stream(self, messages, *, system, system_dynamic=None):
        self.calls += 1
        self.last_usage = {"input_tokens": self.tokens_per_call, "output_tokens": 1}
        code = f"x = {self.calls}"
        for ch in f"```python\n{code}\n```":
            yield ch


class _NoCodeModel:
    """Emits no code blocks — the loop terminates normally after one model call."""

    def __init__(self, tokens_per_call: int = 5) -> None:
        self.tokens_per_call = tokens_per_call
        self.last_usage: dict = {}

    async def stream(self, messages, *, system, system_dynamic=None):
        self.last_usage = {"input_tokens": self.tokens_per_call, "output_tokens": 1}
        for ch in "Done, no code needed.":
            yield ch


# ── tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_token_ceiling_triggers_budget_escalation():
    """Positive (token): cumulative input tokens exceed max_tokens_in → early Escalation."""
    # Each step burns 20 tokens; ceiling is 15 → fires after the first step.
    loop = AgentLoop(
        store=_FakeStore(), bus=EventBus(), sandbox=_OkSandbox(),
        broker=None,
        model=_TokenBurningModel(tokens_per_call=20),
        verifier=_NullVerifier(),
        config=LoopConfig(verify_cmd=None, max_rounds=5, max_steps=30,
                          max_tokens_in=15),   # ceiling below one step's cost
    )
    events = [ev async for ev in loop.run("do work", "s1")]

    escalations = [ev for ev in events if isinstance(ev, Escalation)]
    assert escalations, "expected a budget Escalation when token ceiling is exceeded"

    esc = escalations[0]
    assert "budget exceeded" in esc.reason.lower(), \
        f"Escalation.reason should mention budget, got: {esc.reason!r}"
    assert "budget exceeded" in (esc.last_failure or "").lower(), \
        f"Escalation.last_failure should mention budget, got: {esc.last_failure!r}"
    assert "max_tokens_in" in esc.reason, \
        f"reason should name max_tokens_in, got: {esc.reason!r}"

    # Guard fires after step 1 (ceiling=15 < tokens_per_call=20), so at most 1 code result.
    code_results = [ev for ev in events if isinstance(ev, CodeResult)]
    assert len(code_results) < 5, \
        f"loop should stop early on budget breach, ran {len(code_results)} steps"


@pytest.mark.asyncio
async def test_no_ceiling_runs_to_completion():
    """Negative (pure-additive): both ceilings None → no budget Escalation, loop finishes normally."""
    loop = AgentLoop(
        store=_FakeStore(), bus=EventBus(), sandbox=_OkSandbox(),
        broker=None,
        model=_NoCodeModel(tokens_per_call=1000),   # burns many tokens per call
        verifier=_NullVerifier(),
        config=LoopConfig(verify_cmd=None, max_rounds=1, max_steps=10,
                          max_tokens_in=None, max_cost_usd=None),  # no ceiling
    )
    events = [ev async for ev in loop.run("do work", "s2")]

    budget_escalations = [
        ev for ev in events
        if isinstance(ev, Escalation) and "budget exceeded" in (ev.reason or "").lower()
    ]
    assert not budget_escalations, \
        f"no ceilings set — must not produce budget Escalation, got {budget_escalations}"


@pytest.mark.asyncio
async def test_cost_ceiling_triggers_budget_escalation():
    """Positive (cost): cumulative cost_usd exceeds max_cost_usd → early Escalation."""
    from argos.core.observability import PRICING
    # Only run if the model is in the pricing table (avoids false skip)
    model_name = "claude-sonnet-4-6"
    if model_name not in PRICING:
        pytest.skip(f"{model_name!r} not in PRICING table — cost guard untestable")

    # 1000 input tokens per step at $3/M = $0.000003 per step; ceiling $0.000001 fires immediately
    loop = AgentLoop(
        store=_FakeStore(), bus=EventBus(), sandbox=_OkSandbox(),
        broker=None,
        model=_PricedTokenBurningModel(tokens_per_call=1000),
        verifier=_NullVerifier(),
        config=LoopConfig(verify_cmd=None, max_rounds=5, max_steps=30,
                          max_cost_usd=0.000001),  # ceiling below one step's cost
    )
    events = [ev async for ev in loop.run("do work", "s3")]

    escalations = [ev for ev in events if isinstance(ev, Escalation)]
    budget_esc = [e for e in escalations if "budget exceeded" in (e.reason or "").lower()]
    assert budget_esc, \
        f"expected a budget Escalation on cost ceiling breach; all escalations: {escalations}"

    esc = budget_esc[0]
    assert "max_cost_usd" in esc.reason, \
        f"reason should name max_cost_usd, got: {esc.reason!r}"
