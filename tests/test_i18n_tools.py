"""Wave 2c i18n guard — tools layer English discriminator path.

Confirms that under ARGOS_LANG=en:
  - Tool error strings start with "Error:" (not "错误:")
  - argos.i18n.is_error_result() detects them correctly
  - Non-error strings are NOT flagged as errors

These guards catch EN-path regressions that the zh-default suite
(conftest.py sets ARGOS_LANG=zh) never exercises.
"""
from __future__ import annotations

import pytest

from argos import i18n


@pytest.fixture(autouse=True)
def _en_lang(monkeypatch):
    """Force ARGOS_LANG=en for all tests in this module."""
    monkeypatch.setenv("ARGOS_LANG", "en")
    i18n._catalog.cache_clear()
    yield
    i18n._catalog.cache_clear()


# ── plan_mode error paths ──────────────────────────────────────────────────────

def test_plan_enter_busy_is_error_en():
    """EnterPlanMode busy path → EN string starts with 'Error:' and is detected."""
    from argos.core.plan_mode import EnterPlanMode

    class _BusyLoop:
        _busy = True
        mode = "act"

    msg = EnterPlanMode(_BusyLoop())
    assert msg.startswith("Error:"), f"Expected 'Error:' prefix, got: {msg!r}"
    assert i18n.is_error_result(msg), f"is_error_result should be True for: {msg!r}"


def test_plan_exit_not_in_plan_is_error_en():
    """ExitPlanMode when not in plan mode → EN string starts with 'Error:'."""
    from argos.core.plan_mode import ExitPlanMode

    class _ActLoop:
        mode = "act"

    msg = ExitPlanMode(_ActLoop(), action="approve_start")
    assert msg.startswith("Error:"), f"Expected 'Error:' prefix, got: {msg!r}"
    assert i18n.is_error_result(msg)


def test_plan_exit_refine_no_feedback_is_error_en():
    """ExitPlanMode refine without feedback → EN string starts with 'Error:'."""
    from argos.core.plan_mode import ExitPlanMode

    class _PlanLoop:
        mode = "plan"
        _plan_decision = None

    msg = ExitPlanMode(_PlanLoop(), action="refine", feedback="")
    assert msg.startswith("Error:"), f"Expected 'Error:' prefix, got: {msg!r}"
    assert i18n.is_error_result(msg)


def test_plan_exit_invalid_action_is_error_en():
    """ExitPlanMode invalid action → EN string starts with 'Error:'."""
    from argos.core.plan_mode import ExitPlanMode

    class _PlanLoop:
        mode = "plan"
        _plan_decision = None

    msg = ExitPlanMode(_PlanLoop(), action="bogus_action")
    assert msg.startswith("Error:"), f"Expected 'Error:' prefix, got: {msg!r}"
    assert i18n.is_error_result(msg)


# ── files.py workspace-escape path ────────────────────────────────────────────

def test_files_read_outside_workspace_is_error_en(tmp_path, monkeypatch):
    """read_file with escaping path → EN string starts with 'Error:'."""
    from argos.tools import files as _files
    monkeypatch.setattr(_files, "WORKSPACE", tmp_path.resolve())

    msg = _files.read_file("../../etc/passwd")
    assert msg.startswith("Error:"), f"Expected 'Error:' prefix, got: {msg!r}"
    assert i18n.is_error_result(msg)


def test_files_write_outside_workspace_is_error_en(tmp_path, monkeypatch):
    """write_file with escaping path → EN string starts with 'Error:'."""
    from argos.tools import files as _files
    monkeypatch.setattr(_files, "WORKSPACE", tmp_path.resolve())

    msg = _files.write_file("../escape.txt", "x")
    assert msg.startswith("Error:"), f"Expected 'Error:' prefix, got: {msg!r}"
    assert i18n.is_error_result(msg)


def test_files_edit_outside_workspace_is_error_en(tmp_path, monkeypatch):
    """edit_file with escaping path → EN string starts with 'Error:'."""
    from argos.tools import files as _files
    monkeypatch.setattr(_files, "WORKSPACE", tmp_path.resolve())

    msg = _files.edit_file("../../etc/passwd", "old", "new")
    assert msg.startswith("Error:"), f"Expected 'Error:' prefix, got: {msg!r}"
    assert i18n.is_error_result(msg)


# ── plan_mode guard (tools/__init__.py) ───────────────────────────────────────

def test_plan_mode_blocked_is_error_en():
    """plan-mode sandbox guard → EN string starts with 'Error:'."""
    from argos.core.plan_mode import set_plan_mode
    from argos.tools import write_file_gated

    set_plan_mode(True)
    try:
        msg = write_file_gated(path="x.py", content="y")
        assert msg.startswith("Error:"), f"Expected 'Error:' prefix, got: {msg!r}"
        assert i18n.is_error_result(msg)
    finally:
        set_plan_mode(False)


# ── non-error strings must NOT be flagged ─────────────────────────────────────

def test_non_error_strings_not_flagged_en(tmp_path, monkeypatch):
    """Success strings from files.py do NOT start with 'Error:' and are not flagged."""
    from argos.tools import files as _files
    monkeypatch.setattr(_files, "WORKSPACE", tmp_path.resolve())

    write_msg = _files.write_file("ok.txt", "hello")
    assert not i18n.is_error_result(write_msg), (
        f"Success string should not be an error: {write_msg!r}"
    )
    assert "Error:" not in write_msg


def test_plan_enter_ok_not_error_en():
    """EnterPlanMode success path → not an error string."""
    from argos.core.plan_mode import EnterPlanMode, set_plan_mode

    class _ActLoop:
        _busy = False
        mode = "act"
        def _emit_phase(self, _): pass

    set_plan_mode(False)
    try:
        msg = EnterPlanMode(_ActLoop())
        assert not i18n.is_error_result(msg), f"Should not be error: {msg!r}"
    finally:
        set_plan_mode(False)
