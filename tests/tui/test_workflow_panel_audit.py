"""Regression tests for WorkflowPanel design-audit fixes (2026-06-14).

Pins:
  1. [MEDIUM] Per-glyph Rich colour — each phase glyph has the correct hex colour.
  2. [LOW]    Synthesis + honest-notes lines are dim-styled ($ink-dim / $ink-faint).
  3. [LOW]    Header "工作流:<name>" is bold + $ink-bright.
  4. Honesty invariant — error→失败 / done→完成, never mixed.
  5. markup=False safety — agent_id / note containing "[...]" never crashes _compose_text.

Strategy: _compose_text() is a pure method that only reads instance state
(_name, _order, _agents, _done, _synthesis, _notes).  We bypass __init__
(which calls self.update() and needs a live Textual app) by building a
minimal instance via object.__new__ and wiring the five state attributes.
"""
from __future__ import annotations

from rich.text import Text

import pytest

from argos.tui.widgets.workflow_panel import (
    WorkflowPanel,
    _COL_EYE,
    _COL_FAIL,
    _COL_INK_BRIGHT,
    _COL_INK_DIM,
    _COL_INK_FAINT,
    _COL_PASS,
    _PHASE_GLYPH,
    _PHASE_GLYPH_COLOR,
    _PHASE_TEXT,
)


# ---------------------------------------------------------------------------
# Headless factory — builds a WorkflowPanel-shaped object without Textual app
# ---------------------------------------------------------------------------

def _make_panel(
    name: str,
    agents: list[tuple[str, str, str]] | None = None,  # [(agent_id, phase, note), ...]
    done: bool = False,
    synthesis: str = "",
    notes: tuple[str, ...] = (),
) -> WorkflowPanel:
    """Construct a WorkflowPanel instance with __init__ bypassed.

    Only _compose_text() is exercised here — it is a pure method that reads
    the five state attributes written below.  No Textual app context is needed.
    """
    panel: WorkflowPanel = object.__new__(WorkflowPanel)
    panel._name = name
    panel._order = []
    panel._agents = {}
    for agent_id, phase, note in (agents or []):
        if agent_id not in panel._agents:
            panel._order.append(agent_id)
        panel._agents[agent_id] = (phase, note)
    panel._done = done
    panel._synthesis = synthesis
    panel._notes = notes
    return panel


# ---------------------------------------------------------------------------
# Span helpers
# ---------------------------------------------------------------------------

def _find_span(text: Text, fragment: str) -> str | None:
    """Return the style string of the first span whose exact text == fragment, or None."""
    for span in text._spans:
        if text.plain[span.start:span.end] == fragment:
            return str(span.style)
    return None


def _spans_containing(text: Text, fragment: str) -> list[str]:
    """Return all style strings for spans whose text *contains* fragment."""
    return [
        str(span.style)
        for span in text._spans
        if fragment in text.plain[span.start:span.end]
    ]


# ---------------------------------------------------------------------------
# [MEDIUM] Per-glyph colour contract
# ---------------------------------------------------------------------------

class TestPerGlyphColour:
    """Each phase glyph must be coloured per _PHASE_GLYPH_COLOR, not flat default."""

    @pytest.mark.parametrize("phase,expected_color", [
        ("plan",   _COL_EYE),
        ("act",    _COL_EYE),
        ("verify", _COL_EYE),
        ("report", _COL_PASS),
        ("done",   _COL_PASS),
        ("error",  _COL_FAIL),
    ])
    def test_glyph_colour(self, phase: str, expected_color: str) -> None:
        """Glyph span colour matches the expected token hex for each phase."""
        panel = _make_panel("测试流", agents=[("agent-1", phase, "")])
        text = panel._compose_text()
        glyph = _PHASE_GLYPH[phase]
        style = _find_span(text, glyph)
        assert style is not None, (
            f"Phase '{phase}': glyph '{glyph}' span not found in Rich Text spans"
        )
        assert expected_color.lower() in style.lower(), (
            f"Phase '{phase}': glyph '{glyph}' has style={style!r}, "
            f"expected colour {expected_color!r}"
        )

    def test_glyph_colour_dict_complete(self) -> None:
        """_PHASE_GLYPH_COLOR covers all phases in _PHASE_GLYPH."""
        for phase in _PHASE_GLYPH:
            assert phase in _PHASE_GLYPH_COLOR, (
                f"Phase '{phase}' missing from _PHASE_GLYPH_COLOR"
            )

    def test_colour_constants_match_theme(self) -> None:
        """Spot-check that the hex constants equal the design-token values."""
        assert _COL_EYE.upper()        == "#D9A85C"
        assert _COL_PASS.upper()       == "#9ECE6A"
        assert _COL_FAIL.upper()       == "#F7768E"
        assert _COL_INK_BRIGHT.upper() == "#ECEEF5"
        assert _COL_INK_DIM.upper()    == "#7E869C"
        assert _COL_INK_FAINT.upper()  == "#6B7494"


# ---------------------------------------------------------------------------
# [LOW] Honesty invariant — error→失败 / done→完成
# ---------------------------------------------------------------------------

class TestHonestyInvariant:
    """error phase MUST render 失败; done MUST render 完成; never swapped."""

    def test_error_renders_fail_text(self) -> None:
        panel = _make_panel("流", agents=[("a1", "error", "")])
        plain = panel._compose_text().plain
        assert "失败" in plain, "error phase must render '失败'"
        assert "完成" not in plain, "error phase must NOT render '完成'"

    def test_done_renders_complete_text(self) -> None:
        panel = _make_panel("流", agents=[("a1", "done", "")])
        plain = panel._compose_text().plain
        assert "完成" in plain, "done phase must render '完成'"
        assert "失败" not in plain, "done phase must NOT render '失败'"

    def test_error_glyph_is_fail_colour(self) -> None:
        panel = _make_panel("流", agents=[("a1", "error", "")])
        text = panel._compose_text()
        glyph = _PHASE_GLYPH["error"]  # ◉
        style = _find_span(text, glyph)
        assert style is not None
        assert _COL_FAIL.lower() in style.lower(), (
            f"error glyph must be $fail ({_COL_FAIL}), got {style!r}"
        )

    def test_done_glyph_is_pass_colour(self) -> None:
        panel = _make_panel("流", agents=[("a1", "done", "")])
        text = panel._compose_text()
        glyph = _PHASE_GLYPH["done"]  # ◕
        style = _find_span(text, glyph)
        assert style is not None
        assert _COL_PASS.lower() in style.lower(), (
            f"done glyph must be $pass ({_COL_PASS}), got {style!r}"
        )

    def test_phase_text_contract_frozen(self) -> None:
        """_PHASE_TEXT values must not drift (honesty contract)."""
        assert _PHASE_TEXT["plan"]   == "规划"
        assert _PHASE_TEXT["act"]    == "执行"
        assert _PHASE_TEXT["verify"] == "验证"
        assert _PHASE_TEXT["report"] == "汇总"
        assert _PHASE_TEXT["done"]   == "完成"
        assert _PHASE_TEXT["error"]  == "失败"

    def test_phase_glyph_contract_frozen(self) -> None:
        """_PHASE_GLYPH values must not drift."""
        assert _PHASE_GLYPH["plan"]   == "◔"
        assert _PHASE_GLYPH["act"]    == "◉"
        assert _PHASE_GLYPH["verify"] == "❂"
        assert _PHASE_GLYPH["report"] == "◕"
        assert _PHASE_GLYPH["done"]   == "◕"
        assert _PHASE_GLYPH["error"]  == "◉"


# ---------------------------------------------------------------------------
# [LOW] Header bold + $ink-bright
# ---------------------------------------------------------------------------

class TestHeaderStyling:
    """Header '工作流:<name>' must be bold and $ink-bright."""

    def test_header_contains_name(self) -> None:
        panel = _make_panel("我的流")
        assert "工作流:我的流" in panel._compose_text().plain

    def test_header_is_bold_and_ink_bright(self) -> None:
        panel = _make_panel("我的流")
        text = panel._compose_text()
        style = _find_span(text, "工作流:我的流")
        assert style is not None, "Header span not found in Rich Text"
        assert "bold" in style.lower(), f"Header must be bold, got {style!r}"
        assert _COL_INK_BRIGHT.lower() in style.lower(), (
            f"Header must include $ink-bright ({_COL_INK_BRIGHT}), got {style!r}"
        )

    def test_done_header_is_bold_and_ink_bright(self) -> None:
        """finish() appends '(完成)' — the full header span must still be styled."""
        panel = _make_panel(
            "流",
            agents=[("a", "done", "")],
            done=True,
            synthesis="ok",
        )
        text = panel._compose_text()
        style = _find_span(text, "工作流:流(完成)")
        assert style is not None, "Finished header span not found"
        assert "bold" in style.lower()
        assert _COL_INK_BRIGHT.lower() in style.lower()


# ---------------------------------------------------------------------------
# [LOW] Synthesis + honest-notes dim styling
# ---------------------------------------------------------------------------

class TestSynthesisNotesStyling:
    """synthesis → $ink-dim; each note → $ink-faint."""

    def test_synthesis_text_has_ink_dim(self) -> None:
        panel = _make_panel("流", done=True, synthesis="任务结论")
        text = panel._compose_text()
        styles = _spans_containing(text, "任务结论")
        assert any(_COL_INK_DIM.lower() in s.lower() for s in styles), (
            f"synthesis text must have $ink-dim ({_COL_INK_DIM}); styles: {styles}"
        )

    def test_synthesis_label_has_ink_dim(self) -> None:
        panel = _make_panel("流", done=True, synthesis="结论内容")
        text = panel._compose_text()
        styles = _spans_containing(text, "综合结论")
        assert any(_COL_INK_DIM.lower() in s.lower() for s in styles), (
            f"'综合结论:' label must have $ink-dim ({_COL_INK_DIM}); styles: {styles}"
        )

    def test_note_has_ink_faint(self) -> None:
        panel = _make_panel("流", done=True, synthesis="s", notes=("注记第一条",))
        text = panel._compose_text()
        styles = _spans_containing(text, "注记第一条")
        assert any(_COL_INK_FAINT.lower() in s.lower() for s in styles), (
            f"note text must have $ink-faint ({_COL_INK_FAINT}); styles: {styles}"
        )

    def test_multiple_notes_all_ink_faint(self) -> None:
        notes = ("注记一", "注记二", "注记三")
        panel = _make_panel("流", done=True, synthesis="ok", notes=notes)
        text = panel._compose_text()
        for note in notes:
            styles = _spans_containing(text, note)
            assert any(_COL_INK_FAINT.lower() in s.lower() for s in styles), (
                f"note '{note}' must have $ink-faint; styles: {styles}"
            )

    def test_notes_appear_in_plain_text(self) -> None:
        panel = _make_panel("流", done=True, synthesis="主", notes=("第一条诚实注记",))
        assert "第一条诚实注记" in panel._compose_text().plain


# ---------------------------------------------------------------------------
# markup=False safety — "[...]" in agent_id / note must never raise
# ---------------------------------------------------------------------------

class TestMarkupSafety:
    """Rich markup characters in agent_id/note must not crash _compose_text."""

    def test_bracket_in_agent_id(self) -> None:
        panel = _make_panel("流", agents=[("[agent-1]", "act", "")])
        text = panel._compose_text()
        assert "[agent-1]" in text.plain

    def test_bracket_in_note(self) -> None:
        panel = _make_panel("流", agents=[("a1", "verify", "[test_case_42]")])
        text = panel._compose_text()
        assert "[test_case_42]" in text.plain

    def test_rich_markup_like_note_is_literal(self) -> None:
        note = "[bold red]some text[/bold red]"
        panel = _make_panel("流", agents=[("a1", "act", note)])
        text = panel._compose_text()
        assert note in text.plain

    def test_bracket_in_synthesis(self) -> None:
        panel = _make_panel(
            "流",
            done=True,
            synthesis="[synthesis result]",
            notes=("[note with [brackets]]",),
        )
        text = panel._compose_text()
        assert "[synthesis result]" in text.plain
        assert "[note with [brackets]]" in text.plain

    def test_compose_text_returns_rich_text(self) -> None:
        """_compose_text must return rich.text.Text, not a plain str."""
        panel = _make_panel("流")
        result = panel._compose_text()
        assert isinstance(result, Text), (
            f"_compose_text must return rich.text.Text, got {type(result)}"
        )


# ---------------------------------------------------------------------------
# Multi-agent ordering
# ---------------------------------------------------------------------------

class TestMultiAgentOrdering:
    """Agents appear in insertion order; each gets its own coloured glyph."""

    def test_agent_order_preserved(self) -> None:
        panel = _make_panel("流", agents=[
            ("alpha", "plan", ""),
            ("beta",  "act",  ""),
            ("gamma", "verify", ""),
        ])
        plain = panel._compose_text().plain
        assert plain.index("alpha") < plain.index("beta") < plain.index("gamma")

    def test_error_and_done_coloured_independently(self) -> None:
        """Two agents: error glyph=red, done glyph=green, never swapped."""
        panel = _make_panel("流", agents=[
            ("a", "error", ""),
            ("b", "done",  ""),
        ])
        text = panel._compose_text()
        all_spans = [(text.plain[s.start:s.end], str(s.style)) for s in text._spans]
        fail_glyph = _PHASE_GLYPH["error"]  # ◉
        pass_glyph = _PHASE_GLYPH["done"]   # ◕
        # Collect colours for each glyph occurrence in order
        fail_colours = [style for g, style in all_spans if g == fail_glyph]
        pass_colours = [style for g, style in all_spans if g == pass_glyph]
        assert any(_COL_FAIL.lower() in c.lower() for c in fail_colours), (
            f"No $fail span for error glyph among: {fail_colours}"
        )
        assert any(_COL_PASS.lower() in c.lower() for c in pass_colours), (
            f"No $pass span for done glyph among: {pass_colours}"
        )

    def test_update_overwrites_phase(self) -> None:
        """Re-registering an agent replaces its (phase, note)."""
        panel = _make_panel("流", agents=[
            ("a1", "plan", ""),
            ("a1", "done", ""),  # second entry overwrites first
        ])
        plain = panel._compose_text().plain
        assert "完成" in plain
        assert "规划" not in plain
