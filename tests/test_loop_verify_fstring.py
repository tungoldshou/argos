from __future__ import annotations

from argos.core.loop import AgentLoop, LoopConfig, _PROPOSE_VERIFY
from argos.core.verify_gate import Verdict
from argos.sandbox.backend import ExecResult
from argos.tui.events import EventBus
from tests.test_loop_codeact import FakeModel, FakeStore


class _Sb:
    def spawn(self, **k): pass
    def exec_code(self, code): return ExecResult(stdout="", value_repr="", exc="")
    def close(self): pass


class _Verifier:
    def verify(self, verify_cmd, *, attempts=1):
        return Verdict.passed(detail="[exit_code=0]", verify_cmd=verify_cmd, attempts=attempts)


def _loop():
    return AgentLoop(store=FakeStore(), bus=EventBus(), sandbox=_Sb(), broker=None,
                     model=FakeModel([]), verifier=_Verifier(), config=LoopConfig(verify_cmd=None))


def test_regex_tolerates_fstring_prefix():
    got = [m.group(1) for m in _PROPOSE_VERIFY.finditer("propose_verify(f'pytest {path}')")]
    assert got == ["pytest {path}"]
    got2 = [m.group(1) for m in _PROPOSE_VERIFY.finditer("propose_verify('pytest -q')")]
    assert got2 == ["pytest -q"]


def test_fstring_verify_rejected_with_guidance():
    loop = _loop()
    loop._verify_cmd = None
    assert loop._on_propose_verify("pytest {p}") is False
    assert loop._verify_cmd is None
    assert loop._verify_rejected == "pytest {p}"


def test_normal_verify_still_registers():
    loop = _loop()
    loop._verify_cmd = None
    assert loop._on_propose_verify("pytest -q tests/") is True
    assert loop._verify_cmd == "pytest -q tests/"
