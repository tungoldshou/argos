import subprocess
from pathlib import Path
import pytest
from argos_agent.workflow.worktree import worktree_for


def _git_init(p: Path):
    subprocess.run(["git", "init", "-q"], cwd=p, check=True)
    (p / "f.txt").write_text("hi")
    subprocess.run(["git", "add", "-A"], cwd=p, check=True)
    subprocess.run(["git", "-c", "user.email=a@b.c", "-c", "user.name=t",
                    "commit", "-qm", "init"], cwd=p, check=True)


def test_worktree_isolated_and_cleaned(tmp_path):
    _git_init(tmp_path)
    with worktree_for(tmp_path, "agent#0", "worktree") as (wd, note):
        assert wd != tmp_path and wd.exists()
        assert (wd / "f.txt").exists()
        assert note is None
        (wd / "new.txt").write_text("x")
    assert not wd.exists()
    assert not (tmp_path / "new.txt").exists()


def test_non_git_falls_back_to_shared_with_note(tmp_path):
    with worktree_for(tmp_path, "agent#0", "worktree") as (wd, note):
        assert wd == tmp_path
        assert note and "git" in note


def test_isolation_none_uses_shared(tmp_path):
    _git_init(tmp_path)
    with worktree_for(tmp_path, "agent#0", "none") as (wd, note):
        assert wd == tmp_path and note is None
