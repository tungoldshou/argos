"""git worktree RAII —— 并行写子 agent 的隔离。诚实:非 git 工作区退共享 + 注记无硬隔离。
RAII:上下文退出必拆 worktree(含异常路径),不留残留。"""
from __future__ import annotations

import contextlib
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path


def _is_git_repo(base: Path) -> bool:
    r = subprocess.run(["git", "-C", str(base), "rev-parse", "--is-inside-work-tree"],
                       capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == "true"


@contextlib.contextmanager
def worktree_for(base: Path, agent_id: str, isolation: str) -> Iterator[tuple[Path, str | None]]:
    """yield (workdir, note)。isolation=worktree 且 base 是 git 仓 → 独立 worktree;
    否则退 base 共享(note 说明原因)。退出时拆 worktree。"""
    if isolation != "worktree":
        yield base, None
        return
    if not _is_git_repo(base):
        yield base, "工作区非 git 仓库,无法 worktree 硬隔离 → 退共享工作区(并行写同名文件有撞车风险)"
        return
    safe = agent_id.replace("#", "_").replace("/", "_").replace(" ", "_")
    wt = base / ".argos_worktrees" / safe
    wt.parent.mkdir(parents=True, exist_ok=True)
    if wt.exists():
        shutil.rmtree(wt, ignore_errors=True)
    r = subprocess.run(["git", "-C", str(base), "worktree", "add", "--detach", str(wt)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        yield base, f"git worktree 创建失败({r.stderr.strip()[:80]})→ 退共享工作区"
        return
    try:
        yield wt, None
    finally:
        subprocess.run(["git", "-C", str(base), "worktree", "remove", "--force", str(wt)],
                       capture_output=True, text=True)
        shutil.rmtree(wt, ignore_errors=True)
