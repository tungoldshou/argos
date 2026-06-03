"""broker-gated shell 工具的 host 侧真实现(契约 §4).

run_command 在 host 侧执行真 subprocess —— 但仍受 ALLOWED_CMDS 白名单 + git 只读校验
约束(沿用旧 tools.py 的安全逻辑,6/2 git RCE fix 已并入)。
"""
from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from .files import _ws

# 沿用旧 tools.py 的白名单(契约 §4 要求"沿用现值")。
ALLOWED_CMDS: set[str] = {
    "node", "npm", "pnpm", "npx", "tsc", "eslint", "prettier",
    "python", "python3", "pytest", "ruff", "mypy",
    "cargo", "rustc", "go", "git", "ls", "cat", "grep", "rg", "echo", "pwd",
}
GIT_READONLY_SUBCMDS: set[str] = {
    "status", "diff", "log", "show", "branch", "ls-files", "rev-parse",
    "describe", "blame", "shortlog", "tag", "rev-list", "cat-file", "show-ref",
}


def _validate_git(parts: list[str]) -> str | None:
    """git 专用校验:子命令前任何全局选项(-c/-C/--exec-path)一律拒(防参数注入 RCE)。"""
    for tok in parts[1:]:
        if tok.startswith("-"):
            return f"错误:git 全局选项 {tok!r} 不被允许(防 `git -c …` 参数注入执行任意命令)。"
        if tok not in GIT_READONLY_SUBCMDS:
            return (
                f"错误:git 子命令 {tok!r} 不被允许。只放行只读子命令:"
                f"{', '.join(sorted(GIT_READONLY_SUBCMDS))}"
                "(push/pull/fetch/clone/remote/config/submodule 等被禁)。"
            )
        return None
    return "错误:git 需要一个子命令。"


def run_command(command: str) -> tuple[str, int | None]:
    """host 侧执行白名单命令。返回 (输出串, exit_code)。exit_code 供 Receipt 用;
    校验失败/解析失败时 exit_code=None。"""
    try:
        parts = shlex.split(command)
    except ValueError as e:
        return f"错误:命令解析失败 {e}", None
    if not parts:
        return "错误:空命令。", None
    bin_name = Path(parts[0]).name
    if bin_name not in ALLOWED_CMDS:
        return f"错误:命令 {bin_name!r} 不在白名单。允许:{', '.join(sorted(ALLOWED_CMDS))}", None
    if bin_name == "git":
        git_err = _validate_git(parts)
        if git_err:
            return git_err, None
    ws = _ws()
    ws.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(parts, cwd=ws, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return "错误:命令超时(60s)。", None
    except Exception as e:  # noqa: BLE001
        return f"错误:执行失败 {e}", None
    out = (r.stdout or "")[-3000:]
    err = (r.stderr or "")[-2000:]
    text = f"[exit_code={r.returncode}]\n--- stdout ---\n{out}\n--- stderr ---\n{err}".strip()
    return text, r.returncode
