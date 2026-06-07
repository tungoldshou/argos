"""WorktreeManager:为每个 run 隔离 git worktree 或 temp 目录(spec #5b §8)。

- `create(run_id, workspace) -> path`:git repo → `git worktree add`;否则 temp dir
- `cleanup(run_id) -> None`:git worktree remove + rm -rf;失败静默
- `is_git_repo(workspace) -> bool`:看 `<workspace>/.git` 存在

失败模式(spec §8.3):
  · git 不在 PATH → WorktreeError
  · workspace 不是 git repo → 走 tempdir(诚实标 fallback)
  · 创建 worktree git 报错 → WorktreeError
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from argos_agent import git_worktree as gw
from argos_agent.git_worktree import WorktreeError  # re-export:保持既有 import 路径不变

log = logging.getLogger(__name__)

__all__ = ["WorktreeError", "WorktreeManager"]


class WorktreeManager:
    """每 run 一个隔离 worktree(或 tempdir fallback)。"""

    def __init__(self, base_dir: Path | None = None):
        self._base = Path(base_dir) if base_dir else (Path.home() / ".argos" / "worktrees")
        self._base.mkdir(parents=True, exist_ok=True)

    @property
    def base_dir(self) -> Path:
        return self._base

    def is_git_repo(self, workspace: str) -> bool:
        return gw.is_git_repo(workspace)

    def create(self, *, run_id: str, workspace: str) -> str:
        """为 run 创建隔离工作目录;返回路径字符串。

        1. workspace 是 git repo + git 可用 → `git worktree add -b argos/<run_id> <base>/<run_id> HEAD`
        2. workspace 不是 git repo(或不存) → tempfile.mkdtemp(prefix=argos-<run_id>-) in base
        3. git 不可用 + workspace 是 git repo → WorktreeError
        """
        path = self._base / run_id
        if gw.is_git_repo(workspace) and gw.git_available():
            gw.add_worktree(repo=workspace, path=path, branch=f"argos/{run_id}", ref="HEAD")
            return str(path)
        # Fallback: temp dir(base 内)
        try:
            temp = Path(tempfile.mkdtemp(prefix=f"argos-{run_id}-", dir=str(self._base)))
            return str(temp)
        except OSError as e:
            raise WorktreeError(f"temp dir creation failed: {e}") from e

    def cleanup(self, run_id: str) -> None:
        """清理 worktree 目录。失败静默 log(spec §8.3 失败兜底)。

        1. 目录不存在 → noop
        2. 目录存在 → git worktree remove --force(若是 git worktree)→ shutil.rmtree

        temp fallback 时路径是 `argos-<rid>-<random>`,按 rid 前缀匹配找。
        """
        # 先尝试精确路径(worktree 主路径)
        candidates = [self._base / run_id]
        # 再尝试 temp 兜底路径(前缀匹配)
        for p in self._base.iterdir():
            if p.is_dir() and p.name.startswith(f"argos-{run_id}-"):
                candidates.append(p)
        for path in candidates:
            try:
                gw.remove_worktree(path)
            except Exception as e:  # noqa: BLE001
                log.warning("worktree cleanup failed for %s: %s", run_id, e)

    def path_for(self, run_id: str) -> Path:
        """返 run_id 对应路径(不保证存在,供查询)。"""
        return self._base / run_id
