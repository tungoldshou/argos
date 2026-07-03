from __future__ import annotations

import contextlib
import shutil
from collections.abc import Iterator
from pathlib import Path

from argos import git_worktree as gw
from argos.i18n import t


@contextlib.contextmanager
def worktree_for(base: Path, agent_id: str, isolation: str) -> Iterator[tuple[Path, str | None]]:
    if isolation != "worktree":
        yield base, None
        return
    if not gw.is_git_repo(base):
        yield base, t("wf.worktree.not_git_repo")
        return
    safe = agent_id.replace("#", "_").replace("/", "_").replace(" ", "_")
    wt = base / ".argos_worktrees" / safe
    wt.parent.mkdir(parents=True, exist_ok=True)
    if wt.exists():
        shutil.rmtree(wt, ignore_errors=True)
    try:
        gw.add_worktree(repo=base, path=wt, branch=None)
    except gw.WorktreeError as e:
        yield base, t("wf.worktree.create_failed", error=str(e)[:80])
        return
    try:
        yield wt, None
    finally:
        gw.remove_worktree(wt, repo=base)
