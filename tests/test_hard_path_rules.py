"""系统路径 denylist + workspace 边界 + .env 特殊处理(spec §2.3, D14)。"""
from __future__ import annotations

from pathlib import Path

import pytest

from argos_agent.permissions.hard_rules import (
    HARD_PATH_DENYLIST,
    is_argos_own_env,
    is_env_file,
    is_env_template,
    is_system_path,
    is_workspace_path,
)


def _home(p: str) -> str:
    return str(Path(p).expanduser())


def test_denylist_nonempty():
    """HARD_PATH_DENYLIST 至少 6 条(spec §2.3 列 12+ 系统路径 / 用户私密)。"""
    assert len(HARD_PATH_DENYLIST) >= 6


# ── 系统路径拒 ──────────────────────────────────────────────────────
def test_etc_path_denied():
    assert is_system_path("/etc/passwd") is True


def test_usr_path_denied():
    assert is_system_path("/usr/local/bin/foo") is True


def test_system_path_denied():
    assert is_system_path("/System/Library/x") is True


def test_private_etc_denied():
    assert is_system_path("/private/etc/hosts") is True


def test_ssh_dir_denied():
    assert is_system_path(_home("~/.ssh/id_rsa")) is True


def test_aws_credentials_denied():
    assert is_system_path(_home("~/.aws/credentials")) is True


def test_argos_own_env_allowed():
    """~/.argos/.env 是 Argos 自己的 config,不 lock 自己。"""
    assert is_argos_own_env(_home("~/.argos/.env")) is True


def test_workspace_file_allowed():
    """workspace 内文件 → 不算 system path(由 is_workspace_path 判定)。"""
    assert is_system_path("/Users/zc/Projects/argos/CLAUDE.md") is False


def test_tmp_allowed():
    assert is_system_path("/tmp/x") is False


# ── workspace 边界 ───────────────────────────────────────────────────
def test_workspace_inside(tmp_path):
    p = tmp_path / "a.py"
    p.write_text("")
    assert is_workspace_path(str(p), tmp_path) is True


def test_workspace_outside(tmp_path):
    assert is_workspace_path("/etc/passwd", tmp_path) is False


def test_workspace_traversal_denied(tmp_path):
    """../outside_workspace/x → workspace 外。"""
    p = (tmp_path / ".." / "outside" / "x").resolve()
    assert is_workspace_path(str(p), tmp_path) is False


def test_workspace_none_means_outside():
    """workspace=None → 返 False(走系统路径 check)。"""
    assert is_workspace_path("/etc/passwd", None) is False


def test_workspace_empty_means_outside():
    assert is_workspace_path("/etc/passwd", "") is False


# ── .env 特殊路径 ─────────────────────────────────────────────────
def test_is_env_file():
    assert is_env_file("/x/.env") is True
    assert is_env_file("/x/.env.local") is True
    assert is_env_file("/x/.env.production") is True
    assert is_env_file("/x/foo.txt") is False


def test_is_env_template():
    assert is_env_template("/x/.env.example") is True
    assert is_env_template("/x/.env.sample") is True
    assert is_env_template("/x/.env.template") is True
    assert is_env_template("/x/.env") is False   # 裸 .env 不是模板
