# Argos — The hundred-eyed agent

> **Current version: v0.1.0.** Argos runs as a background kernel with
> pluggable clients — the terminal TUI today, with a single-process fallback
> when the daemon is unavailable.
> Binary packages are not yet published; see [Install](#install) for the
> build-from-source path that works today.

Argos is a **coding agent you run in your terminal** — the same lineage as
Claude Code and Codex: a CodeAct loop that reads your code, writes and edits
files, runs commands, searches the web, and drives a browser. What it adds on
top is a layer that keeps a cheap model honest. It is named for **Argus
Panoptes**, the hundred-eyed guardian of Greek myth — the watchman who never
slept and could not be deceived.

What makes it distinct:

- **"Done" is an exit code, not a sentence.** A verify hard-gate runs your
  check (`pytest`, `cargo test`, `tsc`, …) and reads the result — three-state
  `passed` / `failed` / `unverifiable`, never a fake-green. Completion is the
  gate's reading of the exit code, never the model's word for it.
- **Every side effect crosses a governance layer.** The broker is the *only*
  path to side effects: it checks an egress allowlist, asks the approval gate,
  signs an HMAC receipt, and the model's code runs under smolagents' AST
  limits. Every privileged action leaves a signed receipt; every event is
  persisted to a replayable JSONL journal.
- **An OS sandbox when you want it.** Run with `--sandbox` (or
  `ARGOS_SANDBOX=1`) and macOS Seatbelt / Linux bwrap confines the agent at the
  kernel boundary — no network, writes caged to your workspace, credential
  files (`~/.ssh`, `~/.aws`, …) unreadable. Opt-in, like Claude Code's sandbox;
  **off by default**. The TUI shows an `unsandboxed` badge whenever it's off, so
  the state is never hidden — and the governance layer above still gates every
  side effect either way.
- **A permission model that gets out of the way.** Three modes — **Cautious**
  (default), **Trusted**, **Autonomous** — cycle with `/trust`. Cautious
  auto-approves low-risk actions and pauses on the rest; a small set of HARD
  rules (`rm -rf`, system paths, secret writes, financial computer-use) never
  bypasses, even in Autonomous. No five-level dial, no per-command allowlist.
- **Model-agnostic.** Bring any Anthropic-Messages or OpenAI-compatible
  endpoint — both first-class. `argos setup` probes the connection and the
  CodeAct format for you.

Built in Python on Textual. A background daemon kernel runs the work and
survives a closed terminal; the TUI attaches as a protocol client, with a
single-process fallback when the daemon is unavailable.

---

## Why Argos

A coding agent should get out of your way when it's safe to, and stop you when
it isn't. Argos is built around four choices that make that real:

1. **Governance every side effect crosses.** The broker is the only path to
   side effects — egress allowlist, approval gate, signed receipt, smolagents
   AST limits — applied to every privileged action, whether or not the OS
   sandbox is on. Add `--sandbox` for a kernel-level cage (Seatbelt/bwrap: no
   network, writes caged to your workspace) on top; it's opt-in and off by
   default, the same posture as Claude Code's OS sandbox.
2. **Permissions are three modes, not a maze.** Cautious / Trusted /
   Autonomous, cycled with `/trust`. A handful of HARD rules (`rm -rf`, system
   paths, secret writes, financial computer-use) never bypass, even in
   Autonomous — the user stays the final reviewer for the actions that hurt
   most.
3. **"Done" is an exit code, not a sentence.** When the agent changes code, a
   verify gate runs your check (`pytest`, `cargo test`, `tsc`, …) and reads the
   result; an unverifiable task is flagged *unverifiable*, never a fake-green.
   It runs quietly in the background — it doesn't turn a plain chat into a
   ceremony.
4. **A daemon that survives a closed terminal.** When the `argosd` binary is on
   `PATH` it auto-starts in the background, so 5+ minute tasks outlive a closed
   terminal or a power loss — state, checkpoints, and the event journal live on
   disk. When it isn't (the packaged default ships only `argos`), Argos falls
   back transparently to single-process inline mode. (`ARGOS_NO_DAEMON=1`
   forces inline.)

The result is a normal coding agent that's smooth to drive and hard to fool.

---

## Quick start

Needs Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run argos setup        # interactive wizard: pick a provider, paste a key,
                          # connection + CodeAct-format probe (real request)
uv run argos              # launch the Argos TUI
uv run argos --selftest   # offline full-machine self-check, prints verdicts
uv run pytest -q          # run the test suite
```

Without an API key, `argos` exits with a clear message telling you to run
`argos setup` — it does **not** pretend to run.

---

## Install

> **Current status: build from source only.** v0.1.0 is tagged but the
> release has no binary assets yet — the one-line installer, Homebrew cask,
> PyPI, and platform packages are **infrastructure in progress (stage #13)**
> and will 404 until those artifacts are published. The only path that works
> today is cloning and running via `uv`.

### Platform support

The OS sandbox is **opt-in** (`--sandbox`); the table shows the backend used
when it's enabled. Without it (the default), Argos runs unsandboxed on every
platform and the governance layer (broker + approval + egress + AST limits)
still gates side effects.

| Platform | Sandbox backend (`--sandbox`) | Write cage | Notes |
|---|---|---|---|
| **macOS** | Apple Seatbelt (`sandbox-exec`) | Full kernel-level confinement | Recommended; `argosd` daemon supported |
| **Linux** | `bwrap` (preferred) or `unshare` fallback | `bwrap`: strong; `unshare` fallback: **weaker write cage** — filesystem namespace only, no seccomp | `bwrap` requires bubblewrap ≥ 0.3; `unshare` is a best-effort fallback |
| **Windows** | None | — | Runs unsandboxed (default); `--sandbox` is unsupported (no Seatbelt/bwrap) |

> **Linux unshare note.** When `bwrap` is unavailable, Argos falls back to a
> Linux user-namespace unshare sandbox. This provides basic process isolation
> but the write cage is weaker than bwrap's bind-mount confinement: a
> determined agent could reach paths outside the declared workspace via
> `/proc` or bind mounts. Use `bwrap` (`sudo apt install bubblewrap`) for
> a stronger guarantee.

### From source (the path that works today)

Needs Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/tungoldshou/argos
cd argos
uv sync
uv run argos setup   # pick a provider + key, run a connection probe
uv run argos         # launch the TUI
```

### Planned channels (not yet published — stage #13)

The packaging scaffolding exists in `packaging/` for all of the channels
below. None are live until binary assets are uploaded to a GitHub release.

**One-line installer (macOS arm64)**
```bash
# Will work once arm64 binary assets land in a GitHub release:
curl -fsSL https://raw.githubusercontent.com/tungoldshou/argos/main/packaging/install.sh | bash
```

**Homebrew cask (macOS arm64)** — formula at `packaging/homebrew/argos.rb`,
sha256 placeholder pending release; tap not yet published.

**pip / uv (any platform)** — `argos-agent` is not on PyPI yet.
```bash
# Planned:
pip install argos-agent        # or: uv tool install argos-agent
```

**Linux** (AppImage / .deb / .rpm), **Windows** (WinGet / .exe zip), and
**Homebrew tap** (Linux CLI) — manifests exist in `packaging/` but no
artifacts have been built or uploaded yet.

**Nix** — flake planned; not yet published.

See [`docs/packaging-c.md`](docs/packaging-c.md) for the full per-channel
install matrix and upgrade commands once these channels land.

---

## Core architecture

### The verify hard-gate

Every run that touches code is bound to a user-declared verification
command. When the agent claims "done", the gate runs that command in
isolation and emits a three-state verdict:

- **`passed`** — the command exited 0. The work is genuinely done.
- **`failed`** — non-zero exit; the actual error text is bounced back to
  the agent so it can fix and retry.
- **`unverifiable`** — the agent never declared a meaningful check (or
  the check looks trivial, e.g. `echo ok`). The task is *not* marked
  done; it is flagged for human review.

The gate is host-side, not model-side. It reads exit codes; it does not
trust assertions.

### Honesty protocol

The agent cannot self-certify. Three rules enforce this:

- No fake-greens — a trivial verification command (`echo`, `true`, `:`)
  is rejected at registration. If the agent tries to claim success with
  an empty check, the verdict degrades to `unverifiable`.
- No pretend-success — completion is the gate's verdict, not the
  model's text. If the gate says `unverifiable`, the transcript says
  `unverifiable`.
- Full audit trail — every tool call leaves a signed receipt (HMAC over
  the broker's request envelope), the full event stream is persisted to
  JSONL, and the activity panel shows a live signature counter for the
  human to watch.

### OS sandbox (opt-in)

Run with `--sandbox` (or `ARGOS_SANDBOX=1`) and the agent's code executes
inside a macOS Seatbelt profile (Linux: `bwrap`, with an `unshare` fallback):
no outbound network unless explicitly approved, writes confined to the declared
workspace. Reads are deliberately broad — the agent has to import libraries and
read your code — but credential paths (`~/.ssh`, `~/.aws`, …) are denied.

The OS sandbox is **off by default** (opt-in, the same posture as Claude
Code's). On or off, the capability broker is the boundary every side effect
crosses: egress allowlists (Tavily / DDGS / configured MCP hosts), per-action
approval, signed receipts, and smolagents' AST limits on the model's code —
and the AUTO (`/yolo`) approval level does not silently open the network. What
`--sandbox` adds is a kernel-level backstop: without it, a raw `socket` / `open`
in model-authored code that the AST layer happens to permit is not
OS-contained (declared tool calls are still gated by the broker). The TUI shows
an `unsandboxed` badge whenever the sandbox is off, so the state is never
hidden.

### Smart approval

Three modes — **Cautious** (default) / **Trusted** / **Autonomous** — cycle
with `/trust` (bare `/trust` advances to the next; `/trust status` shows the
current). Cautious auto-approves low-risk actions and pauses on high-risk or
irreversible ones; Trusted remembers the session's approved patterns;
Autonomous stops asking entirely. A hidden `/trust paranoid` confirms every
step. Whatever the mode, **certain hard rules never bypass**, even in
Autonomous:

- Destructive shell operations (`rm -rf`, system paths, format
  commands).
- Writes outside the declared workspace.
- Reads or writes matching secret patterns (private keys, credential
  files, anything in `~/.ssh`).
- Opening network for a command (`pip install`, `git push`, `curl`) — an
  "egress valve" the agent must pass before the cage lets traffic out.

The approval modal itself is a real keyboard-driven inline prompt, not a
decorative pause: `1` deny, `2` once, `3` session, `4` always, with a
visible diff of what the tool would do. `/yolo` is kept as an alias for
`/trust autonomous`.

### Long-running daemon

A 7-state machine (`pending` / `running` / `paused` / `suspended` /
`completed` / `failed` / `cancelled`) runs in a background daemon
process (`argosd`) that Argos auto-detects and auto-spawns at launch
— provided the `argosd` binary is on `PATH`. If `argosd` is missing
(e.g. the current packaged build ships only the `argos` binary, or a
`uv run` checkout where the console script isn't installed) or the
daemon is otherwise unreachable, the TUI falls back transparently to
single-process inline mode (shown in the status bar). There is no
`--with-daemon` flag; daemon mode is the default whenever `argosd`
is available.

Keyboard bindings on the TUI:

- **`Ctrl+B`** — background the current run. It enters `suspended`
  state on disk; you can start a new goal immediately and resume the old
  one later.
- **`Esc`** (daemon mode) — pause at the next step boundary. The worker
  only blocks at well-defined step entry, so the pause is deterministic,
  not interrupt-the-LLM-token.
- **`Esc Esc`** (within 1.5s, daemon mode) — cancel.
- **`Esc`** (inline mode) — cancel the current run immediately.
- **`Ctrl+C`** — quit the TUI.

State survives TUI exit, terminal close, machine reboot, and even a
model upgrade (the worker reattaches from the last checkpoint).
`ARGOS_NO_DAEMON=1` forces inline mode (useful in CI or tests).

### Broker-gated tools

Every tool call — from the agent or from a sub-agent — flows through the
capability registry and broker. The registry is the authoritative source
for tool manifests (name, kind, risk, reversibility, visibility); the
broker checks the action against the egress policy, asks the approval
gate when needed, signs a receipt, and only then hands off to the
executor.

Tools span the breadth of an engineer's day:

- **Files** — `read_file`, `write_file`, `edit_file`, `search_files`
- **Shell** — `run_command` (broker-gated + hard-rule denylist; OS-caged under `--sandbox`)
- **Verification** — `propose_verify` (declare-then-execute, isolated
  from the agent's own code path), `propose_dom_verify` (DOM-level
  verification via CSS selector + expected text)
- **Plan** — `update_plan` (real TODO breakdown, rendered in the
  activity panel)
- **Web** — `web_search`, `web_extract` (Tavily or DDGS, egress
  allowlisted)
- **Browser** — `browser_navigate`, `browser_snapshot`, `browser_click`,
  `browser_type`, `browser_screenshot` (Playwright on a dedicated
  thread; visible window by default so you can watch)
- **LSP** — `lsp_definition`, `lsp_references`, `lsp_hover`,
  `lsp_document_symbols`, `lsp_workspace_symbols`, `lsp_diagnostics`
  (real language-server protocol against user-configured servers)
- **MCP** — `mcp_call(server, tool, args)` (native stdio JSON-RPC,
  zero pre-configuration; `~/.argos/mcp.json` is read on demand)
- **Workflow** — `propose_workflow({name, description, stages})` to
  request a Dynamic Workflow (see below)
- **Computer use** — `computer.screenshot`, `computer.click`,
  `computer.double_click`, `computer.type_text`, `computer.key`,
  `computer.scroll`, `computer.open_app` (OS-level control via
  AppleScript / `screencapture`; requires `ARGOS_COMPUTER_USE=1` and
  macOS Accessibility permission; all actions are `risk=high +
  reversible=False` and governed by hard-CONFIRM approval)
- **Skill** — built-in skills (`/verify`, `/security-review`,
  `/simplify`) callable on demand without re-using the agent's code

The tool count shown in `/tools` is always the real number from
`get_tool_names(registry)`. No padding, no "60+ tools" lies.

### Dynamic Workflows

Big tasks that can be split — refactor + test, fan-out search, panel
review — are expressed as a declarative `WorkflowSpec` (`name`,
`description`, `stages`) and run by a host-side deterministic engine.
The agent *proposes* the spec; the engine *runs* it. The split keeps
the model from writing brittle orchestration code (models are generally
better at emitting JSON than at hand-rolling Python async) while keeping
the user in the approval loop.

Five shapes are supported:

- **`fan_out`** — one agent per item, run in parallel.
- **`pipeline`** — items traverse stages sequentially, no barriers.
- **`panel`** — N voters, adversarial verify generalised.
- **`loop_until`** — accumulate to a target, or stop on consecutive
  empty rounds (hard cap prevents runaway).
- **`synthesize`** — roll up results into a single report.

Each sub-agent is a full Argos — its own ModelClient, its own broker,
its own sandbox (OS-caged under `--sandbox`), its own verify gate. Sub-agents can be
assigned any config profile, so a cheap tier can do the parallel
work and a stronger model can adjudicate. `isolation: worktree` gives
parallel write-agents their own git worktree, with a diff captured
before teardown for the user to review.

### Capability registry

The capability registry (`argos/capability/`) is the authoritative
manifest store for every action the broker can dispatch: name, kind,
risk level (`low` / `medium` / `high`), reversibility, egress hosts, and
visibility. The registry is built at startup by `register_builtins()` and
is the source of truth for the tool count shown in `/tools`.

### Behaviour ledger and Trust Dial

Every signed receipt is distilled into a human-readable ledger entry
(`argos/ledger/`) — what happened, whether it is reversible, and
its undo state. `/ledger` shows the full ledger for the current run.

The Trust Dial (`argos/permissions/trust_dial.py`) presents three plain-language
modes — **Cautious** / **Trusted** / **Autonomous** — that `/trust` cycles
through; a hidden `paranoid` mode confirms every step. HARD RULES are immune to
every mode. Escalating to a more permissive mode always surfaces an explicit
warning; the dial never silently self-upgrades. (Internally these map onto the
ApprovalLevel `CONFIRM` / `ACCEPT_EDITS` / `AUTO` semantics.)

Argos follows **understand-then-act**, like Claude Code / Cursor / Aider — there
is no pre-action intent-confirmation prompt; confirmation lives at the
side-effect layer (the approval gate).

### Conductor (autonomous face)

The conductor (`argos/conductor/`) executes standing orders
without blocking on the user — cron-lite schedules and file-trigger
watchers. The proactive *suggestions* it raises for you always need your
nod: every `ProactiveSuggestion` carries `requires_confirmation=True`, so
you `/confirm <id>` or `/dismiss <id>` and the engine never auto-executes
a suggestion. Its one autonomous standing order is the nightly Dream
consolidation (below): by default it runs on schedule and auto-enables
self-distilled skills that clear its A/B verify gate, without asking.
`/orders` lists the active standing orders.

### Computer use (perception)

`argos/perception/` provides OS-level screen and input control
(screenshot, click, double-click, type, key, scroll, open app) via
AppleScript and `screencapture` — zero third-party Python dependencies.

This is **off by default**. Set `ARGOS_COMPUTER_USE=1` and grant macOS
Accessibility permission to the terminal before use. All seven
`computer.*` tools are `risk=high + reversible=False` and require hard
CONFIRM approval regardless of the Trust Dial level. The Seatbelt
sandbox cannot confine global screen/mouse resources; the approval gate,
the ledger, and the audit trail are the governance layer instead.

### Self-test firewall (learning)

`argos/learning/` promotes only *verified* runs into skill memory:
a `passed` run triggers distillation and an A/B promotion gate;
`failed` / `unverifiable` runs produce a reflection entry for the memory
layer only (never promoted). `argos/verify/` adds an opt-in
self-test generator (`ARGOS_SELF_TEST=1`) that tries to synthesise a
candidate verify command when none was declared — the canary guard
ensures the generated command can actually fail (a trivial always-pass
command is discarded, keeping the `unverifiable` verdict honest).

### Dream nightly consolidation

`argos/learning/dream.py` runs every night (03:00 cron, or on-demand)
to synthesize verified runs into generalized skills. It scans the candidate
pool (distiller products from runs that lacked runner context), clusters
them by similarity (goal + verify_cmd token Jaccard ≥ 0.35), synthesizes
multi-source clusters into a single skill (model writes narrative only;
code and verify commands are copied verbatim from sources), and runs an
A/B promotion gate. Fails safely: missing workspaces → "no evidence to
promote", narrative generation failures → template fallback. By default the
nightly run is autonomous, and a synthesized skill is **auto-enabled** only
when it strictly beats the baseline in a real A/B verify comparison — the
verify gate is the quality bar, so there is no separate confirmation step
(disable `builtin-dream-nightly` in `~/.argos/conductor/orders.jsonl` to turn
it off). Integrates
with memory consolidation to merge reflections, decay low-confidence entries,
and archive old experiences (never hard-delete). See `docs/dream.md`.

---

## Commands

Slash commands live in the TUI. Tab completion is built in.

| Command | Purpose |
|---|---|
| `/help` | Show all commands. |
| `/tools` | List the callable tools (real count from the registry). |
| `/skills` | Manage the skill ecosystem: list / install / remove / refresh / test. |
| `/mcp` | List configured MCP external tools. |
| `/model` | View or switch the active model profile. |
| `/status` | Current run state. |
| `/cost` | Per-round cost and cache statistics. |
| `/resume` | Reattach to the previous session. |
| `/clear` | Start a new session (clears context). |
| `/trust` | Cycle / set the trust mode (`/trust [cautious\|trusted\|autonomous\|paranoid\|status]`; bare `/trust` advances to the next mode). Cautious = ask only at the cage wall; autonomous = full auto; paranoid = confirm every step. HARD RULES always enforced. Replaces `/yolo`. |
| `/yolo` | Legacy alias for `/trust autonomous`. |
| `/undo` | Roll back all file changes made in this run to the run start-point snapshot. |
| `/ledger` | View the behaviour ledger for the current run: human-readable entries and undo state. |
| `/retry` | Resend the last user message. |
| `/plan` | Enter "look at the plan, then act" mode. The agent writes a markdown plan; the host presents an inline approval modal. Plan-mode tool dispatch blocks `write_file` / `edit_file` / `run_command` until you exit. |
| `/hooks` | List the active `~/.argos/hooks.json` lifecycle hooks. `/hooks reload` re-reads the config without restarting. |
| `/lsp` | List the language servers currently in scope. `/lsp reload` re-reads `~/.argos/lsp.json`. |
| `/permissions` | Inspect or change the current approval level. Hard rules are always shown. |
| `/runs` | List persisted runs (daemon mode). `/runs {id} resume\|cancel` acts on one. |
| `/orders` | List standing conductor orders (autonomous scheduled / file-triggered instructions). |
| `/confirm` | Confirm a conductor proactive suggestion by ID. |
| `/dismiss` | Dismiss a conductor proactive suggestion by ID. |
| `/verify` | Run `Verifier.verify` against the configured `verify_cmd`. Never goes through `propose_verify`. Without a `verify_cmd` configured, verdict is `n_a`. |
| `/security-review` | Three passes: secrets, dependency vulnerabilities (shells out to `npm` / `pip-audit` / `cargo-audit` — missing tools reported as `error`, never silently skipped), dangerous APIs. Read-only. |
| `/simplify` | Three passes: token-shingle duplicate detection, function-complexity hotspots, dead-code heuristics. Read-only. |
| `/eval` | Self-eval harness. `/eval` lists recent runs + 7d pass rate. `/eval run <task_id>` runs a corpus task. `/eval compare <a> <b>` runs an A/B (report into transcript). CLI twin: `argos eval list \| run \| compare \| corpus`. |
| `/dream` | Nightly consolidation. `/dream` runs one round immediately (clusters candidates, synthesizes multi-source skills, A/B promotes, consolidates memory). `/dream status` shows the last report. CLI twin: `argos dream [--report]`. |
| `/routing` | View last 10 routing decisions. `/routing set <category> <tier>` updates routing. |
| `/context` | View the current LLM context breakdown by bucket (system / memory / tools / messages). |
| `/remember`, `/forget`, `/memory` | Explicit auto-memory management (hidden from the slash menu; still functional). |

---

## Memory & state

**Task history** (the original 4-tier): per-run records persisted to
`~/.argos/runs/<id>.jsonl` — append-only, fsync on meta, replayable
byte-for-byte. The same event stream drives the live UI, the on-disk
journal, and `/resume`. Recall is hybrid: vector recall when an
embedder is available (reusing the active provider's embeddings
endpoint), FTS5 keyword fallback otherwise. Argos will never call a
model it isn't configured to call.

**Auto memory** (#9, this release): a second 4-tier layer for
**cross-session** recall. Project / User / Skill / Session scopes,
JSONL at `~/.argos/memory/{user,projects/<hash>,skills/<name>,sessions/<sid>}.jsonl`.
5 implicit triggers (escalation / verify fail / repeat tool fail /
run success / undo) + 3 explicit slash commands (`/remember`,
`/forget`, `/memory`). Auto-loads `CLAUDE.md` / `AGENTS.md` (project
walk-up + `~/.argos/CLAUDE.md` global) into the system prompt's
`<memory_context>` segment. Secret redaction on write. Decay
`0.01/day` with use-count recovery `+0.02`. Capacity caps enforced
on write. `ARGOS_NO_MEMORY=1` to opt out. See
[`docs/auto-memory.md`](docs/auto-memory.md).

---

## CLI flags

```bash
uv run argos                       # launch TUI (daemon auto-detected)
uv run argos setup                 # provider + key + format-probe wizard
uv run argos --selftest            # offline self-check, prints verdicts
uv run argos --version             # version (single source: importlib.metadata)
uv run argos self-update           # check GitHub for new version, notify only
uv run argos --project <path>      # confine to a specific project directory
uv run argos --model <name>        # use a specific config profile for this run
uv run argos --effort=low|medium|high  # task effort tier (default: medium)
uv run argos --resume <session_id> # pass-through to TUI /resume
# ARGOS_NO_DAEMON=1 uv run argos   # force single-process inline mode
```

## Per-task model routing (#11)

Different tasks → different models. Configure in `~/.argos/config.json`:

```json
{
  "models": {
    "cheap":   { "protocol": "anthropic", "base_url": "...", "model": "Haiku",   "api_key_env": "K" },
    "default": { "protocol": "anthropic", "base_url": "...", "model": "Sonnet",  "api_key_env": "K" },
    "strong":  { "protocol": "anthropic", "base_url": "...", "model": "Opus",    "api_key_env": "K" }
  },
  "active": "default",
  "routing": {
    "default": "default",
    "by_category": { "file_edit": "cheap", "verify": "strong" },
    "by_tool":     { "run_command": "cheap" },
    "tier_force_confirm": ["strong"]
  }
}
```

TUI: `/routing` to see last 10 calls; `/routing set verify strong` to update.
See [docs/per-task-routing.md](docs/per-task-routing.md) for the full reference.

## Context viz + proactive compaction (#12)

See where your context goes, and stop the model from blowing past the window:

```bash
argos context show              # 4-bucket breakdown: system / memory (4 tier) / tools / messages
argos context show --json       # machine-readable for evals / integrations
```

TUI: `/context` for the same table with markup colors; the activity panel
shows a `[ctx N/M X%]` badge per step and a red dot on the status bar once
usage passes 80%. When the threshold trips, Argos fires `compact_messages`
automatically and prints `[compact 4500 → 2200 (52% reduction)]` in the
activity log. See [docs/context-viz.md](docs/context-viz.md).

---

## Security model

The threat model is **"a model that wants to please you into trouble"**.
The defences compose:

1. **Verify gate** — even a perfectly executed attack ends in
   `unverifiable` if the agent can't pass a real test.
2. **Smart approval** — destructive operations require explicit human
   consent, with a hard wall around the most dangerous patterns.
3. **Governance layer** — the broker gates every side effect (egress
   allowlist, approval, signed receipt) and the model's code runs under
   AST limits, regardless of what the model says. `--sandbox` adds a
   kernel-level Seatbelt/bwrap cage (workspace + network) on top.
4. **Audit trail** — every action is signed, persisted, and visible
   in the activity panel. The JSONL journal is the source of truth.
5. **Memory privacy** — memory never leaves the local filesystem
   unless the user explicitly exports it. Embeddings are computed
   by the active provider, not by a third party.

The trust-outs that remain (and the user is told about each):

- **Hooks and LSP servers run outside the OS sandbox** at the
  user's permission level, since they are user-controlled code by
  design. Argos logs a warning at startup for every configured hook
  and LSP server, and the docs tell you to audit third-party code
  before installing it.
- **Browser-based tools** can reach any URL the user is willing to
  approve. The visible-window default is deliberate: you should
  *see* the browser doing what the agent claims.
- **Computer use** (`computer.*` tools, `ARGOS_COMPUTER_USE=1`) operates
  on global screen and mouse resources that the Seatbelt sandbox cannot
  isolate. Governance is entirely through the approval gate (hard
  CONFIRM, every action), the ledger, and the audit trail. Every
  computer-use action is `risk=high + reversible=False`. Only enable
  this if you are willing to watch what the agent does.
---

## Uninstall

Stop the daemon if it is running, then remove all Argos state:

```bash
# Stop the background daemon (if running)
pkill -f argosd || true

# Remove all Argos state: config, runs, memory, ledger, conductor orders
rm -rf ~/.argos

# If installed from source via uv, remove the checkout:
# rm -rf /path/to/argos

# If installed as a uv tool:
# uv tool uninstall argos-agent
```

After `rm -rf ~/.argos` the next `uv run argos` will start with a clean
state. The `~/.argos/.env` file (holding your API key) is removed as part
of `~/.argos`; remove it separately if you stored it elsewhere.

---

## License

MIT. See `LICENSE`.

---

## Contributing

See `CONTRIBUTING.md` for the development workflow, the test-first
discipline, and the coding standards. The short version: every change
ships with tests (≥80% coverage is the floor), the verify gate stays
hard, and "honest about what works" beats "polished about what
doesn't".

---

## Trademark

Argos is an independent project. All product names, logos, and brands
referenced in this repository are property of their respective owners
and are used here only to describe compatibility or context.
