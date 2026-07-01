"""macOS Seatbelt(sandbox-exec)deny-all profile 生成 + 子进程拉起(spec §6.3)。

诚实边界(spec §6.7):Seatbelt 是进程级 confinement,不是 VM —— 防 agent 自己的错 +
便宜模型幻觉 + 顺手外泄,不防解释器 0-day 逃逸。要真 VM 走 roadmap 的 Apple Containerization。

profile 设计:
  · (deny default)        —— 默认全拒,白名单加回必需的。
  · file-read* 放宽       —— 模型要 import 标准库/三方库、读项目源码;读不是外泄向量(外泄靠网络/写)。
  · file-write* 仅 workspace 子树 + 系统 temp —— 写被牢笼,改不到 ~/.ssh、verify_dir、用户其它文件。
  · (deny network*)       —— 网络系统级关死;外泄 key 的代码连不出去。网络只能走 host broker allowlist。
  · process-exec / sysctl-read / mach-lookup —— 放行 Python 解释器自身运行所需的最小集。
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _temp_roots() -> list[str]:
    """系统 temp 根:tempfile.gettempdir() + macOS 真实 /private/var/folders 解析。"""
    roots: set[str] = set()
    t = Path(tempfile.gettempdir()).resolve()
    roots.add(str(t))
    # macOS 上 /tmp 与 /var 常软链到 /private/...;把两边都加白避免解析后越界。
    for extra in ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders"):
        p = Path(extra)
        if p.exists():
            roots.add(str(p.resolve()))
            roots.add(extra)
    return sorted(roots)


# 凭据目录/文件:Seatbelt 后匹配覆盖前面 (allow file-read*),故在其后 deny 这些路径的读。
# 网络 OFF 时读这些无法外泄,但一旦开"出网阀"(egress valve),全盘可读就成了真外泄风险
# ("能读 ~/.ssh 就已经game over" —— 2026 prompt-injection 共识)。开阀前先堵读侧(Phase 0)。
# 注意:只 deny ~/.argos 下的密钥【文件】,不 deny ~/.argos 目录本身 —— 默认工作区在
# ~/.argos/workspace,整目录 deny 会读不了工作区。
_CRED_DENY_DIRS = (
    ".ssh", ".aws", ".gnupg", ".kube", ".docker", ".azure",
    ".config/gh", ".config/gcloud",
)
_CRED_DENY_FILES = (
    ".netrc", ".pgpass", ".git-credentials", ".npmrc", ".pypirc",
    ".argos/.env", ".argos/config.json", ".argos/mcp.json",
)


def _resolved_and_raw(p: Path) -> set[str]:
    """一条路径的【未解析】+【解析后】两种字符串形式(对齐 _temp_roots 的双写)。
    resolve() 对不存在路径在 3.12 仍可用 —— 它解析存在的软链父级,把不存在的尾段原样保留,
    这正是我们要的:HOME 或凭据子目录是软链时,拿到内核 canonicalize 后的真实路径。"""
    return {str(p), str(p.resolve())}


def _credential_read_denies() -> str:
    """凭据目录(subpath)+ 密钥文件(literal)的读 deny 规则文本。

    macOS Seatbelt 在匹配 (subpath ...)/(literal ...) 前会 canonicalize(解析软链)被访问路径。
    若 HOME 本身是软链(如 /Users/alice -> /Volumes/data/alice),或某凭据子目录/文件被软链
    (chezmoi/yadm/stow 等 dotfile 管理器常见,如 ~/.ssh -> /other/path),仅 emit 未解析路径会让
    deny 前缀匹配不到内核规范化后的真实路径,而 (allow file-read*) 仍生效 → 凭据反而可读;
    出网阀(allow_network=True)一开就是真外泄路径。故每条都把【未解析】与【解析后】两种形式都
    emit(对齐 _temp_roots 的双写),无论内核按哪种匹配都堵住。"""
    home = Path.home()
    subpaths: set[str] = set()
    for d in _CRED_DENY_DIRS:
        subpaths |= _resolved_and_raw(home / d)
    literals: set[str] = set()
    for f in _CRED_DENY_FILES:
        literals |= _resolved_and_raw(home / f)
    parts = "".join(f'\n  (subpath "{s}")' for s in sorted(subpaths))
    parts += "".join(f'\n  (literal "{s}")' for s in sorted(literals))
    return f"(deny file-read*{parts})\n"


def build_profile(*, workspace: Path, allow_network: bool = False) -> str:
    """生成 deny-all Seatbelt profile 文本。workspace 子树 + temp 可写,凭据目录读拒。
    allow_network=False(默认)→ 网络全拒(安全默认);True → 网络放行(出网阀:broker 经审批/
    Autonomous 决定后才用,跑 pip install/git push 这类联网命令;写牢笼+凭据读拒仍在)。"""
    ws = str(workspace.resolve())
    # #2 CC对齐:--add-dir / ARGOS_ADD_DIRS 授权的额外可写目录也进 Seatbelt 可写集(workspace+temp 之外)。
    from argos.config import extra_write_dirs
    write_subpaths = [ws, *(_temp_roots()), *(str(d) for d in extra_write_dirs())]
    write_rules = "".join(f'\n  (subpath "{p}")' for p in write_subpaths)
    net_rule = "(allow network*)\n" if allow_network else "(deny network*)\n"
    return (
        "(version 1)\n"
        "(deny default)\n"
        # —— 进程自身运行所需(最小集)——
        "(allow process-fork)\n"
        "(allow process-exec*)\n"
        "(allow sysctl-read)\n"
        "(allow mach-lookup)\n"
        "(allow signal (target self))\n"
        "(allow ipc-posix-shm)\n"
        # —— 读放宽(import 库/读项目)——
        "(allow file-read*)\n"
        # —— 但凭据目录/密钥文件读拒(后匹配覆盖上面的全盘读;开出网阀前的前置安全)——
        + _credential_read_denies() +
        # —— 写牢笼:仅 workspace + temp ——
        f"(allow file-write*{write_rules})\n"
        # —— 网络:默认全拒(关键安全不变量);出网阀放行时改 (allow network*) ——
        + net_rule
    )


def wrap_command(profile_path: str, argv: list[str]) -> list[str]:
    """把一条命令用 sandbox-exec + profile 文件包起来。"""
    return ["/usr/bin/sandbox-exec", "-f", profile_path, *argv]


def confined_argv(*, workspace: Path, argv: list[str], allow_network: bool = False) -> list[str]:
    """把任意 argv 用本模块的 Seatbelt profile(写牢笼 workspace+temp、凭据读拒)包成 sandbox-exec argv。
    profile 写到 workspace 内的 .argos_run.sb。run_command 用它把 host 子进程关进沙箱:越界写被挡、
    凭据读拒;allow_network=False(默认)网络外泄不可能,True(出网阀经审批)放行联网命令。
    pytest/python/本地构建无需网络照常跑(读放宽能 import venv)。

    macOS only —— 调用方须先确认 sys.platform == 'darwin'(非 darwin 无 sandbox-exec)。
    """
    workspace.mkdir(parents=True, exist_ok=True)
    prof = build_profile(workspace=workspace, allow_network=allow_network)
    prof_file = workspace / ".argos_run.sb"
    prof_file.write_text(prof, encoding="utf-8")
    return wrap_command(str(prof_file), argv)


def spawn_child(*, workspace: Path, child_argv: list[str],
                env: dict[str, str] | None = None, sandbox: bool = True) -> subprocess.Popen:
    """拉起子进程,返回 Popen(stdin/stdout 管道)。
    sandbox=True(默认)→ 用 Seatbelt profile 裹(网络断 + 写牢笼 workspace+temp);profile 写到
    workspace 内临时文件(workspace 可写,符合 profile 自身约束)。
    sandbox=False(opt-in 默认关,#2 CC对齐)→ **不裹 sandbox-exec**,child_argv 直跑 —— 诚实:无
    内核级牢笼,但 broker + 审批 + egress + AST 治理仍在(它们不依赖 Seatbelt)。"""
    workspace.mkdir(parents=True, exist_ok=True)
    if sandbox:
        prof = build_profile(workspace=workspace)
        prof_file = workspace / ".argos_sandbox.sb"
        prof_file.write_text(prof, encoding="utf-8")
        argv = wrap_command(str(prof_file), child_argv)
    else:
        argv = list(child_argv)   # 未沙箱化:直跑(无 OS 牢笼)
    child_env = dict(env or os.environ)
    return subprocess.Popen(
        argv, cwd=str(workspace), env=child_env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )


# 冻结 binary(PyInstaller)里 sys.executable 是 argos 自身,不支持 `-m module`。
# 用这个哨兵 argv 让 argos 入口(__main__.main)在 argparse 之前早分发到沙箱子进程 RPC 循环。
SANDBOX_CHILD_FLAG = "--__argos_sandbox_child__"


def python_child_argv(child_module: str = "argos.sandbox._sandbox_child") -> list[str]:
    """沙箱子进程的 argv:
    · 开发态:`python -m argos.sandbox._sandbox_child`(sys.executable 是真解释器)。
    · 冻结态(PyInstaller):sys.executable 是 argos binary,不能 `-m`;改用哨兵 argv 重新调起
      自身,由 __main__ 早分发到 _sandbox_child.main()。"""
    if getattr(sys, "frozen", False):
        return [sys.executable, SANDBOX_CHILD_FLAG]
    return [sys.executable, "-m", child_module]
