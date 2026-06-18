"""SeatbeltExecutor —— SandboxBackend 的 macOS 实现(spec §6.2/§6.3/§14)。

把 smolagents LocalPythonExecutor 跑在 sandbox-exec(Seatbelt)包着的子进程内:
  · AST 限制(smolagents)+ OS 沙箱(Seatbelt)+ broker 边界 —— 纵深三层。
  · 子进程持久 Python 命名空间,变量跨 exec_code 存活。
  · broker-gated 工具在子进程内发 broker_call,本类把它转给注入的 broker_handler(host 侧)。

任务:补 Linux 后端(linux.py 的 BwrapExecutor / UnshareExecutor)——
- `LinuxExecutor` 是 BwrapExecutor 的别名(优先 bwrap,运行时降级 unshare 仍走 BwrapExecutor 实例);
- `select_backend()` 在本模块也导出(懒导入 linux 防循环);
- 既有 `SeatbeltExecutor` 行为完全不变,1 处新增 4 行让 caller 也能一站式选平台后端。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from . import seatbelt
from .backend import ExecResult

if TYPE_CHECKING:
    from .linux import BwrapExecutor, UnshareExecutor

# broker_call 处理器签名:(action, args) -> 灌回沙箱的值(任意可 JSON 序列化)。
BrokerHandler = Callable[[str, dict[str, Any]], Any]


class SeatbeltExecutor:
    """实现 SandboxBackend(契约 §5)。单 run 单实例;非线程安全(单 run 串行 exec)。"""

    def __init__(self, broker_handler: BrokerHandler | None = None) -> None:
        # broker_handler 由 AgentLoop 注入(host 侧 CapabilityBroker.request 的同步桥)。
        # 留 None 时 broker_call 一律 fail-closed 拒绝(纯沙箱测试用)。
        self._broker_handler = broker_handler
        self._proc = None
        self._workspace: Path | None = None

    def spawn(self, *, workspace: Path, namespace: dict[str, Any],
              allow_workflow: bool = True, read_only: bool = False,
              tool_allowlist: "list[str] | None" = None) -> None:
        self._workspace = workspace
        # 子进程 tools/files.py 的 write_file 牢笼按 ARGOS_WORKSPACE 解析(模块级 WORKSPACE)。
        # 必须把它对齐到本次 spawn 的 workspace —— 否则写会落到继承自父进程的 env 默认目录
        # (常是 ~/.argos/workspace),再被 Seatbelt 挡成 "Operation not permitted" 静默失败。
        # worktree 隔离尤其依赖这条:子 agent 的写要落进 worktree,拆前才抓得到 diff。
        child_env = {**os.environ, "ARGOS_WORKSPACE": str(workspace)}
        self._proc = seatbelt.spawn_child(
            workspace=workspace, child_argv=seatbelt.python_child_argv(), env=child_env,
        )
        authorized = namespace.get("__authorized_imports__") or None
        self._send({"op": "init", "authorized_imports": authorized,
                    "allow_workflow": allow_workflow, "read_only": read_only,
                    "tool_allowlist": list(tool_allowlist) if tool_allowlist is not None else None})
        msg = self._recv()
        if not msg or msg.get("type") != "init_ok":
            raise RuntimeError(f"sandbox init 失败:{msg!r};stderr={self._drain_stderr()}")

    def exec_code(self, code: str) -> ExecResult:
        if self._proc is None:
            raise RuntimeError("executor 未 spawn")
        self._send({"op": "exec", "code": code})
        # 处理可能的 broker_call 往返,直到拿到 exec_result。
        while True:
            msg = self._recv()
            if msg is None:
                return ExecResult(stdout="", value_repr="",
                                  exc=f"沙箱通道意外关闭;stderr={self._drain_stderr()}")
            mtype = msg.get("type")
            if mtype == "broker_call":
                value = self._handle_broker_call(msg.get("action", ""), msg.get("args") or {})
                self._send({"type": "broker_reply", "value": value})
                continue
            if mtype == "exec_result":
                return ExecResult(stdout=msg.get("stdout", ""),
                                  value_repr=msg.get("value_repr", ""),
                                  exc=msg.get("exc", ""))
            # 未知消息忽略,继续等。

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            self._send({"op": "close"})
            # 1s(原 5s):cancel 中途断在 broker_call 时,子进程 parked 等 broker_reply,
            # 收不到 {"op":"close"} → wait 必超时再 kill。短超时把"卡满 5s"压到 ≤1s
            # (正常关闭子进程在读循环里即时退出,这条超时只在 parked 情况触发)。
            self._proc.wait(timeout=1)
        except Exception:  # noqa: BLE001
            self._proc.kill()
        finally:
            self._proc = None

    # ── 内部 ─────────────────────────────────────────────────────────────
    def _handle_broker_call(self, action: str, args: dict[str, Any]) -> Any:
        if self._broker_handler is None:
            return "错误:该工具需要 broker 授权但当前没有 broker 上下文,默认拒绝。"
        return self._broker_handler(action, args)

    def _send(self, obj: dict[str, Any]) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()

    def _recv(self) -> dict[str, Any] | None:
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


# ── Linux 后端别名(任务:caller 可一站式从 executor 选平台后端)──
# 懒导入:linux 模块有 shutil.which + import seatbelt,循环风险用懒加载防住。
_LinuxBackend: Any = None


def _get_linux_backend():
    global _LinuxBackend
    if _LinuxBackend is None:
        from . import linux as _linux
        # BwrapExecutor 优先(unshare 退化 BwrapExecutor 实例内部自处理;
        # 想强 unshare 用 linux.UnshareExecutor)
        _LinuxBackend = _linux.BwrapExecutor
    return _LinuxBackend


def LinuxExecutor(broker_handler=None):  # type: ignore[no-redef]
    """BwrapExecutor 的薄包装:实例化时若 bwrap 不可用,内部会退到 unshare。

    macOS 上 import 它仍能拿到类,但实际跑会 fail(Popen 找不到 bwrap);
    caller 应当按平台调 select_backend() 选合适后端,这里仅作"知道 Linux 后端在哪"的入口。
    """
    return _get_linux_backend()(broker_handler=broker_handler)


def select_backend():
    """按平台 + 工具可用性选后端类。懒转 linux.select_backend()。

    macOS → SeatbeltExecutor;Linux + bwrap → BwrapExecutor;Linux + 仅 unshare → UnshareExecutor;
    其他/都无 → RuntimeError。
    """
    if sys.platform == "darwin":
        return SeatbeltExecutor
    from .linux import select_backend as _linux_select
    return _linux_select()
