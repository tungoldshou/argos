"""Internal documentation."""
from __future__ import annotations

import pytest

from argos.tui.commands import SlashCommand, parse_slash, COMMAND_NAMES, COMMAND_HELP, match_commands


def test_known_commands_listed():
    assert set(COMMAND_NAMES) == {
        "yolo", "trust",
        "undo", "clear", "retry", "status", "model", "resume", "cost",
        "help", "tools", "skills", "mcp", "plan", "hooks",
        "lsp",
        "permissions",
        "verify", "security-review", "simplify",  # 2026-06-06:3 skill slash
        "runs",
        "eval",
        "routing",
        "context",
        "ledger",
        "orders",
        "confirm",
        "dismiss",
        "dream",
        "setup",
        "voice",    # C5 honest entry: voice input not wired in this build
        "journal",
        "loop", "goal", "schedule", "watch",
    }


def test_capability_discovery_commands_known():
    """Internal documentation."""
    for name in ("help", "tools", "skills", "mcp"):
        cmd = parse_slash(f"/{name}")
        assert cmd is not None and cmd.known is True, f"/{name} 应为已知命令"


def test_argos_app_exposes_slash_handler_table():
    """Internal documentation."""
    from argos.tui.app import ArgosApp

    handlers = ArgosApp._slash_handlers()

    for name in (
        "trust", "model", "status", "cost", "clear", "resume", "help",
        "tools", "skills", "mcp", "setup", "eval", "routing", "context",
        "dream", "schedule", "watch", "voice",
    ):
        assert name in handlers


def test_argos_app_default_workspace_uses_argos_config_dir(tmp_path, monkeypatch):
    from argos import config as C
    from argos.tui.app import ArgosApp

    cfg_dir = tmp_path / "cfg"
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(C, "_ENV", {})

    app = ArgosApp()

    assert app._workspace == cfg_dir / "workspace"


def test_parse_plain_text_is_not_a_command():
    assert parse_slash("帮我修个 bug") is None


def test_parse_bare_command():
    cmd = parse_slash("/yolo")
    assert isinstance(cmd, SlashCommand)
    assert cmd.name == "yolo" and cmd.arg == ""


def test_parse_command_with_arg():
    cmd = parse_slash("/model premium")
    assert cmd.name == "model" and cmd.arg == "premium"


def test_parse_strips_whitespace():
    cmd = parse_slash("  /resume   2  ")
    assert cmd.name == "resume" and cmd.arg == "2"


def test_parse_unknown_command_returns_error_marker():
    cmd = parse_slash("/frobnicate")
    assert cmd is not None
    assert cmd.name == "frobnicate"
    assert cmd.known is False


def test_dispatch_unknown_slash_logs_error_kind(monkeypatch):
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    app = ArgosApp()
    log = Log()
    monkeypatch.setattr(app, "query_one", lambda *_args, **_kwargs: log)

    asyncio.run(app._dispatch_slash(parse_slash("/frobnicate")))

    assert log.lines
    assert log.lines[-1][1] == "error"


def test_known_flag_true_for_valid():
    assert parse_slash("/cost").known is True


def test_help_with_command_arg_shows_only_that_command():
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    log = Log()
    asyncio.run(ArgosApp()._cmd_help(log, "model"))

    text = "\n".join(line for line, _kind in log.lines)
    assert "/model" in text
    assert "restart" in text.lower() or "重启" in text
    assert "/clear" not in text


def test_help_with_command_arg_is_case_insensitive():
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    log = Log()
    asyncio.run(ArgosApp()._cmd_help(log, "MODEL"))

    text = "\n".join(line for line, _kind in log.lines)
    assert "/model" in text
    assert "Unknown" not in text and "未知" not in text
    assert not any(kind == "error" for _line, kind in log.lines)


def test_help_with_unknown_command_arg_reports_error():
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    log = Log()
    asyncio.run(ArgosApp()._cmd_help(log, "frobnicate"))

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" in text or "用法" in text
    assert "frobnicate" in text
    assert any(kind == "error" for _line, kind in log.lines)


def test_status_rejects_unexpected_arg_without_querying_status_bar(monkeypatch):
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    called = False

    def fake_query_one(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("status bar should not be queried")

    app = ArgosApp()
    monkeypatch.setattr(app, "query_one", fake_query_one)
    log = Log()
    asyncio.run(app._cmd_status(log, "run-123"))

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" in text or "用法" in text
    assert any(kind == "error" for _line, kind in log.lines)
    assert not called


def test_cost_rejects_unexpected_arg_without_querying_activity(monkeypatch):
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    called = False

    def fake_query_one(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("activity panel should not be queried")

    app = ArgosApp()
    monkeypatch.setattr(app, "query_one", fake_query_one)
    log = Log()
    asyncio.run(app._cmd_cost(log, "run-123"))

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" in text or "用法" in text
    assert any(kind == "error" for _line, kind in log.lines)
    assert not called


# ── Batch 2: /loop /goal /schedule /watch parse-layer registration ─────────

def test_new_loop_commands_in_command_help():
    """All 4 new commands appear in COMMAND_HELP with non-empty descriptions."""
    for name in ("loop", "goal", "schedule", "watch"):
        assert name in COMMAND_HELP, f"/{name} missing from COMMAND_HELP"
        assert COMMAND_HELP[name], f"/{name} has empty description"


def test_loop_command_help_matches_single_run_verify_semantics():
    desc = COMMAND_HELP["loop"].lower()
    assert "repeatedly" not in desc
    assert "循环执行" not in desc
    assert "verify" in desc or "验证" in desc


def test_schedule_command_help_matches_colon_parser():
    desc = COMMAND_HELP["schedule"]
    assert "/schedule <when>: <goal>" in desc
    assert "<cron> <task>" not in desc


def test_watch_command_help_matches_goal_template_semantics():
    desc = COMMAND_HELP["watch"]
    assert "/watch <glob> <goal>" in desc
    assert "/watch <glob> <task>" not in desc
    assert "/watch <glob> <任务>" not in desc


def test_eval_command_help_shows_compare_task_model_syntax():
    desc = COMMAND_HELP["eval"]
    assert "/eval compare <task_id>[:<model>] <task_id>[:<model>]" in desc
    assert "/eval compare <a> <b>" not in desc


def test_goal_command_help_says_verify_is_optional():
    desc = COMMAND_HELP["goal"].lower()
    assert "optional" in desc or "可选" in desc


def test_runs_command_help_mentions_focus_action():
    desc = COMMAND_HELP["runs"]
    assert "focus" in desc


def test_model_command_help_mentions_restart_required():
    desc = COMMAND_HELP["model"]
    assert "restart" in desc.lower() or "重启" in desc


def test_model_command_reports_invalid_config_instead_of_fallback(tmp_path, monkeypatch):
    import asyncio
    import json
    from argos.tui.app import ArgosApp

    cfg_dir = tmp_path / ".argos"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text(json.dumps({
        "active": "bad",
        "models": {
            "bad": {
                "protocol": "bogus",
                "base_url": "https://api.example.com",
                "model": "broken-model",
                "api_key_env": "BAD_KEY",
            },
        },
    }))
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    log = Log()
    asyncio.run(ArgosApp()._cmd_model(log, ""))

    text = "\n".join(line for line, _kind in log.lines)
    assert "default" not in text
    assert "bogus" in text
    assert any(kind == "error" for _line, kind in log.lines)


def test_model_command_rejects_profile_with_missing_key(tmp_path, monkeypatch):
    import asyncio
    import json
    from argos.tui.app import ArgosApp

    cfg_dir = tmp_path / ".argos"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text(json.dumps({
        "active": "a",
        "models": {
            "a": {
                "protocol": "openai",
                "base_url": "https://api.example.com/v1",
                "model": "model-a",
                "api_key_env": "AK",
            },
            "b": {
                "protocol": "openai",
                "base_url": "https://api.example.com/v1",
                "model": "model-b",
                "api_key_env": "BK",
            },
        },
    }))
    (cfg_dir / ".env").write_text("AK=secret\n")
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))
    monkeypatch.delenv("BK", raising=False)

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    log = Log()
    asyncio.run(ArgosApp()._cmd_model(log, "b"))

    text = "\n".join(line for line, _kind in log.lines)
    assert "BK" in text
    assert any(kind == "error" for _line, kind in log.lines)
    assert json.loads((cfg_dir / "config.json").read_text())["active"] == "a"


def test_model_command_lists_missing_key_profiles(tmp_path, monkeypatch):
    import asyncio
    import json
    from argos.tui.app import ArgosApp

    cfg_dir = tmp_path / ".argos"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text(json.dumps({
        "active": "a",
        "models": {
            "a": {
                "protocol": "openai",
                "base_url": "https://api.example.com/v1",
                "model": "model-a",
                "api_key_env": "AK",
            },
            "b": {
                "protocol": "openai",
                "base_url": "https://api.example.com/v1",
                "model": "model-b",
                "api_key_env": "BK",
            },
        },
    }))
    (cfg_dir / ".env").write_text("AK=secret\n")
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))
    monkeypatch.delenv("BK", raising=False)

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    log = Log()
    asyncio.run(ArgosApp()._cmd_model(log, ""))

    text = "\n".join(line for line, _kind in log.lines)
    assert "a *" in text
    assert "b" in text
    assert "BK" in text
    assert "缺" in text or "missing" in text.lower()


def test_model_command_list_marks_switched_profile(tmp_path, monkeypatch):
    import asyncio
    import json
    from argos.tui.app import ArgosApp

    cfg_dir = tmp_path / ".argos"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text(json.dumps({
        "active": "a",
        "models": {
            "a": {
                "protocol": "openai",
                "base_url": "https://api.example.com/v1",
                "model": "model-a",
                "api_key_env": "AK",
            },
            "b": {
                "protocol": "openai",
                "base_url": "https://api.example.com/v1",
                "model": "model-b",
                "api_key_env": "BK",
            },
        },
    }))
    (cfg_dir / ".env").write_text("AK=secret-a\nBK=secret-b\n")
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    app = ArgosApp()
    asyncio.run(app._cmd_model(Log(), "b"))
    log = Log()
    asyncio.run(app._cmd_model(log, ""))

    text = "\n".join(line for line, _kind in log.lines)
    assert "b *" in text
    assert "a *" not in text


def test_trust_command_help_lists_paranoid_mode():
    desc = COMMAND_HELP["trust"]
    assert "paranoid" in desc


def test_trust_status_is_case_insensitive():
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []
            self.blocks: list[object] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

        async def mount_block(self, block: object) -> None:
            self.blocks.append(block)

    log = Log()
    asyncio.run(ArgosApp()._trust_cmd(log, "STATUS"))

    text = "\n".join(line for line, _kind in log.lines)
    assert "Unknown" not in text and "未知" not in text
    assert log.blocks


def test_trust_unknown_mode_is_error():
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    log = Log()
    asyncio.run(ArgosApp()._trust_cmd(log, "banana"))

    text = "\n".join(line for line, _kind in log.lines)
    assert "Unknown" in text or "未知" in text
    assert any(kind == "error" for _line, kind in log.lines)


def test_unwired_fallback_copy_does_not_promise_future_batch():
    from argos.i18n import t

    msg = t("tui.cmd.unwired", name="example").lower()
    assert "future batch" not in msg
    assert "后续批次" not in msg


def test_setup_hint_mentions_existing_environment_variable():
    from argos.i18n import t

    msg = t("tui.setup.hint").lower()
    assert "existing environment variable" in msg or "已有环境变量" in msg
    assert "key source" in msg or "key 来源" in msg
    assert "provider, api key" not in msg


def test_setup_hint_uses_configured_argos_dir(tmp_path, monkeypatch):
    import asyncio
    from argos import config as C
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    cfg_dir = tmp_path / "custom-argos"
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(C, "_ENV", {})

    log = Log()
    asyncio.run(ArgosApp()._setup_cmd(log))

    text = "\n".join(line for line, _kind in log.lines)
    assert str(cfg_dir / "config.json") in text
    assert str(cfg_dir / ".env") in text
    assert "~/.argos" not in text


def test_voice_command_is_honest_unavailable_notice():
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    log = Log()
    asyncio.run(ArgosApp()._cmd_voice(log, ""))

    text = "\n".join(line for line, _kind in log.lines).lower()
    assert "voice" in text or "语音" in text
    assert "not enabled" in text or "未启用" in text
    assert any(kind == "warn" for _line, kind in log.lines)


def test_voice_rejects_unexpected_arg():
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    log = Log()
    asyncio.run(ArgosApp()._cmd_voice(log, "record"))

    text = "\n".join(line for line, _kind in log.lines).lower()
    assert "usage" in text or "用法" in text
    assert "not enabled" not in text and "未启用" not in text
    assert any(kind == "error" for _line, kind in log.lines)


def test_yolo_rejects_unexpected_arg_without_escalating():
    import asyncio
    from argos.approval import ApprovalLevel
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    app = ArgosApp()
    log = Log()
    asyncio.run(app._cmd_yolo(log, "typo"))

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" in text or "用法" in text
    assert any(kind == "error" for _line, kind in log.lines)
    assert app.gate.level is not ApprovalLevel.AUTO


def test_clear_rejects_unexpected_arg_without_clearing_session():
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.cleared = False
            self.lines: list[tuple[str, str | None]] = []

        async def clear(self) -> None:
            self.cleared = True

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    app = ArgosApp()
    before = app._session_id
    app._step_blocks["x"] = object()
    log = Log()
    asyncio.run(app._cmd_clear(log, "typo"))

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" in text or "用法" in text
    assert any(kind == "error" for _line, kind in log.lines)
    assert not log.cleared
    assert app._session_id == before
    assert app._step_blocks


def test_undo_rejects_unexpected_arg_without_restoring(monkeypatch):
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    called = False

    async def fake_undo(log) -> None:
        nonlocal called
        called = True

    app = ArgosApp()
    monkeypatch.setattr(app, "_undo", fake_undo)
    log = Log()
    asyncio.run(app._cmd_undo(log, "typo"))

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" in text or "用法" in text
    assert any(kind == "error" for _line, kind in log.lines)
    assert not called


def test_plan_rejects_unexpected_arg_without_entering_plan_mode(monkeypatch):
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    called = False

    async def fake_enter_plan_mode(log) -> None:
        nonlocal called
        called = True

    app = ArgosApp()
    monkeypatch.setattr(app, "_enter_plan_mode", fake_enter_plan_mode)
    log = Log()
    asyncio.run(app._cmd_plan(log, "typo"))

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" in text or "用法" in text
    assert any(kind == "error" for _line, kind in log.lines)
    assert not called


def test_resume_rejects_unexpected_arg_without_switching_session(monkeypatch):
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    called = False

    async def fake_resume_recent(log) -> None:
        nonlocal called
        called = True

    app = ArgosApp()
    before = app._session_id
    monkeypatch.setattr(app, "_resume_recent", fake_resume_recent)
    log = Log()
    asyncio.run(app._cmd_resume(log, "typo"))

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" in text or "用法" in text
    assert any(kind == "error" for _line, kind in log.lines)
    assert app._session_id == before
    assert not called


def test_retry_rejects_unexpected_arg_without_resending(monkeypatch):
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    called = False

    async def fake_retry(log) -> None:
        nonlocal called
        called = True

    app = ArgosApp()
    monkeypatch.setattr(app, "_retry", fake_retry)
    log = Log()
    asyncio.run(app._cmd_retry(log, "typo"))

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" in text or "用法" in text
    assert any(kind == "error" for _line, kind in log.lines)
    assert not called


def test_setup_rejects_unexpected_arg_without_printing_status(monkeypatch):
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    called = False

    async def fake_setup_cmd(log) -> None:
        nonlocal called
        called = True

    app = ArgosApp()
    monkeypatch.setattr(app, "_setup_cmd", fake_setup_cmd)
    log = Log()
    asyncio.run(app._cmd_setup(log, "typo"))

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" in text or "用法" in text
    assert any(kind == "error" for _line, kind in log.lines)
    assert not called


def test_ledger_rejects_unexpected_arg_without_reading_current_run(monkeypatch):
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    called = False

    async def fake_ledger_cmd(log) -> None:
        nonlocal called
        called = True

    app = ArgosApp()
    monkeypatch.setattr(app, "_ledger_cmd", fake_ledger_cmd)
    log = Log()
    asyncio.run(app._cmd_ledger(log, "other-run"))

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" in text or "用法" in text
    assert any(kind == "error" for _line, kind in log.lines)
    assert not called


def test_journal_rejects_extra_arg_without_printing_path():
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    log = Log()
    asyncio.run(ArgosApp()._journal_cmd(log, "run-1 extra"))

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" in text or "用法" in text
    assert "run-1 extra.jsonl" not in text
    assert any(kind == "error" for _line, kind in log.lines)


def test_journal_uses_argos_config_dir(tmp_path, monkeypatch):
    import asyncio
    from argos import config as C
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    cfg_dir = tmp_path / "cfg"
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(C, "_ENV", {})

    log = Log()
    asyncio.run(ArgosApp()._journal_cmd(log, "run-1"))

    text = "\n".join(line for line, _kind in log.lines)
    assert str(cfg_dir / "ledger" / "run-1.jsonl") in text


def test_mcp_rejects_unexpected_arg_without_listing_all_tools(monkeypatch):
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    called = False

    async def fake_show_mcp(log) -> None:
        nonlocal called
        called = True

    app = ArgosApp()
    monkeypatch.setattr(app, "_show_mcp", fake_show_mcp)
    log = Log()
    asyncio.run(app._cmd_mcp(log, "server-name"))

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" in text or "用法" in text
    assert any(kind == "error" for _line, kind in log.lines)
    assert not called


def test_mcp_empty_mentions_configured_path(tmp_path, monkeypatch):
    import asyncio
    from argos import config as C
    from argos import mcp_native
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    class EmptyManager:
        def list_tools(self):
            return []

    cfg_dir = tmp_path / "cfg"
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(C, "_ENV", {})
    monkeypatch.setattr(mcp_native, "get_manager", lambda: EmptyManager())

    log = Log()
    asyncio.run(ArgosApp()._cmd_mcp(log, ""))

    text = "\n".join(line for line, _kind in log.lines)
    assert str(cfg_dir / "mcp.json") in text
    assert "~/.argos" not in text


def test_tools_rejects_unexpected_arg_without_listing_all_tools(monkeypatch):
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    called = False

    async def fake_show_tools(log) -> None:
        nonlocal called
        called = True

    app = ArgosApp()
    monkeypatch.setattr(app, "_show_tools", fake_show_tools)
    log = Log()
    asyncio.run(app._cmd_tools(log, "file"))

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" in text or "用法" in text
    assert any(kind == "error" for _line, kind in log.lines)
    assert not called


def test_orders_rejects_unexpected_arg_without_listing_orders(monkeypatch):
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    called = False

    async def fake_orders_cmd(log) -> None:
        nonlocal called
        called = True

    app = ArgosApp()
    monkeypatch.setattr(app, "_orders_cmd", fake_orders_cmd)
    log = Log()
    asyncio.run(app._cmd_orders(log, "active"))

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" in text or "用法" in text
    assert any(kind == "error" for _line, kind in log.lines)
    assert not called


def test_confirm_rejects_extra_arg_without_requesting_daemon():
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    class Client:
        async def _request(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("malformed /confirm must not reach daemon")

    app = ArgosApp()
    app._with_daemon = True
    app._daemon_client = Client()
    app._daemon_session_id = "session-1"
    log = Log()
    asyncio.run(app._confirm_suggestion_cmd(log, "suggestion-1 extra"))

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" in text or "用法" in text
    assert any(kind == "error" for _line, kind in log.lines)


def test_dismiss_rejects_extra_arg_without_requesting_daemon():
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    class Client:
        async def _request(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("malformed /dismiss must not reach daemon")

    app = ArgosApp()
    app._with_daemon = True
    app._daemon_client = Client()
    app._daemon_session_id = "session-1"
    log = Log()
    asyncio.run(app._dismiss_suggestion_cmd(log, "suggestion-1 extra"))

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" in text or "用法" in text
    assert any(kind == "error" for _line, kind in log.lines)


def test_runs_rejects_unknown_action_without_querying_run():
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    class Client:
        async def get_run(self, session_id, run_id):  # noqa: ANN001
            raise AssertionError("unknown /runs action should not query run info")

    app = ArgosApp()
    app._with_daemon = True
    app._daemon_client = Client()
    app._daemon_session_id = "session-1"
    log = Log()
    asyncio.run(app._runs_cmd(log, "run-1 typo"))

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" in text or "用法" in text
    assert any(kind == "error" for _line, kind in log.lines)


def test_runs_no_daemon_is_error():
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    app = ArgosApp()
    log = Log()
    asyncio.run(app._runs_cmd(log, ""))

    assert log.lines[0][1] == "error"


def test_runs_action_is_case_insensitive():
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    class Client:
        def __init__(self) -> None:
            self.resumed: list[tuple[str, str]] = []

        async def resume(self, session_id: str, run_id: str) -> None:
            self.resumed.append((session_id, run_id))

    client = Client()
    app = ArgosApp()
    app._with_daemon = True
    app._daemon_client = client
    app._daemon_session_id = "session-1"
    log = Log()
    asyncio.run(app._runs_cmd(log, "run-1 RESUME"))

    assert client.resumed == [("session-1", "run-1")]
    assert not any("Usage" in line or "用法" in line for line, _kind in log.lines)


def test_tui_fallback_copy_does_not_mention_demo_or_fake_modes():
    from argos.i18n import t

    msg = "\n".join([
        t("tui.retry.no_store"),
        t("tui.routing.no_router"),
    ]).lower()
    assert "demo" not in msg
    assert "fake" not in msg


def test_parse_goal_with_verify_pipe():
    """parse_slash parses /goal with pipe-style verify arg as known."""
    cmd = parse_slash("/goal fix bug | verify: pytest")
    assert cmd is not None
    assert cmd.name == "goal"
    assert cmd.arg == "fix bug | verify: pytest"
    assert cmd.known is True


def test_parse_loop_known():
    cmd = parse_slash("/loop run tests until: all pass")
    assert cmd is not None and cmd.known is True
    assert cmd.name == "loop"


def test_goal_rejects_empty_pipe_verify_without_starting_run(monkeypatch):
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    called = False

    async def fake_start_run(*args, **kwargs):  # noqa: ANN002, ANN003
        nonlocal called
        called = True

    app = ArgosApp()
    monkeypatch.setattr(app, "start_run", fake_start_run)
    log = Log()
    asyncio.run(app._goal_cmd(log, "goal", "fix bug | verify:"))

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" in text or "用法" in text
    assert any(kind == "error" for _line, kind in log.lines)
    assert not called


def test_goal_rejects_empty_flag_verify_without_starting_run(monkeypatch):
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    called = False

    async def fake_start_run(*args, **kwargs):  # noqa: ANN002, ANN003
        nonlocal called
        called = True

    app = ArgosApp()
    monkeypatch.setattr(app, "start_run", fake_start_run)
    log = Log()
    asyncio.run(app._goal_cmd(log, "goal", "fix bug --verify"))

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" in text or "用法" in text
    assert any(kind == "error" for _line, kind in log.lines)
    assert not called


def test_loop_rejects_empty_until_without_starting_run(monkeypatch):
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    called = False

    async def fake_start_run(*args, **kwargs):  # noqa: ANN002, ANN003
        nonlocal called
        called = True

    app = ArgosApp()
    monkeypatch.setattr(app, "start_run", fake_start_run)
    log = Log()
    asyncio.run(app._goal_cmd(log, "loop", "fix bug until:"))

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" in text or "用法" in text
    assert any(kind == "error" for _line, kind in log.lines)
    assert not called


@pytest.mark.parametrize("cmd_name", ["goal", "loop"])
def test_goal_commands_reject_empty_goal_as_error(monkeypatch, cmd_name):
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    called = False

    async def fake_start_run(*args, **kwargs):  # noqa: ANN002, ANN003
        nonlocal called
        called = True

    app = ArgosApp()
    monkeypatch.setattr(app, "start_run", fake_start_run)
    log = Log()
    asyncio.run(app._goal_cmd(log, cmd_name, "   "))

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" in text or "用法" in text
    assert any(kind == "error" for _line, kind in log.lines)
    assert not called


def test_parse_schedule_known():
    cmd = parse_slash("/schedule 0 3 * * * dream")
    assert cmd is not None and cmd.known is True


def test_parse_watch_known():
    cmd = parse_slash("/watch src/**/*.py run tests")
    assert cmd is not None and cmd.known is True


def test_match_commands_schedule_prefix():
    """match_commands('/sch') includes 'schedule'."""
    names = [n for n, _ in match_commands("/sch")]
    assert "schedule" in names


def test_match_commands_descriptions_follow_current_language(monkeypatch):
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_LANG", "en")
    desc = dict(match_commands("/set"))["setup"]

    assert "Show setup status" in desc
    assert "显示 setup 状态" not in desc


def test_match_commands_watch_prefix():
    names = [n for n, _ in match_commands("/wat")]
    assert "watch" in names


def test_match_commands_loop_prefix():
    names = [n for n, _ in match_commands("/lo")]
    assert "loop" in names


def test_match_commands_goal_prefix():
    names = [n for n, _ in match_commands("/go")]
    assert "goal" in names
