"""Internal documentation."""
from __future__ import annotations

import os

from argos import config
from argos.permissions import hard_rules
from argos.sandbox import seatbelt
from argos.tools import files


def test_extra_write_dirs_parses_dedupes_resolves(tmp_path, monkeypatch):
    a = tmp_path / "a"; a.mkdir()
    b = tmp_path / "b"; b.mkdir()
    monkeypatch.setenv("ARGOS_ADD_DIRS", os.pathsep.join([str(a), str(b), str(a)]))
    assert config.extra_write_dirs() == [a.resolve(), b.resolve()]


def test_extra_write_dirs_empty_default(monkeypatch):
    monkeypatch.delenv("ARGOS_ADD_DIRS", raising=False)
    assert config.extra_write_dirs() == []


def test_write_file_allows_add_dir(tmp_path, monkeypatch):
    ws = tmp_path / "ws"; ws.mkdir()
    extra = tmp_path / "extra"; extra.mkdir()
    monkeypatch.setattr(files, "WORKSPACE", ws.resolve())
    monkeypatch.setenv("ARGOS_ADD_DIRS", str(extra))
    files.write_file(str(extra / "f.txt"), "hi")
    assert (extra / "f.txt").read_text() == "hi"


def test_read_file_blocks_add_dir(tmp_path, monkeypatch):
    ws = tmp_path / "ws"; ws.mkdir()
    extra = tmp_path / "extra"; extra.mkdir()
    (extra / "secret.txt").write_text("secret")
    monkeypatch.setattr(files, "WORKSPACE", ws.resolve())
    monkeypatch.setenv("ARGOS_ADD_DIRS", str(extra))
    out = files.read_file(str(extra / "secret.txt"))
    assert "越出" in out
    assert "第 1" not in out


def test_write_file_blocks_unlisted_dir(tmp_path, monkeypatch):
    ws = tmp_path / "ws"; ws.mkdir()
    other = tmp_path / "other"; other.mkdir()
    monkeypatch.setattr(files, "WORKSPACE", ws.resolve())
    monkeypatch.delenv("ARGOS_ADD_DIRS", raising=False)
    files.write_file(str(other / "f.txt"), "hi")
    assert not (other / "f.txt").exists()


def test_is_workspace_path_allows_add_dir(tmp_path, monkeypatch):
    ws = tmp_path / "ws"; ws.mkdir()
    extra = tmp_path / "extra"; extra.mkdir()
    monkeypatch.setenv("ARGOS_ADD_DIRS", str(extra))
    assert hard_rules.is_workspace_path(str(extra / "f.txt"), str(ws)) is True
    assert hard_rules.is_workspace_path(str(tmp_path / "nope" / "f.txt"), str(ws)) is False


def test_build_profile_includes_add_dir(tmp_path, monkeypatch):
    extra = tmp_path / "extra"; extra.mkdir()
    monkeypatch.setenv("ARGOS_ADD_DIRS", str(extra))
    prof = seatbelt.build_profile(workspace=tmp_path / "ws")
    assert str(extra.resolve()) in prof


def test_build_profile_no_add_dir_default(tmp_path, monkeypatch):
    monkeypatch.delenv("ARGOS_ADD_DIRS", raising=False)
    prof = seatbelt.build_profile(workspace=tmp_path / "ws")
    assert str((tmp_path / "ws").resolve()) in prof
