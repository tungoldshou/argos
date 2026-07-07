# Repository Instructions

Argos is a Python 3.12+ terminal coding agent. Keep changes small, verified, and aligned with the existing code.

## Project Map

- `argos/` contains the active package.

## Commands

Use `uv`; do not install this project with plain `pip` for local development.

```bash
uv sync
uv run argos setup
uv run argos
uv run argos --selftest
uv run python -m compileall -q argos
```

## Coding Rules

- Prefer the existing pattern over a new abstraction.
- Touch only the files needed for the task.
- Match the local style, including the existing Chinese comments/docstrings where they are already used.
- Keep user-facing text behind `argos.i18n.t`; internal logs, exceptions, and model-facing prompt fragments may stay as local style dictates.
- Do not hardcode version strings. Use the existing single-source version path.
- Do not read or modify real user config/state under `~/.argos/` unless the task explicitly requires it.
- Do not read `.env.local` or credential files unless the user explicitly asks.

## Architecture Notes

- `argos/core/loop.py` owns the framework-free CodeAct loop: plan, act, verify, report.
- `argos/core/verify_gate.py` owns the three-state verification gate: `passed`, `failed`, `unverifiable`.
- `argos/sandbox/broker.py` is the side-effect boundary for privileged actions.
- `argos/tools/` contains broker-gated tools.
- `argos/protocol/events.py` is the canonical event protocol; `argos/tui/events.py` is a compatibility shim.
- `argos/daemon/` is the background kernel.

## Verification

For code changes, run the narrowest useful import or compile check.

```bash
uv run python -m compileall -q argos
uv run argos --selftest
```

## Git Hygiene

- The worktree may contain user changes. Do not revert unrelated changes.
- Do not run destructive git commands unless the user explicitly asks.
- Main is PR-only; use a branch for changes intended to land.
