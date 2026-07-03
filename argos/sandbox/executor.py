"""Internal documentation."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from argos.i18n import t
from . import seatbelt
from .backend import ExecResult

if TYPE_CHECKING:
    from .linux import BwrapExecutor, UnshareExecutor

BrokerHandler = Callable[[str, dict[str, Any]], Any]


class SeatbeltExecutor:
    """Internal documentation."""

    def __init__(self, broker_handler: BrokerHandler | None = None) -> None:
        self._broker_handler = broker_handler
        self._proc = None
        self._workspace: Path | None = None

    def spawn(self, *, workspace: Path, namespace: dict[str, Any],
              allow_workflow: bool = True, read_only: bool = False,
              tool_allowlist: "list[str] | None" = None) -> None:
        self._workspace = workspace
        child_env = {**os.environ, "ARGOS_WORKSPACE": str(workspace)}
        from argos.config import sandbox_enabled
        self._proc = seatbelt.spawn_child(
            workspace=workspace, child_argv=seatbelt.python_child_argv(), env=child_env,
            sandbox=sandbox_enabled(),
        )
        authorized = namespace.get("__authorized_imports__") or None
        self._send({"op": "init", "authorized_imports": authorized,
                    "allow_workflow": allow_workflow, "read_only": read_only,
                    "tool_allowlist": list(tool_allowlist) if tool_allowlist is not None else None})
        msg = self._recv()
        if not msg or msg.get("type") != "init_ok":
            raise RuntimeError(t("sandbox.executor.init_failed", msg=msg, stderr=self._drain_stderr()))

    def exec_code(self, code: str) -> ExecResult:
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

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            self._send({"op": "close"})
            self._proc.wait(timeout=1)
        except Exception:  # noqa: BLE001
            self._proc.kill()
        finally:
            self._proc = None

    def _handle_broker_call(self, action: str, args: dict[str, Any]) -> Any:
        if self._broker_handler is None:
            return t("sandbox.executor.no_broker_context")
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


_LinuxBackend: Any = None


def _get_linux_backend():
    global _LinuxBackend
    if _LinuxBackend is None:
        from . import linux as _linux
        _LinuxBackend = _linux.BwrapExecutor
    return _LinuxBackend


def LinuxExecutor(broker_handler=None):  # type: ignore[no-redef]
    """Internal documentation."""
    return _get_linux_backend()(broker_handler=broker_handler)


def select_backend():
    """Internal documentation."""
    from argos.config import sandbox_enabled
    if not sandbox_enabled():
        return SeatbeltExecutor
    if sys.platform == "darwin":
        return SeatbeltExecutor
    if sys.platform == "win32":
        raise RuntimeError(t("sandbox.executor.win32_unsupported"))
    from .linux import select_backend as _linux_select
    return _linux_select()
