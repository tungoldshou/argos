# DECISIONS

Last updated: 2026-07-04

## Active Decisions

- Keep workflow behavior in instruction files and the existing lightweight dynamic workflow skill, not in a new custom profile system.
- Keep project memory in root-level Markdown files.
- Keep `AGENTS.md` as the project instruction entry point; do not recreate deleted `CLAUDE.md` or `AGENTS.md.bak`.
- Keep `argos setup status` `.env.local` fallback reporting as a source-label-only development behavior.
- Treat the active Argos config directory `.env` as Argos' own key file for permission hard rules.
- Deny Seatbelt sandbox reads of sensitive files under the active Argos config directory.
- Mask Linux bwrap reads of sensitive files under the active Argos config directory.
- Store self-update cache state under the active Argos config directory.
- Store the default SQLite memory database under the active Argos config directory.
- Store default behavior ledger journals under the active Argos config directory.
- Resolve default isolation roots from the active Argos config directory at runtime.
- Use the active Argos config directory for the default app workspace.
- Use the active Argos config directory for direct `AgentLoop` default run directories.
- Resolve runtime sandbox and legacy file-tool default directories from the active Argos config directory at runtime.
- Store default eval corpus data under the active Argos config directory.
- Store default embedding cache data under the active Argos config directory.
- Store workflow subagent diff journals under the active Argos config directory.
- Store auto-memory JSONL tiers and global instruction files under the active Argos config directory by default.
- Store Terminal-Bench eval CLI run data under the shared eval base.
- Expand explicit daemon Dream report override paths before use.
- Expand explicit auto-memory root override paths before use.
- Expand explicit eval corpus override paths before use.
- Expand explicit legacy memory migration file paths before use.
- Expand explicit memory database override paths before use.
- For TUI-spawned daemons, keep pid files beside the selected socket path by passing `--pid-path` explicitly from `probe_or_spawn()`.
- Treat `ARGOS_CONFIG_DIR` as the default root for daemon socket state unless `ARGOS_DAEMON_SOCKET` is explicit.
- Treat root/home wipe shell variants as hard denies even when they use root globs, `--`, quoted `$HOME`, or `${HOME}`.
- Treat Linux AppImage, `.deb`, and `.rpm` as release-blocking artifacts for Linux packaging.
- Treat WinGet `InstallerSha256` as valid only when it is a 64-character hex digest.
- Treat malformed permissions configuration as observe-only on first lazy load.
- Treat malformed hooks configuration as blocking on first lazy load.
- Treat PreToolUse hook timeouts as blocking hook failures.
- Deny sync-bridge `run_command` when OS sandboxing is disabled.
- Treat unpublished package-manager channels as draft/template-only and point fallback users to source install.
- Normalize release tag versions inside Linux/Windows build scripts instead of changing the release workflow contract.
- Require OS sandboxing for Cautious local `run_command` auto-approval.
- Keep `/permissions reload` fail-closed and sync successful reloads into the current TUI gate.
- Keep PyPI manual dispatch as build/test only; only tag refs may publish.
- Treat no-host-loop sync bridge as non-interactive and deny GUI/MCP/computer actions that need approval.
- Treat browser actions as host-loop actions in the no-host-loop sync bridge; browser navigation still uses SSRF/egress checks, and browser screenshots must stay inside the active workspace.
- Treat permission evaluator failures as fail-closed for writes and high-risk/interactive actions.
- Read permissions config fresh for each new run stack so reloads affect future runs without process restart.
- Publish GitHub release assets from an exact manifest instead of suffix-wide file discovery.
- Keep `UserPromptSubmit` hook failures non-blocking but visible in the TUI activity panel.
- Keep daemon run lifecycle identity (`run_id`) separate from model conversation identity (`session_id`).
- Use Windows-native PowerShell compression for release zip assets instead of assuming a `zip` CLI exists on `windows-latest`.
- Route external or real-time facts through web/browser tools before Python or shell commands.
- Describe OS sandbox networking as CodeAct-child direct-network confinement, not as broker web-tool unavailability.
- Limit public broker-governance security claims to declared privileged tools; raw model-authored Python is OS-contained only when the opt-in sandbox is enabled.
- Execute only explicit ` ```python` fenced blocks as CodeAct actions; treat ordinary Markdown fences as prose/data.
- Treat assistant replies that ask for user confirmation before a ` ```python` block as waiting turns, not executable CodeAct turns.
- Keep WinGet multi-file manifests aligned with official schema roles: root file is `version`, locale file is `defaultLocale`, and installer upgrade behavior is a scalar.
- Keep macOS release version injection inside the app bundle copy of `Info.plist`; do not mutate the source plist template during build.
- Keep the public launch install surface to PyPI / `uv tool` plus source checkout; the root `install.sh` is only a curl convenience for that path, and binary/package-manager channels are deferred.
- Prefer API-reported context usage when available, but use the existing token estimator as a UI fallback when a provider omits usage data instead of showing permanent 0 context.
- Use `v0.1.1` as the next fresh public launch tag after deleting the old remote `v0.1.0` release/tag.
- Treat the deleted `v0.1.0` release/tag as unpublished history: do not keep old changelog release sections for it.
- Keep code comments and docstrings English-only; Chinese may remain in user-facing locale strings, intentional Chinese test fixtures, and Chinese documentation prose.
- Point public `curl | bash` docs at the `v0.1.1` raw tag URL for the launch instead of mutable `main`.

## 2026-07-04: Public Launch Uses PyPI And Source Only

- Treat `uv tool install argos-agent` / `pip install argos-agent` as the public package path.
- Treat root `install.sh` as a thin `uv tool` bootstrap for the same package path, not as a new binary installer channel.
- Point launch docs at `https://raw.githubusercontent.com/tungoldshou/argos/v0.1.1/install.sh` so the public installer is tied to the release tag that contains the script.
- Let root `install.sh` install missing `uv` through Astral's official installer, then continue through `uv tool`; this avoids a preinstall prerequisite without adding a new Argos package channel.
- Verify the installed command through `uv tool dir --bin` instead of assuming the current shell already has uv's tool bin directory on `PATH`.
- Keep source checkout as the reliable contributor and pre-publish path.
- Make `release.yml` a manual binary workflow so tag pushes can publish PyPI without being blocked by AppImage, package-manager assets, Homebrew, WinGet, or Nix work.
- Keep binary/package-manager scripts and manifests as draft release engineering assets until a real user need justifies each channel.
- Do not reuse the deleted remote `v0.1.0` release/tag for the public launch; publish from a fresh tag after the PyPI/TestPyPI path is verified.
- Use `v0.1.1` for that fresh launch tag because the old `v0.1.0` release/tag has been removed from GitHub.
- Keep `CHANGELOG.md` as current unpublished release notes only until the first real public release is cut.
- Use manual `publish.yml` dispatch for TestPyPI preflight only; formal PyPI publishing remains tag-gated.

## 2026-07-04: CodeAct Requires Explicit Python Fences

- Require ` ```python` before extracting a model response as executable CodeAct.
- Leave ordinary Markdown fences as non-executable prose/data so creative answers and log examples do not spawn `python` steps.
- Keep the existing TUI behavior that renders executable code through `CodeActionBlock`.

## 2026-07-04: CodeAct Waits On User Confirmation Requests

- If assistant prose before the first ` ```python` block asks for confirmation or permission, treat the turn as waiting for the user and do not execute the block.
- Keep normal explicit ` ```python` CodeAct execution unchanged when no confirmation request is present.

## 2026-07-04: macOS Release Build Uses Tag Version In App Plist

- Strip a leading `v` from `ARGOS_VERSION` in `packaging/build_arm64.sh`, matching Linux and Windows release scripts.
- Write the normalized release version into `dist/Argos.app/Contents/Info.plist`.
- Keep `packaging/Info.plist` as a stable template so local and CI builds do not dirty or stale the source file.

## 2026-07-04: WinGet Manifests Follow Official 1.6 Roles

- Use `ManifestType: version` plus `DefaultLocale: en-US` in `tungoldshou.argos.yaml`.
- Use `ManifestType: defaultLocale` plus `ManifestVersion: 1.6.0` in `tungoldshou.argos.locale.en-US.yaml`.
- Keep installer-only schema fields in `tungoldshou.argos.installer.yaml`; `UpgradeBehavior` must remain one of the schema's scalar values.

## 2026-07-04: Prefer Web Tools for External Facts

- Put external or real-time information ahead of Python/shell in the CodeAct tool-selection prompt.
- Tell the model not to use `run_command`/`curl` or Python HTTP libraries for web facts because those paths are easier to time out and misdiagnose.
- Treat CodeAct execution timeout as execution timeout, not evidence that the OS sandbox or network is unavailable.
- Keep runtime context, CLI help, and user docs explicit that `--sandbox` blocks direct child-process networking while host-side broker `web_search` / `web_extract` can still use governed network access.

## 2026-07-04: Separate Daemon Run IDs from Conversation Session IDs

- Persist the owner TUI session id on daemon run metadata and index entries.
- Use that stable session id when `RunWorker` calls `AgentLoop.run()` so sequential daemon prompts share model history.
- Keep `run_id` for run lifecycle, SSE, approvals, snapshots, and worker routing so concurrent run isolation remains intact.

## 2026-07-04: Browser Actions Stay Behind Host Loop Boundaries

- Deny all `browser_*` actions from the no-host-loop sync bridge because the fallback path cannot show approval UI.
- Keep `browser_navigate` inside the network egress preflight so SSRF/private-network targets fail before browser execution.
- Resolve `browser_screenshot` output under the active workspace and reject paths that escape it.

## 2026-07-04: Windows Release Zips Use PowerShell Compression

- Use `Compress-Archive` for Windows release zip files because GitHub-hosted Windows runners do not guarantee a bare `zip` command.
- Keep the optional MSI zip on the same compression path so release assets are produced consistently.
- Do not add another setup step or dependency just to install `zip`.

## 2026-07-03: Keep Codex Workflow in Instructions, Not Profiles

- Use global and project `AGENTS.md` plus the existing `dynamic-workflow` skill for Codex workflow behavior.
- Do not add a separate personal/coding profile system; Codex App modes already cover coding versus everyday work.
- Keep subagents optional and safety-bounded instead of making every task multi-agent.
- Treat `/goal` as the outer long-running objective loop, with dynamic workflow, worktrees, and PRs as inner execution tools.

## Rejected Alternatives

- Do not require artificial task prefixes such as "做：" or "目标：".
- Do not add a separate personal/coding profile system that duplicates Codex App work modes.
- Do not make every task use subagents, worktrees, `/goal`, or PRs.

## 2026-07-03: Use Lightweight Root Project Memory

- Keep project memory in root-level Markdown files: `PROJECT_STATE.md`, `TODO.md`, `CHANGELOG.md`, and `DECISIONS.md`.
- Preserve `AGENTS.md` as the project instruction file; do not overwrite it.
- Keep these files concise and factual instead of generating ceremonial documentation.

## 2026-07-03: Do Not Recreate CLAUDE.md

- Keep `AGENTS.md` as the source of truth for project instructions.
- The user intentionally deleted `CLAUDE.md` and `AGENTS.md.bak`; do not restore or replace them.
- Argos auto-memory still supports `AGENTS.md`, so a Claude-specific compatibility file is not required.

## 2026-07-03: Document .env.local as Setup Status Fallback

- Keep `.env.local` as the development fallback source for legacy/no-config setup status.
- `argos setup status` may show `.env.local` as the key source label, but it must not print key values.
- Document this behavior in setup docs instead of changing the existing config fallback contract.

## 2026-07-03: Permission Hard Rules Follow ARGOS_CONFIG_DIR

- Treat `ARGOS_CONFIG_DIR/.env` as Argos' own key file when permission hard rules check `.env` writes.
- Keep the default behavior for `~/.argos/.env` when no config-dir override is active.
- Do not allow arbitrary workspace `.env` files through this special case.

## 2026-07-03: Seatbelt Protects Active Config Secrets

- Deny sandbox reads of `.env`, `config.json`, and `mcp.json` under the active `ARGOS_CONFIG_DIR`.
- Keep the legacy `~/.argos/{.env,config.json,mcp.json}` deny entries for default installs and compatibility.
- Do not deny the whole Argos config directory because the default workspace can live under that root.

## 2026-07-03: Linux Bwrap Masks Active Config Secrets

- Mask raw and resolved `.env`, `config.json`, and `mcp.json` paths under the active `ARGOS_CONFIG_DIR` with `/dev/null` in bwrap.
- Reuse the Seatbelt sensitive-file list so macOS and Linux strong sandboxes do not drift.
- Leave unshare documented as weaker because it cannot provide the same mount-based masking.

## 2026-07-03: Self-Update Cache Follows ARGOS_CONFIG_DIR

- Store `.last_update_check` under `ARGOS_CONFIG_DIR` so startup and manual update checks do not write to the default `~/.argos` when the config root is moved.
- Keep the update-check cache filename and updater behavior unchanged.

## 2026-07-03: Memory Store Follows ARGOS_CONFIG_DIR

- Default `ArgosStore()` persists `argos.db` under `ARGOS_CONFIG_DIR`.
- Keep `ARGOS_DB_PATH` as the explicit override for tests and users who need a custom database path.

## 2026-07-03: Ledger Store Follows ARGOS_CONFIG_DIR

- Default `LedgerStore()` persists behavior journals under `ARGOS_CONFIG_DIR/ledger`.
- Keep explicit `LedgerStore(path)` callers unchanged for tests and injected daemon/server paths.

## 2026-07-03: Isolation Roots Follow ARGOS_CONFIG_DIR

- Default sandbox run directories live under `ARGOS_CONFIG_DIR/runs`.
- Default daemon git worktrees live under `ARGOS_CONFIG_DIR/worktrees`.
- Keep `RUNS_ROOT` and `WORKTREES_ROOT` monkeypatch injection available for focused tests.

## 2026-07-03: App Workspace Follows ARGOS_CONFIG_DIR

- Default `build_components()` workspace lives under `ARGOS_CONFIG_DIR/workspace`.
- Keep `ARGOS_WORKSPACE` and explicit `workspace=` overrides ahead of the config-root default.

## 2026-07-03: AgentLoop Defaults Follow ARGOS_CONFIG_DIR

- Default direct `AgentLoop(...)` workspace lives under `ARGOS_CONFIG_DIR/workspace`.
- Default direct `AgentLoop(...)` verify directory lives under `ARGOS_CONFIG_DIR/verify`.
- Keep explicit `workspace=` and `verify_dir=` constructor arguments unchanged.

## 2026-07-03: Runtime Tool Defaults Follow ARGOS_CONFIG_DIR

- Default `runtime.use_sandbox()` workspace and verify directories live under `ARGOS_CONFIG_DIR/workspace` and `ARGOS_CONFIG_DIR/verify`.
- Default file-tool helpers resolve workspace from `ARGOS_CONFIG_DIR/workspace`.
- Keep `ARGOS_WORKSPACE`, `ARGOS_VERIFY_DIR`, and test-injected module overrides ahead of the config-root default.

## 2026-07-03: Eval Corpus Follows ARGOS_CONFIG_DIR

- Default eval corpus tasks live under `ARGOS_CONFIG_DIR/eval/corpus`.
- Keep `ARGOS_EVAL_CORPUS_DIR` as the explicit override for tests and custom corpus locations.
- Keep eval run/results/report data under the same `ARGOS_CONFIG_DIR/eval` root used by CLI eval commands.

## 2026-07-03: Embedding Cache Follows ARGOS_CONFIG_DIR

- Default remote embedding cache lives at `ARGOS_CONFIG_DIR/embeddings.json`.
- Keep `ARGOS_EMB_CACHE` as the explicit override for users and tests that need a custom cache file.
- Resolve the cache path at runtime instead of freezing it at module import.

## 2026-07-03: Workflow Diff Journals Follow ARGOS_CONFIG_DIR

- Default subagent diff journals live under `ARGOS_CONFIG_DIR/workflow/diffs`.
- Keep diff persistence best-effort: failed journal writes still return an empty diff reference instead of failing the subagent.
- Keep inline diff mode unchanged; only the default out-of-band journal path changed.

## 2026-07-03: Auto Memory Roots Follow ARGOS_CONFIG_DIR

- Default auto-memory JSONL tiers live under `ARGOS_CONFIG_DIR/memory`.
- Default global instruction lookup reads `ARGOS_CONFIG_DIR/CLAUDE.md` and `ARGOS_CONFIG_DIR/AGENTS.md`.
- Keep `ARGOS_MEMORY_DIR` and `ARGOS_HOME` as explicit overrides for tests and users who intentionally split those roots.

## 2026-07-03: Terminal-Bench Eval Uses Shared Eval Root

- `argos eval tb` uses the same `ARGOS_CONFIG_DIR/eval` base as other eval CLI commands.
- Keep `--keep-worktree`, budget settings, and Terminal-Bench corpus workdir behavior unchanged.
- Reuse `argos.cli.eval._eval_base()` instead of adding another eval-root helper.

## 2026-07-03: Daemon Dream Overrides Expand User Paths

- `ARGOS_DREAMS_DIR=~/...` in daemon Dream report handling expands to the user's home directory.
- Keep the default daemon Dream root under `ARGOS_CONFIG_DIR/dreams`.
- Keep CLI Dream behavior unchanged; this aligns the daemon override path with the CLI path.

## 2026-07-03: Auto Memory Overrides Expand User Paths

- `ARGOS_MEMORY_DIR=~/...` expands before auto-memory JSONL paths are built.
- `ARGOS_HOME=~/...` expands before global instruction files are discovered.
- Keep `ARGOS_CONFIG_DIR/memory` and `ARGOS_CONFIG_DIR/{CLAUDE.md,AGENTS.md}` as the defaults when explicit overrides are absent.

## 2026-07-03: Eval Corpus Overrides Expand User Paths

- `ARGOS_EVAL_CORPUS_DIR=~/...` expands before eval corpus manifests are read.
- Keep `ARGOS_CONFIG_DIR/eval/corpus` as the default when the explicit override is absent.
- Keep the override path semantics aligned with other explicit Argos root overrides.

## 2026-07-03: Legacy Memory Migration Overrides Expand User Paths

- `ARGOS_MEMORY_FILE=~/...` expands before old JSONL memory rows are imported.
- Keep the built-in legacy fallback at `~/.argos/memory.jsonl` for existing users.
- Keep migration non-destructive: source JSONL files are read, never deleted.

## 2026-07-03: Memory Database Overrides Expand User Paths

- `ARGOS_DB_PATH=~/...` expands before SQLite opens or creates the memory database.
- Keep `ARGOS_DB_PATH` ahead of the `ARGOS_CONFIG_DIR/argos.db` default.
- Keep explicit constructor `db_path=` behavior unchanged for tests and direct callers.

## 2026-07-03: TUI Daemon Spawn Owns Its PID Path

- `argos.tui.daemon_spawn.probe_or_spawn()` passes both `--socket-path` and `--pid-path` to `argosd`.
- The pid path is derived from the selected socket directory, matching `_kill_stale_daemon()` cleanup.
- This keeps the TUI auto-spawn path fixed without changing manual `argosd` CLI defaults in the same patch.

## 2026-07-03: Daemon Socket Defaults Follow ARGOS_CONFIG_DIR

- When `ARGOS_DAEMON_SOCKET` is unset, daemon socket defaults resolve to `ARGOS_CONFIG_DIR/daemon.sock`.
- `argos.daemon.socket.default_socket_path()`, `argosd` defaults, and TUI daemon probing share that behavior.
- Explicit `ARGOS_DAEMON_SOCKET` still wins for users who need a custom socket path.

## 2026-07-03: Shell Hard Rules Cover Common Wipe Variants

- Deny root/home wipe commands before Trust Dial semantics can auto-approve them.
- Cover root globs, `--` option separators, quoted `$HOME`, `${HOME}`, `//`, `/.`, and trailing-slash home forms.
- Keep the fix in `check_hard_shell()` so async broker, sync broker, and evaluator paths share the same hard rule.

## 2026-07-03: Linux Package Assets Are Release-Blocking

- Treat AppImage as the required Linux release artifact because the Linux Homebrew formula installs it.
- Fail `packaging/build_linux.sh` when `appimagetool` cannot be downloaded, `appimagetool` fails, or the AppImage file is missing.
- Also fail when `dpkg-deb` or `rpmbuild` is missing, rpm build fails, rpm output is missing, or rpm renaming does not produce the exact release asset name required by `release.yml`.
- Keep Linux package asset creation fail-closed when the binary workflow is manually run.

## 2026-07-03: WinGet Manifest SHA Must Be Valid Hex

- `argospkg manifest` must list all three WinGet manifest files before manual release review.
- Reject placeholder and non-64-hex `InstallerSha256` values.
- Do not generate a fake SHA locally; the release bump workflow remains responsible for inserting the real release digest.

## 2026-07-03: Malformed Policy Config Fails Closed

- Missing `permissions.json` still means no user policy and falls back to the gate level.
- Malformed `permissions.json` on first lazy load or first reload forces `default_level="observe"` so commands are denied until the user fixes or reloads the file.
- Successful `/permissions reload` updates the current TUI gate's per-session config, not only the module-level singleton.
- Malformed `hooks.json` on first lazy load raises `HooksConfigError`; missing hooks file still means no hooks.
- PreToolUse hook timeouts block tool execution because policy hooks that do not complete cannot prove the action is safe.

## 2026-07-03: Release Tag Normalization Lives in Build Scripts

- Manual binary release jobs pass the requested workflow tag through `ARGOS_VERSION`.
- Linux and Windows build scripts strip one leading `v` from `ARGOS_VERSION` before artifact names or MSI metadata are emitted.
- This keeps tag naming (`v0.1.0`) compatible with semver-style asset names (`0.1.0`) without adding workflow-level indirection.

## 2026-07-03: Cautious Shell Auto-Approval Requires Sandbox

- Cautious mode may auto-approve local `run_command` only when OS sandboxing is active.
- Low-risk non-shell actions and `accept_edits` write semantics keep their existing evaluator behavior.
- This keeps async approval and sync broker behavior aligned on the same sandbox boundary.

## 2026-07-03: PyPI Publish Requires Tag and Wheel Smoke

- `workflow_dispatch` may run PyPI build verification, but it must not publish to PyPI.
- The PyPI publish job is gated to `refs/tags/v*`.
- The build job installs the freshly built wheel and runs the existing entry-point smoke before upload.

## 2026-07-03: Sync Bridge Interactive Actions Need Host Loop

- Without a host event loop, the sync bridge cannot show an approval card.
- `mcp_call`, browser write actions, and `computer_*` actions fail closed on the no-host-loop fallback path.
- `request_blocking()` remains the supported path for these actions because it bridges back to the host loop for normal approval.

## 2026-07-03: Evaluator Failures Fail Closed for Sensitive Actions

- Permission evaluator exceptions deny writes, `run_command`, MCP calls, browser writes, computer actions, and other high-risk actions.
- Low-risk read actions keep the old compatibility fallback when the evaluator is unavailable.
- This prevents gate-only writes and AUTO computer actions from turning evaluator crashes into approvals.

## 2026-07-03: Sync Bridge Shell Requires OS Sandbox

- The sync bridge cannot wait for interactive approval, so `run_command` is denied when OS sandboxing is disabled.
- Async `request()` keeps the normal approval path; this decision only covers headless/subagent fallback execution through `execute_sync()`.
- File write gate-only behavior remains unchanged because writes are still broker-gated before sandbox-side application.

## 2026-07-03: Unpublished Install Channels Stay Draft

- Linux `.deb` missing-asset fallback points to source install until PyPI/Homebrew artifacts are live.
- The Homebrew tap mirror README is explicitly draft, not a current install page.
- The legacy `packaging/homebrew/argos.rb` cask is template-only; do not treat it as a release source.

## 2026-07-03: New Run Stacks Read Current Permissions Config

- `build_components()` may keep the startup permissions config for the initial inline/session gate.
- `build_run_stack()` reads `get_config()` for each new run so `/permissions reload` affects future daemon/app runs.
- This avoids mutating shared `AppComponents` while keeping reload behavior observable without restarting Argos.

## 2026-07-03: Release Assets Use an Exact Manifest

- Release creation uses a fixed `release-assets.txt` list for expected macOS, Linux, and Windows artifacts.
- Optional Windows MSI zip is included only when present; required artifacts fail the release job when missing.
- `SHA256SUMS` is generated from the same manifest so staging files with release-like suffixes cannot be published or checksummed.

## 2026-07-03: UserPromptSubmit Failures Are Visible but Non-Blocking

- `UserPromptSubmit` remains a lifecycle notification hook, not a policy gate.
- Failed or timed-out prompt hooks emit `HookFired` rows into ActivityPanel before the run continues.
- `PreToolUse` remains the fail-closed hook path for blocking unsafe tool execution.
