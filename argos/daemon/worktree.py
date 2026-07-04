from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from argos import git_worktree as gw
from argos.git_worktree import WorktreeError

log = logging.getLogger(__name__)

__all__ = ["WorktreeError", "WorktreeManager"]


class WorktreeManager:

    def __init__(self, base_dir: Path | None = None):
        if base_dir is None:
            from argos import config

            base_dir = config.config_dir() / "worktrees"
        self._base = Path(base_dir).expanduser()
        self._base.mkdir(parents=True, exist_ok=True)

    @property
    def base_dir(self) -> Path:
        return self._base

    def is_git_repo(self, workspace: str) -> bool:
        return gw.is_git_repo(workspace)

    def create(self, *, run_id: str, workspace: str) -> str:
        path = self._base / run_id
        if gw.is_git_repo(workspace) and gw.git_available():
            gw.add_worktree(repo=workspace, path=path, branch=f"argos/{run_id}", ref="HEAD")
            return str(path)
        try:
            temp = Path(tempfile.mkdtemp(prefix=f"argos-{run_id}-", dir=str(self._base)))
            return str(temp)
        except OSError as e:
            raise WorktreeError(f"temp dir creation failed: {e}") from e

    def cleanup(self, run_id: str) -> None:
        candidates = [self._base / run_id]
        for p in self._base.iterdir():
            if p.is_dir() and p.name.startswith(f"argos-{run_id}-"):
                candidates.append(p)
        for path in candidates:
            try:
                gw.remove_worktree(path)
            except Exception as e:  # noqa: BLE001
                log.warning("worktree cleanup failed for %s: %s", run_id, e)

    def path_for(self, run_id: str) -> Path:
        return self._base / run_id
