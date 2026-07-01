"""#2 CC对齐:--add-dir / ARGOS_ADD_DIRS 授权 workspace 之外的额外可写目录(对齐 CC 的 --add-dir)。
覆盖:config 解析 + 应用层写牢笼(_safe_path / write_file)放行 + hard-path 边界放行 +
Seatbelt profile 写牢笼含额外目录 + 未授权目录仍被挡。"""
from __future__ import annotations

import os

from argos import config
from argos.permissions import hard_rules
from argos.sandbox import seatbelt
from argos.tools import files


# ── config.extra_write_dirs:解析 / 去重 / 默认空 ──────────────────────────────
def test_extra_write_dirs_parses_dedupes_resolves(tmp_path, monkeypatch):
    a = tmp_path / "a"; a.mkdir()
    b = tmp_path / "b"; b.mkdir()
    monkeypatch.setenv("ARGOS_ADD_DIRS", os.pathsep.join([str(a), str(b), str(a)]))
    assert config.extra_write_dirs() == [a.resolve(), b.resolve()]   # 保序、去重、resolve


def test_extra_write_dirs_empty_default(monkeypatch):
    monkeypatch.delenv("ARGOS_ADD_DIRS", raising=False)
    assert config.extra_write_dirs() == []


# ── 应用层写牢笼:授权目录可写,未授权仍挡 ────────────────────────────────────
def test_write_file_allows_add_dir(tmp_path, monkeypatch):
    ws = tmp_path / "ws"; ws.mkdir()
    extra = tmp_path / "extra"; extra.mkdir()
    monkeypatch.setattr(files, "WORKSPACE", ws.resolve())
    monkeypatch.setenv("ARGOS_ADD_DIRS", str(extra))
    files.write_file(str(extra / "f.txt"), "hi")
    assert (extra / "f.txt").read_text() == "hi"        # 授权目录:真写入


def test_write_file_blocks_unlisted_dir(tmp_path, monkeypatch):
    ws = tmp_path / "ws"; ws.mkdir()
    other = tmp_path / "other"; other.mkdir()
    monkeypatch.setattr(files, "WORKSPACE", ws.resolve())
    monkeypatch.delenv("ARGOS_ADD_DIRS", raising=False)
    files.write_file(str(other / "f.txt"), "hi")
    assert not (other / "f.txt").exists()               # 未授权:仍被判越界,不写


# ── hard-path workspace 边界:授权目录视同边界内 ──────────────────────────────
def test_is_workspace_path_allows_add_dir(tmp_path, monkeypatch):
    ws = tmp_path / "ws"; ws.mkdir()
    extra = tmp_path / "extra"; extra.mkdir()
    monkeypatch.setenv("ARGOS_ADD_DIRS", str(extra))
    assert hard_rules.is_workspace_path(str(extra / "f.txt"), str(ws)) is True
    assert hard_rules.is_workspace_path(str(tmp_path / "nope" / "f.txt"), str(ws)) is False


# ── OS 层:Seatbelt profile 写牢笼含额外目录 ─────────────────────────────────
def test_build_profile_includes_add_dir(tmp_path, monkeypatch):
    extra = tmp_path / "extra"; extra.mkdir()
    monkeypatch.setenv("ARGOS_ADD_DIRS", str(extra))
    prof = seatbelt.build_profile(workspace=tmp_path / "ws")
    assert str(extra.resolve()) in prof                 # 额外目录进了 file-write* 白名单


def test_build_profile_no_add_dir_default(tmp_path, monkeypatch):
    monkeypatch.delenv("ARGOS_ADD_DIRS", raising=False)
    prof = seatbelt.build_profile(workspace=tmp_path / "ws")
    assert str((tmp_path / "ws").resolve()) in prof      # workspace 恒在
