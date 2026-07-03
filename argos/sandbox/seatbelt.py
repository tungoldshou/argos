from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _temp_roots() -> list[str]:
    roots: set[str] = set()
    t = Path(tempfile.gettempdir()).resolve()
    roots.add(str(t))
    for extra in ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders"):
        p = Path(extra)
        if p.exists():
            roots.add(str(p.resolve()))
            roots.add(extra)
    return sorted(roots)


_CRED_DENY_DIRS = (
    ".ssh", ".aws", ".gnupg", ".kube", ".docker", ".azure",
    ".config/gh", ".config/gcloud",
)
_CRED_DENY_FILES = (
    ".netrc", ".pgpass", ".git-credentials", ".npmrc", ".pypirc",
    ".argos/.env", ".argos/config.json", ".argos/mcp.json",
)
_ARGOS_CONFIG_DENY_FILES = (".env", "config.json", "mcp.json")


def _resolved_and_raw(p: Path) -> set[str]:
    return {str(p), str(p.resolve())}


def _credential_read_denies() -> str:
    home = Path.home()
    subpaths: set[str] = set()
    for d in _CRED_DENY_DIRS:
        subpaths |= _resolved_and_raw(home / d)
    literals: set[str] = set()
    for f in _CRED_DENY_FILES:
        literals |= _resolved_and_raw(home / f)
    try:
        from argos import config
        config_dir = Path(config.get("ARGOS_CONFIG_DIR") or (home / ".argos")).expanduser()
        for f in _ARGOS_CONFIG_DENY_FILES:
            literals |= _resolved_and_raw(config_dir / f)
    except Exception:  # noqa: BLE001
        pass
    parts = "".join(f'\n  (subpath "{s}")' for s in sorted(subpaths))
    parts += "".join(f'\n  (literal "{s}")' for s in sorted(literals))
    return f"(deny file-read*{parts})\n"


def build_profile(*, workspace: Path, allow_network: bool = False) -> str:
    ws = str(workspace.resolve())
    from argos.config import extra_write_dirs
    write_subpaths = [ws, *(_temp_roots()), *(str(d) for d in extra_write_dirs())]
    write_rules = "".join(f'\n  (subpath "{p}")' for p in write_subpaths)
    net_rule = "(allow network*)\n" if allow_network else "(deny network*)\n"
    return (
        "(version 1)\n"
        "(deny default)\n"
        "(allow process-fork)\n"
        "(allow process-exec*)\n"
        "(allow sysctl-read)\n"
        "(allow mach-lookup)\n"
        "(allow signal (target self))\n"
        "(allow ipc-posix-shm)\n"
        "(allow file-read*)\n"
        + _credential_read_denies() +
        f"(allow file-write*{write_rules})\n"
        + net_rule
    )


def wrap_command(profile_path: str, argv: list[str]) -> list[str]:
    return ["/usr/bin/sandbox-exec", "-f", profile_path, *argv]


def confined_argv(*, workspace: Path, argv: list[str], allow_network: bool = False) -> list[str]:
    workspace.mkdir(parents=True, exist_ok=True)
    prof = build_profile(workspace=workspace, allow_network=allow_network)
    prof_file = workspace / ".argos_run.sb"
    prof_file.write_text(prof, encoding="utf-8")
    return wrap_command(str(prof_file), argv)


def spawn_child(*, workspace: Path, child_argv: list[str],
                env: dict[str, str] | None = None, sandbox: bool = True) -> subprocess.Popen:
    workspace.mkdir(parents=True, exist_ok=True)
    if sandbox:
        prof = build_profile(workspace=workspace)
        prof_file = workspace / ".argos_sandbox.sb"
        prof_file.write_text(prof, encoding="utf-8")
        argv = wrap_command(str(prof_file), child_argv)
    else:
        argv = list(child_argv)
    child_env = dict(env or os.environ)
    return subprocess.Popen(
        argv, cwd=str(workspace), env=child_env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )


SANDBOX_CHILD_FLAG = "--__argos_sandbox_child__"


def python_child_argv(child_module: str = "argos.sandbox._sandbox_child") -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, SANDBOX_CHILD_FLAG]
    return [sys.executable, "-m", child_module]
