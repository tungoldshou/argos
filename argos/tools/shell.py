from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

from ..sandbox import seatbelt
from .files import _ws
from argos.i18n import t

ALLOWED_CMDS: set[str] = {
    "node", "npm", "pnpm", "npx", "tsc", "eslint", "prettier",
    "python", "python3", "pytest", "ruff", "mypy",
    "cargo", "rustc", "go", "git", "ls", "cat", "grep", "rg", "echo", "pwd",
}

NETWORK_BINARIES: set[str] = {
    "pip", "pip3", "npm", "pnpm", "yarn", "npx", "curl", "wget", "ssh", "scp",
    "brew", "rsync", "ping", "nc", "telnet",
}
_GIT_NETWORK_SUBCMDS: set[str] = {
    "push", "pull", "fetch", "clone", "remote", "submodule", "ls-remote", "archive",
}


def _linux_available_backend() -> str | None:
    import shutil
    if shutil.which("bwrap"):
        return "bwrap"
    if shutil.which("unshare"):
        return "unshare"
    return None


def command_needs_network(command: str) -> bool:
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
    try:
        parts = shlex.split(command)
    except ValueError as e:
        return t("tools.shell.parse_error", exc=e), None
    if not parts:
        return t("tools.shell.empty_command"), None
    ws = workspace if workspace is not None else _ws()
    ws.mkdir(parents=True, exist_ok=True)
    from argos.config import sandbox_enabled
    if not sandbox_enabled():
        argv = parts
    elif sys.platform == "darwin":
        argv = seatbelt.confined_argv(workspace=ws, argv=parts, allow_network=allow_network)
    elif sys.platform == "linux":
        backend = _linux_available_backend()
        if backend is None:
            return t("tools.shell.no_backend_linux"), 1
        from ..sandbox.linux import _bwrap_argv, _unshare_argv
        if backend == "bwrap":
            argv = _bwrap_argv(workspace=ws, child_argv=parts, allow_network=allow_network)
        else:
            argv = _unshare_argv(workspace=ws, child_argv=parts, allow_network=allow_network)
    else:
        return t("tools.shell.no_backend_platform", platform=sys.platform), 1
    try:
        r = subprocess.run(argv, cwd=ws, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return t("tools.shell.timeout"), None
    except Exception as e:  # noqa: BLE001
        return t("tools.shell.exec_failed", exc=e), None
    out = (r.stdout or "")[-3000:]
    err = (r.stderr or "")[-2000:]
    text = f"[exit_code={r.returncode}]\n--- stdout ---\n{out}\n--- stderr ---\n{err}".strip()
    return text, r.returncode
