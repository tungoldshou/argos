"""/goal and /loop slash command dispatch — verify_cmd threading + honest fallback.

Run:
    /Users/zc/Projects/argos/.venv/bin/pytest tests/test_tui_goal_command.py -v --no-cov -p no:cacheprovider
"""
from __future__ import annotations

import pytest

from argos.tui.app import ArgosApp
from argos.tui.widgets.transcript import Transcript


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_app() -> ArgosApp:
    """Minimal ArgosApp without __init__ — only the fields _goal_cmd / _dispatch_slash touch."""
    app = ArgosApp.__new__(ArgosApp)
    app._run_active = False
    app._loop_factory = lambda: _NoopLoop()
    app._with_daemon = False
    app._daemon_client = None
    app._daemon_session_id = None
    app._input_history = []
    app._input_history_max = 50
    return app


class _NoopLoop:
    """Minimal stub — has verify_cmd attribute so the inline path can set it."""
    verify_cmd: str | None = None

    async def run(self, goal, session_id=None, **kwargs):
        # yield nothing — we only care about verify_cmd being set before run() is called
        return
        yield  # make it an async generator  # noqa: unreachable


# ── _parse_verify_arg unit tests (no app context needed) ─────────────────────

def test_parse_pipe_syntax():
    app = _make_app()
    goal, vcmd = app._parse_verify_arg("fix bug | verify: pytest")
    assert goal == "fix bug"
    assert vcmd == "pytest"


def test_parse_flag_syntax():
    app = _make_app()
    goal, vcmd = app._parse_verify_arg("fix bug --verify pytest -x")
    assert goal == "fix bug"
    assert vcmd == "pytest -x"


def test_parse_no_verify():
    app = _make_app()
    goal, vcmd = app._parse_verify_arg("just a task")
    assert goal == "just a task"
    assert vcmd is None


# ── /goal handler: verify_cmd flows into start_run ───────────────────────────

@pytest.mark.asyncio
async def test_goal_with_verify_submits_run_with_verify_cmd():
    """/goal X | verify: pytest submits start_run with verify_cmd='pytest'."""
    submitted: list[dict] = []

    async def _fake_start_run(goal: str, attachments=None, *, verify_cmd=None):
        submitted.append({"goal": goal, "verify_cmd": verify_cmd})

    app = _make_app()
    app.start_run = _fake_start_run  # type: ignore[method-assign]

    log = Transcript()
    await app._goal_cmd(log, "goal", "write tests | verify: pytest")

    assert len(submitted) == 1
    assert submitted[0]["goal"] == "write tests"
    assert submitted[0]["verify_cmd"] == "pytest"


@pytest.mark.asyncio
async def test_goal_without_verify_submits_run_with_none():
    """/goal X with no verify clause → verify_cmd=None."""
    submitted: list[dict] = []

    async def _fake_start_run(goal: str, attachments=None, *, verify_cmd=None):
        submitted.append({"goal": goal, "verify_cmd": verify_cmd})

    app = _make_app()
    app.start_run = _fake_start_run  # type: ignore[method-assign]

    log = Transcript()
    await app._goal_cmd(log, "goal", "write tests")

    assert len(submitted) == 1
    assert submitted[0]["verify_cmd"] is None


# ── /loop handler: until: alias maps to verify_cmd ───────────────────────────

@pytest.mark.asyncio
async def test_loop_until_alias_maps_to_verify_cmd():
    """/loop <task> until: <cmd> submits run with verify_cmd=<cmd>."""
    submitted: list[dict] = []

    async def _fake_start_run(goal: str, attachments=None, *, verify_cmd=None):
        submitted.append({"goal": goal, "verify_cmd": verify_cmd})

    app = _make_app()
    app.start_run = _fake_start_run  # type: ignore[method-assign]

    log = Transcript()
    await app._goal_cmd(log, "loop", "run the suite until: pytest -q")

    assert len(submitted) == 1
    assert submitted[0]["verify_cmd"] == "pytest -q"


# ── /schedule falls through to honest unwired message ────────────────────────

@pytest.mark.asyncio
async def test_known_unwired_command_shows_honest_fallback():
    """/schedule (known, no handler) → honest 'not wired yet' message, not silence."""
    from argos.tui.commands import parse_slash

    app = ArgosApp(loop_factory=lambda: _NoopLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        cmd = parse_slash("/schedule 0 3 * * * dream")
        assert cmd is not None and cmd.known is True
        await app._dispatch_slash(cmd)
        txt = app.query_one("#transcript", Transcript).rendered_text
        assert "schedule" in txt
        # must mention something about being unwired / coming soon
        assert "wired" in txt.lower() or "batch" in txt.lower() or "实现" in txt


# ── busy guard ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_goal_busy_guard():
    """/goal while run is active → no new run, busy message."""
    submitted: list[dict] = []

    async def _fake_start_run(goal: str, attachments=None, *, verify_cmd=None):
        submitted.append({"goal": goal, "verify_cmd": verify_cmd})

    app = _make_app()
    app._run_active = True
    app.start_run = _fake_start_run  # type: ignore[method-assign]

    log = Transcript()
    await app._goal_cmd(log, "goal", "write tests | verify: pytest")

    assert submitted == []
    # tui.run.busy message (zh: "当前任务进行中"; en: "Task in progress")
    assert "进行中" in log.rendered_text or "in progress" in log.rendered_text.lower()
