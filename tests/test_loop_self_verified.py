"""E4 self_verified 防火墙 —— loop 决策面回归测试(审稿发现 C1/C2)。

覆盖两个漏点:
  C1. loop.py 的 passed-break 之前用 `verdict.status == "passed"`,在 E4 开启后
     Verifier.verify 返 Verdict.passed_self 时会被放过去,污染下游(run_success memory
     + worker→hook 透传到 distill/promote)。修后改用 is_user_verified。
  C2. run_success 写 memory 之前没卡 is_user_verified,自验证通过会被持久化进
     跨会话 memory graph,放大自验证的死亡螺旋。修后只写用户级通过。
"""
from __future__ import annotations

import pytest

from argos.core.loop import AgentLoop, LoopConfig
from argos.core.verify_gate import Verdict
from argos.sandbox.backend import ExecResult
from argos.tui.events import Escalation, EventBus, PhaseChange, VerifyVerdict


class CompletingModel:
    """每次 stream 均返回无代码块文本(模型"宣布完成"),触发 verify 门。"""
    def __init__(self):
        self.calls = 0

    async def stream(self, messages, *, system, system_dynamic=None):
        self.calls += 1
        for ch in "我觉得完成了。":
            yield ch


class WorkingThenCompletingModel:
    """吐 6 个 code block(让 step >= 5 满足 run_success 门槛),然后宣布完成。"""
    def __init__(self):
        self.calls = 0
        self.code_emitted = 0

    async def stream(self, messages, *, system, system_dynamic=None):
        self.calls += 1
        # 第 1-6 次:吐 code(loop 会 exec_code,FakeSandbox 返回 ok)
        if self.code_emitted < 6:
            self.code_emitted += 1
            yield f"```python\nx_{self.code_emitted} = {self.code_emitted}\n```\n"
            return
        # 第 7 次:无代码块 → 触发 verify 门 → break
        for ch in "任务完成了。":
            yield ch


class FakeSandbox:
    def spawn(self, *, workspace, namespace, allow_workflow=True, read_only=False): ...
    def exec_code(self, code): return ExecResult(stdout="", value_repr="", exc="")
    def close(self): ...


class FakeStore:
    def append_event(self, sid, ev): ...
    def append_message(self, sid, **kw): return "m0"


class SelfPassedVerifier:
    """E4 模式:verifier 总是返 Verdict.passed_self(自验证通过,status=='passed'
    但 self_verified=True)。这是防火墙要拦的"伪绿"。"""
    def __init__(self):
        self.calls = 0

    def verify(self, verify_cmd, *, attempts=1):
        self.calls += 1
        return Verdict.passed_self(
            detail="[self_verified] 自造测试真过了",
            verify_cmd=verify_cmd, attempts=attempts,
        )


class UserPassedVerifier:
    """对照:verifier 返 Verdict.passed(用户级,自验证 False),应被放过去正常 break。"""
    def __init__(self):
        self.calls = 0

    def verify(self, verify_cmd, *, attempts=1):
        self.calls += 1
        return Verdict.passed(
            detail="[exit_code=0]",
            verify_cmd=verify_cmd, attempts=attempts,
        )


# ── C1:自验证通过不应当作"用户级通过"被 loop break ────


@pytest.mark.asyncio
async def test_loop_self_verified_pass_does_not_break_as_user_verified(monkeypatch):
    """verifier 持续返 passed_self → loop 必须 bounce + 升级(因为 C1 防火墙把
    self_verified 视为非用户级通过,落到 failed 分支走 _fail_count++)。"""
    # 关掉 memory 副作用,只看 loop 走向
    monkeypatch.setenv("ARGOS_NO_MEMORY", "1")
    verifier = SelfPassedVerifier()
    loop = AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=FakeSandbox(), broker=None,
        model=CompletingModel(), verifier=verifier,
        config=LoopConfig(verify_cmd="pytest -q", max_rounds=2, max_steps=20),
    )
    escalations: list[Escalation] = []
    verdicts: list[Verdict] = []
    async for ev in loop.run("写个 fix", "s"):
        if isinstance(ev, VerifyVerdict):
            verdicts.append(ev.verdict)
        if isinstance(ev, Escalation):
            escalations.append(ev)

    # 防火墙:verifier 一直被调至少 1 次(说明没被 break 短路)
    assert verifier.calls >= 1, "verifier 应当被反复调用(防火墙:不把 self_verified 当 break 信号)"
    # 必须有 Escalation:loop 走 bounce → _fail_count++ → 超 max_rounds → 升级
    # 关键:这是防火墙生效的证据 —— 如果 C1 没修,会直接 break,无 Escalation。
    assert escalations, "C1 修复后,self_verified 不得 break → 必走 bounce→escalation"
    # 收到的 verdict 至少一个 self_verified=True
    assert any(getattr(v, "self_verified", False) for v in verdicts), \
        "verdict 流里至少一个应带 self_verified=True"


@pytest.mark.asyncio
async def test_loop_user_verified_pass_breaks_normally(monkeypatch):
    """对照:verifier 返 Verdict.passed(self_verified=False)→ loop 正常 break。"""
    monkeypatch.setenv("ARGOS_NO_MEMORY", "1")
    verifier = UserPassedVerifier()
    loop = AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=FakeSandbox(), broker=None,
        model=CompletingModel(), verifier=verifier,
        config=LoopConfig(verify_cmd="pytest -q", max_rounds=3, max_steps=20),
    )
    escalations: list[Escalation] = []
    phases: list[str] = []
    async for ev in loop.run("写个 fix", "s"):
        if isinstance(ev, PhaseChange):
            phases.append(ev.phase)
        if isinstance(ev, Escalation):
            escalations.append(ev)

    # 用户级通过 → break 正常 → 无 Escalation
    assert not escalations, "用户级 passed 必走 break,不应触发 Escalation"
    # 走到 report
    assert phases[-1] == "report"
    # verifier 只被调 1 次(break 短路)
    assert verifier.calls == 1, "用户级 passed 应在第一次 verify 后 break,verifier 不应反复跑"


# ── C2:自验证通过不写 run_success 进 memory ────


@pytest.mark.asyncio
async def test_loop_self_verified_does_not_capture_run_success(monkeypatch, tmp_path):
    """C2 防火墙:loop 的 run_success 写 memory 必须卡 is_user_verified。
    自验证通过 → 即便走完也不写 run_success,跨会话 memory graph 不被 reward-hacked 成功污染。
    """
    # 用 tmp_path 隔离 memory,验 ARGS 文件下没 run_success 记录
    mem_dir = tmp_path / "memory"
    monkeypatch.setenv("ARGOS_MEMORY_DIR", str(mem_dir))
    monkeypatch.setenv("ARGOS_NO_MEMORY", "1")  # 关 auto-memory 副作用,只观察 capture_event

    from argos.memory import auto as mem_auto
    captured: list[dict] = []
    orig_capture = mem_auto.capture_event

    def _spy_capture(event_type, **kw):
        captured.append({"type": event_type, **kw})
        return orig_capture(event_type, **kw)
    monkeypatch.setattr(mem_auto, "capture_event", _spy_capture)

    verifier = SelfPassedVerifier()
    loop = AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=FakeSandbox(), broker=None,
        model=CompletingModel(), verifier=verifier,
        config=LoopConfig(verify_cmd="pytest -q", max_rounds=2, max_steps=20),
    )
    async for _ in loop.run("写个 fix", "s"):
        pass

    # 防火墙:run_success 不应被捕获
    run_success = [c for c in captured if c.get("type") == "run_success"]
    assert run_success == [], \
        f"C2 修复后,self_verified 不得触发 run_success 写 memory,实际抓到 {run_success}"
    # 但 escalation_decision 应被记(防火墙把 self_verified 降级为失败 → 升级)
    assert any(c.get("type") == "escalation_decision" for c in captured), \
        "升级路径应正常写 escalation_decision memory"


@pytest.mark.asyncio
async def test_loop_user_verified_captures_run_success(monkeypatch, tmp_path):
    """对照:用户级 passed → run_success 应被正常写进 memory(回归测试)。

    step 必须 >= 5 是 loop.py 原有门槛(防止 trivial 短跑被持久化),所以 model 须先吐
    6 个 code block 让 step 达到 6,再宣布完成触发 verify。
    """
    mem_dir = tmp_path / "memory"
    monkeypatch.setenv("ARGOS_MEMORY_DIR", str(mem_dir))
    monkeypatch.setenv("ARGOS_NO_MEMORY", "1")

    from argos.memory import auto as mem_auto
    captured: list[dict] = []
    orig_capture = mem_auto.capture_event

    def _spy_capture(event_type, **kw):
        captured.append({"type": event_type, **kw})
        return orig_capture(event_type, **kw)
    monkeypatch.setattr(mem_auto, "capture_event", _spy_capture)

    verifier = UserPassedVerifier()
    loop = AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=FakeSandbox(), broker=None,
        model=WorkingThenCompletingModel(), verifier=verifier,
        config=LoopConfig(verify_cmd="pytest -q", max_rounds=5, max_steps=20),
    )
    async for _ in loop.run("写个 fix", "s"):
        pass

    # 用户级 passed + step>=5 → run_success 应被记
    run_success = [c for c in captured if c.get("type") == "run_success"]
    assert run_success, "用户级 passed + step>=5 应正常写 run_success(回归测试)"


# ── 谓词自身不变量(契约 §6.1)───


def test_is_user_verified_is_single_source_of_truth():
    """is_user_verified 是用户级 passed 的唯一信源;不能仅看 status=='passed'。"""
    user_passed = Verdict.passed("ok", "pytest -q", 1)
    self_passed = Verdict.passed_self("ok", "pytest -q", 1)
    failed = Verdict.failed("boom", "pytest -q", 1)
    unver = Verdict.unverifiable("can't tell", [], 1)

    # 谓词表
    truth_table = {
        "user_passed": user_passed.is_user_verified,
        "self_passed": self_passed.is_user_verified,
        "failed": failed.is_user_verified,
        "unverifiable": unver.is_user_verified,
    }
    assert truth_table == {
        "user_passed": True,
        "self_passed": False,
        "failed": False,
        "unverifiable": False,
    }, f"is_user_verified 真值表错位:{truth_table}"
    # 关键反例:status=='passed' 但 is_user_verified=False(防火墙要拦的)
    assert self_passed.status == "passed" and not self_passed.is_user_verified, \
        "防火墙核心不变量:status=='passed' + self_verified=True → is_user_verified 必须 False"
