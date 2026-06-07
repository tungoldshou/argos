"""WorktreeManager 单元测试(#5b T6)。"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from argos_agent.daemon.worktree import WorktreeError, WorktreeManager


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
    """真 git init + worktree add。"""
    import shutil
    if not shutil.which("git"):
        pytest.skip("git not in PATH")
    # 起一个真 git repo
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@x"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("hi")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    # 起 worktree
    mgr = WorktreeManager(base_dir=tmp_path / "wt")
    rid = "abc123def456"
    wt_path = mgr.create(run_id=rid, workspace=str(repo))
    assert (tmp_path / "wt" / rid).exists()
    assert (tmp_path / "wt" / rid / "README.md").exists()
    # 列出 worktree 校验 git 真记了
    r = subprocess.run(
        ["git", "worktree", "list"], cwd=repo, capture_output=True, text=True, check=True,
    )
    assert rid in r.stdout or f"argos/{rid}" in r.stdout
    # cleanup
    mgr.cleanup(rid)
    assert not (tmp_path / "wt" / rid).exists()


def test_create_non_git_uses_temp(tmp_path: Path):
    """workspace 不是 git repo → temp 目录。"""
    mgr = WorktreeManager(base_dir=tmp_path / "wt")
    rid = "abc123def456"
    wt_path = mgr.create(run_id=rid, workspace=str(tmp_path / "nope"))
    assert Path(wt_path).exists()
    assert rid in wt_path
    mgr.cleanup(rid)
    assert not Path(wt_path).exists()


def test_create_fails_when_git_missing(monkeypatch, tmp_path: Path):
    """git 不在 PATH → WorktreeError(若 workspace 是 git repo)。"""
    # 先建一个 .git 目录欺骗 is_git_repo
    (tmp_path / "fake-git").mkdir()
    (tmp_path / "fake-git" / ".git").mkdir()
    # 强 is_git_repo 走自定义路径
    mgr = WorktreeManager(base_dir=tmp_path / "wt")
    # monkeypatch subprocess.run 在 worktree 路径上抛 FileNotFoundError
    # (底层 git 调用现统一在 git_worktree;在那里注入,才真正走 git-missing 路径)
    import argos_agent.git_worktree as gwmod

    original_run = gwmod.subprocess.run

    def fake_run(*args, **kwargs):
        if args and args[0] and args[0][0] == "git":
            raise FileNotFoundError("git not in PATH")
        return original_run(*args, **kwargs)

    monkeypatch.setattr(gwmod.subprocess, "run", fake_run)
    with pytest.raises(WorktreeError):
        mgr.create(run_id="a" * 12, workspace=str(tmp_path / "fake-git"))


def test_create_workspace_does_not_exist_falls_back_to_temp(tmp_path: Path):
    """workspace 路径根本不存在 → 走 temp 兜底(不抛)。"""
    mgr = WorktreeManager(base_dir=tmp_path / "wt")
    rid = "fff123fff123"
    wt_path = mgr.create(run_id=rid, workspace="/totally/nonexistent/path/x/y/z")
    assert Path(wt_path).exists()
    mgr.cleanup(rid)


# ── cleanup ────────────────────────────────────────────────────────────


def test_cleanup_nonexistent_is_noop(tmp_path: Path):
    mgr = WorktreeManager(base_dir=tmp_path / "wt")
    mgr.cleanup("a" * 12)  # 不抛
    mgr.cleanup("a" * 12)  # 双 cleanup 也不抛


def test_cleanup_force_removes_locked_worktree(tmp_path: Path):
    """目录存在但 git 锁/外部锁 → cleanup 仍尽力删(shutil ignore_errors)。"""
    mgr = WorktreeManager(base_dir=tmp_path / "wt")
    rid = "a" * 12
    wt = tmp_path / "wt" / rid
    wt.mkdir(parents=True)
    (wt / "stale.lock").write_text("x")
    mgr.cleanup(rid)
    assert not wt.exists()


# ── module-level constants ─────────────────────────────────────────────


def test_default_base_dir_under_home():
    """默认 base_dir = ~/.argos/worktrees。"""
    import os
    mgr = WorktreeManager()
    expected = Path(os.path.expanduser("~/.argos/worktrees"))
    assert str(mgr._base).rstrip("/") == str(expected).rstrip("/")
