"""SeatbeltExecutor —— SandboxBackend 的 macOS 实现(spec §6.2/§6.3/§14)。

把 smolagents LocalPythonExecutor 跑在 sandbox-exec(Seatbelt)包着的子进程内:
  · AST 限制(smolagents)+ OS 沙箱(Seatbelt)+ broker 边界 —— 纵深三层。
  · 子进程持久 Python 命名空间,变量跨 exec_code 存活。
  · broker-gated 工具在子进程内发 broker_call,本类把它转给注入的 broker_handler(host 侧)。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from . import seatbelt
from .backend import ExecResult

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
              allow_workflow: bool = True) -> None:
        self._workspace = workspace
        self._proc = seatbelt.spawn_child(
            workspace=workspace, child_argv=seatbelt.python_child_argv(),
        )
        authorized = namespace.get("__authorized_imports__") or None
        self._send({"op": "init", "authorized_imports": authorized,
                    "allow_workflow": allow_workflow})
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
            self._proc.wait(timeout=5)
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
