"""Internal documentation."""
from __future__ import annotations

from pathlib import Path

import pytest

from argos.permissions.hard_rules import (
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
    """Internal documentation."""
    assert len(HARD_PATH_DENYLIST) >= 6


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


def test_argos_own_env_allowed(monkeypatch):
    """Internal documentation."""
    from argos import config as C

    monkeypatch.delenv("ARGOS_CONFIG_DIR", raising=False)
    monkeypatch.setattr(C, "_ENV", {})
    assert is_argos_own_env(_home("~/.argos/.env")) is True


def test_argos_own_env_honors_argos_config_dir(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "argos-config"
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))
    assert is_argos_own_env(str(cfg_dir / ".env")) is True


def test_workspace_file_allowed():
    """Internal documentation."""
    assert is_system_path("/Users/zc/Projects/argos/CLAUDE.md") is False


def test_tmp_allowed():
    assert is_system_path("/tmp/x") is False


def test_workspace_inside(tmp_path):
    p = tmp_path / "a.py"
    p.write_text("")
    assert is_workspace_path(str(p), tmp_path) is True


def test_workspace_outside(tmp_path):
    assert is_workspace_path("/etc/passwd", tmp_path) is False


def test_workspace_traversal_denied(tmp_path):
    """Internal documentation."""
    p = (tmp_path / ".." / "outside" / "x").resolve()
    assert is_workspace_path(str(p), tmp_path) is False


def test_workspace_none_means_outside():
    """Internal documentation."""
    assert is_workspace_path("/etc/passwd", None) is False


def test_workspace_empty_means_outside():
    assert is_workspace_path("/etc/passwd", "") is False


def test_is_env_file():
    assert is_env_file("/x/.env") is True
    assert is_env_file("/x/.env.local") is True
    assert is_env_file("/x/.env.production") is True
    assert is_env_file("/x/foo.txt") is False


def test_is_env_template():
    assert is_env_template("/x/.env.example") is True
    assert is_env_template("/x/.env.sample") is True
    assert is_env_template("/x/.env.template") is True
    assert is_env_template("/x/.env") is False
