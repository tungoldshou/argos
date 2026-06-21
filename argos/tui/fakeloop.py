"""FakeLoop:按脚本投 Event 的测试/演示替身(契约 §3 run 签名形状)。

真 AgentLoop(Phase 3)落地前,TUI 接线靠它驱动;落地后只换注入对象,TUI 零改动。
默认脚本走一遍 plan→act→verify→report,覆盖 12 类事件里 UI 关心的主路径。
"""
from __future__ import annotations

import time
from collections.abc import AsyncIterator

from argos.core.types import Verdict
from argos.i18n import t
from argos.tui.events import (
    Event,
    TokenDelta,
    CodeAction,
    CodeResult,
    FileDiff,
    VerifyVerdict,
    PhaseChange,
    CostUpdate,
    Escalation,
    Error,
)


class FakeLoop:
    """run(goal, session_id) 产出一串脚本化 Event。script 可注入自定义序列。"""

    def __init__(self, script: list[Event] | None = None) -> None:
        self._script = script

    def _default_script(self, goal: str) -> list[Event]:
        t0 = time.monotonic()
        return [
            PhaseChange(phase="plan", actions=0),
            TokenDelta(text=t("core2.fakeloop.plan_prefix", goal=goal)),
            PhaseChange(phase="act", actions=1),
            CodeAction(code="files = search_files('TODO')", step=0),
            CodeResult(step=0, stdout="2 matches", value_repr="['a.py', 'b.py']", exc="", ok=True),
            FileDiff(
                path="a.py", added=2, removed=1,
                unified="--- a/a.py\n+++ b/a.py\n@@\n-old\n+new1\n+new2\n",
            ),
            CostUpdate(tokens_in=12400, tokens_out=3100, cost_usd=0.013, elapsed_s=time.monotonic() - t0),
            PhaseChange(phase="verify", actions=2),
            VerifyVerdict(verdict=Verdict.passed(detail="12 passed (0.8s)", verify_cmd="pytest", attempts=1)),
            PhaseChange(phase="report", actions=2),
            TokenDelta(text=t("core2.fakeloop.done")),
        ]

    async def run(self, goal: str, session_id: str,
                  attachments: list | None = None) -> AsyncIterator[Event]:
        # attachments:与真 AgentLoop.run 同签名(演示/测试不消费,仅记录供断言)。
        self.last_attachments = list(attachments or [])
        script = self._script if self._script is not None else self._default_script(goal)
        for ev in script:
            yield ev


class FailingFakeLoop(FakeLoop):
    """演示/测试 escalation + error 路径。"""

    def _default_script(self, goal: str) -> list[Event]:
        return [
            PhaseChange(phase="act", actions=1),
            CodeAction(code="boom()", step=0),
            CodeResult(step=0, stdout="", value_repr="", exc="NameError: boom", ok=False),
            VerifyVerdict(verdict=Verdict.failed(detail="1 failed", verify_cmd="pytest", attempts=3)),
            Escalation(reason=t("core2.fakeloop.escalation_reason"), attempts=3, last_failure="1 failed"),
            Error(message=t("core2.fakeloop.error_message"), chain=["NameError: boom", "verify failed x3"]),
        ]
