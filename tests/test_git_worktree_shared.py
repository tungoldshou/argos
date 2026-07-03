from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from argos import git_worktree as gw
from argos.daemon.worktree import WorktreeManager
from argos.workflow.worktree import worktree_for

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="git not in PATH")


def _git_repo(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=p, check=True)
    (p / "tracked.txt").write_text("hello")
    subprocess.run(["git", "add", "-A"], cwd=p, check=True)
    subprocess.run(["git", "-c", "user.email=a@b.c", "-c", "user.name=t",
                    "commit", "-qm", "init"], cwd=p, check=True)
    return p




def test_primitive_is_git_repo(tmp_path: Path):
    assert gw.is_git_repo(_git_repo(tmp_path / "repo")) is True
    assert gw.is_git_repo(tmp_path / "plain") is False
    assert gw.is_git_repo("/no/such/path") is False


def test_primitive_add_and_remove_detached(tmp_path: Path):
    repo = _git_repo(tmp_path / "repo")
    wt = tmp_path / "wt"
    gw.add_worktree(repo=repo, path=wt, branch=None)
    assert wt.exists() and (wt / "tracked.txt").exists()
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
    gw.remove_worktree(tmp_path / "nope")




def test_daemon_and_workflow_produce_equivalent_isolation(tmp_path: Path):
    repo = _git_repo(tmp_path / "repo")

    mgr = WorktreeManager(base_dir=tmp_path / "wt-base")
    rid = "abc123def456"
    d_path = Path(mgr.create(run_id=rid, workspace=str(repo)))
    d_isolated = d_path.exists() and d_path != repo
    d_has_tracked = (d_path / "tracked.txt").exists()
    mgr.cleanup(rid)
    d_cleaned = not d_path.exists()

    with worktree_for(repo, "agent#0", "worktree") as (w_path, note):
        w_isolated = w_path.exists() and w_path != repo
        w_has_tracked = (w_path / "tracked.txt").exists()
        w_note = note
    w_cleaned = not w_path.exists()

    assert (d_isolated, d_has_tracked, d_cleaned) == (True, True, True)
    assert (w_isolated, w_has_tracked, w_cleaned) == (True, True, True)
    assert w_note is None
    assert (d_isolated, d_has_tracked, d_cleaned) == (w_isolated, w_has_tracked, w_cleaned)


def test_daemon_and_workflow_both_degrade_honestly_on_non_git(tmp_path: Path):
    plain = tmp_path / "plain"
    plain.mkdir()

    mgr = WorktreeManager(base_dir=tmp_path / "wt-base")
    rid = "fff000fff000"
    d_path = Path(mgr.create(run_id=rid, workspace=str(plain)))
    assert d_path.exists()
    assert not gw.is_git_repo(d_path)
    mgr.cleanup(rid)

    with worktree_for(plain, "agent#0", "worktree") as (w_path, note):
        assert w_path == plain
        assert note and "git" in note
