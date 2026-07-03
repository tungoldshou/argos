"""Internal documentation."""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

WORKTREE_TIMEOUT_S = 10


class WorktreeError(Exception):
    """Internal documentation."""


def git_available() -> bool:
    """Internal documentation."""
    return shutil.which("git") is not None


def is_git_repo(workspace: str | Path) -> bool:
    """Internal documentation."""
    try:
        return (Path(workspace) / ".git").exists()
    except OSError:
        return False


def add_worktree(
    *,
    repo: str | Path,
    path: str | Path,
    branch: str | None = None,
    ref: str = "HEAD",
) -> None:
    """Internal documentation."""
    if branch is not None:
        cmd = ["git", "worktree", "add", "-b", branch, str(path), ref]
    else:
        cmd = ["git", "worktree", "add", "--detach", str(path)]
    try:
        subprocess.run(
            cmd, cwd=str(repo), check=True,
            capture_output=True, text=True, timeout=WORKTREE_TIMEOUT_S,
        )
    except subprocess.CalledProcessError as e:
        raise WorktreeError(
            f"git worktree add failed: {e.stderr.strip() or e.stdout.strip()}"
        ) from e
    except FileNotFoundError as e:
        raise WorktreeError("git not in PATH") from e
    except subprocess.TimeoutExpired as e:
        raise WorktreeError(f"git worktree add timeout: {e}") from e


def remove_worktree(path: str | Path, *, repo: str | Path | None = None) -> None:
    """Internal documentation."""
    p = Path(path)
    if not p.exists():
        return
    if (p / ".git").exists() and git_available():
        cmd = ["git"]
        if repo is not None:
            cmd += ["-C", str(repo)]
        cmd += ["worktree", "remove", "--force", str(p)]
        try:
            subprocess.run(
                cmd, check=False, capture_output=True,
                text=True, timeout=WORKTREE_TIMEOUT_S,
            )
        except Exception as e:  # noqa: BLE001
            log.debug("remove_worktree: git remove failed for %s: %s", p, e)
    shutil.rmtree(p, ignore_errors=True)
