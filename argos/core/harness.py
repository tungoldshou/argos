from __future__ import annotations

from argos.core.types import Phase, Verdict
from argos.i18n import t as _i18n_t
from argos.core.verify_gate import Verifier
from argos.tools.receipts import Receipt, ReceiptSigner
from argos.protocol.events import PhaseChange, VerifyVerdict, Escalation
from argos.protocol.events import EventBus

PHASE_ORDER: list[str] = ["plan", "act", "verify", "report"]

NO_TEST_LABEL = _i18n_t("loop.report_note.no_test")


class Harness:
    def __init__(self, *, verifier: Verifier, signer: ReceiptSigner, bus: EventBus,
                 max_rounds: int | None = None) -> None:
        self.verifier = verifier
        self.signer = signer
        self.bus = bus
        self.max_rounds = max_rounds if max_rounds is not None else getattr(verifier, "max_rounds", 3)
        self._phase_idx = -1
        self._last_failure = ""

    async def enter_phase(self, phase: Phase, *, actions: int, max_steps: int | None = None) -> None:
        target = PHASE_ORDER.index(phase)
        if self._phase_idx == -1 and target != 0:
            raise ValueError(
                _i18n_t("core2.harness.must_start_plan", phase=phase)
            )
        if self._phase_idx >= 0 and 0 <= target < self._phase_idx:
            raise ValueError(
                _i18n_t("core2.harness.no_retreat", current=PHASE_ORDER[self._phase_idx], phase=phase)
            )
        if self._phase_idx >= 0 and target > self._phase_idx + 1:
            raise ValueError(
                _i18n_t("core2.harness.no_skip", current=PHASE_ORDER[self._phase_idx], phase=phase, order=PHASE_ORDER)
            )
        self._phase_idx = max(self._phase_idx, target)
        await self.bus.emit(PhaseChange(phase=phase, actions=actions, max_steps=max_steps))

    @staticmethod
    def is_honest_completion(verdict: Verdict, *, verify_cmd: str | None) -> bool:
        return verify_cmd is None and verdict.status == "unverifiable"

    async def run_verify_gate(self, verify_cmd: str | None, *, attempt: int) -> Verdict:
        verdict = self.verifier.verify(verify_cmd, attempts=attempt)
        await self.bus.emit(VerifyVerdict(verdict=verdict))

        if self.is_honest_completion(verdict, verify_cmd=verify_cmd):
            return verdict

        is_real_problem = (
            verdict.status == "failed"
            or (verdict.status == "unverifiable" and verify_cmd is not None)
            or (verdict.status == "passed" and getattr(verdict, "self_verified", False))
        )
        if is_real_problem:
            self._last_failure = verdict.detail
            if attempt > self.max_rounds:
                await self.bus.emit(Escalation(
                    reason=_i18n_t(
                        "verdict_detail.escalation_reason",
                        attempt=attempt,
                        verify_cmd=verify_cmd,
                        max_rounds=self.max_rounds,
                    ),
                    attempts=attempt,
                    last_failure=verdict.detail,
                ))
        return verdict

    def accept_receipt(self, receipt: Receipt) -> bool:
        return self.signer.verify(receipt)
