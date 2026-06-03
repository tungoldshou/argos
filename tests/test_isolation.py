"""isolation 测试 —— sandbox 子目录 / git worktree / 非 git 降级。"""
import subprocess
from pathlib import Path

import pytest

from argos_agent import isolation


@pytest.fixture
def reroot(tmp_path, monkeypatch):
    monkeypatch.setattr(isolation, "RUNS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(isolation, "WORKTREES_ROOT", tmp_path / "wt")
    return tmp_path


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def test_acquire_sandbox_makes_isolated_dirs(reroot):
    ws, vd = isolation.acquire_sandbox("sess1")
    assert ws.exists() and vd.exists()
    assert "sess1" in str(ws) and ws != vd


def test_sandbox_two_sessions_distinct(reroot):
    ws1, _ = isolation.acquire_sandbox("s1")
    ws2, _ = isolation.acquire_sandbox("s2")
    assert ws1 != ws2


def test_is_git_project_false_for_plain_dir(reroot, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert isolation.is_git_project(str(plain)) is False


def test_acquire_worktree_creates_and_reuses(reroot, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    _git("init", cwd=proj)
    _git("-c", "user.email=a@b.c", "-c", "user.name=t", "commit", "--allow-empty", "-m", "init", cwd=proj)
    assert isolation.is_git_project(str(proj)) is True

    ws1, vd1 = isolation.acquire_worktree("sessW", str(proj))
    assert ws1.exists() and ws1 == vd1
    (ws1 / "scratch.txt").write_text("x", encoding="utf-8")
    # 同会话第二次复用同一 worktree(不报错、路径不变)
    ws2, _ = isolation.acquire_worktree("sessW", str(proj))
    assert ws2 == ws1 and (ws2 / "scratch.txt").exists()

    isolation.release_worktree("sessW", str(proj))
    assert not ws1.exists()


def test_acquire_worktree_raises_on_non_git(reroot, tmp_path):
    plain = tmp_path / "ng"
    plain.mkdir()
    with pytest.raises(isolation.IsolationError):
        isolation.acquire_worktree("s", str(plain))


def test_acquire_worktree_reusable_after_release(reroot, tmp_path):
    """release 后能重新 acquire(分支残留不再撞车) —— I1 回归。"""
    proj = tmp_path / "proj2"
    proj.mkdir()
    _git("init", cwd=proj)
    _git("-c", "user.email=a@b.c", "-c", "user.name=t", "commit", "--allow-empty", "-m", "init", cwd=proj)
    ws1, _ = isolation.acquire_worktree("reacq", str(proj))
    isolation.release_worktree("reacq", str(proj))
    assert not ws1.exists()
    # 关键:再 acquire 不报 "branch already exists"
    ws2, _ = isolation.acquire_worktree("reacq", str(proj))
    assert ws2.exists()
    isolation.release_worktree("reacq", str(proj))


def test_path_traversal_session_id_rejected(reroot):
    """恶意 session_id 不能逃出隔离根 —— C1 回归。"""
    with pytest.raises(isolation.IsolationError):
        isolation.acquire_sandbox("../../etc/evil")
    with pytest.raises(isolation.IsolationError):
        isolation.acquire_worktree("../../x", str(reroot))


def test_release_sandbox_removes_dir(reroot):
    """release_sandbox 真的删目录 —— M3。"""
    ws, _ = isolation.acquire_sandbox("delme")
    assert ws.exists()
    isolation.release_sandbox("delme")
    assert not ws.exists()
