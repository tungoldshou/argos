"""Runtime context defaults.

The default workspace is ARGOS_CONFIG_DIR/workspace, verification output uses
ARGOS_CONFIG_DIR/verify, and MCP config is read from ARGOS_CONFIG_DIR/mcp.json.
"""
from __future__ import annotations

import contextvars
import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from argos.i18n import t


def _config_root() -> Path:
    from argos import config
    return Path(config.get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos")).expanduser()


def _default_ws() -> Path:
    return Path(os.environ.get("ARGOS_WORKSPACE") or (_config_root() / "workspace")).expanduser()


def _default_verify() -> Path:
    return Path(os.environ.get("ARGOS_VERIFY_DIR") or (_config_root() / "verify")).expanduser()

SNAPSHOT_PRUNE_DIRS: frozenset[str] = frozenset({
    ".git", ".hg", ".svn",
    ".venv", "venv", "env",
    "node_modules",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".argo-snapshots",
    "dist", "build", "target", ".next", ".nuxt", ".tox", ".codegraph", ".gradle",
})


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class RunContext:
    workspace: Path
    verify_dir: Path
    project_mode: bool = False
    guarded: dict[str, str] = field(default_factory=dict)
    guarded_dirs: dict[str, dict[str, str]] = field(default_factory=dict)
    plan_mode: bool = False


_current_var: contextvars.ContextVar[RunContext | None] = contextvars.ContextVar(
    "argos_run_context", default=None,
)


def _make_default_ctx() -> RunContext:
    return RunContext(workspace=_default_ws().resolve(), verify_dir=_default_verify().resolve())


def current() -> RunContext:
    ctx = _current_var.get()
    if ctx is None:
        ctx = _make_default_ctx()
        _current_var.set(ctx)
    return ctx


def set_context(ctx: RunContext) -> "contextvars.Token[RunContext | None]":
    return _current_var.set(ctx)


def reset(token: contextvars.Token) -> None:
    _current_var.reset(token)


def use_sandbox() -> contextvars.Token:
    return set_context(RunContext(workspace=_default_ws().resolve(), verify_dir=_default_verify().resolve()))


def use_project(project_dir: str) -> contextvars.Token:
    p = Path(project_dir).expanduser().resolve()
    return set_context(RunContext(workspace=p, verify_dir=p, project_mode=True))


def guard_files(paths: list[str]) -> None:
    ctx = current()
    for rel in paths:
        p = ctx.workspace / rel
        if p.is_dir():
            ctx.guarded_dirs[rel] = {
                str(f.relative_to(ctx.workspace)): _sha256(f)
                for f in sorted(p.rglob("*")) if f.is_file()
            }
        elif p.is_file():
            ctx.guarded[rel] = _sha256(p)


def detect_tampering() -> list[str]:
    ctx = current()
    changed: list[str] = []
    for rel, digest in ctx.guarded.items():
        f = ctx.workspace / rel
        if not f.exists():
            changed.append(rel + t("core2.runtime.deleted"))
        elif _sha256(f) != digest:
            changed.append(rel + t("core2.runtime.modified"))
    for drel, snap in ctx.guarded_dirs.items():
        d = ctx.workspace / drel
        now = (
            {str(f.relative_to(ctx.workspace)) for f in d.rglob("*") if f.is_file()}
            if d.is_dir() else set()
        )
        for frel, digest in snap.items():
            f = ctx.workspace / frel
            if not f.exists():
                changed.append(frel + t("core2.runtime.deleted"))
            elif _sha256(f) != digest:
                changed.append(frel + t("core2.runtime.modified"))
        for frel in sorted(now - set(snap)):
            changed.append(frel + t("core2.runtime.added"))
    return changed


_TEST_GLOBS = (
    "test_*.py", "*_test.py", "*_spec.py", "conftest.py",
    "*.test.ts", "*.test.tsx", "*.test.js", "*.spec.ts", "*.spec.js",
    "*_test.go", "*_spec.rb", "test_*.rb",
)
_SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", "dist", "build",
    ".next", "target", ".argos", ".idea", ".vscode",
})


def guard_project_tests(*, cap: int = 2000) -> int:
    ctx = current()
    if not ctx.project_mode:
        return 0
    from fnmatch import fnmatch
    rels: list[str] = []
    for root, dirs, files in os.walk(ctx.workspace):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fn in files:
            if any(fnmatch(fn, g) for g in _TEST_GLOBS):
                rels.append(os.path.relpath(os.path.join(root, fn), ctx.workspace))
                if len(rels) >= cap:
                    break
        if len(rels) >= cap:
            break
    if rels:
        guard_files(rels)
    return len(rels)
