"""每个并发 run 的隔离区分配 + 回收。

- sandbox 模式:每会话一个 ~/.argos/runs/<session>/{workspace,verify} 子目录。
- project 模式 + git:每会话一个 git worktree(分支 argos/<session>),worker 互不踩、
  用户工作树不被动;review 分支再 merge(契合 GTM)。
- project 模式 + 非 git:无法 worktree → 由 server 降级"原地 + 该项目单飞"(本模块只负责
  诚实报 is_git_project=False,降级策略在 server)。

worktree 用 server 端 subprocess(基础设施),与 agent 被锁成只读的 run_command 工具无关。
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

RUNS_ROOT = Path.home() / ".argos" / "runs"
WORKTREES_ROOT = Path.home() / ".argos" / "worktrees"


class IsolationError(RuntimeError):
    """隔离区创建失败(worktree add 失败等)。server 据此直接 error,绝不退回原地假装隔离。"""


def acquire_sandbox(session_id: str) -> tuple[Path, Path]:
    """sandbox:返回该会话专属 (workspace, verify)。幂等(多轮复用)。"""
    base = RUNS_ROOT / session_id
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
    """project+git:在 worktree 里隔离,返回 (worktree, worktree)。分支 argos/<session>。
    幂等:worktree 已存在(同会话多轮)直接复用。非 git/失败 → IsolationError。"""
    proj = Path(project_dir).expanduser().resolve()
    wt = (WORKTREES_ROOT / session_id).resolve()
    if wt.exists():
        return wt, wt
    if not is_git_project(str(proj)):
        raise IsolationError(f"not a git repo: {proj}")
    WORKTREES_ROOT.mkdir(parents=True, exist_ok=True)
    branch = f"argos/{session_id}"
    r = subprocess.run(
        ["git", "-C", str(proj), "worktree", "add", "-b", branch, str(wt), "HEAD"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise IsolationError(f"git worktree add failed: {r.stderr.strip()[:200]}")
    return wt, wt


def release_worktree(session_id: str, project_dir: str) -> None:
    """回收 worktree(LRU 淘汰时)。worktree remove 失败也强删目录兜底。"""
    proj = Path(project_dir).expanduser().resolve()
    wt = (WORKTREES_ROOT / session_id).resolve()
    if not wt.exists():
        return
    subprocess.run(
        ["git", "-C", str(proj), "worktree", "remove", "--force", str(wt)],
        capture_output=True, text=True,
    )
    if wt.exists():
        shutil.rmtree(wt, ignore_errors=True)


def release_sandbox(session_id: str) -> None:
    base = RUNS_ROOT / session_id
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
