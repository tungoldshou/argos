from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import seatbelt
from .backend import ExecResult


def _probe_backend() -> str | None:
    if shutil.which("bwrap"):
        return "bwrap"
    if shutil.which("unshare"):
        return "unshare"
    return None


_AVAILABLE_BACKEND: str | None = _probe_backend()


def _bwrap_argv(workspace: Path, child_argv: list[str], *,
                allow_network: bool = False) -> list[str]:
    ws = workspace.resolve()
    argv = [
        "bwrap",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-user",
        "--uid", "0",
        "--gid", "0",
        "--unshare-uts",
        "--die-with-parent",
    ]
    if not allow_network:
        argv.append("--unshare-net")
    argv += [
        "--ro-bind", "/", "/",
        "--dev", "/dev",
        "--proc", "/proc",
        "--tmpfs", "/tmp",
    ]
    from argos.config import extra_write_dirs
    extra_binds: list[str] = []
    for d in extra_write_dirs():
        if d.exists():
            extra_binds += ["--bind", str(d), str(d)]
    credential_masks = _credential_mask_args()
    argv += [
        "--bind", str(ws), str(ws),
        *extra_binds,
        *credential_masks,
        "--chdir", str(ws),
        "--",
        *child_argv,
    ]
    return argv


def _credential_mask_args() -> list[str]:
    from .seatbelt import _ARGOS_CONFIG_DENY_FILES, _CRED_DENY_DIRS, _CRED_DENY_FILES
    home = Path.home()
    args: list[str] = []
    seen_dirs: set[str] = set()
    for d in _CRED_DENY_DIRS:
        p = home / d
        for q in (p, p.resolve()):
            key = str(q)
            if key in seen_dirs:
                continue
            seen_dirs.add(key)
            if q.exists():
                args += ["--tmpfs", str(q)]
    files = [home / f for f in _CRED_DENY_FILES]
    try:
        from argos import config
        config_dir = Path(config.get("ARGOS_CONFIG_DIR") or (home / ".argos")).expanduser()
        files.extend(config_dir / f for f in _ARGOS_CONFIG_DENY_FILES)
    except Exception:  # noqa: BLE001
        pass
    seen: set[str] = set()
    for p in files:
        for q in (p, p.resolve()):
            key = str(q)
            if key in seen:
                continue
            seen.add(key)
            if q.exists():
                args += ["--ro-bind", "/dev/null", str(q)]
    return args


def _unshare_argv(workspace: Path, child_argv: list[str], *,
                  allow_network: bool = False) -> list[str]:
    ws = workspace.resolve()
    argv = [
        "unshare",
        "--user",
        "--map-root-user",
    ]
    if not allow_network:
        argv.append("--net")
    argv += [
        "--pid",
        "--mount",
        "--fork",
        "--",
        *child_argv,
    ]
    return argv


def _linux_spawn(*, backend: str, workspace: Path, child_argv: list[str],
                 env: dict[str, str] | None = None, sandbox: bool = True) -> subprocess.Popen:
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    if not sandbox:
        argv = list(child_argv)
    elif backend == "bwrap":
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


class _BaseLinuxExecutor:

    backend: str = ""

    def __init__(self, broker_handler=None) -> None:
        self._broker_handler = broker_handler
        self._proc = None
        self._workspace: Path | None = None

    def spawn(self, *, workspace: Path, namespace: dict[str, Any],
              allow_workflow: bool = True, read_only: bool = False,
              tool_allowlist: "list[str] | None" = None) -> None:
        from argos.config import sandbox_enabled
        _sandbox = sandbox_enabled()
        effective_backend = ""
        if _sandbox:
            if _AVAILABLE_BACKEND is None:
                from argos.i18n import t
                raise RuntimeError(t("sandbox.linux.no_backend_spawn"))
            if self.backend and self.backend != _AVAILABLE_BACKEND:
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
        child_env = {**os.environ, "ARGOS_WORKSPACE": str(workspace)}
        self._proc = _linux_spawn(
            backend=effective_backend, workspace=Path(workspace),
            child_argv=seatbelt.python_child_argv(), env=child_env, sandbox=_sandbox,
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
    backend = "bwrap"


class UnshareExecutor(_BaseLinuxExecutor):
    backend = "unshare"


def sandbox_backend_summary() -> tuple[str, bool]:
    import sys as _sys
    if _sys.platform == "darwin":
        return ("seatbelt", False)
    if _sys.platform == "linux":
        if _AVAILABLE_BACKEND == "bwrap":
            return ("bwrap", False)
        if _AVAILABLE_BACKEND == "unshare":
            return ("unshare", True)
        return ("none", True)
    return ("none", True)


def select_backend():
    if sys.platform == "darwin":
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
