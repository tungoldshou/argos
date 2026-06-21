"""broker-gated shell 工具的 host 侧真实现(契约 §4).

2026-06-20 重设(Codex/Claude Code 模型):run_command 不再有命令名白名单 / arg-inspection ——
那些在牢笼之上的层是鸡肋摩擦。**唯一边界是 OS 沙箱**,任意命令都能跑进去:
  · macOS 上把子进程关进 executor 同款 Seatbelt profile —— 默认网络全拒(deny network*)、
    写仅 workspace+temp、凭据目录读拒、其余读放宽。pytest/python/本地构建/python -c 照常跑,
    但网络外泄不可能、越界写被挡、读不到 ~/.ssh 等密钥。
  · Linux 上用 bwrap(优先)或 unshare 提供等价牢笼;都不可用时 honest-refuse —— 拒绝裸跑。
  · 危险命令(rm -rf / 等)由评估器 hard rule(permissions/)在【审批层】先拦,不靠命令名单。
  · 联网命令(pip install / git push / curl …)默认在牢笼里失败;经"出网阀"审批(Cautious 弹卡、
    Autonomous 自动)后用 allow_network=True 的 profile 跑 —— command_needs_network() 供 broker
    判定是否要走这条阀。

非 darwin/linux 平台(Windows 等)目前不支持 —— honest-refuse 返回明确错误。
"""
from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

from ..sandbox import seatbelt
from .files import _ws

# ALLOWED_CMDS:**verify 命令**白名单(verify_gate / self_test / eval 用它限制 verify_cmd 的首 token,
# 防 agent 声明任意命令当"验证")。**run_command 不再用它做名字级门禁** —— 那层在 2026-06-20 重设
# 里砍掉了(Codex/Claude Code 模型:边界是 OS 沙箱,不是命令名单;危险命令由评估器 hard rule 在
# 审批层先拦)。保留此集仅供 verify 侧;勿在 run_command 复用。
ALLOWED_CMDS: set[str] = {
    "node", "npm", "pnpm", "npx", "tsc", "eslint", "prettier",
    "python", "python3", "pytest", "ruff", "mypy",
    "cargo", "rustc", "go", "git", "ls", "cat", "grep", "rg", "echo", "pwd",
}

# 联网命令首词(broker 据此决定要不要走"出网阀":Cautious 弹卡问、Autonomous 自动)。
# 沙箱默认网络 OFF,这些命令在牢笼里会失败;经审批后用 allow_network profile 跑(出网阀)。
NETWORK_BINARIES: set[str] = {
    "pip", "pip3", "npm", "pnpm", "yarn", "npx", "curl", "wget", "ssh", "scp",
    "brew", "rsync", "ping", "nc", "telnet",
}
# git 的联网子命令(push/fetch/pull/clone/remote/submodule 需要网络)。
_GIT_NETWORK_SUBCMDS: set[str] = {
    "push", "pull", "fetch", "clone", "remote", "submodule", "ls-remote", "archive",
}


def _linux_available_backend() -> str | None:
    """探测 Linux 沙箱后端(可被测试 monkeypatch):bwrap 优先,unshare 次之,都无则 None。
    仅在 sys.platform == 'linux' 的路径里被调用。"""
    import shutil
    if shutil.which("bwrap"):
        return "bwrap"
    if shutil.which("unshare"):
        return "unshare"
    return None


def command_needs_network(command: str) -> bool:
    """启发式:这条命令是否需要网络(供 broker 决定是否走出网阀)。
    NETWORK_BINARIES 首词,或 git 的联网子命令。不精确无妨 —— 误判只是多/少弹一次出网卡。"""
    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    if not parts:
        return False
    bin_name = Path(parts[0]).name
    if bin_name in NETWORK_BINARIES:
        return True
    if bin_name == "git":
        for tok in parts[1:]:
            if not tok.startswith("-"):
                return tok in _GIT_NETWORK_SUBCMDS
    return False


def run_command(command: str, *, workspace: Path | None = None,
                allow_network: bool = False) -> tuple[str, int | None]:
    """host 侧执行命令,子进程关进 Seatbelt(写牢笼 workspace+temp、凭据读拒;默认网络 OFF)。
    返回 (输出串, exit_code)。exit_code 供 Receipt 用;解析失败时 exit_code=None。

    无命令名白名单(2026-06-20 重设,Codex/Claude Code 模型):边界是 OS 沙箱 —— 任意命令都能跑,
    但越界写被挡、凭据读拒、危险命令(rm -rf 等)由评估器 hard rule 在审批层先拦。
    allow_network=True 时用网络放行的 profile(broker 经"出网阀"审批/Autonomous 决定后传)。
    workspace 缺省由 files._ws() 解析。"""
    try:
        parts = shlex.split(command)
    except ValueError as e:
        return f"错误:命令解析失败 {e}", None
    if not parts:
        return "错误:空命令。", None
    ws = workspace if workspace is not None else _ws()
    ws.mkdir(parents=True, exist_ok=True)
    # ── 平台別沙箱路由 ──────────────────────────────────────────────────────
    # macOS: Seatbelt(sandbox-exec)写牢笼 workspace+temp,凭据读拒,网络默认 OFF。
    # Linux: bwrap(优先)或 unshare;都不可用时 honest-refuse —— 拒绝裸跑(P0 修复)。
    # 其他平台(Windows 等):暂不支持 → honest-refuse。
    if sys.platform == "darwin":
        argv = seatbelt.confined_argv(workspace=ws, argv=parts, allow_network=allow_network)
    elif sys.platform == "linux":
        backend = _linux_available_backend()
        if backend is None:
            return (
                "错误:no sandbox backend available on this platform"
                " (bwrap / unshare not found in PATH)"
                " — refusing to run shell command uncaged."
                " Install bwrap (bubblewrap) or unshare and retry.",
                1,
            )
        from ..sandbox.linux import _bwrap_argv, _unshare_argv
        # allow_network 必须穿透到 Linux cage —— 否则出网阀在 Linux 完全失效:bwrap/unshare 恒
        # 断网,approved 的 pip/curl/git push 静默失败(2026-06-21 修)。darwin 走 seatbelt 已 honor。
        if backend == "bwrap":
            argv = _bwrap_argv(workspace=ws, child_argv=parts, allow_network=allow_network)
        else:
            argv = _unshare_argv(workspace=ws, child_argv=parts, allow_network=allow_network)
    else:
        return (
            f"错误:no sandbox backend available on platform {sys.platform!r}"
            " — refusing to run shell command uncaged."
            " Argos supports macOS (Seatbelt) and Linux (bwrap/unshare) only.",
            1,
        )
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
