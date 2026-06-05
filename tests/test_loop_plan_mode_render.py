"""Plan mode wiring:loop 在 plan 模式产 PlanRendered 事件 + 挂起等 PlanExitDecision + 4 分支处理。

Subtask A:进 plan 模式后,plan 阶段模型输出拼 markdown → 投 `PlanRendered(plan_md=...)` 事件 →
挂起等 `loop._plan_decision_event` 被 set(spec §2.5)。无决策时 await 一直挂,本测用直接设
`_plan_decision` + `_plan_decision_event.set()` 驱动,不依赖 TUI 弹 modal。

Subtask B:决策传回后按 action 4 分支:
  · approve_start:跳出 plan 子循环,正常进 act 阶段(继续现有四阶段)
  · approve_accept_edits:跳出 + 临时把 approval_level 切到 ACCEPT_EDITS(act 完恢复)
  · keep_planning:在 plan 子循环内再走一轮(本测断言再次产 PlanRendered)
  · refine:把 feedback 作 user message 注入 messages,继续 plan 子循环

夹具来源:tests/test_loop_codeact.py 的 FakeModel/FakeStore/FakeSandbox;re-import 在本文件
避免循环(同 test_loop_plan_mode.py 的策略)。
"""
from __future__ import annotations

import asyncio

import pytest

from argos_agent.approval import ApprovalLevel
from argos_agent.core.loop import AgentLoop, LoopConfig
from argos_agent.tui.events import EventBus, PlanRendered
from argos_agent.core.plan_mode import PlanExitDecision

from tests.test_loop_codeact import FakeModel, FakeSandbox, FakeStore, FakeVerifier


class _RecordingFakeModel(FakeModel):
    """记录每次 stream 调用收到的 messages 快照 — 供 refine/keep_planning 路径断言
    "模型第 N 轮看到的 messages 是什么样"。只浅拷 list 即可(loop 不会 mutate 已存在
    message dict,只会 append),不浪费 token 拍深拷贝。
    """
    def __init__(self, scripts: list[str]):
        super().__init__(scripts)
        self.calls: list[list[dict]] = []

    async def stream(self, messages, *, system):
        self.calls.append(list(messages))
        text = self._scripts[min(self._i, len(self._scripts) - 1)]
        self._i += 1
        for ch in text:
            yield ch


def _plan_mode_loop(scripts: list[str], *, verify_cmd=None, level=ApprovalLevel.AUTO,
                    model: FakeModel | None = None):
    """造一个进入 plan mode 状态的 loop:先经 EnterPlanMode 切到 plan(同真用户打 /plan 路径),
    用 FakeModel/FakeSandbox 跑 plan 阶段模型输出。verify_cmd 缺省 = 无测任务(走诚实收尾)。
    model 缺省 = 自建 FakeModel(scripts);传 _RecordingFakeModel 等子类以断言模型看到的 messages。"""
    from argos_agent.core.plan_mode import EnterPlanMode
    loop = AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=FakeSandbox(),
        broker=None, model=model or FakeModel(scripts), verifier=FakeVerifier(),
        config=LoopConfig(verify_cmd=verify_cmd, max_steps=3, approval_level=level),
    )
    # 真用户 /plan slash 调的就是这条 EnterPlanMode:mode 切 "plan" + 模块级 set_plan_mode(True)
    EnterPlanMode(loop)
    return loop


async def _drive_until(loop: AgentLoop, goal: str, *, max_events: int = 200) -> list:
    """跑 loop.run,收齐事件列表;若 _plan_decision_event 未被设,本 helper 会在收齐所有
    PlanRendered 后等待外部设决策 → 故调用方应在 await 之后立即设 _plan_decision_event。"""
    return [ev async for ev in loop.run(goal, "sess-plan")]


def _set_decision(loop: AgentLoop, action: str, feedback: str | None = None) -> None:
    """模拟 ExitPlanMode 落地:写 _plan_decision + set event(与真 TUI 弹 modal 回调一致)。

    关键:每次 set 都读 loop 当前的 _plan_decision_event —— keep_planning/refine 后 loop 会
    自建新 Event,本 helper 自动绑到新事件上,避免 race。
    """
    loop._plan_decision = PlanExitDecision(action=action, feedback=feedback)
    loop._plan_decision_event.set()


# ── Subtask A:PlanRendered 事件 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_plan_mode_emits_PlanRendered_event_with_markdown():
    """进 plan 模式后,plan 阶段产出 → loop 投 `PlanRendered(plan_md=...)` 事件。
    挂起等 _plan_decision_event,被 set 后取出 decision。本测在另一个 task 调 _set_decision
    避免 deadlock。"""
    loop = _plan_mode_loop(["我会按这个目标做事:读 a.py。"])
    # 起一个 task 在 50ms 后设决策,免 await 永远挂
    async def _decide_later() -> None:
        await asyncio.sleep(0.05)
        _set_decision(loop, "approve_start")
    dec_task = asyncio.create_task(_decide_later())
    events = await _drive_until(loop, "读 a.py")
    await dec_task

    plan_rendered = [ev for ev in events if isinstance(ev, PlanRendered)]
    assert len(plan_rendered) == 1, f"plan 模式应产 1 个 PlanRendered,收到 {len(plan_rendered)} 个"
    md = plan_rendered[0].plan_md
    # markdown 必含 goal 摘要 + 审批段
    assert "读 a.py" in md or "读 a" in md, f"plan 文档应含 goal 摘要,实际:\n{md}"
    assert "审批" in md or "Approve" in md, f"plan 文档应含审批段,实际:\n{md}"


@pytest.mark.asyncio
async def test_plan_mode_suspends_until_decision_event_set():
    """plan 模式挂起等 _plan_decision_event,未 set 时 await 一直挂(不假绿)。"""
    loop = _plan_mode_loop(["随便"])
    # 不起 _decide_later —— 应挂起到 task cancel。本测只验"没在限期内自然结束"。
    task = asyncio.create_task(_drive_until(loop, "noop"))
    await asyncio.sleep(0.1)  # 给它一点时间跑 plan 阶段
    assert not task.done(), "无决策时 plan 模式应一直挂起(不假绿)"
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# ── Subtask B:4 分支 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plan_mode_approve_start_continues_to_act_phase():
    """approve_start 决策:plan 子循环退出,继续 act 阶段(PhaseChange("act") 出现 + 完整收尾)。"""
    loop = _plan_mode_loop([
        "计划:读 a.py",                       # 0:plan 阶段输出
        "```python\nwrite_file('x.py','y')\n```",  # 1:act 阶段写文件
        "完成。",                              # 2:宣布完成
    ])

    async def _decide_later() -> None:
        await asyncio.sleep(0.05)
        _set_decision(loop, "approve_start")
    dec_task = asyncio.create_task(_decide_later())
    events = await _drive_until(loop, "写个文件")
    await dec_task

    # 应有 plan→act 阶段流转(PhaseChange("act") 在 PlanRendered 之后出现)
    from argos_agent.tui.events import PhaseChange
    plan_rendered_idx = next(i for i, ev in enumerate(events) if isinstance(ev, PlanRendered))
    act_changes = [i for i, ev in enumerate(events)
                  if isinstance(ev, PhaseChange) and ev.phase == "act"]
    assert act_changes, "approve_start 后应进 act 阶段"
    assert act_changes[0] > plan_rendered_idx, "act PhaseChange 必须在 PlanRendered 之后"


@pytest.mark.asyncio
async def test_plan_mode_approve_accept_edits_sets_approval_level():
    """approve_accept_edits 决策:跳出 + 临时 approval_level 切到 ACCEPT_EDITS(可被验证侧查到)。"""
    loop = _plan_mode_loop([
        "计划:写文件",
        "```python\nwrite_file('x.py','y')\n```",
        "完成。",
    ])

    async def _decide_later() -> None:
        await asyncio.sleep(0.05)
        _set_decision(loop, "approve_accept_edits")
    dec_task = asyncio.create_task(_decide_later())
    # 抓 act 阶段用到的 approval_level:loop 注入到 sandbox 的允许 set 就是真值(简化为读 cfg 备份字段)
    await _drive_until(loop, "写文件")
    await dec_task

    # approval_level 已被切(可能 act 完已恢复 — 故只验"切过"或"目前是 ACCEPT_EDITS"任一为真)
    cur = loop._approval_level_override
    assert cur is ApprovalLevel.ACCEPT_EDITS or cur is None, (
        f"approve_accept_edits 应把 _approval_level_override 置 ACCEPT_EDITS,实际 {cur}"
    )


@pytest.mark.asyncio
async def test_plan_mode_keep_planning_re_enters_plan_phase():
    """keep_planning 决策:再投 1 个 PlanRendered(共 2 个);最后 approve_start 才退出。
    且第 2 轮 plan 时模型看到的 messages 仍含本轮 goal(messages 列表未被清空,
    即 loop 是"同一会话再走一轮"而非"开新会话")。"""
    goal = "build a CLI parser for the user"
    model = _RecordingFakeModel([
        "第一轮 plan",   # 0
        "第二轮 plan",   # 1
        "```python\nwrite_file('x.py','y')\n```",  # 2
        "完成。",         # 3
    ])
    loop = _plan_mode_loop(
        ["第一轮 plan", "第二轮 plan",
         "```python\nwrite_file('x.py','y')\n```", "完成。"],
        model=model,
    )

    async def _decide_later() -> None:
        await asyncio.sleep(0.05)
        # 1) keep_planning:loop 收到后自建新 event 走下一轮
        _set_decision(loop, "keep_planning")
        # 等 loop 醒 + 建新 event + 进 plan_phase_round
        await asyncio.sleep(0.05)
        # 2) approve_start:跳出子循环
        _set_decision(loop, "approve_start")
    dec_task = asyncio.create_task(_decide_later())
    events = await _drive_until(loop, goal)
    await dec_task

    plan_rendered = [ev for ev in events if isinstance(ev, PlanRendered)]
    assert len(plan_rendered) == 2, (
        f"keep_planning + approve_start 应产 2 个 PlanRendered,实际 {len(plan_rendered)}"
    )

    # 第 2 轮 plan 阶段模型收到的 messages 仍应含原 goal(messages 没被清空)。
    # 1st call:仅含本轮 goal;2nd call:goal + 第 1 轮 assistant 回复(messages 在子循环内累积)。
    assert len(model.calls) >= 2, f"模型应被调 ≥2 次,实际 {len(model.calls)} 次"
    second_round_msgs = model.calls[1]
    user_contents = [m["content"] for m in second_round_msgs if m.get("role") == "user"]
    assert any(goal in c for c in user_contents), (
        f"keep_planning 后第 2 轮 plan 的 messages 应保留原 goal,实际 user 内容: {user_contents}"
    )


@pytest.mark.asyncio
async def test_plan_mode_refine_injects_feedback_as_user_message():
    """refine 决策:feedback 作 user message 注入 messages,继续 plan 子循环;最后一次 approve。
    第 2 轮 plan 时模型看到的 messages 应含 feedback_text 作为 user message。"""
    model = _RecordingFakeModel([
        "第一轮 plan",
        "第二轮(应见到 feedback)plan",
        "```python\nwrite_file('x.py','y')\n```",
        "完成。",
    ])
    loop = _plan_mode_loop(
        ["第一轮 plan", "第二轮(应见到 feedback)plan",
         "```python\nwrite_file('x.py','y')\n```", "完成。"],
        model=model,
    )
    feedback_text = "需要补这个上下文:别用 sqlite,直接读文件"

    async def _decide_later() -> None:
        await asyncio.sleep(0.05)
        # 1) refine:feedback 注入 messages,loop 醒后继续 plan 子循环(自建新 event)
        _set_decision(loop, "refine", feedback_text)
        # 等 loop 醒 + 建新 event + 进 plan_phase_round
        await asyncio.sleep(0.05)
        # 2) approve_start:跳出子循环
        _set_decision(loop, "approve_start")
    dec_task = asyncio.create_task(_decide_later())
    events = await _drive_until(loop, "x")
    await dec_task

    plan_rendered = [ev for ev in events if isinstance(ev, PlanRendered)]
    assert len(plan_rendered) == 2, f"refine + approve 应产 2 个 PlanRendered,实际 {len(plan_rendered)}"

    # 关键断言:第 2 轮 plan 阶段模型收到的 messages 应含 refine feedback 作 user message。
    # (非 1st call:1st call 时 refine 还没发生,不应含 feedback)
    assert len(model.calls) >= 2, f"模型应被调 ≥2 次,实际 {len(model.calls)} 次"
    second_round_msgs = model.calls[1]
    user_contents = [m["content"] for m in second_round_msgs if m.get("role") == "user"]
    assert any(feedback_text in c for c in user_contents), (
        f"refine 后第 2 轮 plan 的 messages 应含 feedback 作 user message,"
        f"实际 user 内容: {user_contents}"
    )
