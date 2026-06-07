"""底层 git worktree 原语 + daemon/workflow 两条隔离路径的等价性测试。

核心断言:daemon 的 `WorktreeManager.create` 与 workflow 的 `worktree_for` 现在都基于
`argos_agent.git_worktree`,对同一个真 git 仓产出**等价的隔离结果**;非 git 工作区则两条
都诚实降级(daemon→temp 目录,workflow→共享 base + 注记)。
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from argos_agent import git_worktree as gw
from argos_agent.daemon.worktree import WorktreeManager
from argos_agent.workflow.worktree import worktree_for

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="git not in PATH")


def _git_repo(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=p, check=True)
    (p / "tracked.txt").write_text("hello")
    subprocess.run(["git", "add", "-A"], cwd=p, check=True)
    subprocess.run(["git", "-c", "user.email=a@b.c", "-c", "user.name=t",
                    "commit", "-qm", "init"], cwd=p, check=True)
    return p


# ── 底层原语 ───────────────────────────────────────────────────────────


def test_primitive_is_git_repo(tmp_path: Path):
    assert gw.is_git_repo(_git_repo(tmp_path / "repo")) is True
    assert gw.is_git_repo(tmp_path / "plain") is False
    assert gw.is_git_repo("/no/such/path") is False


def test_primitive_add_and_remove_detached(tmp_path: Path):
    repo = _git_repo(tmp_path / "repo")
    wt = tmp_path / "wt"
    gw.add_worktree(repo=repo, path=wt, branch=None)
    assert wt.exists() and (wt / "tracked.txt").exists()
    # git 真记了这个 worktree
    listed = subprocess.run(["git", "worktree", "list"], cwd=repo,
                            capture_output=True, text=True, check=True).stdout
    assert str(wt) in listed
    gw.remove_worktree(wt, repo=repo)
    assert not wt.exists()


def test_primitive_add_named_branch(tmp_path: Path):
    repo = _git_repo(tmp_path / "repo")
    wt = tmp_path / "wt"
    gw.add_worktree(repo=repo, path=wt, branch="argos/xyz", ref="HEAD")
    branches = subprocess.run(["git", "branch"], cwd=repo,
                              capture_output=True, text=True, check=True).stdout
    assert "argos/xyz" in branches
    gw.remove_worktree(wt, repo=repo)


def test_primitive_add_on_non_git_raises(tmp_path: Path):
    with pytest.raises(gw.WorktreeError):
        gw.add_worktree(repo=tmp_path / "plain", path=tmp_path / "wt", branch=None)


def test_primitive_remove_nonexistent_is_noop(tmp_path: Path):
    gw.remove_worktree(tmp_path / "nope")  # 不抛


# ── 两条路径等价性 ─────────────────────────────────────────────────────


def test_daemon_and_workflow_produce_equivalent_isolation(tmp_path: Path):
    """同一个真 git 仓:daemon.create 与 workflow.worktree_for 都产出
    "独立目录 + 含源仓已跟踪文件 + 退出后清干净"的硬隔离。"""
    repo = _git_repo(tmp_path / "repo")

    # daemon 路径
    mgr = WorktreeManager(base_dir=tmp_path / "wt-base")
    rid = "abc123def456"
    d_path = Path(mgr.create(run_id=rid, workspace=str(repo)))
    d_isolated = d_path.exists() and d_path != repo
    d_has_tracked = (d_path / "tracked.txt").exists()
    mgr.cleanup(rid)
    d_cleaned = not d_path.exists()

    # workflow 路径
    with worktree_for(repo, "agent#0", "worktree") as (w_path, note):
        w_isolated = w_path.exists() and w_path != repo
        w_has_tracked = (w_path / "tracked.txt").exists()
        w_note = note
    w_cleaned = not w_path.exists()

    # 等价:两条都隔离成功、都带源仓文件、都无降级注记、退出后都清干净
    assert (d_isolated, d_has_tracked, d_cleaned) == (True, True, True)
    assert (w_isolated, w_has_tracked, w_cleaned) == (True, True, True)
    assert w_note is None
    assert (d_isolated, d_has_tracked, d_cleaned) == (w_isolated, w_has_tracked, w_cleaned)


def test_daemon_and_workflow_both_degrade_honestly_on_non_git(tmp_path: Path):
    """非 git 工作区:两条都诚实降级 —— daemon 退 temp 目录(仍给独立可写目录),
    workflow 退共享 base 并给"无硬隔离"注记。"""
    plain = tmp_path / "plain"
    plain.mkdir()

    # daemon:非 git → temp 兜底目录(独立、可写、不在源工作区下)
    mgr = WorktreeManager(base_dir=tmp_path / "wt-base")
    rid = "fff000fff000"
    d_path = Path(mgr.create(run_id=rid, workspace=str(plain)))
    assert d_path.exists()
    assert not gw.is_git_repo(d_path)   # 诚实:这不是 git 硬隔离
    mgr.cleanup(rid)

    # workflow:非 git → 退共享 base + 注记
    with worktree_for(plain, "agent#0", "worktree") as (w_path, note):
        assert w_path == plain          # 退共享
        assert note and "git" in note   # 注记说明无硬隔离
