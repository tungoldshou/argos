from __future__ import annotations

import sys
from pathlib import Path

import pytest

from argos.sandbox import seatbelt


def test_profile_denies_by_default():
    prof = seatbelt.build_profile(workspace=Path("/tmp/argos_ws"))
    assert "(deny default)" in prof


def test_profile_denies_network():
    prof = seatbelt.build_profile(workspace=Path("/tmp/argos_ws"))
    assert "(allow network" not in prof
    assert "(deny network*)" in prof


def test_profile_allows_workspace_write():
    ws = Path("/tmp/argos_ws")
    prof = seatbelt.build_profile(workspace=ws)
    assert "file-write*" in prof
    assert str(ws.resolve()) in prof


def test_profile_allows_temp_and_reads():
    prof = seatbelt.build_profile(workspace=Path("/tmp/argos_ws"))
    assert "file-read*" in prof
    assert "(allow file-write*" in prof
    assert ("/tmp" in prof) or ("/private/var/folders" in prof) or ("/var/folders" in prof)


def test_profile_workspace_outside_not_writable():
    ws = Path("/tmp/argos_ws")
    prof = seatbelt.build_profile(workspace=ws)
    home_ssh = str(Path.home() / ".ssh")
    write_block = prof.split("(allow file-write*")[1]
    assert home_ssh not in write_block


def test_profile_denies_credential_reads():
    prof = seatbelt.build_profile(workspace=Path.home() / ".argos" / "workspace")
    home = Path.home()
    assert "(allow file-read*)" in prof
    deny_block = prof.split("(allow file-read*)")[1].split("(allow file-write*")[0]
    assert "(deny file-read*" in deny_block
    for d in (".ssh", ".aws", ".gnupg", ".kube", ".docker", ".azure"):
        assert str(home / d) in deny_block, f"凭据目录 {d} 应被读 deny"
    for f in (".netrc", ".git-credentials", ".argos/.env", ".argos/config.json"):
        assert str(home / f) in deny_block, f"密钥文件 {f} 应被读 deny"
    assert str(home / ".argos" / "workspace") not in deny_block


def test_profile_denies_active_argos_config_dir_credential_reads(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "cfg"
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))

    prof = seatbelt.build_profile(workspace=tmp_path / "ws")
    deny_block = prof.split("(allow file-read*)")[1].split("(allow file-write*")[0]

    for name in (".env", "config.json", "mcp.json"):
        assert str(cfg_dir / name) in deny_block


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX home/symlink 语义")
def test_profile_denies_resolved_credential_reads_when_home_symlinked(tmp_path, monkeypatch):
    real_home = tmp_path / "real_home"
    real_home.mkdir()
    link_home = tmp_path / "link_home"
    link_home.symlink_to(real_home, target_is_directory=True)
    monkeypatch.setenv("HOME", str(link_home))

    assert Path.home() == link_home
    assert str(real_home.resolve() / ".ssh") != str(link_home / ".ssh")

    prof = seatbelt.build_profile(workspace=tmp_path / "ws")
    deny_block = prof.split("(allow file-read*)")[1].split("(allow file-write*")[0]

    for d in (".ssh", ".aws", ".gnupg"):
        assert str(real_home.resolve() / d) in deny_block, f"resolved 凭据目录 {d} 应被读 deny"
    for f in (".netrc", ".git-credentials", ".argos/.env"):
        assert str(real_home.resolve() / f) in deny_block, f"resolved 密钥文件 {f} 应被读 deny"

    assert str(link_home / ".ssh") in deny_block
