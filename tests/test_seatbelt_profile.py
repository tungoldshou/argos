"""Phase 3:Seatbelt deny-all profile 文本(纯函数,不起进程)。
断言安全不变量:deny default · 网络拒绝 · workspace+temp 可写 · workspace 外不在 write 白名单。"""
from __future__ import annotations

from pathlib import Path

import pytest

from argos.sandbox import seatbelt


def test_profile_denies_by_default():
    prof = seatbelt.build_profile(workspace=Path("/tmp/argos_ws"))
    assert "(deny default)" in prof


def test_profile_denies_network():
    prof = seatbelt.build_profile(workspace=Path("/tmp/argos_ws"))
    # 绝不出现 allow network*;且显式 deny 网络
    assert "(allow network" not in prof
    assert "(deny network*)" in prof


def test_profile_allows_workspace_write():
    ws = Path("/tmp/argos_ws")
    prof = seatbelt.build_profile(workspace=ws)
    # workspace 子树 file-write* 被放行(用 subpath)
    assert "file-write*" in prof
    assert str(ws.resolve()) in prof


def test_profile_allows_temp_and_reads():
    prof = seatbelt.build_profile(workspace=Path("/tmp/argos_ws"))
    assert "file-read*" in prof          # 读放宽(模型要 import 库/读项目)
    assert "(allow file-write*" in prof  # temp 也在 write 白名单
    # temp 目录(/private/var/folders 或 /tmp)出现在 write 子集
    assert ("/tmp" in prof) or ("/private/var/folders" in prof) or ("/var/folders" in prof)


def test_profile_workspace_outside_not_writable():
    ws = Path("/tmp/argos_ws")
    prof = seatbelt.build_profile(workspace=ws)
    home_ssh = str(Path.home() / ".ssh")
    # ~/.ssh 不应在【写白名单】里(写牢笼只含 workspace+temp)。
    # 注:Phase 0 起 ~/.ssh 会出现在【读 deny】块,故只检查 write-allow 段。
    write_block = prof.split("(allow file-write*")[1]
    assert home_ssh not in write_block


def test_profile_denies_credential_reads():
    """Phase 0(2026-06-20):全盘可读基线上,凭据目录/密钥文件读被 deny(开出网阀前的前置安全)。
    Seatbelt 后匹配覆盖:(deny file-read* 凭据...) 在 (allow file-read*) 之后。"""
    prof = seatbelt.build_profile(workspace=Path.home() / ".argos" / "workspace")
    home = Path.home()
    # deny 块在 allow file-read* 之后、allow file-write* 之前
    assert "(allow file-read*)" in prof
    deny_block = prof.split("(allow file-read*)")[1].split("(allow file-write*")[0]
    assert "(deny file-read*" in deny_block
    for d in (".ssh", ".aws", ".gnupg", ".kube", ".docker", ".azure"):
        assert str(home / d) in deny_block, f"凭据目录 {d} 应被读 deny"
    for f in (".netrc", ".git-credentials", ".argos/.env", ".argos/config.json"):
        assert str(home / f) in deny_block, f"密钥文件 {f} 应被读 deny"
    # 工作区目录本身绝不能在读 deny 块里(否则读不了工作区)
    assert str(home / ".argos" / "workspace") not in deny_block
