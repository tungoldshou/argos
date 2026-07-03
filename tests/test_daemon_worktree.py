from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from argos.daemon.worktree import WorktreeError, WorktreeManager


# ── is_git_repo ────────────────────────────────────────────────────────


def test_is_git_repo_true(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    mgr = WorktreeManager(base_dir=tmp_path / "wt")
    assert mgr.is_git_repo(str(tmp_path)) is True


def test_is_git_repo_false(tmp_path: Path):
    mgr = WorktreeManager(base_dir=tmp_path / "wt")
    assert mgr.is_git_repo(str(tmp_path)) is False


def test_is_git_repo_nonexistent_returns_false(tmp_path: Path):
    mgr = WorktreeManager(base_dir=tmp_path / "wt")
    assert mgr.is_git_repo("/this/does/not/exist") is False


# ── create ─────────────────────────────────────────────────────────────


@pytest.mark.skipif(not Path("/usr/bin/git").exists() and not Path("/opt/homebrew/bin/git").exists() and not Path("/usr/local/bin/git").exists(),
                    reason="git not available")
def test_create_git_worktree(tmp_path: Path):
    import shutil
    if not shutil.which("git"):
        pytest.skip("git not in PATH")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@x"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("hi")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    mgr = WorktreeManager(base_dir=tmp_path / "wt")
    rid = "abc123def456"
    wt_path = mgr.create(run_id=rid, workspace=str(repo))
    assert (tmp_path / "wt" / rid).exists()
    assert (tmp_path / "wt" / rid / "README.md").exists()
    r = subprocess.run(
        ["git", "worktree", "list"], cwd=repo, capture_output=True, text=True, check=True,
    )
    assert rid in r.stdout or f"argos/{rid}" in r.stdout
    # cleanup
    mgr.cleanup(rid)
    assert not (tmp_path / "wt" / rid).exists()


def test_create_non_git_uses_temp(tmp_path: Path):
    mgr = WorktreeManager(base_dir=tmp_path / "wt")
    rid = "abc123def456"
    wt_path = mgr.create(run_id=rid, workspace=str(tmp_path / "nope"))
    assert Path(wt_path).exists()
    assert rid in wt_path
    mgr.cleanup(rid)
    assert not Path(wt_path).exists()


def test_create_fails_when_git_missing(monkeypatch, tmp_path: Path):
    (tmp_path / "fake-git").mkdir()
    (tmp_path / "fake-git" / ".git").mkdir()
    mgr = WorktreeManager(base_dir=tmp_path / "wt")
    import argos.git_worktree as gwmod

    original_run = gwmod.subprocess.run

    def fake_run(*args, **kwargs):
        if args and args[0] and args[0][0] == "git":
            raise FileNotFoundError("git not in PATH")
        return original_run(*args, **kwargs)

    monkeypatch.setattr(gwmod.subprocess, "run", fake_run)
    with pytest.raises(WorktreeError):
        mgr.create(run_id="a" * 12, workspace=str(tmp_path / "fake-git"))


def test_create_workspace_does_not_exist_falls_back_to_temp(tmp_path: Path):
    mgr = WorktreeManager(base_dir=tmp_path / "wt")
    rid = "fff123fff123"
    wt_path = mgr.create(run_id=rid, workspace="/totally/nonexistent/path/x/y/z")
    assert Path(wt_path).exists()
    mgr.cleanup(rid)


# ── cleanup ────────────────────────────────────────────────────────────


def test_cleanup_nonexistent_is_noop(tmp_path: Path):
    mgr = WorktreeManager(base_dir=tmp_path / "wt")
    mgr.cleanup("a" * 12)
    mgr.cleanup("a" * 12)


def test_cleanup_force_removes_locked_worktree(tmp_path: Path):
    mgr = WorktreeManager(base_dir=tmp_path / "wt")
    rid = "a" * 12
    wt = tmp_path / "wt" / rid
    wt.mkdir(parents=True)
    (wt / "stale.lock").write_text("x")
    mgr.cleanup(rid)
    assert not wt.exists()


# ── module-level constants ─────────────────────────────────────────────


def test_default_base_dir_honors_argos_config_dir(tmp_path, monkeypatch):
    from argos import config as C

    cfg_dir = tmp_path / "cfg"
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(C, "_ENV", {})

    mgr = WorktreeManager()
    assert mgr._base == cfg_dir / "worktrees"
