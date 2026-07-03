"""Internal documentation."""
from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from argos.lsp.config import (
    LspConfig,
    LspServerConfig,
    LspConfigError,
    BUILTIN_DEFAULT_CONFIG,
    load,
)
from argos.lsp import get_config, reload_config, _reset_config



def test_lsp_server_config_frozen():
    """Internal documentation."""
    s = LspServerConfig(
        command=("pyright-langserver", "--stdio"),
        filetypes=(".py", ".pyi"),
    )
    assert s.command == ("pyright-langserver", "--stdio")
    assert s.filetypes == (".py", ".pyi")
    assert s.disabled is False
    assert s.init_options == {}
    assert s.env == {}
    with pytest.raises(FrozenInstanceError):
        s.disabled = True  # type: ignore[misc]


def test_lsp_server_config_with_init_options():
    """Internal documentation."""
    s = LspServerConfig(
        command=("rust-analyzer",),
        filetypes=(".rs",),
        init_options={"cargo": {"allFeatures": True}},
        env={"RUST_LOG": "debug"},
        disabled=True,
    )
    assert s.init_options == {"cargo": {"allFeatures": True}}
    assert s.env == {"RUST_LOG": "debug"}
    assert s.disabled is True


def test_lsp_server_config_empty_command_raises():
    """Internal documentation."""
    with pytest.raises(ValueError, match="command"):
        LspServerConfig(command=(), filetypes=(".py",))


def test_lsp_server_config_empty_filetypes_raises():
    """Internal documentation."""
    with pytest.raises(ValueError, match="filetypes"):
        LspServerConfig(command=("x",), filetypes=())


def test_lsp_server_config_filetype_no_dot_raises():
    """Internal documentation."""
    with pytest.raises(ValueError, match=r"\."):
        LspServerConfig(command=("x",), filetypes=("py",))


def test_lsp_config_construction():
    """Internal documentation."""
    s = LspServerConfig(command=("pyright-langserver", "--stdio"), filetypes=(".py",))
    cfg = LspConfig(version=1, servers={"python": s})
    assert cfg.version == 1
    assert "python" in cfg.servers
    assert cfg.servers["python"].command == ("pyright-langserver", "--stdio")


def test_lsp_config_server_name_special_chars_raises():
    """Internal documentation."""
    s = LspServerConfig(command=("x",), filetypes=(".py",))
    with pytest.raises(ValueError, match="name"):
        LspConfig(version=1, servers={"py thon": s})


def test_lsp_config_empty():
    """Internal documentation."""
    cfg = LspConfig.empty()
    assert cfg.version == 1
    assert cfg.servers == {}


def test_builtin_default_has_python_only():
    """Internal documentation."""
    assert "python" in BUILTIN_DEFAULT_CONFIG.servers
    assert BUILTIN_DEFAULT_CONFIG.servers["python"].command == ("pyright-langserver", "--stdio")
    assert "rust" not in BUILTIN_DEFAULT_CONFIG.servers
    assert "typescript" not in BUILTIN_DEFAULT_CONFIG.servers


def test_lsp_config_error_is_exception():
    """Internal documentation."""
    err = LspConfigError("bad json")
    assert isinstance(err, Exception)
    assert "bad json" in str(err)



def test_load_default_path_honors_argos_config_dir(tmp_path, monkeypatch):
    from argos import config as C
    from argos.lsp import config as LC

    cfg_dir = tmp_path / "cfg"
    lsp_file = cfg_dir / "lsp.json"
    lsp_file.parent.mkdir(parents=True)
    lsp_file.write_text(json.dumps({"version": 1, "servers": {}}))
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(C, "_ENV", {})
    monkeypatch.setattr(LC, "LSP_CONFIG_PATH", None)

    assert load().servers == {}


def test_load_missing_file_returns_builtin(tmp_path, monkeypatch):
    """Internal documentation."""
    monkeypatch.setattr("argos.lsp.config.LSP_CONFIG_PATH", tmp_path / "nope.json")
    cfg = load()
    assert "python" in cfg.servers
    assert cfg.servers["python"].command == ("pyright-langserver", "--stdio")


def test_load_valid_minimal(tmp_path, monkeypatch):
    """Internal documentation."""
    p = tmp_path / "lsp.json"
    p.write_text(json.dumps({
        "version": 1,
        "servers": {
            "python": {"command": ["pyright-langserver", "--stdio"], "filetypes": [".py", ".pyi"]},
        },
    }))
    monkeypatch.setattr("argos.lsp.config.LSP_CONFIG_PATH", p)
    cfg = load()
    assert cfg.version == 1
    assert "python" in cfg.servers


def test_load_valid_multi_server(tmp_path, monkeypatch):
    """Internal documentation."""
    p = tmp_path / "lsp.json"
    p.write_text(json.dumps({
        "version": 1,
        "servers": {
            "python": {"command": ["pyright-langserver", "--stdio"], "filetypes": [".py"]},
            "rust": {
                "command": ["rust-analyzer"],
                "filetypes": [".rs"],
                "init_options": {"cargo": {"allFeatures": True}},
            },
            "disabled_one": {
                "command": ["x"],
                "filetypes": [".y"],
                "disabled": True,
                "env": {"FOO": "bar"},
            },
        },
    }))
    monkeypatch.setattr("argos.lsp.config.LSP_CONFIG_PATH", p)
    cfg = load()
    assert len(cfg.servers) == 3
    assert cfg.servers["rust"].init_options == {"cargo": {"allFeatures": True}}
    assert cfg.servers["disabled_one"].disabled is True
    assert cfg.servers["disabled_one"].env == {"FOO": "bar"}


def test_load_invalid_json_raises(tmp_path, monkeypatch):
    """Internal documentation."""
    p = tmp_path / "lsp.json"
    p.write_text("{not valid json")
    monkeypatch.setattr("argos.lsp.config.LSP_CONFIG_PATH", p)
    with pytest.raises(LspConfigError):
        load()


def test_load_missing_version_raises(tmp_path, monkeypatch):
    """Internal documentation."""
    p = tmp_path / "lsp.json"
    p.write_text(json.dumps({"servers": {}}))
    monkeypatch.setattr("argos.lsp.config.LSP_CONFIG_PATH", p)
    with pytest.raises(LspConfigError, match="version"):
        load()


def test_load_wrong_version_raises(tmp_path, monkeypatch):
    """Internal documentation."""
    p = tmp_path / "lsp.json"
    p.write_text(json.dumps({"version": 2, "servers": {}}))
    monkeypatch.setattr("argos.lsp.config.LSP_CONFIG_PATH", p)
    with pytest.raises(LspConfigError, match="version"):
        load()


def test_load_command_not_array_raises(tmp_path, monkeypatch):
    """Internal documentation."""
    p = tmp_path / "lsp.json"
    p.write_text(json.dumps({
        "version": 1,
        "servers": {"x": {"command": "pyright-langserver --stdio", "filetypes": [".py"]}},
    }))
    monkeypatch.setattr("argos.lsp.config.LSP_CONFIG_PATH", p)
    with pytest.raises(LspConfigError, match="command"):
        load()


def test_load_filetypes_empty_raises(tmp_path, monkeypatch):
    """Internal documentation."""
    p = tmp_path / "lsp.json"
    p.write_text(json.dumps({
        "version": 1,
        "servers": {"x": {"command": ["y"], "filetypes": []}},
    }))
    monkeypatch.setattr("argos.lsp.config.LSP_CONFIG_PATH", p)
    with pytest.raises(LspConfigError, match="filetypes"):
        load()


def test_load_server_name_with_space_raises(tmp_path, monkeypatch):
    """Internal documentation."""
    p = tmp_path / "lsp.json"
    p.write_text(json.dumps({
        "version": 1,
        "servers": {"py thon": {"command": ["y"], "filetypes": [".py"]}},
    }))
    monkeypatch.setattr("argos.lsp.config.LSP_CONFIG_PATH", p)
    with pytest.raises(LspConfigError, match="name"):
        load()


def test_load_unreadable_file_treated_as_missing(tmp_path, monkeypatch):
    """Internal documentation."""
    p = tmp_path / "lsp.json"
    p.write_text(json.dumps({"version": 1, "servers": {}}))
    p.chmod(0o000)
    monkeypatch.setattr("argos.lsp.config.LSP_CONFIG_PATH", p)
    try:
        cfg = load()
        assert "python" in cfg.servers
    finally:
        p.chmod(0o644)


def test_reload_replaces_singleton(tmp_path, monkeypatch):
    """Internal documentation."""
    p = tmp_path / "lsp.json"
    p.write_text(json.dumps({
        "version": 1,
        "servers": {"python": {"command": ["a"], "filetypes": [".py"]}},
    }))
    monkeypatch.setattr("argos.lsp.config.LSP_CONFIG_PATH", p)
    cfg1 = reload_config()
    assert "python" in cfg1.servers
    p.write_text(json.dumps({
        "version": 1,
        "servers": {
            "python": {"command": ["a"], "filetypes": [".py"]},
            "rust": {"command": ["b"], "filetypes": [".rs"]},
        },
    }))
    cfg2 = reload_config()
    assert "rust" in cfg2.servers
    assert "rust" in get_config().servers


def test_reload_invalid_keeps_old(tmp_path, monkeypatch):
    """Internal documentation."""
    p = tmp_path / "lsp.json"
    p.write_text(json.dumps({
        "version": 1,
        "servers": {"python": {"command": ["a"], "filetypes": [".py"]}},
    }))
    monkeypatch.setattr("argos.lsp.config.LSP_CONFIG_PATH", p)
    cfg_old = reload_config()
    p.write_text("{not json")
    with pytest.raises(LspConfigError):
        reload_config()
    assert get_config() is cfg_old
    assert "python" in get_config().servers
