"""#11:propose_verify 对 f-string 的处理 —— host 侧独立跑验证、拿不到沙箱变量,无法求值
f-string 占位({...})。过去 propose_verify(f'...') 被正则完全失配 → 验证命令静默丢失(降级
NO_TEST,用户以为没验证,其实是 agent 想验证但格式错)。修法:正则容忍 f/r 前缀以【检测】,
含占位的命令拒登记 + 回灌诚实告知用普通字符串字面量。
"""
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
    # 过去 propose_verify(f'...') 完全失配;现容忍 f/r 前缀,能抓到(供下游 f-string 检测)。
    got = [m.group(1) for m in _PROPOSE_VERIFY.finditer("propose_verify(f'pytest {path}')")]
    assert got == ["pytest {path}"]
    # 普通字面量仍正常抓取
    got2 = [m.group(1) for m in _PROPOSE_VERIFY.finditer("propose_verify('pytest -q')")]
    assert got2 == ["pytest -q"]


def test_fstring_verify_rejected_with_guidance():
    # 含 {} 占位 → 拒登记(host 求不了变量),设 _verify_rejected 回灌(不静默丢失)。
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
