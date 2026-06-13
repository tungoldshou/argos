"""git worktree RAII —— 并行写子 agent 的隔离。诚实:非 git 工作区退共享 + 注记无硬隔离。
RAII:上下文退出必拆 worktree(含异常路径),不留残留。

底层 git 原语统一在 `argos.git_worktree`(与 daemon 的 WorktreeManager 共用一份),
本模块只负责 RAII 编排 + 子 agent 工作目录命名 + 降级注记。"""
from __future__ import annotations

import contextlib
import shutil
from collections.abc import Iterator
from pathlib import Path

from argos import git_worktree as gw


@contextlib.contextmanager
def worktree_for(base: Path, agent_id: str, isolation: str) -> Iterator[tuple[Path, str | None]]:
    """yield (workdir, note)。isolation=worktree 且 base 是 git 仓 → 独立 worktree;
    否则退 base 共享(note 说明原因)。退出时拆 worktree。"""
    if isolation != "worktree":
        yield base, None
        return
    if not gw.is_git_repo(base):
        yield base, "工作区非 git 仓库,无法 worktree 硬隔离 → 退共享工作区(并行写同名文件有撞车风险)"
        return
    safe = agent_id.replace("#", "_").replace("/", "_").replace(" ", "_")
    wt = base / ".argos_worktrees" / safe
    wt.parent.mkdir(parents=True, exist_ok=True)
    if wt.exists():
        shutil.rmtree(wt, ignore_errors=True)
    try:
        gw.add_worktree(repo=base, path=wt, branch=None)  # 游离头,不建命名分支
    except gw.WorktreeError as e:
        yield base, f"git worktree 创建失败({str(e)[:80]})→ 退共享工作区"
        return
    try:
        yield wt, None
    finally:
        gw.remove_worktree(wt, repo=base)
