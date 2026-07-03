from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from argos.i18n import t

if TYPE_CHECKING:
    from argos.perception.executor import ComputerExecutor

_TEXT_EXCERPT_MAX = 200


@dataclass(frozen=True, slots=True)
class GuiProbeResult:
    found: bool = False
    text_excerpt: str = ""
    error: str = ""


class GuiProber:

    def __init__(self, executor: "ComputerExecutor | None") -> None:
        self._executor = executor

    def probe(self, expected_text: str | None, *, timeout_s: float = 15.0) -> GuiProbeResult:
        if not expected_text:
            return GuiProbeResult(
                error=t("verify.gui_probe.no_expected_text"),
            )
        if self._executor is None:
            return GuiProbeResult(error=t("verify.gui_probe.no_executor"))
        try:
            from argos.perception.actions import ComputerAction
            shot = self._executor.dispatch(ComputerAction(kind="screenshot"))
            if not getattr(shot, "ok", False) or not getattr(shot, "artifact_path", None):
                return GuiProbeResult(error=t(
                    "verify.gui_probe.screenshot_failed",
                    detail=getattr(shot, "detail", "?"),
                ))
            text = _ocr(shot.artifact_path)
            if text is None:
                return GuiProbeResult(
                    error=t("verify.gui_probe.ocr_unavailable"),
                )
            if expected_text.lower() in text.lower():
                return GuiProbeResult(found=True, text_excerpt=_excerpt_around(text, expected_text))
            return GuiProbeResult(found=False, text_excerpt="", error="")
        except Exception as exc:  # noqa: BLE001
            return GuiProbeResult(error=t(
                "verify.gui_probe.exception",
                exc_type=type(exc).__name__,
                exc=exc,
            ))


def _ocr(path: str) -> str | None:
    try:
        import pytesseract  # type: ignore[import]
        from PIL import Image  # type: ignore[import]
        with Image.open(path) as img:
            return pytesseract.image_to_string(img)
    except Exception:  # noqa: BLE001
        return None


def _excerpt_around(text: str, keyword: str, window: int = _TEXT_EXCERPT_MAX) -> str:
    low = text.lower()
    idx = low.find(keyword.lower())
    if idx < 0:
        return text[:window]
    start = max(0, idx - window // 2)
    end = min(len(text), idx + len(keyword) + window // 2)
    excerpt = text[start:end]
    if start > 0:
        excerpt = "…" + excerpt
    if end < len(text):
        excerpt = excerpt + "…"
    return excerpt
