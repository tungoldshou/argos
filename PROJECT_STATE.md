# Project State

Last updated: 2026-07-03

## Current Status

- Argos is a Python 3.12+ terminal coding agent with active package code in `argos/`.
- Project instructions live in `AGENTS.md`; keep that file intact and read it before code edits.
- The worktree already contains broad pre-existing uncommitted changes. Treat them as user-owned unless explicitly told otherwise.
- 2026-07-03 dynamic-workflow read-only analysis used an `explorer` subagent plus local inspection. No business code was changed.
- Current branch `feat/system-prompt-rewrite` has a broad dirty worktree across config, setup, TUI, daemon/eval, docs, and tests; keep future edits narrowly scoped.
- 2026-07-03 dynamic-workflow product closeout fixed several `ARGOS_CONFIG_DIR` default-path drifts: MCP config, LSP prompt injection gating, external-surface warnings, skills user dir/cache, Dream candidates, Dream CLI roots, conductor Dream material gate, and permissions audit logs now resolve through the configured Argos root unless explicitly injected.
- `argos --selftest` now verifies with the current Python interpreter when safe, and falls back to `python3` for frozen/PyInstaller binaries where `sys.executable` is the Argos binary.
- Dream CLI startup now distinguishes missing-key fallback from real initialization failures; malformed config/runtime errors return failure instead of running memory-only mode.

## Current Priority

- Keep future changes small, verified, and aligned with existing `uv` workflows.
- Before coding, inspect the relevant existing code path and add the narrowest useful verification.
- Pick one bounded product or bug target before editing; avoid opportunistic cleanup while the large uncommitted branch is in progress.
- Next product closeout targets: align daemon custom socket/pid cleanup; reduce hard-coded `~/.argos` user-facing docs/TUI copy where `ARGOS_CONFIG_DIR` changes the actual path.

## Verification Notes

- Targeted tests should usually use `uv run pytest <path> -q --no-cov`.
- Smoke check for runtime behavior: `uv run argos --selftest`.
- Latest closeout verification: `uv run pytest tests/test_mcp_native.py tests/test_external_surfaces.py tests/test_prompt_tool_exposure.py tests/test_skills.py tests/test_skills_curator_index.py tests/learning/test_candidates.py tests/test_audit_log.py tests/test_cli_setup.py tests/test_cli_dream.py tests/conductor/test_daemon_wiring.py::test_material_gate_silences_empty_candidates tests/conductor/test_dream_autonomous.py -q --no-cov` (`128 passed`) and `uv run argos --selftest`.
