# TODO

Last updated: 2026-07-03

## Active

- Preserve the existing `AGENTS.md` instructions and avoid overwriting project memory files.
- For the next coding task, inspect the broad pre-existing worktree changes before editing touched files.
- If the next target touches config, TUI, setup, or eval/daemon paths, run the smallest matching pytest slice with `--no-cov`.
- Align daemon custom socket and pid-path handling so stale-daemon cleanup uses the same pid file the spawned daemon writes.
- Audit user-facing docs/TUI copy that still hard-codes `~/.argos/...` for paths whose runtime source is `ARGOS_CONFIG_DIR`.
- Add a small ActivityPanel widget-level regression proving MCP configured-state display follows `ARGOS_CONFIG_DIR`.

## Done

- Created missing project memory files: `PROJECT_STATE.md`, `TODO.md`, and `DECISIONS.md`.
- Completed a dynamic-workflow read-only project analysis with an `explorer` subagent; no business code was changed.
- Completed dynamic-workflow product closeout for `ARGOS_CONFIG_DIR` path drift across MCP, LSP prompt gating, external-surface warnings, skills, Dream candidates/CLI/material gate, and permissions audit logs.
- Changed `argos --selftest` to use the current Python interpreter for its verification command instead of assuming `python3` exists.
- Preserved packaged-binary selftest behavior by falling back to `python3` when `sys.executable` is a frozen Argos binary or otherwise not accepted by the verify whitelist.
- Fixed Dream CLI startup error semantics so missing-key fallback remains memory-only, while malformed config/runtime initialization errors return failure instead of being reported as no-key mode.
