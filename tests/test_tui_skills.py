"""Internal documentation."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import argos.skills_curator.index as _idx
import argos.skills_curator.capabilities as _cap
from argos.tui.commands import COMMAND_HELP, parse_slash


def _make_skill_md(*, name: str, enabled: bool = True) -> str:
    return (
        f"---\nname: {name}\nversion: 0.1.0\nauthor: t\n"
        f"description: test\ncapabilities: [read]\n"
        f"enabled: {str(bool(enabled)).lower()}\n---\n\nbody\n"
    )


class _FakeLog:
    """Async-capable fake transcript log."""

    def __init__(self):
        self.lines: list[tuple[str, str]] = []

    async def append_line(self, text: str, kind: str = "system") -> None:
        self.lines.append((text, kind))


# ── COMMAND_HELP ────────────────────────────────────────────


def test_command_help_includes_skills():
    assert "skills" in COMMAND_HELP
    assert "list" in COMMAND_HELP["skills"] or "install" in COMMAND_HELP["skills"]


def test_parse_slash_skills_recognized():
    cmd = parse_slash("/skills")
    assert cmd is not None
    assert cmd.name == "skills"
    assert cmd.arg == ""


def test_parse_slash_skills_install_recognized():
    cmd = parse_slash("/skills install python-lint")
    assert cmd is not None
    assert cmd.name == "skills"
    assert cmd.arg == "install python-lint"


# ── /skills no args (list installed + available) ────────────────


@pytest.mark.asyncio
async def test_skills_command_no_args_lists_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)
    for n in ("a", "b"):
        d = tmp_path / n
        d.mkdir()
        (d / "SKILL.md").write_text(_make_skill_md(name=n), encoding="utf-8")

    from argos.tui.app import ArgosApp
    app = ArgosApp()
    app._last_skills_arg = ""
    log = _FakeLog()
    await app._show_skills(log)
    assert len(log.lines) >= 1
    text, kind = log.lines[0]
    assert kind == "system"
    assert "Installed skills" in text
    assert "a" in text and "b" in text


@pytest.mark.asyncio
async def test_skills_command_no_installed_prints_message(tmp_path, monkeypatch):
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)
    from argos.tui.app import ArgosApp
    app = ArgosApp()
    app._last_skills_arg = ""
    log = _FakeLog()
    await app._show_skills(log)
    assert any("Installed skills" in t for t, _ in log.lines)




@pytest.mark.asyncio
async def test_skills_install_subcommand_writes_hint(tmp_path, monkeypatch):
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)
    from argos.tui.app import ArgosApp
    app = ArgosApp()
    app._last_skills_arg = "install python-lint"
    log = _FakeLog()
    await app._show_skills(log)
    text, _ = log.lines[0]
    assert "host" in text.lower()
    assert "install python-lint" in text


@pytest.mark.asyncio
async def test_skills_install_subcommand_is_case_insensitive(tmp_path, monkeypatch):
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)
    from argos.tui.app import ArgosApp
    app = ArgosApp()
    app._last_skills_arg = "INSTALL python-lint"
    log = _FakeLog()
    await app._show_skills(log)
    text, kind = log.lines[0]
    assert kind == "system"
    assert "host" in text.lower()
    assert "install python-lint" in text.lower()


@pytest.mark.asyncio
async def test_skills_remove_subcommand_writes_hint(tmp_path, monkeypatch):
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)
    from argos.tui.app import ArgosApp
    app = ArgosApp()
    app._last_skills_arg = "remove python-lint"
    log = _FakeLog()
    await app._show_skills(log)
    text, _ = log.lines[0]
    assert "host" in text.lower()
    assert "remove python-lint" in text


@pytest.mark.asyncio
async def test_skills_refresh_subcommand_writes_hint(tmp_path, monkeypatch):
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)
    from argos.tui.app import ArgosApp
    app = ArgosApp()
    app._last_skills_arg = "refresh"
    log = _FakeLog()
    await app._show_skills(log)
    text, _ = log.lines[0]
    assert "host" in text.lower()
    assert "refresh" in text


@pytest.mark.asyncio
async def test_skills_test_subcommand_writes_hint(tmp_path, monkeypatch):
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)
    from argos.tui.app import ArgosApp
    app = ArgosApp()
    app._last_skills_arg = "test python-lint"
    log = _FakeLog()
    await app._show_skills(log)
    text, _ = log.lines[0]
    assert "host" in text.lower()
    assert "test python-lint" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("sub", ["install", "remove", "test"])
async def test_skills_named_subcommands_require_name(tmp_path, monkeypatch, sub):
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)
    from argos.tui.app import ArgosApp
    app = ArgosApp()
    app._last_skills_arg = sub
    log = _FakeLog()
    await app._show_skills(log)
    text, kind = log.lines[0]
    assert kind == "error"
    assert f"/skills {sub} <name>" in text


@pytest.mark.asyncio
async def test_skills_named_subcommand_rejects_extra_args(tmp_path, monkeypatch):
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)
    from argos.tui.app import ArgosApp
    app = ArgosApp()
    app._last_skills_arg = "install python-lint extra"
    log = _FakeLog()
    await app._show_skills(log)
    text, kind = log.lines[0]
    assert kind == "error"
    assert "Usage" in text or "用法" in text


@pytest.mark.asyncio
async def test_skills_refresh_rejects_extra_args(tmp_path, monkeypatch):
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)
    from argos.tui.app import ArgosApp
    app = ArgosApp()
    app._last_skills_arg = "refresh now"
    log = _FakeLog()
    await app._show_skills(log)
    text, kind = log.lines[0]
    assert kind == "error"
    assert "Usage" in text or "用法" in text


@pytest.mark.asyncio
async def test_skills_unknown_subcommand_prints_usage(tmp_path, monkeypatch):
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)
    from argos.tui.app import ArgosApp
    app = ArgosApp()
    app._last_skills_arg = "bogus"
    log = _FakeLog()
    await app._show_skills(log)
    text, kind = log.lines[0]
    assert kind == "error"
    assert "Usage" in text or "用法" in text




@pytest.mark.asyncio
async def test_skills_command_includes_builtin_three(tmp_path, monkeypatch):
    """Internal documentation."""
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)
    from argos.tui.app import ArgosApp
    app = ArgosApp()
    app._last_skills_arg = ""
    log = _FakeLog()
    await app._show_skills(log)




@pytest.mark.asyncio
async def test_skills_command_no_args_includes_recommendations(tmp_path, monkeypatch):
    """Internal documentation."""
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)
    from argos.skills_curator import recommend as _rec
    monkeypatch.setattr(
        _rec, "build_activity_from_session",
        lambda: _rec.SessionActivity(files_edited=("a.py", "b.py", "c.py", "d.py")),
    )
    from argos.tui.app import ArgosApp
    app = ArgosApp()
    app._last_skills_arg = ""
    log = _FakeLog()
    await app._show_skills(log)
    text = "\n".join(t for t, _ in log.lines)
    assert "Recommended" in text
    assert "python-lint" in text
