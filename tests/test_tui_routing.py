"""Internal documentation."""
import json
from pathlib import Path

import pytest

from argos.routing.categorizer import TaskCategory
from argos.routing.config import (
    RoutingConfig, load_routing, set_category,
)
from argos.tui.commands import parse_slash


def test_parse_slash_routing_known():
    cmd = parse_slash("/routing")
    assert cmd is not None
    assert cmd.name == "routing"
    assert cmd.known is True
    assert cmd.arg == ""


def test_parse_slash_routing_set_args():
    cmd = parse_slash("/routing set verify strong")
    assert cmd is not None
    assert cmd.name == "routing"
    assert cmd.arg == "set verify strong"


def test_tui_routing_unknown_subcommand_prints_usage(monkeypatch):
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    app = ArgosApp()
    monkeypatch.setattr(app, "_current_router", lambda: None)
    log = Log()

    asyncio.run(app._routing_cmd(log, "bogus"))

    assert any("Usage" in line or "用法" in line for line, _kind in log.lines)
    assert any(kind == "error" for _line, kind in log.lines)


def test_tui_routing_set_subcommand_is_case_insensitive(monkeypatch):
    import asyncio
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    app = ArgosApp()
    called: list[str] = []

    async def fake_routing_set(log, arg: str) -> None:
        called.append(arg)
        await log.append_line("set", kind="done")

    monkeypatch.setattr(app, "_routing_set", fake_routing_set)
    log = Log()

    asyncio.run(app._routing_cmd(log, "SET verify strong"))

    assert called == ["verify strong"]
    assert not any("Usage" in line or "用法" in line for line, _kind in log.lines)


def test_routing_config_set_persists(tmp_path):
    """Internal documentation."""
    (tmp_path / "config.json").write_text(json.dumps({
        "models": {"default": {}, "cheap": {}, "strong": {}},
        "active": "default",
    }))
    set_category(tmp_path, TaskCategory.VERIFY, "strong")
    cfg = load_routing(tmp_path)
    assert cfg.by_category["verify"] == "strong"


def test_routing_config_set_unknown_tier_raises(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({
        "models": {"default": {}}, "active": "default",
    }))
    with pytest.raises(Exception) as exc_info:
        set_category(tmp_path, TaskCategory.VERIFY, "srong")
    assert "srong" in str(exc_info.value)


def test_routing_config_set_invalid_category_raises(tmp_path):
    from argos.config import ConfigError
    with pytest.raises(ValueError):
        TaskCategory("foo_bar")


def test_tui_routing_set_rejects_profile_with_missing_key(tmp_path, monkeypatch):
    import asyncio
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
    asyncio.run(ArgosApp()._routing_set(log, "verify b"))

    text = "\n".join(line for line, _kind in log.lines)
    assert "BK" in text
    assert any(kind == "error" for _line, kind in log.lines)
    raw = json.loads((cfg_dir / "config.json").read_text())
    assert raw.get("routing", {}).get("by_category", {}).get("verify") is None


def test_tui_routing_set_allows_active_profile_not_named_default(tmp_path, monkeypatch):
    import asyncio
    from argos.tui.app import ArgosApp

    cfg_dir = tmp_path / ".argos"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text(json.dumps({
        "active": "local",
        "models": {
            "local": {
                "protocol": "openai",
                "base_url": "https://api.example.com/v1",
                "model": "model-local",
                "api_key_env": "AK",
            },
            "strong": {
                "protocol": "openai",
                "base_url": "https://api.example.com/v1",
                "model": "model-strong",
                "api_key_env": "SK",
            },
        },
    }))
    (cfg_dir / ".env").write_text("AK=secret\nSK=secret\n")
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    log = Log()
    asyncio.run(ArgosApp()._routing_set(log, "verify strong"))

    assert any(kind == "done" for _line, kind in log.lines)
    raw = json.loads((cfg_dir / "config.json").read_text())
    assert raw["routing"]["by_category"]["verify"] == "strong"
    assert load_routing(cfg_dir).default == "local"


def test_tui_routing_set_honors_env_local_config_dir(tmp_path, monkeypatch):
    import asyncio
    from argos import config as C
    from argos.tui.app import ArgosApp

    cfg_dir = tmp_path / "from-env-local"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text(json.dumps({
        "active": "local",
        "models": {
            "local": {
                "protocol": "openai",
                "base_url": "https://api.example.com/v1",
                "model": "model-local",
                "api_key_env": "AK",
            },
            "strong": {
                "protocol": "openai",
                "base_url": "https://api.example.com/v1",
                "model": "model-strong",
                "api_key_env": "SK",
            },
        },
    }))
    (cfg_dir / ".env").write_text("AK=secret\nSK=secret\n")
    monkeypatch.delenv("ARGOS_CONFIG_DIR", raising=False)
    monkeypatch.setattr(C, "_ENV", {"ARGOS_CONFIG_DIR": str(cfg_dir)})

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    log = Log()
    asyncio.run(ArgosApp()._routing_set(log, "verify strong"))

    assert any(kind == "done" for _line, kind in log.lines)
    raw = json.loads((cfg_dir / "config.json").read_text())
    assert raw["routing"]["by_category"]["verify"] == "strong"


def test_routing_config_builtin_default_when_no_routing(tmp_path):
    """Internal documentation."""
    from argos.routing.config import _DEFAULT_BY_CATEGORY
    cfg = load_routing(tmp_path)
    assert cfg.by_category == _DEFAULT_BY_CATEGORY
    assert cfg.tier_force_confirm == []


def test_routing_config_safe_default_when_no_file(tmp_path):
    cfg = load_routing(tmp_path)
    assert cfg.default == "default"


def test_routing_config_force_confirm_helper():
    cfg = RoutingConfig(tier_force_confirm=["strong"])
    assert cfg.is_force_confirm("strong") is True
    assert cfg.is_force_confirm("cheap") is False


def test_activity_panel_cost_update_renders_tier_label():
    """Internal documentation."""
    import inspect
    from argos.tui.widgets.activity_panel import ActivityPanel
    sig = inspect.signature(ActivityPanel.on_cost)
    assert "tier_name" in sig.parameters
    assert sig.parameters["tier_name"].default == ""


def test_activity_panel_on_cost_default_no_tier_label():
    """Internal documentation."""
    import inspect
    from argos.tui.widgets.activity_panel import ActivityPanel
    sig = inspect.signature(ActivityPanel.on_cost)
    assert sig.parameters["tier_name"].default == ""
