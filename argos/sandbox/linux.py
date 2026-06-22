"""Linux 沙箱后端(任务:Linux VPS 无人值守跑;等价 Seatbelt 边界)。

设计:
- 优先 bwrap(强隔离:网络 OFF + 挂载命名空间 + 用户命名空间 + PID/IPC 命名空间;
  workspace bind-write, /tmp tmpfs, / ro-bind)
- 退而求其次 unshare(仍能 net/pid/ipc 隔离,但无 mount namespace → workspace
  牢笼弱于 bwrap;若 bwrap 不可用,用 unshare 至少保网络 OFF)
- 都不可用 → select_backend() 抛 RuntimeError,不假装隔离(诚实失败)

接口与 SeatbeltExecutor 对齐:spawn(workspace, namespace, allow_workflow, read_only)
通过 ARGOS_WORKSPACE env + JSON init 消息跟 _sandbox_child.py 通信(子进程入口跨平台)。

诚实的隔离强度(任务验收):
- bwrap:网络 OFF,workspace 写牢笼,读放宽(ro-bind / /)—— 等价 Seatbelt
- unshare:网络 OFF,workspace 仅靠 --chdir 防意外(无 bind mount)—— 比 bwrap 弱
- 都无:RuntimeError(不静默 fallback 到"无沙箱")
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import seatbelt
from .backend import ExecResult


# ── 工具探测(模块导入时一次性缓存)──────────────────────────
def _probe_backend() -> str | None:
    """探测可用后端:有 bwrap → "bwrap";只有 unshare → "unshare";都无 → None。"""
    if shutil.which("bwrap"):
        return "bwrap"
    if shutil.which("unshare"):
        return "unshare"
    return None


# 测试可 mock 此常量(避免重复探测 + 强制选某路径)
_AVAILABLE_BACKEND: str | None = _probe_backend()


# ── 公共:build linux argv(仿 seatbelt.confined_argv)─────────────────
def _bwrap_argv(workspace: Path, child_argv: list[str], *,
                allow_network: bool = False) -> list[str]:
    """bwrap argv:网络默认 OFF / 挂载命名空间 / 写牢笼 workspace / tmpfs /tmp / ro-bind / /

    挂载顺序关键(bwrap 按 argv 顺序应用 fs 操作):**先 `--ro-bind / /`(整根只读),
    最后 `--bind $WS $WS`(workspace 可写)** —— 因为 $WS 在 / 之下,可写 bind 必须后应用才能
    覆盖只读根的该子树。顺序写反会让 workspace 被只读根重新盖住 → run_command 写入 EROFS
    (2026-06-21 修;对齐 Codex bubblewrap 沙箱的 canonical 顺序)。

    allow_network=False(默认,安全不变量)→ `--unshare-net` 断网;True(出网阀经审批)→ 省略
    该 flag,子进程共享 host 网络命名空间(approved 的 pip/curl/git push 才能联网)。
    """
    ws = workspace.resolve()
    argv = [
        "bwrap",
        "--unshare-pid",       # PID 命名空间
        "--unshare-ipc",       # IPC 命名空间
        "--unshare-user",      # 用户命名空间(预存在 bug 修复 2026-06-21:--unshare-user-uid
                               # 不是合法 bwrap 选项,真 Linux 上 init 必失败 "Unknown option")
        "--uid", "0",          # 映射为 namespace 内 root → 获 CAP_NET_ADMIN,--unshare-net 才能
        "--gid", "0",          # 配 loopback(否则 bwrap "loopback: RTM_NEWADDR Operation not permitted")
        "--unshare-uts",       # UTS 命名空间
        "--die-with-parent",   # 父进程退出则子进程死
    ]
    if not allow_network:
        argv.append("--unshare-net")  # 网络 OFF(默认安全不变量,等价 Seatbelt deny network*)
    argv += [
        # 读放宽:/ 只读 bind 先应用(spec 允许模型 import 库 + 读项目源码)
        "--ro-bind", "/", "/",
        # 自身运行所需:dev(允许 /dev/null 等)+ proc
        "--dev", "/dev",
        "--proc", "/proc",
        # 临时目录:tmpfs(可写,被 namespace 隔离)
        "--tmpfs", "/tmp",
    ]
    # 凭据遮蔽:在只读根之上盖空,真密钥读不到(机制对齐 Seatbelt 的 deny file-read* ~/.ssh ...)。
    # Seatbelt 靠 stat 抛 EPERM;bwrap 对 namespace 内 mapped-root 无法让 stat 抛错,改用 tmpfs(目录)
    # / /dev/null(文件)遮蔽 —— 殊途同归:读侧凭据不可读。开"出网阀"(allow_network=True)时尤其
    # 关键(能读 ~/.ssh + 联网 = 真外泄)。复用 seatbelt 的同一份凭据清单,单一真源不漂移。
    argv += _credential_mask_args()
    argv += [
        # 写牢笼:workspace 绑定为可写 —— 最后应用,覆盖只读根的该子树(顺序关键,见 docstring)
        "--bind", str(ws), str(ws),
        # 跑子进程
        "--chdir", str(ws),
        "--",
        *child_argv,
    ]
    return argv


def _credential_mask_args() -> list[str]:
    """凭据遮蔽 bwrap argv 片段:目录 → 空 tmpfs;密钥文件 → /dev/null(读到空)。

    清单复用 seatbelt._CRED_DENY_DIRS / _CRED_DENY_FILES(macOS deny 的同一份),保证两后端不漂移。
    路径基于 Path.home():host 侧拼 argv 与沙箱子进程内的 Path.home() 同源(HOME 一致)。"""
    from .seatbelt import _CRED_DENY_DIRS, _CRED_DENY_FILES
    home = Path.home()
    args: list[str] = []
    # 只遮蔽【真实存在】的路径:① 不存在=无可泄露,跳过即安全(沙箱写牢笼禁止子进程新建它);
    # ② 关键 —— 在 `--ro-bind / /` 只读根之上,mount-over 已存在的目录/文件不需 mkdir(纯命名空间
    # 操作,只读也成立),而对不存在路径建挂载点会在只读根上 mkdir 失败(EROFS)拖垮整个 init。
    for d in _CRED_DENY_DIRS:
        p = home / d
        if p.exists():
            args += ["--tmpfs", str(p)]                    # 凭据目录:盖空 tmpfs,真内容看不到
    for f in _CRED_DENY_FILES:
        p = home / f
        if p.exists():
            args += ["--ro-bind", "/dev/null", str(p)]     # 密钥文件:盖 /dev/null,读到空
    return args


def _unshare_argv(workspace: Path, child_argv: list[str], *,
                  allow_network: bool = False) -> list[str]:
    """unshare fallback:无 mount 命名空间(workspace 牢笼弱);网络默认 OFF。

    退化路径:当 bwrap 不可用(老 Linux 发行版 / 容器内)时,至少保网络 OFF。
    workspace 防逃逸仅靠 --chdir(无 bind mount 隔离),所以严格说写牢笼弱于 bwrap。

    allow_network=False(默认)→ `--net` 断网;True(出网阀经审批)→ 省略,共享 host 网络。
    """
    ws = workspace.resolve()
    argv = [
        "unshare",
        "--user",            # 用户命名空间(让 --map-root-user 生效)
        "--map-root-user",   # 当前用户映成 namespace 内 root(子进程能 fork 自身)
    ]
    if not allow_network:
        argv.append("--net")  # 网络 OFF(默认关键不变量)
    argv += [
        "--pid",             # PID 命名空间
        "--mount",           # mount 命名空间(空,内层无新 mount,但隔离)
        "--fork",            # fork 一个新子进程(让 PID 命名空间生效)
        "--",
        *child_argv,
    ]
    return argv


def _linux_spawn(*, backend: str, workspace: Path, child_argv: list[str],
                 env: dict[str, str] | None = None) -> subprocess.Popen:
    """按 backend 选 bwrap/unshare 包子进程,返 Popen(stdin/stdout 管道)。

    与 seatbelt.spawn_child 签名对齐:caller 给 child_argv + env,内部写 .profile
    或拼 argv,返可 await 的 Popen。
    """
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    if backend == "bwrap":
        argv = _bwrap_argv(workspace, child_argv)
    elif backend == "unshare":
        argv = _unshare_argv(workspace, child_argv)
    else:
        from argos.i18n import t
        raise RuntimeError(t("sandbox.linux.unknown_backend", backend=backend))
    child_env = dict(env or os.environ)
    return subprocess.Popen(
        argv, cwd=str(workspace), env=child_env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )


# ── 后端实现 ────────────────────────────────────────
class _BaseLinuxExecutor:
    """BwrapExecutor / UnshareExecutor 共享的 spawn 子协议(与 SeatbeltExecutor 对齐)。"""

    backend: str = ""  # 子类覆盖:"bwrap" / "unshare"

    def __init__(self, broker_handler=None) -> None:
        self._broker_handler = broker_handler
        self._proc = None
        self._workspace: Path | None = None

    def spawn(self, *, workspace: Path, namespace: dict[str, Any],
              allow_workflow: bool = True, read_only: bool = False,
              tool_allowlist: "list[str] | None" = None) -> None:
        if _AVAILABLE_BACKEND is None:
            from argos.i18n import t
            raise RuntimeError(t("sandbox.linux.no_backend_spawn"))
        if self.backend and self.backend != _AVAILABLE_BACKEND:
            # 想用 bwrap 但只有 unshare(或反之)—— 降级提示但不抛(让代码继续跑)
            import warnings
            warnings.warn(
                f"沙箱后端退化:想用 {self.backend},实际用 {_AVAILABLE_BACKEND} "
                f"(前者更强,后者仅保网络隔离)",
                RuntimeWarning, stacklevel=2,
            )
            effective_backend = _AVAILABLE_BACKEND
        else:
            effective_backend = self.backend or _AVAILABLE_BACKEND
        self._workspace = Path(workspace)
        # 子进程 tools/files.py 写牢笼按 ARGOS_WORKSPACE 解析(模块级 WORKSPACE);
        # 必须把它对齐到本次 spawn 的 workspace(同 SeatbeltExecutor 行为)。
        child_env = {**os.environ, "ARGOS_WORKSPACE": str(workspace)}
        self._proc = _linux_spawn(
            backend=effective_backend, workspace=Path(workspace),
            child_argv=seatbelt.python_child_argv(), env=child_env,
        )
        import json
        authorized = namespace.get("__authorized_imports__") or None
        self._send({"op": "init", "authorized_imports": authorized,
                    "allow_workflow": allow_workflow, "read_only": read_only,
                    "tool_allowlist": list(tool_allowlist) if tool_allowlist is not None else None})
        msg = self._recv()
        if not msg or msg.get("type") != "init_ok":
            from argos.i18n import t
            raise RuntimeError(t("sandbox.executor.init_failed", msg=msg, stderr=self._drain_stderr()))

    def exec_code(self, code: str) -> ExecResult:
        from argos.i18n import t
        if self._proc is None:
            raise RuntimeError(t("sandbox.executor.not_spawned"))
        self._send({"op": "exec", "code": code})
        while True:
            msg = self._recv()
            if msg is None:
                return ExecResult(stdout="", value_repr="",
                                  exc=t("sandbox.executor.channel_closed", stderr=self._drain_stderr()))
            mtype = msg.get("type")
            if mtype == "broker_call":
                value = self._handle_broker_call(msg.get("action", ""), msg.get("args") or {})
                self._send({"type": "broker_reply", "value": value})
                continue
            if mtype == "exec_result":
                return ExecResult(stdout=msg.get("stdout", ""),
                                  value_repr=msg.get("value_repr", ""),
                                  exc=msg.get("exc", ""))
            # 未知消息忽略,继续等

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            self._send({"op": "close"})
            self._proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            self._proc.kill()
        finally:
            self._proc = None

    # ── 内部(与 SeatbeltExecutor 同) ─────────────────────────────
    def _handle_broker_call(self, action: str, args: dict[str, Any]) -> Any:
        if self._broker_handler is None:
            from argos.i18n import t
            return t("sandbox.executor.no_broker_context")
        return self._broker_handler(action, args)

    def _send(self, obj: dict[str, Any]) -> None:
        import json
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()

    def _recv(self) -> dict[str, Any] | None:
        import json
        assert self._proc is not None and self._proc.stdout is not None
        line = self._proc.stdout.readline()
        if not line:
            return None
        return json.loads(line)

    def _drain_stderr(self) -> str:
        if self._proc is None or self._proc.stderr is None:
            return ""
        try:
            return self._proc.stderr.read()[-2000:]
        except Exception:  # noqa: BLE001
            return ""


class BwrapExecutor(_BaseLinuxExecutor):
    """bwrap 后端:网络/挂载/用户/PID/IPC/UTS 全部 unshare;workspace bind-write, /tmp tmpfs。

    隔离强度等价 Seatbelt(deny-all + workspace 写牢笼 + 网络 OFF + 读放宽)。
    """
    backend = "bwrap"


class UnshareExecutor(_BaseLinuxExecutor):
    """unshare 退化后端:网络/PID/IPC 隔离;无 mount 命名空间 → workspace 牢笼弱于 bwrap。

    当 bwrap 不可用时,至少保网络 OFF(任务关键安全不变量)。诚实标注:写牢笼弱,
    依赖 OS 权限 + chdir 防意外。
    """
    backend = "unshare"


# ── 后端摘要(Contract D:供 TUIAPP/CLI 显示沙箱强度)───────────────
def sandbox_backend_summary() -> tuple[str, bool]:
    """返回 (backend_name, is_weak_cage)。

    - darwin / seatbelt → ("seatbelt", False)   —— 强:OS 内核 Seatbelt + workspace 写牢笼
    - linux + bwrap     → ("bwrap", False)       —— 强:挂载/用户/网络命名空间全隔离
    - linux + unshare   → ("unshare", True)      —— 弱:无 mount namespace,写牢笼仅靠 --chdir
    - 都不可用          → ("none", True)          —— 无沙箱(调用前应已 RuntimeError,此为防御)

    消费方约定(TUIAPP/CLI):
      is_weak_cage=True  → 显示警告标记(例:⚠ unshare 轻量牢笼)
      is_weak_cage=False → 正常显示(例:✓ seatbelt / bwrap 强隔离)
    """
    import sys as _sys
    if _sys.platform == "darwin":
        return ("seatbelt", False)
    if _sys.platform == "linux":
        if _AVAILABLE_BACKEND == "bwrap":
            return ("bwrap", False)
        if _AVAILABLE_BACKEND == "unshare":
            return ("unshare", True)
        return ("none", True)
    # 其他平台(win32 等):无沙箱
    return ("none", True)


# ── 平台 + 工具探测选择 ─────────────────────────────
def select_backend():
    """按平台 + 工具可用性选后端类(macOS → SeatbeltExecutor,Linux → bwrap/unshare)。

    Linux 上 bwrap 优先(强隔离);无 bwrap 退 unshare(网络隔离);都无 → RuntimeError
    (诚实失败,不假装隔离)。
    """
    if sys.platform == "darwin":
        # macOS 走 seatbelt;此处懒导入防循环
        from .executor import SeatbeltExecutor
        return SeatbeltExecutor
    if sys.platform == "linux":
        if _AVAILABLE_BACKEND == "bwrap":
            return BwrapExecutor
        if _AVAILABLE_BACKEND == "unshare":
            return UnshareExecutor
        from argos.i18n import t
        raise RuntimeError(t("sandbox.linux.no_backend_select"))
    from argos.i18n import t
    raise RuntimeError(t("sandbox.executor.win32_unsupported"))
