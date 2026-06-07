"""git worktree 底层原语 —— daemon 与 workflow 两条隔离路径共用的一份实现。

本模块只做最底层的三件事 + 一个诚实降级判定,**不决定**把 worktree 放哪、用不用
命名分支:那是上层策略(daemon 的 `WorktreeManager` 按 run_id 有状态管理、workflow 的
`worktree_for` RAII 上下文)各自的事。

提供:
  · `git_available()`        —— git 是否在 PATH
  · `is_git_repo(workspace)` —— 文件系统判定 `<workspace>/.git` 是否存在(目录或文件,
                                后者是 worktree 检出);不起子进程
  · `add_worktree(...)`      —— `git worktree add`;branch 给定走命名分支,否则 --detach
  · `remove_worktree(...)`   —— best-effort 拆 worktree + rm,全程不抛

诚实降级(两边共享的不变量):workspace 非 git 仓库时,上层退共享/temp 工作区并注记
"无硬隔离",绝不假装隔离成功。
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

WORKTREE_TIMEOUT_S = 10


class WorktreeError(Exception):
    """worktree git 操作失败(git 不在 PATH / git 报错 / 超时)。"""


def git_available() -> bool:
    """git 是否在 PATH。"""
    return shutil.which("git") is not None


def is_git_repo(workspace: str | Path) -> bool:
    """workspace 是否 git 仓:看 `<workspace>/.git` 是否存在(目录=普通仓,文件=worktree
    检出,两者都算)。文件系统判定,不起子进程。路径不存在/不可访问 → False。"""
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
    """在 repo 上新建一个 worktree 到 path。

    · branch 给定 → `git worktree add -b <branch> <path> <ref>`(命名分支,daemon 用)
    · branch=None → `git worktree add --detach <path>`(游离头,workflow 用)

    失败抛 `WorktreeError`:git 不在 PATH(FileNotFoundError)、git 非零退出
    (CalledProcessError)、超时(TimeoutExpired)三种都归一到它。
    """
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
    """拆掉 path 处的 worktree 并删目录。best-effort:git 报错也兜底 `shutil.rmtree`,
    全程不抛 —— cleanup 是事后兜底,run 状态机已落,清理失败只 log 不影响正确性。

    · repo 给定 → `git -C <repo> worktree remove --force <path>`(repo 与 worktree
      异地时从仓库侧拆,workflow 用)
    · repo=None → `git worktree remove --force <path>`(daemon 用:它不持有源仓路径,
      git 拆不掉就靠 rmtree 兜底)
    """
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
        except Exception as e:  # noqa: BLE001 — git 拆失败不抛,下面 rmtree 兜底
            log.debug("remove_worktree: git remove failed for %s: %s", p, e)
    shutil.rmtree(p, ignore_errors=True)
