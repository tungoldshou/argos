"""Internal documentation."""
from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import Static

from argos.core.types import Verdict, VerdictStatus
from argos.i18n import t


class VerdictBadge(Static):
    """Internal documentation."""

    DEFAULT_CSS = """
    VerdictBadge { padding: 0 2; margin: 0 0 1 0; height: auto; }
    VerdictBadge.verdict-passed       { color: $pass; text-style: bold; }
    VerdictBadge.verdict-failed       { color: $fail; text-style: bold; }
    VerdictBadge.verdict-unverifiable { color: $unverif; }
    VerdictBadge.verdict-self         { color: $pass-weak; text-style: italic; }
    VerdictBadge.verdict-no-test      { color: $ink-dim; text-style: dim; }
    """

    status: reactive[VerdictStatus | None] = reactive(None)

    _ALL_CLASSES = (
        "verdict-passed", "verdict-failed", "verdict-unverifiable",
        "verdict-self", "verdict-no-test",
    )

    def __init__(self, **kwargs) -> None:
        super().__init__("", markup=False, **kwargs)
        self.render_text: str = ""

    def watch_status(self, value: VerdictStatus | None) -> None:
        """Internal documentation."""
        for s in ("passed", "failed", "unverifiable"):
            self.set_class(value == s, f"verdict-{s}")

    def _clear_all_classes(self) -> None:
        """Internal documentation."""
        for cls in self._ALL_CLASSES:
            self.set_class(False, cls)

    def show(self, verdict: Verdict) -> None:
        """Internal documentation."""
        cmd = verdict.verify_cmd or "—"

        if getattr(verdict, "no_test", False):
            self.render_text = t("verdict.no_test_line", detail=verdict.detail)
            self.status = verdict.status
            self._clear_all_classes()
            self.set_class(True, "verdict-no-test")
            self.update(self.render_text)
            return

        self.status = verdict.status

        if verdict.status == "passed" and verdict.self_verified:
            line1 = t("verdict.self_verified_line1", cmd=cmd, detail=verdict.detail)
            line2 = t("verdict.self_verified_line2")
            self.render_text = f"{line1}\n{line2}"
            self._clear_all_classes()
            self.set_class(True, "verdict-self")
            self.update(self.render_text)
            return

        if verdict.status == "passed":
            attempts_str = t("verdict.passed_attempts", attempts=verdict.attempts)
            self.render_text = t(
                "verdict.passed_line", cmd=cmd, attempts_str=attempts_str, detail=verdict.detail
            )
            self._clear_all_classes()
            self.set_class(True, "verdict-passed")
            self.update(self.render_text)
            return

        if verdict.status == "failed":
            # ── failed ────────────────────────────────────────────
            line1 = t("verdict.failed_line1", cmd=cmd, detail=verdict.detail)
            line2 = t("verdict.failed_line2", attempts=verdict.attempts)
            self.render_text = f"{line1}\n{line2}"
            self._clear_all_classes()
            self.set_class(True, "verdict-failed")
            self.update(self.render_text)
            return

        if verdict.tampered:
            tampered_str = " ".join(verdict.tampered)
            self.render_text = t(
                "verdict.unverifiable_tampered", tampered=tampered_str, detail=verdict.detail
            )
        else:
            self.render_text = t("verdict.unverifiable", cmd=cmd, detail=verdict.detail)
        self._clear_all_classes()
        self.set_class(True, "verdict-unverifiable")
        self.update(self.render_text)
