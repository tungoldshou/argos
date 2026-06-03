"""5 层 harness 编排(契约 §9;spec §3.3)。

不重写 loop(Phase 3 的 AgentLoop 拥有循环);本模块提供 loop 串起来的纯编排单元:
  L3 阶段门:enter_phase 强制 plan→act→verify→report 不可跳,投 PhaseChange。
  L2 验证:run_verify_gate 调 Verifier 出三态 Verdict,投 VerifyVerdict;失败累计超 max_rounds
        → 投 Escalation(诚实卡住,不假装完成)。
  L3 回执:accept_receipt 用 ReceiptSigner 核验,伪造 → 拒(防谎报工具执行)。
loop 把 token_delta/code_action/code_result/file_diff/tool_receipt/cost_update 等其余事件直接投
EventBus(一份事件三用),harness 只负责上述硬门禁性质的编排。

HONESTY CORRECTION(spec HONESTY_SYSTEM 规则 1):Verifier 在没配 verify_cmd 时返回
`unverifiable`(绝不当 passed —— 没有命令真的跑过)。但"无测任务"必须能收尾,所以 Harness
据 `verify_cmd is None` 把这种 unverifiable 当**诚实非阻塞完成**(不 bounce/escalate,报告诚实
标"未机检验证 (no test command)")。反之,配了 verify_cmd 却 unverifiable(篡改/超时)或 failed
→ 真问题 → 走 bounce/escalate。两种情形由 `verify_cmd is None` 显式区分。
"""
from __future__ import annotations

from argos_agent.core.types import Phase, Verdict
from argos_agent.core.verify_gate import Verifier
from argos_agent.tools.receipts import Receipt, ReceiptSigner
from argos_agent.tui.events import EventBus, PhaseChange, VerifyVerdict, Escalation

# 阶段顺序不可跳(spec §3.3 L3:plan→act→verify→report)。
PHASE_ORDER: list[str] = ["plan", "act", "verify", "report"]

# 无测任务诚实完成的报告标签(spec HONESTY:never claim passed without verification)。
NO_TEST_LABEL = "未机检验证 (no test command)"


class Harness:
    def __init__(self, *, verifier: Verifier, signer: ReceiptSigner, bus: EventBus,
                 max_rounds: int | None = None) -> None:
        self.verifier = verifier
        self.signer = signer
        self.bus = bus
        # bounce 上限:显式传入(loop 用 LoopConfig.max_rounds 喂)优先;否则取 verifier 的。
        # 二者本应一致 —— 取 verifier 是 standalone harness 测试(真 Verifier 带 max_rounds)的便利。
        self.max_rounds = max_rounds if max_rounds is not None else getattr(verifier, "max_rounds", 3)
        self._phase_idx = -1     # 尚未进入任何阶段
        self._last_failure = ""

    async def enter_phase(self, phase: Phase, *, actions: int) -> None:
        """阶段门:只允许按 PHASE_ORDER 顺序前进(允许停留同阶段,不允许跳过中间阶段或倒退)。

        规则(Phase 4 #2):
          · 首次 enter_phase(_phase_idx == -1)必须从 plan 开始(target == 0)。
          · 已进入阶段后不允许倒退(target < _phase_idx)。
          · 不允许跳过中间阶段(target > _phase_idx + 1)。
        """
        target = PHASE_ORDER.index(phase)
        # 首次进入必须从 plan 开始。
        if self._phase_idx == -1 and target != 0:
            raise ValueError(
                f"首次 enter_phase 必须从 plan 开始,收到 {phase}。"
            )
        # 不允许倒退。
        if self._phase_idx >= 0 and 0 <= target < self._phase_idx:
            raise ValueError(
                f"阶段不可倒退:当前 {PHASE_ORDER[self._phase_idx]} → 试图回到 {phase}。"
            )
        # 不允许跳过中间阶段。
        if self._phase_idx >= 0 and target > self._phase_idx + 1:
            raise ValueError(
                f"阶段不可跳:当前 {PHASE_ORDER[self._phase_idx]} → 试图直接到 {phase}"
                f"(必须依次经过 {PHASE_ORDER})。"
            )
        self._phase_idx = max(self._phase_idx, target)
        await self.bus.emit(PhaseChange(phase=phase, actions=actions))

    @staticmethod
    def is_honest_completion(verdict: Verdict, *, verify_cmd: str | None) -> bool:
        """是否属于"诚实非阻塞完成":没配 verify_cmd 的无测任务,verdict=unverifiable
        但本就没有可机检的断言可跑 —— 收尾,报告诚实标 NO_TEST_LABEL,不 bounce/escalate。

        显式区分(HONESTY CORRECTION):
          · verify_cmd is None 且 unverifiable → True(诚实完成,无测任务必须能收尾)。
          · verify_cmd 非 None 时的 unverifiable(篡改/超时)→ False(真问题,要 bounce/escalate)。
          · passed/failed → False(走各自既有路径,不归"诚实完成"这条)。
        """
        return verify_cmd is None and verdict.status == "unverifiable"

    async def run_verify_gate(self, verify_cmd: str | None, *, attempt: int) -> Verdict:
        """称'完成'时跑 verify → 三态 Verdict,投 VerifyVerdict。

        · passed → 通过,不 escalate。
        · unverifiable 且 verify_cmd is None(无测任务)→ 诚实非阻塞完成,不 escalate
          (HONESTY CORRECTION:无测任务必须能收尾,但报告诚实标"未机检验证")。
        · failed,或 verify_cmd 非 None 时的 unverifiable(篡改/超时)→ 真问题;attempt 超
          self.max_rounds(bounce 上限,loop 用 LoopConfig.max_rounds 喂)→ 投 Escalation
          (诚实卡住,不假装完成)。
        """
        verdict = self.verifier.verify(verify_cmd, attempts=attempt)
        await self.bus.emit(VerifyVerdict(verdict=verdict))

        # 无测任务的诚实完成:不当失败,不 escalate。
        if self.is_honest_completion(verdict, verify_cmd=verify_cmd):
            return verdict

        # 真问题:failed,或配了 cmd 却 unverifiable(篡改/超时)。
        is_real_problem = verdict.status == "failed" or (
            verdict.status == "unverifiable" and verify_cmd is not None
        )
        if is_real_problem:
            self._last_failure = verdict.detail
            if attempt > self.max_rounds:
                await self.bus.emit(Escalation(
                    reason=(
                        f"已尝试 {attempt} 次仍无法通过验证 "
                        f"`{verify_cmd}`(bounce 上限 {self.max_rounds} 轮)"
                        f" —— 我没搞定,需要你介入指路,不会假装完成。"
                    ),
                    attempts=attempt,
                    last_failure=verdict.detail,
                ))
        return verdict

    def accept_receipt(self, receipt: Receipt) -> bool:
        """harness 接受'我做了 X'前核验回执(spec §6.5)。伪造 → False(拒)。"""
        return self.signer.verify(receipt)
