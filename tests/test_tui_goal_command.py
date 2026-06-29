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
    app._loop_factory = _noop_loop_factory
    app._with_daemon = False
    app._daemon_client = None
    app._daemon_session_id = None
    app._input_history = []
    app._input_history_max = 50
    return app


class _NoopLoop:
    """Minimal stub — no verify_cmd class attribute (phantom attr masked the inline bug)."""

    async def run(self, goal, session_id=None, **kwargs):
        # yield nothing — we only care about dispatch, not run body
        return
        yield  # make it an async generator  # noqa: unreachable


def _noop_loop_factory(verify_cmd: str | None = None) -> _NoopLoop:
    """Factory that accepts verify_cmd kwarg (matching the real build_loop_factory signature)."""
    return _NoopLoop()


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


# ── /schedule is now wired (Task 2.3): inline mode → honest daemon-required msg ──

@pytest.mark.asyncio
async def test_known_unwired_command_shows_honest_fallback():
    """/schedule (now wired, Task 2.3) in inline mode → honest daemon-required message."""
    from argos.tui.commands import parse_slash

    app = ArgosApp(loop_factory=_noop_loop_factory)
    async with app.run_test() as pilot:
        await pilot.pause()
        cmd = parse_slash("/schedule every 1h: dream")
        assert cmd is not None and cmd.known is True
        await app._dispatch_slash(cmd)
        txt = app.query_one("#transcript", Transcript).rendered_text
        # Wired handler: inline mode produces daemon-required message
        assert "daemon" in txt.lower() or "argosd" in txt.lower()


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


# ── daemon path: verify_cmd flows through DaemonClient.create_run → POST body ─

@pytest.mark.asyncio
async def test_daemon_client_verify_cmd_in_payload():
    """DaemonClient.create_run(verify_cmd='pytest') includes verify_cmd in the POST body."""
    import json as _json
    from unittest.mock import AsyncMock, patch
    from argos.daemon.client import DaemonClient
    from pathlib import Path

    client = DaemonClient(Path("/nonexistent.sock"))
    captured: list[dict] = []

    async def _fake_request(method, path, *, session_id=None, body=None):
        captured.append(body or {})
        # simulate 201 {"run_id": "abc123456789"}
        raw = _json.dumps({"run_id": "abc123456789"}).encode()
        return 201, {}, raw

    with patch.object(client, "_request", side_effect=_fake_request):
        rid = await client.create_run(
            "test-session", goal="fix auth", verify_cmd="pytest -q"
        )

    assert rid == "abc123456789"
    assert len(captured) == 1
    assert captured[0].get("verify_cmd") == "pytest -q"


@pytest.mark.asyncio
async def test_daemon_client_no_verify_cmd_omits_key():
    """DaemonClient.create_run without verify_cmd does NOT include verify_cmd key."""
    import json as _json
    from unittest.mock import patch
    from argos.daemon.client import DaemonClient
    from pathlib import Path

    client = DaemonClient(Path("/nonexistent.sock"))
    captured: list[dict] = []

    async def _fake_request(method, path, *, session_id=None, body=None):
        captured.append(body or {})
        raw = _json.dumps({"run_id": "abc123456789"}).encode()
        return 201, {}, raw

    with patch.object(client, "_request", side_effect=_fake_request):
        await client.create_run("test-session", goal="fix auth")

    assert "verify_cmd" not in captured[0]


# ── daemon path: _daemon_create_run forwards verify_cmd ──────────────────────

@pytest.mark.asyncio
async def test_daemon_create_run_forwards_verify_cmd():
    """_daemon_create_run passes verify_cmd kwarg to DaemonClient.create_run."""
    from unittest.mock import AsyncMock

    app = _make_app()
    app._with_daemon = True
    app._workspace = __import__("pathlib").Path("/tmp")

    class _FakeClient:
        async def create_run(self, session_id, *, goal, workspace, approval_level,
                             attachments=None, verify_cmd=None):
            self._last_verify_cmd = verify_cmd
            return "run-abc"

    fake_client = _FakeClient()
    app._daemon_client = fake_client  # type: ignore[attr-defined]
    app._daemon_session_id = "sid-123"  # type: ignore[attr-defined]

    rid = await app._daemon_create_run("fix the tests", None, verify_cmd="pytest -x")
    assert rid == "run-abc"
    assert fake_client._last_verify_cmd == "pytest -x"


# ── build_run_stack: verify_cmd overrides LoopConfig ─────────────────────────

def test_build_run_stack_verify_cmd_overrides_loop_config(tmp_path):
    """build_run_stack(verify_cmd='pytest') produces a loop_factory that returns
    a loop whose config.verify_cmd equals 'pytest'."""
    from unittest.mock import MagicMock, patch
    from argos.app_factory import build_run_stack, AppComponents
    from argos.core.loop import LoopConfig, AgentLoop
    from argos.approval import ApprovalLevel

    # Minimal AppComponents stub — build_run_stack only needs a few fields
    c = MagicMock(spec=AppComponents)
    c.config = LoopConfig(model_tier="default", verify_cmd=None)
    c.workspace = tmp_path
    c.registry = None
    c.browser_controller = None
    c.permissions_config = MagicMock()

    created_configs: list[LoopConfig] = []

    class _StubLoop:
        def __init__(self, **kwargs):
            created_configs.append(kwargs["config"])

    with patch("argos.app_factory._make_gate_broker_sandbox") as mock_gbs, \
         patch("argos.app_factory.AgentLoop", _StubLoop), \
         patch("argos.app_factory.EventBus"):
        mock_gbs.return_value = (MagicMock(), MagicMock(), MagicMock())
        stack = build_run_stack(c, workspace=tmp_path, verify_cmd="pytest -q")
        stack.loop_factory()

    assert len(created_configs) == 1
    assert created_configs[0].verify_cmd == "pytest -q"


# ── inline path: verify_cmd reaches AgentLoop._cfg via build_loop_factory ─────

def test_build_loop_factory_verify_cmd_reaches_loop_config(tmp_path):
    """build_loop_factory returns a factory that accepts verify_cmd and passes it
    into the AgentLoop config — the real inline path (was a silent no-op before fix).
    This test FAILS against the pre-fix code (factory was nullary) and PASSES after."""
    from unittest.mock import MagicMock, patch
    from argos.app_factory import build_loop_factory, AppComponents
    from argos.core.loop import LoopConfig

    c = MagicMock(spec=AppComponents)
    c.config = LoopConfig(model_tier="default", verify_cmd=None)
    c.workspace = tmp_path

    created_configs: list[LoopConfig] = []

    class _StubLoop:
        def __init__(self, **kwargs):
            created_configs.append(kwargs["config"])

    with patch("argos.app_factory.AgentLoop", _StubLoop), \
         patch("argos.app_factory.EventBus"):
        factory = build_loop_factory(c)
        # call with verify_cmd — this is what _start_run_inline now does
        factory(verify_cmd="pytest --tb=short")

    assert len(created_configs) == 1, "loop was not constructed"
    assert created_configs[0].verify_cmd == "pytest --tb=short", (
        "verify_cmd did not reach LoopConfig — inline path still broken"
    )


def test_build_loop_factory_nullary_call_preserves_config_verify_cmd(tmp_path):
    """build_loop_factory()(no verify_cmd) leaves LoopConfig.verify_cmd unchanged."""
    from unittest.mock import MagicMock, patch
    from argos.app_factory import build_loop_factory, AppComponents
    from argos.core.loop import LoopConfig

    c = MagicMock(spec=AppComponents)
    c.config = LoopConfig(model_tier="default", verify_cmd="pre-existing")
    c.workspace = tmp_path

    created_configs: list[LoopConfig] = []

    class _StubLoop:
        def __init__(self, **kwargs):
            created_configs.append(kwargs["config"])

    with patch("argos.app_factory.AgentLoop", _StubLoop), \
         patch("argos.app_factory.EventBus"):
        factory = build_loop_factory(c)
        factory()  # nullary — should not clobber

    assert created_configs[0].verify_cmd == "pre-existing"
