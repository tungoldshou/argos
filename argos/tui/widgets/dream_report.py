# argos/tui/widgets/dream_report.py
"""Internal documentation."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from argos.i18n import t

_COL_PASS       = "#9ECE6A"
_COL_FAIL       = "#F7768E"
_COL_UNVERIF    = "#FF9E64"
_COL_EYE        = "#D9A85C"
_COL_INK        = "#C8CCDA"
_COL_INK_DIM    = "#7E869C"
_COL_INK_FAINT  = "#6B7494"
_COL_INK_BRIGHT = "#ECEEF5"

# spec §13:scan/memory → ◔;cluster/synthesize → ◉;promote → ❂;done → ◕
_STAGE_GLYPH: dict[str, str] = {
    "scan":       "◔",   # U+25D4 CIRCLE WITH UPPER RIGHT QUADRANT BLACK
    "cluster":    "◉",   # U+25C9 FISHEYE
    "synthesize": "◉",
    "promote":    "❂",   # U+2742 EIGHT TEARDROP-SPOKED ASTERISK
    "memory":     "◔",
    "done":       "◕",   # U+25D5 CIRCLE WITH THREE QUARTERS BLACK
}

_FALLBACK_GLYPH = "·"


def _coerce_report(report: Any) -> dict[str, Any]:
    """Internal documentation."""
    if isinstance(report, dict):
        return report
    # dataclass → dict(frozen=True,slots=True)
    try:
        return asdict(report)
    except Exception:
        try:
            return vars(report)
        except Exception:
            return {}


class DreamReportCard(Vertical):
    """Internal documentation."""

    DEFAULT_CSS = """
    DreamReportCard {
        height: auto;
        margin: 0 0 1 0;
        padding: 1 2;
        background: $stream;
        border: round $hairline-lit;
    }
    DreamReportCard #dream-stages {
        height: auto;
    }
    DreamReportCard #dream-report-box {
        background: $raise;
        padding: 1 2;
        margin: 1 0 0 0;
        height: auto;
        border: round $hairline-lit;
    }
    DreamReportCard .dream-echo {
        color: $ink-dim;
    }
    DreamReportCard .dream-caption {
        color: $ink-faint;
        margin: 1 0 0 0;
    }
    DreamReportCard .dream-footer {
        color: $ink-faint;
    }
    DreamReportCard .dream-report-title {
        text-style: bold;
        color: $ink-bright;
    }
    DreamReportCard .dream-report-row {
        color: $ink;
    }
    DreamReportCard .dream-report-dim {
        color: $ink-dim;
        margin: 1 0 0 0;
    }
    """

    _done_appended: bool = False

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._done_appended = False
        self._report_box_mounted = False


    def compose(self) -> ComposeResult:
        """Internal documentation."""
        yield Static(t("widget.dream_echo"), markup=False, classes="dream-echo")
        yield Vertical(id="dream-stages")
        yield Static(
            t("widget.dream_caption"),
            markup=False,
            classes="dream-caption",
        )
        yield Static(
            t("widget.dream_footer"),
            markup=False,
            classes="dream-footer",
        )


    def append_stage(self, stage: str, detail: str) -> None:
        """Internal documentation."""
        if stage == "done":
            if self._done_appended:
                return
            self._done_appended = True

        glyph = _STAGE_GLYPH.get(stage, _FALLBACK_GLYPH)
        row_text = self._build_stage_row(stage, glyph, detail)

        stage_static = Static(row_text, markup=False)
        self.call_after_refresh(self._mount_stage_row, stage_static)

    def show_report(self, report: Any) -> None:
        """Internal documentation."""
        d = _coerce_report(report)
        self.call_after_refresh(self._mount_report_box, d)


    def _build_stage_row(self, stage: str, glyph: str, detail: str) -> Text:
        """Internal documentation."""
        txt = Text()
        if stage == "done":
            txt.append(glyph, style=_COL_PASS)
            txt.append(f" {stage}", style=_COL_PASS)
        else:
            txt.append(glyph, style=_COL_EYE)
            txt.append(f" {stage}", style=_COL_INK)
            label_key = _STAGE_LABEL_KEYS.get(stage, "")
            label = t(label_key) if label_key else ""
            if label:
                txt.append(f"    {label}", style=_COL_INK)
        if detail:
            txt.append(f" · {detail}", style=_COL_INK_DIM)
        return txt

    def _build_row_b(self, report: Any) -> Text:
        """Internal documentation."""
        d = _coerce_report(report)
        units   = d.get("units_total", 0)
        promoted = d.get("promoted", 0)
        rejected = d.get("rejected", 0)
        skipped  = d.get("skipped", 0)

        tx = Text()
        tx.append(t("widget.dream_row_b", units=units), style=_COL_INK)
        tx.append(t("widget.dream_promoted", promoted=promoted), style=_COL_PASS)
        tx.append(" · ", style=_COL_INK)
        tx.append(t("widget.dream_rejected", rejected=rejected), style=_COL_FAIL)
        tx.append(" · ", style=_COL_INK)
        tx.append(t("widget.dream_skipped", skipped=skipped), style=_COL_UNVERIF)
        return tx


    def _mount_stage_row(self, stage_static: Static) -> None:
        """Internal documentation."""
        try:
            stages = self.query_one("#dream-stages", Vertical)
            stages.mount(stage_static)
        except Exception:  # noqa: BLE001
            pass

    def _mount_report_box(self, d: dict[str, Any]) -> None:
        """Internal documentation."""
        memory_merged  = d.get("memory_merged", 0)
        memory_archived = d.get("memory_archived", 0)
        promoted = d.get("promoted", 0)
        promoted_name = d.get("promoted_name")

        if not self._report_box_mounted:
            box = Vertical(id="dream-report-box")

            row_a = Static(t("widget.dream_report_title"), markup=False, classes="dream-report-title")
            row_b_text = self._build_row_b(d)
            row_b = Static(row_b_text, markup=False, classes="dream-report-row")
            row_c_text = t("widget.dream_row_c", memory_merged=memory_merged, memory_archived=memory_archived)
            row_c = Static(row_c_text, markup=False, classes="dream-report-row")

            children = [row_a, row_b, row_c]

            if promoted >= 1 and promoted_name:
                row_d_text = t("widget.dream_row_d", promoted_name=promoted_name)
                row_d = Static(row_d_text, markup=False, classes="dream-report-dim")
                children.append(row_d)

            try:
                caption = self.query_one(".dream-caption", Static)
                self.mount(box, before=caption)
                for child in children:
                    box.mount(child)
                self._report_box_mounted = True
            except Exception:  # noqa: BLE001
                pass
        else:
            try:
                box = self.query_one("#dream-report-box", Vertical)
                box.remove_children()
                row_a = Static(t("widget.dream_report_title"), markup=False, classes="dream-report-title")
                row_b_text = self._build_row_b(d)
                row_b = Static(row_b_text, markup=False, classes="dream-report-row")
                row_c_text = t("widget.dream_row_c", memory_merged=memory_merged, memory_archived=memory_archived)
                row_c = Static(row_c_text, markup=False, classes="dream-report-row")
                children = [row_a, row_b, row_c]
                if promoted >= 1 and promoted_name:
                    row_d_text = t("widget.dream_row_d", promoted_name=promoted_name)
                    row_d = Static(row_d_text, markup=False, classes="dream-report-dim")
                    children.append(row_d)
                for child in children:
                    box.mount(child)
            except Exception:  # noqa: BLE001
                pass


# spec §13 exact format strings — only used when detail is absent
# Keys are looked up via t() at render time so they respect ARGOS_LANG.
_STAGE_LABEL_KEYS: dict[str, str] = {
    "scan":       "widget.dream_stage_scan",
    "cluster":    "widget.dream_stage_cluster",
    "synthesize": "widget.dream_stage_synthesize",
    "promote":    "widget.dream_stage_promote",
    "memory":     "widget.dream_stage_memory",
    "done":       "widget.dream_stage_done",
}
