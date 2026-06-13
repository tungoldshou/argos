"""T10:/lsp + /lsp reload slash 命令 + 启动 splash 坏配置 banner。"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest


# ── /lsp COMMAND_HELP 注册 ───────────────────────────────────────


def test_command_help_includes_lsp():
    """COMMAND_HELP 含 'lsp' 描述,含 'reload' 关键字。"""
    from argos.tui.commands import COMMAND_HELP
    assert "lsp" in COMMAND_HELP
    assert "reload" in COMMAND_HELP["lsp"]


# ── /lsp reload 错误处理 ────────────────────────────────────────


@pytest.fixture
def isolated_lsp_home(monkeypatch):
    """每测试 HOME 临时目录 → ~/.argos/lsp.json 独立。"""
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv("HOME", tmp)
    yield Path(tmp) / ".argos"
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


def test_lsp_reload_invalid_keeps_old(isolated_lsp_home, monkeypatch):
    """reload 时新配不合规 → 保旧 + 抛 LspConfigError。"""
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


# ── splash 坏配置 banner ────────────────────────────────────────


def test_bad_config_splash_banner_lsp_message():
    """StartupSplash.set_bad_config('LSP ...') → renderable_text 含 'LSP 已禁用'。"""
    from argos.tui.widgets.splash import StartupSplash
    sp = StartupSplash(model_label="x", tier="default", live=True)
    sp.set_bad_config("LSP parse error: bad json at line 3")
    text = sp.renderable_text
    assert "LSP" in text
    assert "已禁用" in text
    assert "parse error" in text


# ── /lsp 列出 servers ──────────────────────────────────────────


def test_lsp_cmd_lists_servers(isolated_lsp_home, monkeypatch):
    """/lsp 列当前生效 server(3 个 server,disabled=True 在 config 而非 status)。

    状态机(spec §2.6):disabled=True 是用户配置;NotStarted/Ready/Crashed 是运行时
    状态。未启动时所有 server 都是 NotStarted;`disabled` 在 `list_servers()` 透出
    给 /lsp 渲染用(command 字符串后显 'disabled' 标识)。"""
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
    # disabled_one: config.disabled=True → 反映在 LspServerConfig.disabled(给 /lsp 渲染用)
    assert cfg.servers["disabled_one"].disabled is True
