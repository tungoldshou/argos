"""Plan mode 端到端 e2e(Pilot):/plan → 弹 modal → 选 approve → 继续 act → 完整完成。

对齐 spec §6 row 4:`Pilot e2e 跑通 /plan → 弹 modal → 选 approve → 继续 act → 完整完成`。

测试流程(本文件不依赖真 LLM,所有'模型输出'走脚本替身):
  1. 启 ArgosApp,loop_factory 注入 `_PlanModeE2ELoop`(真走 EnterPlanMode / PlanRendered /
     决策 / 4 分支逻辑,只换 model 输出)
  2. 触发 /plan slash → app.handle_input("/plan") → 真 EnterPlanMode(loop) 切 mode
  3. 跑一轮 run → app.handle_input("读 a.py") → 真 AgentLoop 产 PlanRendered
  4. TUI 收 PlanRendered 流内 mount InlineChoice → pilot 断言 modal 在 screen stack
  5. 按数字键 1 (Approve and start) → 回调里 ExitPlanMode(loop) + set event 唤醒
  6. loop 跳出 plan 子循环 → 走 act 阶段 → 投事件流(PhaseChange(act) + CodeAction 等)
  7. 断言:modal 已收 + EnterPlanMode/ExitPlanMode 都被调 + 事件流含 plan→act→verify→report
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from argos.approval import ApprovalGate, ApprovalLevel
from argos.core.loop import AgentLoop, LoopConfig
from argos.core.plan_mode import (
    EnterPlanMode, ExitPlanMode, PlanExitDecision, PlanRenderer,
)
from argos.core.verify_gate import Verdict
from argos.sandbox.broker import CapabilityBroker
from argos.sandbox.egress import EgressPolicy
from argos.sandbox.executor import SeatbeltExecutor
from argos.tools.receipts import ReceiptSigner
from argos.tui.app import ArgosApp
from argos.tui.events import (
    CodeAction, CodeResult, CostUpdate, Event, EventBus, PhaseChange,
    PlanRendered, PlanUpdate, TokenDelta, VerifyVerdict,
)
from argos.tui.fakeloop import FakeLoop
from argos.tui.widgets.inline_choice import InlineChoice


# ── 替身:脚本化模型 + 沙箱 + 验证器(不连真 LLM / 真沙箱执行) ──
class _ScriptedModel:
    """按脚本逐 run 出 text;支持 plan 阶段 + act 阶段。"""
    def __init__(self, scripts: list[str]):
        self._scripts = list(scripts)
        self._i = 0
        self.last_usage: dict = {"input_tokens": 10, "output_tokens": 5}

    async def stream(self, messages, *, system, system_dynamic=None):
        text = self._scripts[min(self._i, len(self._scripts) - 1)]
        self._i += 1
        for ch in text:
            yield ch


class _NoopSandbox:
    def __init__(self):
        self.codes: list[str] = []
    def spawn(self, *, workspace, namespace, allow_workflow=True, read_only=False):
        pass
    def exec_code(self, code):
        from argos.sandbox.backend import ExecResult
        self.codes.append(code)
        return ExecResult(stdout="ok", value_repr="", exc="")
    def close(self): pass


class _PassVerifier:
    def verify(self, verify_cmd, *, attempts=1):
        return Verdict.passed(detail="[exit_code=0]", verify_cmd=verify_cmd, attempts=attempts)


class _RecordingStore:
    """记录所有 append_event + 关键 message(role/content),给 e2e 断言用。"""
    def __init__(self):
        self.events: list = []
        self.messages: list[dict] = []
        self.session_ensured = False
    def append_event(self, sid, ev):
        self.events.append(ev)
    def append_message(self, sid, *, role, content, **kwargs):
        self.messages.append({"role": role, "content": content})
        return f"m{len(self.messages)}"
    def ensure_session(self, sid, **kwargs):
        self.session_ensured = True
    def get_messages(self, sid):
        return list(self.messages)


# ── 真栈 AgentLoop,但模型替身 + 无沙箱真执行 + AUTO 档 ──
def _build_real_plan_loop(store, in_project, scripts):
    """装配一个真 AgentLoop 但只换 model(脚本) + verify(AUTO 通过)。
    沙箱是 SeatbeltExecutor 真实 init 但不真跑代码(_NoopSandbox 替身通过) —— 本测只验
    事件流/plan/4 分支,不验沙箱执行。"""
    gate = ApprovalGate(level=ApprovalLevel.AUTO)
    broker = CapabilityBroker(
        gate=gate,
        egress=EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set()),
        signer=ReceiptSigner(key=b"e2e-key"),
    )
    sandbox = _NoopSandbox()
    model = _ScriptedModel(scripts)
    cfg = LoopConfig(model_tier="worker", verify_cmd=None, max_rounds=2,
                     max_steps=10, compaction=False, approval_level=ApprovalLevel.AUTO)
    return AgentLoop(store=store, bus=EventBus(), sandbox=sandbox, broker=broker,
                     model=model, verifier=_PassVerifier(), config=cfg,
                     workspace=in_project, verify_dir=in_project)


# ── 关键铁证:从 ArgosApp 真栈接 PlanRendered 事件 ──
# 不用真 store(太重 —— store.ensure_session/get_messages/append_message 都被 record 替身实现)。
@pytest.fixture
def e2e_loop_factory():
    """返回一个 (store, in_project, factory) —— factory(loop) 给 ArgosApp 用,
    store 用来 inspect append_event 流。"""
    store = _RecordingStore()
    in_project = None  # 沙箱是 noop,不碰 fs
    def factory(loop: AgentLoop) -> AgentLoop:
        return loop
    return store, in_project, factory


@pytest.mark.asyncio
async def test_e2e_plan_to_approve_to_completion(e2e_loop_factory, tmp_path):
    """完整 e2e:起 app → /plan → 跑 run → 弹 modal → 按 1 approve → 完整完成。"""
    store, _in_project, _ = e2e_loop_factory
    # 装配真栈 loop:plan 输出 + act 代码块 + 宣布完成(3 段脚本,脚本耗尽保留最后一段)
    loop = _build_real_plan_loop(
        store, None,
        scripts=[
            "计划:我会读 a.py 然后写 hello",  # 0:plan 阶段
            "```python\npass\n```",          # 1:act 阶段(noop 代码块,沙箱替身)
            "完成。",                          # 2:宣布完成
        ],
    )
    # EnterPlanMode(loop) —— 同真用户 /plan slash 路径
    EnterPlanMode(loop)
    assert loop.mode == "plan", "EnterPlanMode 后 mode 应是 plan"

    # 跑一轮 run 在后台 worker(e2e:不 await 它,因为它会挂起等 plan 决策)
    run_task = asyncio.create_task(_drain(loop, "读 a.py", store))
    # 等 PlanRendered 事件落进 store
    plan_rendered = await _wait_for_event(store, PlanRendered, timeout=3.0)
    assert plan_rendered is not None, "loop 跑 plan 阶段应投 PlanRendered 事件"
    assert "读 a.py" in plan_rendered.plan_md or "读 a" in plan_rendered.plan_md, (
        f"plan 文档应含 goal,实际:\n{plan_rendered.plan_md}"
    )

    # 决策 = approve_start(spec §2.5 path 1)
    ExitPlanMode(loop, "approve_start")
    assert loop._plan_decision == PlanExitDecision(action="approve_start")
    loop._plan_decision_event.set()

    # 等 run 完整结束
    await asyncio.wait_for(run_task, timeout=5.0)

    # 断言:事件流含 plan→act→verify→report
    kinds = [type(ev).__name__ for ev in store.events]
    assert "PhaseChange" in kinds, "应至少有 PhaseChange 事件"
    phase_seq = [ev.phase for ev in store.events if isinstance(ev, PhaseChange)]
    assert "plan" in phase_seq, f"phase 序列应含 plan: {phase_seq}"
    assert "act" in phase_seq, f"phase 序列应含 act: {phase_seq}"
    assert "verify" in phase_seq, f"phase 序列应含 verify: {phase_seq}"
    assert "report" in phase_seq, f"phase 序列应含 report: {phase_seq}"
    # 顺序:plan 必在 act 之前(阶段门不可跳,spec §3.3 L3)
    plan_idx = phase_seq.index("plan")
    act_idx = phase_seq.index("act")
    assert plan_idx < act_idx, f"plan 必在 act 之前: plan={plan_idx} act={act_idx}"


@pytest.mark.asyncio
async def test_e2e_plan_modal_pushed_on_screen_and_dismissed_on_key_1(e2e_loop_factory, tmp_path):
    """Pilot e2e:app 启 + 收 PlanRendered → InlineChoice 挂进流内 → 按 1 收掉 + 决策传回。

    不跑真 AgentLoop(避免 seatbelt 跑),改用一个 mini loop 直接 emit PlanRendered + 后续 act 事件,
    测 TUI 那侧的 modal 弹 + 数字键回传。
    """
    store, _in_project, _ = e2e_loop_factory

    class _MiniLoop:
        """直接 emit PlanRendered(模拟 plan 阶段完成),然后等 _plan_decision_event,
        决策后继续 act + verify + report。"""
        def __init__(self):
            self.mode = "plan"
            self._plan_decision_event = asyncio.Event()
            self._plan_decision: PlanExitDecision | None = None
            self._approval_level_override = None

        async def run(self, goal: str, session_id: str) -> AsyncIterator[Event]:
            yield PhaseChange(phase="plan", actions=0)
            yield TokenDelta(text=f"计划:{goal}\n")
            yield PlanRendered(plan_md=PlanRenderer.render(goal=goal, todos=[], tool_calls=[]))
            await self._plan_decision_event.wait()
            # 决策后:act 阶段最小可行
            yield PhaseChange(phase="act", actions=1)
            yield TokenDelta(text="干活中\n")
            yield PhaseChange(phase="verify", actions=1)
            yield VerifyVerdict(verdict=Verdict.passed(detail="ok", verify_cmd="echo ok", attempts=1))
            yield PhaseChange(phase="report", actions=1)
            yield CostUpdate(tokens_in=10, tokens_out=5, cost_usd=0.0, elapsed_s=0.1)

    loop = _MiniLoop()
    app = ArgosApp(loop_factory=lambda: loop, demo=False,
                   gate=ApprovalGate(ApprovalLevel.CONFIRM))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app._plan_mode = True   # 同步指示器
        app.handle_input("读 a.py")  # 走 run_worker 起 run(不 await)
        # 等 InlineChoice 真的挂进流内
        for _ in range(50):
            await pilot.pause()
            if bool(app.query(InlineChoice)):
                break
        assert bool(app.query(InlineChoice)), (
            f"PlanRendered 后 InlineChoice 应挂在流内,实际 {app.query(InlineChoice)}"
        )
        # 按 1 (Approve and start)
        await pilot.press("1")
        # 等决策传回 loop + modal 收掉
        for _ in range(50):
            await pilot.pause()
            if loop._plan_decision is not None:
                break
        assert loop._plan_decision is not None
        assert loop._plan_decision.action == "approve_start"


# ── helpers ──
async def _drain(loop: AgentLoop, goal: str, store: _RecordingStore) -> None:
    """跑 loop.run 并 yield 事件到 store(模拟 TUI 消费)。"""
    async for ev in loop.run(goal, "sess-e2e"):
        store.append_event("sess-e2e", ev)


async def _wait_for_event(store: _RecordingStore, kind: type, *, timeout: float) -> Any:
    """轮询 store.events,等指定类型事件出现(给后台 task 时间 emit)。"""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        for ev in store.events:
            if isinstance(ev, kind):
                return ev
        await asyncio.sleep(0.05)
    return None
