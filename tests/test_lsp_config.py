"""LSP 配置 dataclass 单元测试(spec §2.2) + 加载/校验/单例流程(spec §2.2 / §3 / D11)。"""
from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from argos_agent.lsp.config import (
    LspConfig,
    LspServerConfig,
    LspConfigError,
    BUILTIN_DEFAULT_CONFIG,
    LSP_CONFIG_PATH,
    load,
)
from argos_agent.lsp import get_config, reload_config, _reset_config


# ── Task 1: dataclass 单元测试 ─────────────────────────────────────

def test_lsp_server_config_frozen():
    """LspServerConfig 是 frozen dataclass;含 command/filetypes/disabled/init_options/env 字段。"""
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
    """init_options 走 dict,env 同(spec §2.2)。"""
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
    """command 空 → ValueError(防 spawn 空 argv)。"""
    with pytest.raises(ValueError, match="command"):
        LspServerConfig(command=(), filetypes=(".py",))


def test_lsp_server_config_empty_filetypes_raises():
    """filetypes 空 → ValueError(0 server 服务 = 死代码)。"""
    with pytest.raises(ValueError, match="filetypes"):
        LspServerConfig(command=("x",), filetypes=())


def test_lsp_server_config_filetype_no_dot_raises():
    """filetype 必须以 . 开头(spec §2.2)。"""
    with pytest.raises(ValueError, match=r"\."):
        LspServerConfig(command=("x",), filetypes=("py",))


def test_lsp_config_construction():
    """LspConfig 含 version + servers dict。"""
    s = LspServerConfig(command=("pyright-langserver", "--stdio"), filetypes=(".py",))
    cfg = LspConfig(version=1, servers={"python": s})
    assert cfg.version == 1
    assert "python" in cfg.servers
    assert cfg.servers["python"].command == ("pyright-langserver", "--stdio")


def test_lsp_config_server_name_special_chars_raises():
    """server name 允许 ASCII 字母数字 + _ + -(spec §2.2);含特殊字符 → ValueError。"""
    s = LspServerConfig(command=("x",), filetypes=(".py",))
    with pytest.raises(ValueError, match="name"):
        LspConfig(version=1, servers={"py thon": s})


def test_lsp_config_empty():
    """LspConfig.empty() → 全等 manager 禁用(0 server)的配置。"""
    cfg = LspConfig.empty()
    assert cfg.version == 1
    assert cfg.servers == {}


def test_builtin_default_has_python_only():
    """BUILTIN_DEFAULT_CONFIG 仅含 python server(spec §2.2)。"""
    assert "python" in BUILTIN_DEFAULT_CONFIG.servers
    assert BUILTIN_DEFAULT_CONFIG.servers["python"].command == ("pyright-langserver", "--stdio")
    assert "rust" not in BUILTIN_DEFAULT_CONFIG.servers
    assert "typescript" not in BUILTIN_DEFAULT_CONFIG.servers


def test_lsp_config_error_is_exception():
    """LspConfigError 是 Exception 子类,带 message。"""
    err = LspConfigError("bad json")
    assert isinstance(err, Exception)
    assert "bad json" in str(err)


# ── Task 2: 加载 / 校验 / 单例 ─────────────────────────────────────

def test_lsp_config_path_is_argos_home():
    """LSP_CONFIG_PATH = ~/.argos/lsp.json(spec §2.2)。"""
    assert LSP_CONFIG_PATH == Path.home() / ".argos" / "lsp.json"


def test_load_missing_file_returns_builtin(tmp_path, monkeypatch):
    """lsp.json 不存在 → load() 返 BUILTIN_DEFAULT_CONFIG(单 python)。"""
    monkeypatch.setattr("argos_agent.lsp.config.LSP_CONFIG_PATH", tmp_path / "nope.json")
    cfg = load()
    assert "python" in cfg.servers
    assert cfg.servers["python"].command == ("pyright-langserver", "--stdio")


def test_load_valid_minimal(tmp_path, monkeypatch):
    """合法最小配置:1 server(无 init_options/disabled/env)。"""
    p = tmp_path / "lsp.json"
    p.write_text(json.dumps({
        "version": 1,
        "servers": {
            "python": {"command": ["pyright-langserver", "--stdio"], "filetypes": [".py", ".pyi"]},
        },
    }))
    monkeypatch.setattr("argos_agent.lsp.config.LSP_CONFIG_PATH", p)
    cfg = load()
    assert cfg.version == 1
    assert "python" in cfg.servers


def test_load_valid_multi_server(tmp_path, monkeypatch):
    """合法配置:3 server + 带 init_options / env / disabled。"""
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
    monkeypatch.setattr("argos_agent.lsp.config.LSP_CONFIG_PATH", p)
    cfg = load()
    assert len(cfg.servers) == 3
    assert cfg.servers["rust"].init_options == {"cargo": {"allFeatures": True}}
    assert cfg.servers["disabled_one"].disabled is True
    assert cfg.servers["disabled_one"].env == {"FOO": "bar"}


def test_load_invalid_json_raises(tmp_path, monkeypatch):
    """JSON 坏字 → LspConfigError(绝不部分加载,spec D11)。"""
    p = tmp_path / "lsp.json"
    p.write_text("{not valid json")
    monkeypatch.setattr("argos_agent.lsp.config.LSP_CONFIG_PATH", p)
    with pytest.raises(LspConfigError):
        load()


def test_load_missing_version_raises(tmp_path, monkeypatch):
    """version 缺 → LspConfigError。"""
    p = tmp_path / "lsp.json"
    p.write_text(json.dumps({"servers": {}}))
    monkeypatch.setattr("argos_agent.lsp.config.LSP_CONFIG_PATH", p)
    with pytest.raises(LspConfigError, match="version"):
        load()


def test_load_wrong_version_raises(tmp_path, monkeypatch):
    """version 不匹配(本机 v1,文件 v2)→ 报错 + 拒载。"""
    p = tmp_path / "lsp.json"
    p.write_text(json.dumps({"version": 2, "servers": {}}))
    monkeypatch.setattr("argos_agent.lsp.config.LSP_CONFIG_PATH", p)
    with pytest.raises(LspConfigError, match="version"):
        load()


def test_load_command_not_array_raises(tmp_path, monkeypatch):
    """command 非 array → LspConfigError(spec §2.2:argv 数组,不是 shell 字符串)。"""
    p = tmp_path / "lsp.json"
    p.write_text(json.dumps({
        "version": 1,
        "servers": {"x": {"command": "pyright-langserver --stdio", "filetypes": [".py"]}},
    }))
    monkeypatch.setattr("argos_agent.lsp.config.LSP_CONFIG_PATH", p)
    with pytest.raises(LspConfigError, match="command"):
        load()


def test_load_filetypes_empty_raises(tmp_path, monkeypatch):
    """filetypes 空数组 → LspConfigError(0 server 服务 = 死代码)。"""
    p = tmp_path / "lsp.json"
    p.write_text(json.dumps({
        "version": 1,
        "servers": {"x": {"command": ["y"], "filetypes": []}},
    }))
    monkeypatch.setattr("argos_agent.lsp.config.LSP_CONFIG_PATH", p)
    with pytest.raises(LspConfigError, match="filetypes"):
        load()


def test_load_server_name_with_space_raises(tmp_path, monkeypatch):
    """server name 含空格 → LspConfigError(spec §2.2:仅 ASCII 字母数字 + _ + -)。"""
    p = tmp_path / "lsp.json"
    p.write_text(json.dumps({
        "version": 1,
        "servers": {"py thon": {"command": ["y"], "filetypes": [".py"]}},
    }))
    monkeypatch.setattr("argos_agent.lsp.config.LSP_CONFIG_PATH", p)
    with pytest.raises(LspConfigError, match="name"):
        load()


def test_load_unreadable_file_treated_as_missing(tmp_path, monkeypatch):
    """权限不可读文件 → 视同"不存在"走 built-in 默认(spec §3)。"""
    p = tmp_path / "lsp.json"
    p.write_text(json.dumps({"version": 1, "servers": {}}))
    p.chmod(0o000)
    monkeypatch.setattr("argos_agent.lsp.config.LSP_CONFIG_PATH", p)
    try:
        cfg = load()
        assert "python" in cfg.servers
    finally:
        p.chmod(0o644)


def test_reload_replaces_singleton(tmp_path, monkeypatch):
    """reload 改 ~/.argos/lsp.json 后,get_config() 返新配置。"""
    p = tmp_path / "lsp.json"
    p.write_text(json.dumps({
        "version": 1,
        "servers": {"python": {"command": ["a"], "filetypes": [".py"]}},
    }))
    monkeypatch.setattr("argos_agent.lsp.config.LSP_CONFIG_PATH", p)
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
    """reload 时新配置不合规 → 保旧 + 报错(spec §3 reload 行)。"""
    p = tmp_path / "lsp.json"
    p.write_text(json.dumps({
        "version": 1,
        "servers": {"python": {"command": ["a"], "filetypes": [".py"]}},
    }))
    monkeypatch.setattr("argos_agent.lsp.config.LSP_CONFIG_PATH", p)
    cfg_old = reload_config()
    p.write_text("{not json")
    with pytest.raises(LspConfigError):
        reload_config()
    assert get_config() is cfg_old
    assert "python" in get_config().servers
