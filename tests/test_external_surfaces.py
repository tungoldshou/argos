"""#9:沙箱外执行面启动警告 —— lsp/hooks/mcp 子系统在 OS 沙箱【外】以子进程运行用户控制的
代码/命令(不受 Seatbelt 约束)。CLAUDE.md 承诺 "warned at startup",过去未兑现。本测试锁住
启动检测:用户配置了这些 config → 发警告,诚实告知信任边界。"""
from __future__ import annotations

from pathlib import Path

from argos.external_surfaces import external_surface_warnings


def test_no_config_no_warnings(tmp_path: Path):
    assert external_surface_warnings(tmp_path) == []


def test_hooks_config_warns(tmp_path: Path):
    (tmp_path / "hooks.json").write_text("{}", encoding="utf-8")
    w = external_surface_warnings(tmp_path)
    assert len(w) == 1 and "hooks" in w[0]


def test_lsp_config_warns(tmp_path: Path):
    (tmp_path / "lsp.json").write_text("{}", encoding="utf-8")
    w = external_surface_warnings(tmp_path)
    assert len(w) == 1 and "lsp" in w[0]


def test_mcp_config_warns(tmp_path: Path):
    (tmp_path / "mcp.json").write_text("{}", encoding="utf-8")
    w = external_surface_warnings(tmp_path)
    assert len(w) == 1 and "mcp" in w[0]


def test_all_three_warn(tmp_path: Path):
    for name in ("hooks.json", "lsp.json", "mcp.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    w = external_surface_warnings(tmp_path)
    assert len(w) == 3
    joined = " ".join(w)
    assert "lsp" in joined and "mcp" in joined and "hooks" in joined
