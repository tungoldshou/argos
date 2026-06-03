"""自建 CodeAct AgentLoop(契约 §3 + spec §3.1-§3.3) —— 替换 LangChain create_agent。

原生 async 全链路直喂 EventBus。四阶段(plan→act→verify→report)不可跳(spec §3.3 L3):
  · plan:出方案(第一次模型输出)。
  · act:CodeAct 执行 —— 抽 Python 代码块 → sandbox.exec_code → CodeResult 回灌,循环。
  · verify:模型称"完成"(无代码块)→ PhaseChange("verify") → verifier.verify → VerifyVerdict。
  · report:全绿或诚实标注"未完整验证";失败 bounce 重生成,超 max_rounds → Escalation。
一份事件三用:每个 Event 既 yield 给调用方,又 store.append_event 持久化。

契约 §9 锁定:
  锁#1: _verify_step 调 self._verifier.verify(verify_cmd, attempts=...) -> Verdict,
         无自建 _Verdict,无 detect_tampering(由 Verifier 内部处理)。
  锁#6: LoopConfig.model_tier: ModelTierName, approval_level: ApprovalLevel。
  W1:   PhaseChange("verify") 在 VerifyVerdict 之前发出。
  W2:   Harness(enter_phase/run_verify_gate/accept_receipt) 延迟到 Phase 4;本阶段内联处理。
  W3:   compose_system + recall 注入链延迟到 Phase 4;本阶段 system = HONESTY_SYSTEM。
目标 <800 行。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator

from argos_agent.core.honesty import HONESTY_SYSTEM
from argos_agent.core.types import ModelTierName
from argos_agent.tui.events import (
    CodeAction, CodeResult, Error, Escalation, Event, PhaseChange,
    TokenDelta, ToolReceipt, VerifyVerdict,
)

if TYPE_CHECKING:
    from argos_agent.memory.store import ArgosStore
    from argos_agent.sandbox.backend import SandboxBackend
    from argos_agent.sandbox.broker import CapabilityBroker
    from argos_agent.tui.events import EventBus

# 延迟 import ApprovalLevel 避免循环;用 TYPE_CHECKING 拿类型,运行时懒 import。
try:
    from argos_agent.approval import ApprovalLevel as _ApprovalLevel
    _DEFAULT_APPROVAL_LEVEL: Any = _ApprovalLevel.CONFIRM
except Exception:  # noqa: BLE001
    _DEFAULT_APPROVAL_LEVEL = None  # Phase 4 接线前的极端兜底

_CODE_BLOCK = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)


def extract_code_block(text: str) -> str | None:
    """从模型输出抽第一个 Python 代码块;无则 None。"""
    m = _CODE_BLOCK.search(text)
    if not m:
        return None
    return m.group(1).strip()


@dataclass(frozen=True, slots=True)
class LoopConfig:
    """契约 §9 锁#6 — model_tier: ModelTierName, approval_level: ApprovalLevel。"""
    model_tier: ModelTierName = "worker"
    verify_cmd: str | None = None
    max_rounds: int = 3              # verify bounce 上限
    max_steps: int = 40              # CodeAct 步数硬上限(death-spiral 兜底)
    compaction: bool = True
    # approval_level 默认 ApprovalLevel.CONFIRM(契约 §9 锁#6)。
    # TYPE_CHECKING import 避循环;运行时懒 import 拿真枚举值。
    approval_level: Any = field(default_factory=lambda: _DEFAULT_APPROVAL_LEVEL)


class AgentLoop:
    """CodeAct 主循环。

    W2 注记(Phase 4 延迟):Harness(enter_phase/run_verify_gate/accept_receipt)不存在。
    本阶段把 phase 门/verify/receipt 内联处理,Phase 4 引入 Harness 时重构这里。

    W3 注记(Phase 4 延迟):system 固定为 HONESTY_SYSTEM(无 recall/scrubber 注入)。
    Phase 4 引入 compose_system + recall + StreamingContextScrubber 时补完。
    """

    def __init__(
        self,
        *,
        store: "ArgosStore",
        bus: "EventBus",
        sandbox: "SandboxBackend",
        broker: "CapabilityBroker | None",
        model: Any,
        verifier: Any,
        config: LoopConfig,
        workspace: Path | None = None,
        verify_dir: Path | None = None,
    ) -> None:
        self._store = store
        self._bus = bus
        self._sandbox = sandbox
        self._broker = broker
        self._model = model
        self._verifier = verifier
        self._cfg = config
        self._workspace = workspace or Path.home() / ".argos" / "workspace"
        self._verify_dir = verify_dir or Path.home() / ".argos" / "verify"
        self._actions = 0
        self._fail_count = 0
        self._started = 0.0

    async def run(self, goal: str, session_id: str) -> AsyncIterator["Event"]:
        """驱动一次 run。plan→act→verify→report,投并持久化每个 Event(一份事件三用)。

        顶层兜底:捕获 _drive 内任何未处理异常,挖异常链投 Error(spec §3.3 L5)。
        """
        self._started = time.time()
        self._sandbox.spawn(workspace=self._workspace, namespace={})
        try:
            async for ev in self._drive(goal, session_id):
                self._store.append_event(session_id, ev)
                yield ev
        except Exception as e:  # noqa: BLE001
            chain: list[str] = []
            cur: BaseException | None = e
            while cur is not None and len(chain) < 4:
                chain.append(f"{type(cur).__name__}: {cur}")
                cur = cur.__cause__ or cur.__context__
            err = Error(message=str(e), chain=chain)
            self._store.append_event(session_id, err)
            yield err
        finally:
            self._sandbox.close()

    async def _drive(self, goal: str, session_id: str) -> AsyncIterator["Event"]:
        """四阶段驱动(不可跳):plan → act(CodeAct 循环) → verify(门禁) → report。"""
        # ── plan ──
        async for ev in self._phase("plan"):
            yield ev
        messages: list[dict] = [{"role": "user", "content": goal}]
        self._store.append_message(session_id, role="user", content=goal)

        # ── act(CodeAct 循环)──
        async for ev in self._phase("act"):
            yield ev
        step = 0
        while step < self._cfg.max_steps:
            # W3 注记:system 固定 HONESTY_SYSTEM;Phase 4 改 compose_system + recall。
            text = ""
            async for delta in self._model.stream(messages, system=HONESTY_SYSTEM):
                text += delta
                yield TokenDelta(text=delta)
            messages.append({"role": "assistant", "content": text})

            code = extract_code_block(text)
            if code is not None:
                yield CodeAction(code=code, step=step)
                result = self._sandbox.exec_code(code)
                self._actions += 1
                yield CodeResult(
                    step=step, stdout=result.stdout,
                    value_repr=result.value_repr, exc=result.exc, ok=result.ok,
                )
                # W2 注记:accept_receipt gating 延迟到 Phase 4;本阶段直接读 last_receipt。
                if self._broker is not None and getattr(self._broker, "last_receipt", None) is not None:
                    yield ToolReceipt(receipt=self._broker.last_receipt)
                # 回灌执行结果给模型,继续下一步。
                messages.append({"role": "user", "content": self._feedback(result)})
                step += 1
                continue

            # 无代码块 → 模型宣布"完成" → 进 verify。
            # W1:先发 PhaseChange("verify"),再跑 verifier,再发 VerifyVerdict。
            async for ev in self._phase("verify"):
                yield ev

            # 契约 §9 锁#1:调 verify(verify_cmd, attempts=...) -> Verdict(无_Verdict/无tampered)。
            verdict = self._verifier.verify(
                self._cfg.verify_cmd, attempts=self._fail_count + 1
            )
            verdict_ev = VerifyVerdict(verdict=verdict)
            yield verdict_ev

            if verdict.status == "passed":
                break                        # 通过 → 收尾
            if verdict.status == "unverifiable":
                break                        # 诚实标注,不假装成功,收尾
            # failed → bounce / escalate
            self._fail_count += 1
            if self._fail_count > self._cfg.max_rounds:
                yield Escalation(
                    reason=(
                        f"已尝试 {self._cfg.max_rounds} 轮仍无法通过验证 "
                        f"`{self._cfg.verify_cmd}`,需人工介入。"
                    ),
                    attempts=self._fail_count,
                    last_failure=verdict.detail,
                )
                break                        # 诚实升级,终止
            bounce = (
                f"[Argos 验证门] 你声称完成,但验证命令 `{self._cfg.verify_cmd}` 没通过:"
                f"\n{verdict.detail}\n请用工具定位并修复,改完再说完成。"
            )
            messages.append({"role": "user", "content": bounce})
            step += 1

        # ── report ──
        async for ev in self._phase("report"):
            yield ev

    async def _phase(self, phase: str) -> AsyncIterator["Event"]:
        """投 PhaseChange,推进阶段门。"""
        yield PhaseChange(phase=phase, actions=self._actions)  # type: ignore[arg-type]

    @staticmethod
    def _feedback(result: Any) -> str:
        """把 ExecResult 转成给模型回灌的文本。"""
        if not result.ok:
            return f"[执行异常]\n{result.exc}"
        out = result.stdout
        if result.value_repr:
            out += f"\n[返回值] {result.value_repr}"
        return f"[执行结果]\n{out}" if out.strip() else "[执行完成,无输出]"
