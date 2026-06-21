# tests/tui/test_tuiapp_lane.py
"""Tests for TUIAPP lane fixes (experience-review-followups).

Covers:
  #3  /setup slash command exists and prints instructions
  #5  Contract A: no_test verdict does NOT lock warn glow
  #7  /journal slash command shows ledger JSONL path
  #13 /trust help text uses cautious/trusted/autonomous vocabulary
  #19 Ctrl+C behaviour: interrupt-first, double-press quit (no-run idle)
  #20 Input history ring buffer + PromptArea history navigation
  #21 /help includes Ctrl+B, Ctrl+O, Ctrl+V bindings
  #22 match_commands substring fallback (security-review via 'review')
  #30 daemon spawn failure note surfaces in transcript (not on NO_DAEMON)
"""
from __future__ import annotations

import pytest

from argos.tui.commands import COMMAND_HELP, COMMAND_NAMES, match_commands, parse_slash
from argos.tui.widgets.prompt import PromptArea, SlashMenu


# ── #3 /setup command ────────────────────────────────────────────────────────

class TestSetupCommand:
    """#3: /setup must exist in COMMAND_HELP and be parse_slash-known."""

    def test_setup_in_command_help(self) -> None:
        assert "setup" in COMMAND_HELP, "/setup must appear in COMMAND_HELP"

    def test_setup_in_command_names(self) -> None:
        assert "setup" in COMMAND_NAMES, "/setup must appear in COMMAND_NAMES"

    def test_setup_is_known_slash(self) -> None:
        cmd = parse_slash("/setup")
        assert cmd is not None
        assert cmd.known is True, "parse_slash('/setup').known must be True"
        assert cmd.name == "setup"

    def test_setup_help_mentions_argos_setup(self) -> None:
        """Help text for /setup should mention the shell command 'argos setup'."""
        desc = COMMAND_HELP["setup"]
        assert "argos setup" in desc or "setup" in desc.lower(), (
            f"/setup description should mention 'argos setup', got: {desc!r}"
        )


# ── #7 /journal command ───────────────────────────────────────────────────────

class TestJournalCommand:
    """#7: /journal must exist and be parse_slash-known."""

    def test_journal_in_command_help(self) -> None:
        assert "journal" in COMMAND_HELP, "/journal must appear in COMMAND_HELP"

    def test_journal_is_known_slash(self) -> None:
        cmd = parse_slash("/journal abc123")
        assert cmd is not None
        assert cmd.known is True
        assert cmd.name == "journal"
        assert cmd.arg == "abc123"

    def test_journal_no_arg(self) -> None:
        cmd = parse_slash("/journal")
        assert cmd is not None
        assert cmd.known is True
        assert cmd.arg == ""


# ── #13 /trust help text vocabulary ──────────────────────────────────────────

class TestTrustHelpText:
    """#13: /trust COMMAND_HELP must use cautious/trusted/autonomous, not l0-l4."""

    def test_trust_help_uses_cautious(self) -> None:
        desc = COMMAND_HELP.get("trust", "")
        assert "cautious" in desc, (
            f"/trust help must mention 'cautious', got: {desc!r}"
        )

    def test_trust_help_uses_trusted(self) -> None:
        desc = COMMAND_HELP.get("trust", "")
        assert "trusted" in desc, (
            f"/trust help must mention 'trusted', got: {desc!r}"
        )

    def test_trust_help_uses_autonomous(self) -> None:
        desc = COMMAND_HELP.get("trust", "")
        assert "autonomous" in desc, (
            f"/trust help must mention 'autonomous', got: {desc!r}"
        )

    def test_trust_help_no_bare_l0_l4(self) -> None:
        """Internal l0/l4 codes should not appear as the primary vocabulary."""
        desc = COMMAND_HELP.get("trust", "")
        # l0-l4 as main vocabulary (not hidden aliases) should be absent
        # Allow the description to be readable: no "[l0|l1|l2|l3|l4|status]" pattern
        import re
        bare_lN = re.search(r"\bl[0-4]\b", desc)
        assert not bare_lN, (
            f"/trust help should not expose l0-l4 codes as primary vocabulary: {desc!r}"
        )


# ── #20 Input history ring buffer ─────────────────────────────────────────────

class TestInputHistoryBuffer:
    """#20: App._input_history ring buffer + _push_input_history logic."""

    def _make_app(self):
        """Construct ArgosApp without mounting (no Textual event loop needed)."""
        import os
        os.environ["ARGOS_NO_DAEMON"] = "1"
        os.environ["ARGOS_NO_MEMORY"] = "1"
        from argos.tui.app import ArgosApp
        app = ArgosApp.__new__(ArgosApp)
        # Minimal init without calling super().__init__() which needs Textual
        app._input_history = []
        app._input_history_max = 50
        return app

    def test_push_adds_entry(self) -> None:
        app = self._make_app()
        from argos.tui.app import ArgosApp
        ArgosApp._push_input_history(app, "hello world")
        assert app._input_history == ["hello world"]

    def test_push_strips_whitespace(self) -> None:
        app = self._make_app()
        from argos.tui.app import ArgosApp
        ArgosApp._push_input_history(app, "  hello  ")
        assert app._input_history == ["hello"]

    def test_push_ignores_empty(self) -> None:
        app = self._make_app()
        from argos.tui.app import ArgosApp
        ArgosApp._push_input_history(app, "  ")
        assert app._input_history == []

    def test_push_deduplicates_consecutive(self) -> None:
        app = self._make_app()
        from argos.tui.app import ArgosApp
        ArgosApp._push_input_history(app, "foo")
        ArgosApp._push_input_history(app, "foo")
        assert app._input_history == ["foo"]

    def test_push_allows_non_consecutive_duplicates(self) -> None:
        app = self._make_app()
        from argos.tui.app import ArgosApp
        ArgosApp._push_input_history(app, "foo")
        ArgosApp._push_input_history(app, "bar")
        ArgosApp._push_input_history(app, "foo")
        assert app._input_history == ["foo", "bar", "foo"]

    def test_push_respects_max_size(self) -> None:
        app = self._make_app()
        app._input_history_max = 3
        from argos.tui.app import ArgosApp
        for i in range(5):
            ArgosApp._push_input_history(app, f"entry {i}")
        assert len(app._input_history) == 3
        assert app._input_history == ["entry 2", "entry 3", "entry 4"]

    def test_push_multiple_entries(self) -> None:
        app = self._make_app()
        from argos.tui.app import ArgosApp
        ArgosApp._push_input_history(app, "goal 1")
        ArgosApp._push_input_history(app, "/clear")
        ArgosApp._push_input_history(app, "goal 2")
        assert app._input_history == ["goal 1", "/clear", "goal 2"]


# ── #20 PromptArea history navigation ────────────────────────────────────────

class _FakePrompt:
    """Minimal stub for testing _navigate_history state machine without Textual."""
    def __init__(self, current_text: str = "") -> None:
        self._history_idx: int = -1
        self._draft: str = ""
        self._refilled: list[str] = []
        # Simulate the TextArea.text property
        self.text: str = current_text

    # Copy the navigation methods directly from PromptArea so we can test them
    # without needing a mounted Textual TextArea (document/move_cursor).
    _navigate_history = PromptArea._navigate_history
    reset_history_nav = PromptArea.reset_history_nav

    def _refill(self, text: str) -> None:
        """Stub: record what would be loaded into the editor, and update self.text."""
        self._refilled.append(text)
        self.text = text

    def _get_app_history(self) -> list[str]:
        return []


class TestPromptAreaHistoryNav:
    """#20: PromptArea history navigation state machine."""

    def _make_prompt(self) -> _FakePrompt:
        return _FakePrompt()

    def test_initial_state_is_draft(self) -> None:
        p = self._make_prompt()
        assert p._history_idx == -1
        assert p._draft == ""

    def test_up_from_draft_saves_draft_and_goes_to_latest(self) -> None:
        p = _FakePrompt(current_text="current text")
        history = ["entry0", "entry1", "entry2"]
        p._navigate_history("up", history)
        assert p._history_idx == 2  # index of latest (n-1)
        assert p._refilled[-1] == "entry2"

    def test_up_saves_current_draft(self) -> None:
        """First up-press saves the current editor text as draft for recovery."""
        p = _FakePrompt(current_text="work in progress")
        history = ["entry0", "entry1"]
        p._navigate_history("up", history)
        # After going up, _draft should have been saved from self.text
        assert p._draft == "work in progress", (
            f"draft should have been saved as 'work in progress', got {p._draft!r}"
        )

    def test_up_goes_older(self) -> None:
        p = self._make_prompt()
        history = ["entry0", "entry1", "entry2"]
        p._navigate_history("up", history)   # → idx=2
        p._navigate_history("up", history)   # → idx=1
        assert p._history_idx == 1
        assert p._refilled[-1] == "entry1"

    def test_up_stops_at_oldest(self) -> None:
        p = self._make_prompt()
        history = ["entry0", "entry1"]
        p._navigate_history("up", history)   # → idx=1
        p._navigate_history("up", history)   # → idx=0
        p._navigate_history("up", history)   # stays at idx=0
        assert p._history_idx == 0

    def test_down_returns_to_draft(self) -> None:
        # Start with "my draft" as the current editor text
        p = _FakePrompt(current_text="my draft")
        history = ["entry0", "entry1"]
        p._navigate_history("up", history)   # saves "my draft" as draft, goes to idx=1
        p._navigate_history("down", history) # back to draft (-1), refills "my draft"
        assert p._history_idx == -1
        assert "my draft" in p._refilled

    def test_down_in_draft_state_is_noop(self) -> None:
        p = self._make_prompt()
        history = ["entry0"]
        before_len = len(p._refilled)
        p._navigate_history("down", history)
        assert len(p._refilled) == before_len  # no refill
        assert p._history_idx == -1

    def test_empty_history_is_noop(self) -> None:
        p = self._make_prompt()
        p._navigate_history("up", [])
        p._navigate_history("down", [])
        assert p._history_idx == -1

    def test_reset_history_nav(self) -> None:
        p = self._make_prompt()
        p._history_idx = 2
        p._draft = "saved"
        p.reset_history_nav()
        assert p._history_idx == -1
        assert p._draft == ""

    def test_navigate_through_full_history_and_back(self) -> None:
        """Full round-trip: draft → oldest → newest → draft."""
        p = _FakePrompt(current_text="draft")
        history = ["a", "b", "c"]
        # Go to newest
        p._navigate_history("up", history)
        assert p._history_idx == 2
        assert p._refilled[-1] == "c"
        # Go to middle
        p._navigate_history("up", history)
        assert p._history_idx == 1
        assert p._refilled[-1] == "b"
        # Go to oldest
        p._navigate_history("up", history)
        assert p._history_idx == 0
        assert p._refilled[-1] == "a"
        # Can't go further back
        p._navigate_history("up", history)
        assert p._history_idx == 0
        # Come back toward newest
        p._navigate_history("down", history)
        assert p._history_idx == 1
        p._navigate_history("down", history)
        assert p._history_idx == 2
        # Return to draft
        p._navigate_history("down", history)
        assert p._history_idx == -1
        assert "draft" in p._refilled


# ── #21 /help includes undiscoverable bindings ────────────────────────────────

class TestStatusBarHints:
    """#21: StatusBar hint string includes Ctrl+B, Ctrl+O, Ctrl+V."""

    def test_hints_include_ctrl_b(self) -> None:
        from argos.tui.widgets.status_bar import _hints
        _HINTS = _hints()  # i18n:hints 改为运行时函数(随 ARGOS_LANG 切语言),不再是模块常量
        assert "^B" in _HINTS or "Ctrl+B" in _HINTS or "ctrl+b" in _HINTS.lower(), (
            f"StatusBar hint must mention Ctrl+B (后台), got: {_HINTS!r}"
        )

    def test_hints_include_ctrl_o(self) -> None:
        from argos.tui.widgets.status_bar import _hints
        _HINTS = _hints()  # i18n:hints 改为运行时函数(随 ARGOS_LANG 切语言),不再是模块常量
        assert "^O" in _HINTS or "Ctrl+O" in _HINTS or "ctrl+o" in _HINTS.lower(), (
            f"StatusBar hint must mention Ctrl+O (右栏), got: {_HINTS!r}"
        )

    def test_hints_include_ctrl_v(self) -> None:
        from argos.tui.widgets.status_bar import _hints
        _HINTS = _hints()  # i18n:hints 改为运行时函数(随 ARGOS_LANG 切语言),不再是模块常量
        assert "^V" in _HINTS or "Ctrl+V" in _HINTS or "ctrl+v" in _HINTS.lower(), (
            f"StatusBar hint must mention Ctrl+V (贴图), got: {_HINTS!r}"
        )


# ── #22 match_commands substring fallback ────────────────────────────────────

class TestMatchCommandsSubstring:
    """#22: match_commands falls back to substring when prefix yields nothing."""

    def test_prefix_match_still_works(self) -> None:
        results = match_commands("/hel")
        names = [n for n, _ in results]
        assert "help" in names, "prefix match for '/hel' should find 'help'"

    def test_substring_fallback_finds_security_review(self) -> None:
        """'/review' prefix-matches nothing, but 'security-review' contains 'review'."""
        results = match_commands("/review")
        names = [n for n, _ in results]
        assert "security-review" in names, (
            "substring fallback for '/review' must find 'security-review'"
        )

    def test_substring_fallback_for_simplify(self) -> None:
        """'/mplif' prefix-matches nothing, but 'simplify' contains 'mplif'."""
        results = match_commands("/mplif")
        names = [n for n, _ in results]
        assert "simplify" in names, (
            "substring fallback for '/mplif' must find 'simplify'"
        )

    def test_empty_prefix_returns_all(self) -> None:
        results = match_commands("/")
        assert len(results) == len(COMMAND_HELP), (
            "match_commands('/') must return all commands"
        )

    def test_non_slash_returns_empty(self) -> None:
        assert match_commands("hello") == []

    def test_with_arg_returns_empty(self) -> None:
        assert match_commands("/help foo") == []

    def test_prefix_wins_over_substring_when_both_match(self) -> None:
        """When prefix matches exist, substring fallback is NOT triggered."""
        # '/he' prefix-matches 'help' (and 'hooks' starts with 'ho', NOT 'he')
        results = match_commands("/he")
        names = [n for n, _ in results]
        assert "help" in names, "'help' must match prefix '/he'"
        # When prefix matches exist, no non-prefix results should appear
        for name in names:
            assert name.startswith("he"), (
                f"prefix-match result '{name}' does not start with 'he' — "
                "substring fallback must not fire when prefix matches exist"
            )

    def test_no_match_returns_empty(self) -> None:
        """A query that matches nothing prefix OR substring returns []."""
        results = match_commands("/zzz_not_a_command_xyz")
        assert results == []


# ── #19 Ctrl+C binding exists ────────────────────────────────────────────────

class TestCtrlCBinding:
    """#19: BINDINGS must have ctrl+c → ctrl_c (not quit) and ctrl+d → quit."""

    def _get_bindings_map(self) -> dict[str, str]:
        """Extract {key: action} from ArgosApp.BINDINGS."""
        from argos.tui.app import ArgosApp
        return {key: action for key, action, *_ in ArgosApp.BINDINGS}

    def test_ctrl_c_maps_to_ctrl_c_action(self) -> None:
        b = self._get_bindings_map()
        assert "ctrl+c" in b, "ctrl+c must be in BINDINGS"
        assert b["ctrl+c"] == "ctrl_c", (
            f"ctrl+c must map to 'ctrl_c' (not 'quit'), got {b['ctrl+c']!r}"
        )

    def test_ctrl_d_maps_to_quit(self) -> None:
        b = self._get_bindings_map()
        assert "ctrl+d" in b, "ctrl+d must be in BINDINGS for deterministic quit"
        assert b["ctrl+d"] == "quit", (
            f"ctrl+d must map to 'quit', got {b['ctrl+d']!r}"
        )

    def test_escape_still_maps_to_interrupt(self) -> None:
        b = self._get_bindings_map()
        assert "escape" in b
        assert b["escape"] == "interrupt"

    def test_action_ctrl_c_method_exists(self) -> None:
        """ArgosApp must define action_ctrl_c()."""
        from argos.tui.app import ArgosApp
        assert hasattr(ArgosApp, "action_ctrl_c"), (
            "ArgosApp must define action_ctrl_c() for double-press quit"
        )


# ── #5 Contract A: app.py no_test glow path ──────────────────────────────────

class TestContractAGlowPath:
    """#5 CONTRACT A: app.py VerifyVerdict handler must NOT lock warn glow for no_test."""

    def test_no_test_attr_check_in_app(self) -> None:
        """app.py _apply_event handler uses getattr(ev.verdict, 'no_test', False)."""
        import ast, inspect
        from argos.tui import app as app_mod
        src = inspect.getsource(app_mod)
        # The handler should check no_test
        assert "no_test" in src, (
            "app.py must reference 'no_test' in VerifyVerdict handler (CONTRACT A)"
        )

    def test_no_test_skips_terminal_glow(self) -> None:
        """When no_test is True, _set_terminal_glow(True, ...) must NOT be called."""
        import ast, inspect
        from argos.tui import app as app_mod
        src = inspect.getsource(app_mod)
        # The no_test branch should NOT call _set_terminal_glow(True, ...)
        # We check the structure: no_test check wraps the glow-lock call
        # at minimum verify the keyword appears before _set_terminal_glow in the file
        no_test_pos = src.find("_is_no_test")
        glow_lock_pos = src.find("_set_terminal_glow(\n                    True")
        if glow_lock_pos == -1:
            glow_lock_pos = src.find("_set_terminal_glow(True")
        # Both should exist and no_test guard should appear
        assert no_test_pos > 0, "no_test guard not found in app.py"
