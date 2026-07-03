from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest




def test_command_help_includes_lsp():
    from argos.tui.commands import COMMAND_HELP
    assert "lsp" in COMMAND_HELP
    assert "reload" in COMMAND_HELP["lsp"]




@pytest.fixture
def isolated_lsp_home(monkeypatch):
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv("HOME", tmp)
    yield Path(tmp) / ".argos"
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


def test_lsp_reload_invalid_keeps_old(isolated_lsp_home, monkeypatch):
    from argos.lsp import _reset_config, get_config, reload_config, LspConfigError
    from argos.lsp import config as _lsp_config
    isolated_lsp_home.mkdir(parents=True, exist_ok=True)
    p = isolated_lsp_home / "lsp.json"
    p.write_text(json.dumps({
        "version": 1,
        "servers": {
            "python": {"command": ["a"], "filetypes": [".py"]},
        },
    }))
    monkeypatch.setattr(_lsp_config, "LSP_CONFIG_PATH", p)
    _reset_config()
    cfg_old = reload_config()
    p.write_text("{not json")
    with pytest.raises(LspConfigError):
        reload_config()
    assert get_config() is cfg_old




def test_bad_config_splash_banner_lsp_message():
    from argos.tui.widgets.splash import StartupSplash
    sp = StartupSplash(model_label="x", tier="default", live=True)
    sp.set_bad_config("LSP parse error: bad json at line 3")
    text = sp.renderable_text
    assert "LSP" in text
    assert "已禁用" in text
    assert "parse error" in text




def test_lsp_cmd_lists_servers(isolated_lsp_home, monkeypatch):
    from argos.lsp import _reset_config, reload_config
    from argos.lsp import config as _lsp_config
    isolated_lsp_home.mkdir(parents=True, exist_ok=True)
    p = isolated_lsp_home / "lsp.json"
    p.write_text(json.dumps({
        "version": 1,
        "servers": {
            "python": {"command": ["a"], "filetypes": [".py"]},
            "rust": {"command": ["b"], "filetypes": [".rs"]},
            "disabled_one": {
                "command": ["c"], "filetypes": [".x"], "disabled": True,
            },
        },
    }))
    monkeypatch.setattr(_lsp_config, "LSP_CONFIG_PATH", p)
    _reset_config()
    cfg = reload_config()
    assert len(cfg.servers) == 3
    from argos.lsp import get_manager
    mgr = get_manager()
    servers_info = mgr.list_servers()
    assert len(servers_info) == 3
    statuses = {s["name"]: s["status"] for s in servers_info}
    assert statuses["python"] == "NotStarted"
    assert statuses["rust"] == "NotStarted"
    assert cfg.servers["disabled_one"].disabled is True


@pytest.mark.asyncio
async def test_lsp_empty_mentions_configured_path(tmp_path, monkeypatch):
    from argos import config as C
    from argos.lsp import _reset_config
    from argos.lsp import config as _lsp_config
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    (cfg_dir / "lsp.json").write_text(json.dumps({"version": 1, "servers": {}}))
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(C, "_ENV", {})
    monkeypatch.setattr(_lsp_config, "LSP_CONFIG_PATH", None)
    _reset_config()

    log = Log()
    await ArgosApp()._lsp_cmd(log, "")

    text = "\n".join(line for line, _kind in log.lines)
    assert str(cfg_dir / "lsp.json") in text
    assert "~/.argos" not in text


@pytest.mark.asyncio
async def test_lsp_unknown_arg_prints_usage(isolated_lsp_home, monkeypatch):
    from argos.lsp import _reset_config
    from argos.lsp import config as _lsp_config
    from argos.tui.app import ArgosApp

    isolated_lsp_home.mkdir(parents=True, exist_ok=True)
    p = isolated_lsp_home / "lsp.json"
    p.write_text(json.dumps({"version": 1, "servers": {}}))
    monkeypatch.setattr(_lsp_config, "LSP_CONFIG_PATH", p)
    _reset_config()

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    log = Log()
    await ArgosApp()._lsp_cmd(log, "bogus")

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" in text or "用法" in text
    assert any(kind == "error" for _line, kind in log.lines)


@pytest.mark.asyncio
async def test_lsp_reload_arg_is_case_insensitive(isolated_lsp_home, monkeypatch):
    """/lsp RELOAD should behave like /lsp reload."""
    from argos.lsp import _reset_config
    from argos.lsp import config as _lsp_config
    from argos.tui.app import ArgosApp

    isolated_lsp_home.mkdir(parents=True, exist_ok=True)
    p = isolated_lsp_home / "lsp.json"
    p.write_text(json.dumps({"version": 1, "servers": {}}))
    monkeypatch.setattr(_lsp_config, "LSP_CONFIG_PATH", p)
    _reset_config()

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    log = Log()
    await ArgosApp()._lsp_cmd(log, "RELOAD")

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" not in text and "用法" not in text
    assert any(kind == "system" for _line, kind in log.lines)
