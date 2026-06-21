# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Argos — **the hundred-eyed agent** (named for Argus Panoptes, the all-seeing guardian) — runs cheap
models reliably by wrapping them in a verify hard-gate, an honesty protocol, and an OS-level
sandbox. Its runtime is a background daemon kernel (auto-spawned) with the Textual TUI as its client,
falling back to a single inline process when the daemon is unavailable. Model-agnostic
(Anthropic-Messages and OpenAI-compatible endpoints both first-class).
See `README.md` for the product story and `docs/argos-product-definition.md` for the spec.

## Where the code lives

- **`argos/`** — the entire active codebase (Python 3.12+). All work happens here.
- **`tests/`** — pytest suite (3459 tests). Mirrors `argos/` subpackage layout, plus
  integration subdirs: `tests/e2e/`, `tests/eval/`, `tests/workflow/`, `tests/skills_curator/`,
  `tests/input/`, `tests/daemon/`, `tests/tui/`, …
- **`scripts/`** — standalone demo/benchmark scripts (`best_of_n_demo.py`, `tb_pass_at_1_benchmark.py`, …).
- **`examples/`** — user-facing quickstart guide (`quickstart.md`).
- **`packaging/`** — multi-channel install (install.sh, Homebrew, WinGet, .deb, PyInstaller spec).
- **`docs/`** — one doc per major feature (auto-memory, context-viz, per-task-routing, eval,
  voice-image-input, …); `docs/superpowers/` holds dated design records (`specs/` + `plans/`).

## Commands

```bash
uv sync                       # install deps (uv is the package manager; package is NOT pip-installed in dev)
uv sync --extra cloud-stt     # optional: enable cloud STT (OpenAI Whisper); local faster-whisper is default-on
uv run argos                  # launch the TUI (auto-probes daemon socket, falls back to inline)
uv run argos setup            # provider + key + format-probe wizard
uv run argos self-update      # check for a newer version and print upgrade instructions (cached 7d)
uv run argos dream            # run Dream consolidation now (cross-run distill + memory tidy)
uv run argos dream --report   # show the latest Dream report
uv run argos --selftest       # offline full-machine self-check (scripted model, real sandbox) — fast smoke
uv run argos --demo           # FakeLoop success demo (no key needed)
uv run argos --demo-fail      # FakeLoop escalation / honest-failure demo
uv run argos --effort high    # per-run effort tier (low=8 steps/AUTO, medium=40/CONFIRM, high=80/CONFIRM)
uv run argos --project PATH   # run in a user project directory
python -m argos.daemon  # start the background daemon (Unix socket at ~/.argos/daemon.sock)
uv run pytest                 # full suite; enforces --cov=argos --cov-fail-under=80
uv run pytest -n auto --dist loadgroup  # parallel run (~100-150s); xdist NOT in addopts by default
uv run pytest -m "not slow"   # skip real-subprocess / real-pyright e2e (faster)
uv run pytest -m slow         # ONLY the slow real-process tests
uv run pytest tests/test_loop.py::test_name   # single test
uv run pytest tests/test_loop.py -k pattern   # by name pattern
```

- **No linter/formatter is wired in CI** — match surrounding style (PEP 8, type annotations on
  signatures, Chinese docstrings/comments are the house norm).
- Coverage gate is 80% on the **full** suite. Running a subset reports lower total coverage; that
  is expected — judge coverage against `uv run pytest`, not a subset.
- `pytest-xdist` is in dev-deps; `-n auto --dist loadgroup` keeps same-`xdist_group` tests
  on one worker. `addopts` does **not** include `-n` — serial entry is preserved for debugging.
- Mark tests that spawn real subprocesses or run real pyright with `@pytest.mark.slow`.
- `pythonpath = ["."]` in `pyproject.toml` lets tests import `argos` without installing it.
- Set `ARGOS_NO_DAEMON=1` in tests to prevent TUI tests from attaching to a live daemon.

## Architecture — the big picture

### The four-phase loop (`core/loop.py`, `AgentLoop`)

A hand-built CodeAct loop (intentionally **framework-free** — langchain/langgraph/fastapi were
removed; deps are smolagents for the executor, textual for the TUI, httpx for I/O). Every run goes
through four **unskippable** phases: **plan → act → verify → report**.

- **act** extracts ```python blocks from the model output, runs them in the sandbox, and feeds the
  `CodeResult` back. Loops until the model emits no code block (= claims done).
- One event stream serves three consumers: each `Event` is yielded to the caller, persisted via
  `store.append_event`, and rendered in the TUI. Event types live in `protocol/events.py`
  (`tui/events.py` is a backward-compat shim).

### Everything flows through the broker → sandbox

`CapabilityBroker` (`sandbox/broker.py`) is the **only** path to side effects. It checks the action
against the egress policy (v6: manifest-driven from `CapabilityRegistry` + `_NETWORK_ACTIONS`
fallback), asks the `ApprovalGate` when needed, signs an HMAC receipt, then hands to the executor.
The sandbox is `SeatbeltExecutor` (`sandbox/executor.py`) — a **separate subprocess** under a macOS
Seatbelt profile (no network by default, writes caged to the declared workspace).

- v6 adds `CapabilityRegistry` (`capability/`): a per-process manifest of all capabilities
  (kind, visibility, egress_hosts). `register_builtins()` populates it; broker derives its
  network-action set from the registry at runtime.

- The PyInstaller binary **re-execs itself** as the sandbox child: `__main__.main()` checks for
  `SANDBOX_CHILD_FLAG` in argv *before* argparse and dispatches to `sandbox/_sandbox_child.py`.
- The sandbox child reads `ARGOS_WORKSPACE` from the env at module load — it must be set before spawn.

### Verify hard-gate + honesty (`core/verify_gate.py`, `core/honesty.py`, `core/harness.py`)

- The gate runs a user-declared `verify_cmd` and returns a **three-state** verdict:
  `passed` / `failed` / `unverifiable`. Completion is the gate's exit-code reading, never the
  model's text.
- `propose_verify('<cmd>')` is parsed **host-side** from the model's code text (regex in `loop.py`),
  because the Seatbelt child is a separate process the host can't inject into — the in-sandbox
  `propose_verify()` tool only returns a registration receipt.
- Trivial commands (`echo`, `true`, `:`) are rejected at registration → verdict degrades to
  `unverifiable` (anti-fake-green). `verify_cmd is None` → honest non-blocking completion labelled
  `NO_TEST`; a configured-but-failing/unverifiable check bounces the real error back to the agent.

### Assembly (`app_factory.py`)

`build_components()` builds the persistent store/sandbox/broker/model/verifier once (including the
`CapabilityRegistry`); `build_loop_factory()` returns a `() -> AgentLoop` that makes a fresh
`EventBus` per run and shares the rest. **No worker key → `RuntimeError`** → `__main__` catches it
and falls back to an honest demo state. `build_run_stack()` is the per-run path used by the daemon:
each run gets its own `SeatbeltExecutor + ApprovalGate + CapabilityBroker` so concurrent runs don't
share mutable state. The `ApprovalGate` from `build_components` is shared with the TUI app so
`/yolo` and tool/workflow approvals land on the gate the loop actually awaits.

### Subpackage map (`argos/`)

| Package / module | Responsibility |
|---|---|
| `core/` | the loop, harness, verify gate, honesty protocol, plan-mode, recovery, snapshot, model client (`models.py`), `updater.py` |
| `sandbox/` | broker, Seatbelt executor + child, egress policy, executor backend |
| `protocol/` | ACP event dataclasses + `EventBus` + `EventEnvelope` frame format (v6 P0; canonical source; `tui/events.py` is a compat shim) |
| `capability/` | `CapabilityRegistry` — per-process manifest of all capabilities (kind / visibility / egress_hosts); `register_builtins()` populates it; broker derives network-action set from it at runtime |
| `tui/` | Textual app (`app.py`) — v3 「黑曜石之眼」 design; slash commands, events shim, theme, glow, fakeloop (demo); auto-probes daemon socket on startup, falls back to inline |
| `tools/` | broker-gated tools: shell/web/browser/mcp/computer execute host-side; **file writes (`write_file`/`edit_file`) are gate-only** — the host broker runs the hard-path denylist + secret detection (`evaluate_sync`) and signs a receipt, then the Seatbelt child performs the actual write (broker returns an approval sentinel); `read_file`/`search_files` are pure-sandbox |
| `input/` | multimodal input kernel (interface-agnostic, host-side / outside sandbox) — `ImageAttachment` + path detection / validate / base64 (`attachments.py`), `Recorder` (sounddevice mic capture, `recorder.py`), provider-agnostic STT (`LocalWhisper` mlx→faster-whisper / `CloudWhisper` OpenAI, `stt.py`), `SttConfig` (reads `~/.argos/config.json` stt block, `stt_config.py`). Voice is wired in the TUI (space-to-record); image attachments are materialized in `protocols.py` `payload()` gated by `ModelTier.multimodal`. See `docs/voice-image-input.md` |
| `permissions/` | approval evaluator, hard rules (never bypass), secret patterns, audit |
| `approval.py` | `ApprovalGate`, `ApprovalLevel` (OBSERVE/PROPOSE/CONFIRM/AUTO), `guarded_call`; works as a top-level module shared by broker, daemon, TUI |
| `workflow/` | Dynamic Workflows — declarative `WorkflowSpec`, deterministic `engine.py`, sub-agents, worktree isolation |
| `daemon/` | always-on background kernel (Unix socket HTTP/SSE server at `~/.argos/daemon.sock`); TUI probes/auto-spawns it on startup then becomes a protocol client; `build_run_stack()` gives each run its own sandbox; 7-state machine, supervision, conductor supervisor, session registry |
| `memory/` | auto-memory (cross-session 4-tier JSONL) + embedding + store (vector via sqlite-vec, FTS5 fallback); consolidate (merge duplicate reflections, decay low-confidence entries, archive without hard-delete) |
| `routing/` | per-task model routing (categorizer / resolver / router) + effort tiers |
| `context/` | context-window analyzer, token counting, compaction threshold |
| `ledger/` | behavior ledger — signed receipts persisted as human-readable JSONL under `~/.argos/ledger/`; `LedgerEntry`, `LedgerStore`, `summarize`, `build_entry`; three-state undo (`Reversible`) |
| `conductor/` | autonomous scheduling core — `ConductorEngine`, `StandingOrder`, cron-lite triggers, `ProactiveSuggestion` (always requires user confirmation); builtin-dream-nightly (03:00 cron) triggers Dream consolidation; orders stored under `~/.argos/conductor/` |
| `perception/` | OS-level computer use (macOS): `ComputerExecutor` + `ComputerAction`; opt-in via `ARGOS_COMPUTER_USE=1` |
| `learning/` | post-run skill distillation pipeline — only promotes verified (passed) runs; failed/unverifiable runs produce memory reflections only; Dream nightly consolidation (candidates → clustering → synthesis → A/B promotion → memory consolidate) |
| `verify/` | self-test sub-system — opt-in (`ARGOS_SELF_TEST`); reviewer-role generates candidate test for unverifiable runs; canary guard rejects trivial tests |
| `lsp/`, `hooks/`, `mcp_native.py` | LSP client, lifecycle hooks, native MCP stdio JSON-RPC — run **outside** the sandbox (user-controlled code; warned at startup) |
| `skills.py` | skills repository — builtin + user/community markdown skills (YAML frontmatter: name/description/trust/enabled), recalled by goal at run start |
| `skills_builtin/` | markdown + dir skills (`verify`, `security-review`, `simplify`, …) |
| `skills_curator/`, `skills_runtime/` | skill discovery/install and execution |
| `eval/` | self-eval harness (corpus / runner / compare); CLI twin under `cli/eval.py` |
| `cli/` | subcommands wired into `__main__.py` argparse: `eval`, `skills`, `context`, `dream`; also `pkg.py` (`argospkg` packaging/release dispatcher, separate console entry point) |
| `browser.py` | `BrowserController` — Playwright browser automation on a dedicated thread (avoids asyncio/sync-API conflict); lazy-launch, honest error on missing chromium |
| `web.py` | provider abstraction for `web_search` / `web_extract` (search + fetch) — Tavily / DDGS behind one interface, egress-allowlisted |
| `contracts.py` | contract injection for structured engineering tasks (REST API / DB schema / state machine / config) — domain detection + template; bypassed for open-ended tasks |
| `runtime.py` | per-run runtime context: workspace path + verify isolation mode; project mode uses tamper-visible fingerprinting (can't sandbox user's own repo, so makes changes visible instead) |
| `isolation.py` | per-run directory / git-worktree allocation and teardown for daemon runs |
| `git_worktree.py` | low-level `git worktree add/remove` primitives shared by daemon and workflow |
| `llm_embed.py` | MiniMax `embo-01` embedding client + local cache; raises `EmbedError` on failure (memory falls back to FTS5) |
| `jsonl_log.py` | shared best-effort JSONL appender for audit / eval / memory sampling |
| `config_base.py` | shared JSON-file read + singleton-cache helpers used by lsp/hooks/permissions/routing |
| `config.py` | env + `config.json` loader — `ARGOS_*` > `VITE_*` > `.env` priority chain; builds `ModelTier` (incl. `multimodal` bit) + `CredentialPool` from comma-split keys; model-agnostic (no hardcoded provider) |
| `setup_wizard.py` | `argos setup` interactive wizard — provider + key entry, format-probe connectivity test, writes `~/.argos/.env` (0600) + `config.json`; I/O-decoupled (reader/writer/client injected) for testability |

### Conventions that bite

- **Version is single-sourced** from `importlib.metadata` (`argos.__version__`) ← `pyproject.toml`
  + `packaging/VERSION`. Don't hardcode version strings; use `/ship` to bump the three in sync.
- Config and state live under `~/.argos/`:
  `config.json`, `.env`, `mcp.json`, `lsp.json`, `hooks.json`,
  `runs/<id>.jsonl`, `runs/index.json`, `memory/`,
  `ledger/<run_id>.jsonl`, `conductor/orders.jsonl`,
  `daemon.sock`, `daemon.pid`.
  `ARGOS_NO_MEMORY=1` opts out of auto-memory.
  `ARGOS_WORKFLOWS=1` opts **in** to Dynamic Workflows (`propose_workflow`/fan-out/best-of-N): the
  `WORKFLOW_PROMPT` section is injected and the model is steered to use it. Off by default — the
  default agent isn't burdened with workflow complexity (the `propose_workflow` tool stays callable,
  it's just not advertised in the system prompt).
- **Daemon is always-on by default**: TUI probes `~/.argos/daemon.sock` at startup and
  auto-spawns `argosd` if not running; falls back to inline (single-process) mode only on
  failure. There is no `--with-daemon` flag — daemon is the default path. `ARGOS_NO_DAEMON=1`
  forces inline (used in tests to prevent attaching to a live daemon).
- Honesty is the product invariant: when something can't be verified, say `unverifiable` — never
  fabricate success, tool counts, or status. The `/tools` count comes from `ALL_TOOL_NAMES`.
- Changing Python that ships in the binary requires re-running PyInstaller before the packaging
  smoke test (`smoke_packaged.py`) reflects it (see `packaging/` and `docs/packaging-c.md`).
