from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

RUNS_ROOT: Path | None = None
WORKTREES_ROOT: Path | None = None

_SAFE_SID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _valid_sid(session_id: str) -> bool:
    return bool(_SAFE_SID.fullmatch(session_id or ""))


def _argos_dir() -> Path:
    from argos import config

    return config.config_dir()


def _runs_root() -> Path:
    return RUNS_ROOT if RUNS_ROOT is not None else _argos_dir() / "runs"


def _worktrees_root() -> Path:
    return WORKTREES_ROOT if WORKTREES_ROOT is not None else _argos_dir() / "worktrees"


class IsolationError(RuntimeError):
    pass


def acquire_sandbox(session_id: str) -> tuple[Path, Path]:
    if not _valid_sid(session_id):
        raise IsolationError(f"invalid session_id: {session_id!r}")
    base = _runs_root() / session_id
    ws = (base / "workspace").resolve()
    vd = (base / "verify").resolve()
    ws.mkdir(parents=True, exist_ok=True)
    vd.mkdir(parents=True, exist_ok=True)
    return ws, vd


def is_git_project(project_dir: str) -> bool:
    p = Path(project_dir).expanduser().resolve()
    r = subprocess.run(
        ["git", "-C", str(p), "rev-parse", "--is-inside-work-tree"],
        capture_output=True, text=True,
    )
    return r.returncode == 0 and r.stdout.strip() == "true"


def acquire_worktree(session_id: str, project_dir: str) -> tuple[Path, Path]:
    if not _valid_sid(session_id):
        raise IsolationError(f"invalid session_id: {session_id!r}")
    proj = Path(project_dir).expanduser().resolve()
    root = _worktrees_root()
    wt = (root / session_id).resolve()
    if wt.exists():
        return wt, wt
    if not is_git_project(str(proj)):
        raise IsolationError(f"not a git repo: {proj}")
    root.mkdir(parents=True, exist_ok=True)
    branch = f"argos/{session_id}"
    r = subprocess.run(
        ["git", "-C", str(proj), "worktree", "add", "-b", branch, str(wt), "HEAD"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        r2 = subprocess.run(
            ["git", "-C", str(proj), "worktree", "add", str(wt), branch],
            capture_output=True, text=True,
        )
        if r2.returncode != 0:
            raise IsolationError(f"git worktree add failed: {r.stderr.strip()[:500]} / {r2.stderr.strip()[:500]}")
    return wt, wt


def release_worktree(session_id: str, project_dir: str) -> None:
    if not _valid_sid(session_id):
        return
    proj = Path(project_dir).expanduser().resolve()
    wt = (_worktrees_root() / session_id).resolve()
    if not wt.exists():
        subprocess.run(["git", "-C", str(proj), "worktree", "prune"], capture_output=True, text=True)
        return
    subprocess.run(["git", "-C", str(proj), "worktree", "remove", "--force", str(wt)], capture_output=True, text=True)
    if wt.exists():
        shutil.rmtree(wt, ignore_errors=True)
    subprocess.run(["git", "-C", str(proj), "worktree", "prune"], capture_output=True, text=True)


def release_sandbox(session_id: str) -> None:
    if not _valid_sid(session_id):
        return
    base = _runs_root() / session_id
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
