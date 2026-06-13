"""broker-gated shell 工具的 host 侧真实现(契约 §4).

C1 安全修复(spec §6.2/§6.3):run_command 曾在 host 侧无约束跑 subprocess(全网络 +
能读写 workspace 外),是一个可被 `python3 -c "...urlopen(...read('~/.ssh/id_rsa'))"`
利用的外泄原语。现三层防御:
  ① OS 沙箱(真边界):macOS 上把子进程关进 executor 同款 Seatbelt profile —— 网络全拒
     (deny network*)、写仅 workspace+temp、读放宽。pytest/python/本地构建仍能跑(无需网络),
     但网络外泄不可能、越界写被挡。
  ② arg-inspection(纵深):拒 python/node 内联 eval(-c/-e/--eval/- stdin)与 npx 任意包执行,
     不出厂一个显眼的内联 eval 原语(真边界仍是 OS 沙箱)。
  ③ 白名单 + git 只读校验(沿用旧 tools.py,6/2 git RCE fix 已并入)。

权衡(MVP 可接受,见 CHANGELOG):network OFF 下合法联网命令(pip install / git fetch|push /
npm install)会被拒 —— 这是安全默认值;"显式批准联网的命令"路径留作后续。
"""
from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

from ..sandbox import seatbelt
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
# 解释器内联 eval / stdin 求值标志 —— 出厂即拒(纵深;真边界是 OS 沙箱)。
_INTERPRETER_EVAL_FLAGS: dict[str, set[str]] = {
    "python": {"-c", "-e", "--eval"},
    "python3": {"-c", "-e", "--eval"},
    "node": {"-e", "--eval", "-p", "--print", "--eval-string"},
}


def _validate_git(parts: list[str]) -> str | None:
    """git 专用校验(M6:意图显式化)。
    RCE 向量 = 子命令【之前】的全局选项(`git -c core.sshCommand=… status` /
    `git --exec-path=…`)。故:
      ① 扫到第一个非 `-` token 作子命令;在它之前出现任何 `-` 开头的 token → 拒(全局选项注入)。
      ② 子命令必须在只读白名单。
      ③ 子命令【之后】的旗标(如 `git show --stat`)是该子命令的局部选项,安全放行。"""
    rest = parts[1:]
    if not rest:
        return "错误:git 需要一个子命令。"
    subcmd: str | None = None
    for tok in rest:
        if tok.startswith("-"):
            # 子命令尚未出现 → 这是全局选项(RCE 向量),拒。
            return f"错误:git 全局选项 {tok!r} 不被允许(防 `git -c …` 参数注入执行任意命令)。"
        subcmd = tok
        break
    if subcmd is None:                      # 理论上不可达(rest 非空且无非选项 token)
        return "错误:git 需要一个子命令。"
    if subcmd not in GIT_READONLY_SUBCMDS:
        return (
            f"错误:git 子命令 {subcmd!r} 不被允许。只放行只读子命令:"
            f"{', '.join(sorted(GIT_READONLY_SUBCMDS))}"
            "(push/pull/fetch/clone/remote/config/submodule 等被禁)。"
        )
    return None


def _validate_interpreter_args(bin_name: str, parts: list[str]) -> str | None:
    """纵深:拒解释器内联 eval(-c/-e/--eval)、python stdin(裸 `-`)、npx 任意包执行。
    OS 沙箱才是真边界,但不出厂一个显眼的内联 eval 原语。"""
    args = parts[1:]
    eval_flags = _INTERPRETER_EVAL_FLAGS.get(bin_name)
    if eval_flags is not None:
        for tok in args:
            if tok in eval_flags:
                return (
                    f"错误:{bin_name} 内联求值标志 {tok!r} 不被允许 —— 请把代码写进 workspace "
                    "内的脚本文件再执行(沙箱里跑脚本是安全的)。"
                )
            if bin_name in ("python", "python3") and tok == "-":
                return "错误:python 从 stdin 求值(裸 `-`)不被允许 —— 请用 workspace 内的脚本文件。"
    if bin_name == "npx":
        return (
            "错误:npx 执行任意包不被允许(等价拉取并运行任意代码)。"
            "请用已声明的本地依赖 / 脚本,或让用户显式批准。"
        )
    return None


def run_command(command: str, *, workspace: Path | None = None) -> tuple[str, int | None]:
    """host 侧执行白名单命令,子进程关进 Seatbelt(网络 OFF + 写牢笼 workspace)。
    返回 (输出串, exit_code)。exit_code 供 Receipt 用;校验失败/解析失败时 exit_code=None。
    workspace 缺省由 files._ws() 解析;遗留 LangChain 路径显式传它自己的 _ws() 保持隔离。"""
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
    interp_err = _validate_interpreter_args(bin_name, parts)
    if interp_err:
        return interp_err, None
    ws = workspace if workspace is not None else _ws()
    ws.mkdir(parents=True, exist_ok=True)
    # C1:macOS 上把子进程关进 Seatbelt(网络 OFF、写仅 workspace+temp);非 darwin 退回裸跑
    # (Seatbelt 仅 macOS;打包目标平台 = macOS,Linux 上 run_command 仅供测试且无 OS 边界)。
    if sys.platform == "darwin":
        argv = seatbelt.confined_argv(workspace=ws, argv=parts)
    else:
        argv = parts
    try:
        r = subprocess.run(argv, cwd=ws, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return "错误:命令超时(60s)。", None
    except Exception as e:  # noqa: BLE001
        return f"错误:执行失败 {e}", None
    out = (r.stdout or "")[-3000:]
    err = (r.stderr or "")[-2000:]
    text = f"[exit_code={r.returncode}]\n--- stdout ---\n{out}\n--- stderr ---\n{err}".strip()
    return text, r.returncode
