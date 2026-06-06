"""Phase 3:Seatbelt deny-all profile 文本(纯函数,不起进程)。
断言安全不变量:deny default · 网络拒绝 · workspace+temp 可写 · workspace 外不在 write 白名单。"""
from __future__ import annotations

from pathlib import Path

import pytest

from argos_agent.sandbox import seatbelt


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
    # 一个明确越界目录不应出现在 write subpath 白名单里
    assert "/Users/zc/.ssh" not in prof
