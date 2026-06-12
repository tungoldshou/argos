# Argos — A Terminal Super-Agent

Argos is a single-process terminal (TUI) super-agent for engineers who want
**reliable, verifiable work from cheap models** — without the lying.

Three pillars carry the design:

- **A verify hard-gate.** No task is marked "done" until a real, user-defined
  check command (`pytest`, `cargo test`, `ruff`, `tsc`, `mypy`, …) returns
  zero. The agent must *declare* how its work will be verified before the
  gate trusts it, and a three-state verdict (`passed` / `failed` /
  `unverifiable`) prevents fake-greens.
- **An honesty protocol.** Argos would rather say "I don't know" than ship
  a lie. Failed checks bounce the actual error back to the agent; an
  unverifiable task is *unverifiable*, not passed. Every action the agent
  takes leaves a signed receipt; every event is persisted to a JSONL
  journal you can replay.
- **An OS-level sandbox.** macOS Seatbelt confines the agent at the kernel
  boundary — no network by default, writes only inside the declared
  workspace. Approval gates sit on top for the destructive paths the
  user wants to opt into.

Built in Python on Textual. A background daemon kernel runs the work and
survives a closed terminal; the TUI attaches as a protocol client, with an
honest single-process fallback when the daemon is unavailable. Model-agnostic
(Anthropic-Messages and OpenAI-compatible endpoints are both first-class).
Designed to make honest results cheap, not to make a single model cleverer.

---

## Why Argos

Cheap models fail in two painful ways: they get the work wrong, **and** they
say "done" anyway. The first problem gets better with every new model
release; the second is structural — it's a politeness failure, not a
capability failure, and a cleverer model often lies more smoothly.

We built Argos around the assumption that **trustworthy output is an
engineering problem, not a model problem**. Four design choices follow:

1. The verify gate turns "is it done?" from a sentence the model writes
   into an exit code a harness reads. A model can bluff the user, but
   not `subprocess.run()`.
2. The honesty protocol makes "I don't know" a first-class outcome —
   escalation paths to the human, never a fake completion, every
   unverifiable step flagged in the activity panel.
3. The smart-approval system puts a hard wall in front of destructive
   operations (`rm -rf`, system paths, secret patterns) that **never
   bypasses** even at the most permissive AUTO level. The user is always
   the final reviewer for the actions that hurt most.
4. A long-running daemon that auto-starts in the background lets 5+
   minute tasks survive a closed terminal, a power loss, or a model
   upgrade — state, checkpoints, and the event journal all live on
   disk, so the next session picks up exactly where the last left off.
   (Set `ARGOS_NO_DAEMON=1` to force single-process inline mode.)

The result is a tool that lets a developer pick a cheap model, ship real
work, and catch the lies.

---

## Quick start

Needs Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run argos              # launch the Argos TUI
uv run argos setup        # interactive wizard: pick a provider, paste a key,
                          # connection + CodeAct-format probe (real request)
uv run argos --selftest   # offline full-machine self-check, prints verdicts
uv run pytest -q          # run the test suite
```

Without an API key, `argos` falls back to an honest demo state — it does
**not** pretend to run. The TUI tells you to run `argos setup`.

---

## Install

### One-line installer (macOS arm64)

```bash
curl -fsSL https://raw.githubusercontent.com/tungoldshou/argos/main/packaging/install.sh | bash
```

Installs to `/Applications/Argos.app` and creates an `/usr/local/bin/argos`
symlink.

### Homebrew Cask (macOS arm64)

```bash
brew install --cask -s packaging/homebrew/argos.rb
```

(TODO: once a `tungoldshou/homebrew-argos` tap is published, this becomes
`brew install --cask argos` — tracked in the #13 stage.)

### pip / uv (any platform, #13)

```bash
pip install argos-agent        # or: uv tool install argos-agent
argos --version
```

`argospkg` ships in the same install for packaging helpers (`argospkg info`,
`argospkg check`, `argospkg manifest`).

### Linux AppImage / .deb / .rpm (#13)

```bash
# AppImage (cross-glibc universal)
curl -fsSL https://github.com/tungoldshou/argos/releases/latest/download/Argos-X.Y.Z-x86_64.AppImage -o argos
chmod +x argos && ./argos

# .deb (apt route)
curl -fsSL https://raw.githubusercontent.com/tungoldshou/argos/main/packaging/install-deb.sh | bash

# .rpm (dnf/yum route)
sudo dnf install ./argos-X.Y.Z-1.x86_64.rpm
```

### Windows (#13)

```powershell
# WinGet (once accepted into microsoft/winget-pkgs)
winget install tungoldshou.argos

# Or grab the .exe zip directly
Invoke-WebRequest -Uri "https://github.com/tungoldshou/argos/releases/latest/download/Argos-X.Y.Z-x86_64-windows.zip" -OutFile argos.zip
Expand-Archive argos.zip ; .\argos.exe
```

### Homebrew tap (Linux CLI + macOS GUI, #13)

```bash
brew tap tungoldshou/argos
brew install argos           # Linux CLI: AppImage
brew install --cask argos    # macOS GUI: .app bundle
```

### Nix (#13)

```bash
nix run github:tungoldshou/argos#argos
```

(Flake is a simplified `buildPythonApplication`;full nixpkgs coverage lands in v1.1.)

See [`docs/packaging-c.md`](docs/packaging-c.md) for the full per-channel
install matrix, known limitations, and upgrade commands.

### Upgrade

```bash
argos self-update   # notifies when a new version is available (does not download)
# to actually upgrade: re-run install.sh | `brew upgrade` | `pip install --upgrade argos-agent` | `winget upgrade`
```

### From source

```bash
git clone https://github.com/tungoldshou/argos
cd argos
uv sync
uv run argos
```

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

### OS sandbox

The agent runs inside a macOS Seatbelt profile: no outbound network
unless explicitly approved, writes confined to the declared workspace,
reads scoped to the project plus user home. The capability broker on
top adds egress allowlists (Tavily / DDGS / configured MCP hosts) and
per-action approval requests. Network is *off* by default — and the
AUTO (`/yolo`) approval level does not silently flip it on.

### Smart approval

Five Trust Dial levels (L0 `every-step` / L1 `dangerous-only` /
L2 `irreversible-only` / L3 `session-trusted` / L4 `autonomous`) are
configurable per session via `/trust`, but **certain hard rules never
bypass** even at L4:

- Destructive shell operations (`rm -rf`, system paths, format
  commands).
- Writes outside the declared workspace.
- Reads or writes matching secret patterns (private keys, credential
  files, anything in `~/.ssh`).
- Outbound network access to non-allowlisted hosts.

The approval modal itself is a real keyboard-driven inline prompt, not a
decorative pause: `1` deny, `2` once, `3` session, `4` always, with a
visible diff of what the tool would do. `/yolo` is kept as an alias for
`/trust l4`.

### Long-running daemon

A 7-state machine (`pending` / `running` / `paused` / `suspended` /
`completed` / `failed` / `cancelled`) runs in a background daemon
process (`argosd`) that Argos auto-detects and auto-starts at launch.
If the daemon is unreachable, the TUI falls back transparently to
single-process inline mode (shown in the status bar). There is no
`--with-daemon` flag; daemon mode is the default when available.

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

### 30 broker-gated tools

Every tool call — from the agent or from a sub-agent — flows through the
capability registry and broker. The registry is the authoritative source
for tool manifests (name, kind, risk, reversibility, visibility); the
broker checks the action against the egress policy, asks the approval
gate when needed, signs a receipt, and only then hands off to the
executor.

Tools span the breadth of an engineer's day:

- **Files** — `read_file`, `write_file`, `edit_file`, `search_files`
- **Shell** — `run_command` (allowlist + Seatbelt + workspace cage)
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
the model from writing brittle orchestration code (cheap models are
better at JSON than at Python async) while keeping the user in the
approval loop.

Five shapes are supported:

- **`fan_out`** — one agent per item, run in parallel.
- **`pipeline`** — items traverse stages sequentially, no barriers.
- **`panel`** — N voters, adversarial verify generalised.
- **`loop_until`** — accumulate to a target, or stop on consecutive
  empty rounds (hard cap prevents runaway).
- **`synthesize`** — roll up results into a single report.

Each sub-agent is a full Argos — its own ModelClient, its own broker,
its own Seatbelt sandbox, its own verify gate. Sub-agents can be
assigned any config profile, so a cheap tier can do the parallel
work and a stronger model can adjudicate. `isolation: worktree` gives
parallel write-agents their own git worktree, with a diff captured
before teardown for the user to review.

### Capability registry

The capability registry (`argos_agent/capability/`) is the authoritative
manifest store for every action the broker can dispatch: name, kind,
risk level (`low` / `medium` / `high`), reversibility, egress hosts, and
visibility. The registry is built at startup by `register_builtins()` and
is the source of truth for the tool count shown in `/tools`.

### Behaviour ledger and Trust Dial

Every signed receipt is distilled into a human-readable ledger entry
(`argos_agent/ledger/`) — what happened, whether it is reversible, and
its undo state. `/ledger` shows the full ledger for the current run.

The Trust Dial (`argos_agent/permissions/trust_dial.py`) replaces the
legacy four-level approval knob with five named levels (L0–L4) that
speak in plain language: "every step", "dangerous only", "irreversible
only", "session-trusted", "autonomous". HARD RULES are immune to every
level. Escalation from a lower to a higher level always surfaces an
explicit warning; the dial never silently self-upgrades.

### Intent confirmation loop

Before starting a run, the intent engine (`argos_agent/intent/`)
parses the user's natural-language goal into a structured `IntentCard`
and surfaces it for a brief confirmation. This catches
"translation-error = source drift" before any tool is called.

### Conductor (autonomous face)

The conductor (`argos_agent/conductor/`) executes standing orders
without blocking on the user — cron-lite schedules and file-trigger
watchers — but **never acts without confirmation**. Every suggestion is
a `ProactiveSuggestion` with `requires_confirmation=True`. The user
either `/confirm <id>` or `/dismiss <id>`; the engine does not
auto-execute. `/orders` lists the active standing orders.

### Computer use (perception)

`argos_agent/perception/` provides OS-level screen and input control
(screenshot, click, double-click, type, key, scroll, open app) via
AppleScript and `screencapture` — zero third-party Python dependencies.

This is **off by default**. Set `ARGOS_COMPUTER_USE=1` and grant macOS
Accessibility permission to the terminal before use. All seven
`computer.*` tools are `risk=high + reversible=False` and require hard
CONFIRM approval regardless of the Trust Dial level. The Seatbelt
sandbox cannot confine global screen/mouse resources; the approval gate,
the ledger, and the audit trail are the governance layer instead.

### Desktop shell (ACP channel)

`desktop/` contains a Tauri 2 shell that connects to the running
`argosd` daemon via the ACP protocol (Unix socket, HTTP/SSE). The
TypeScript SDK (`desktop/sdk/`) is a zero-runtime-dependency client
library (`DaemonClient`, typed SSE subscriptions).

Build the desktop shell:

```bash
bash packaging/build_desktop.sh      # release build → .app + .dmg
bash packaging/build_desktop.sh --debug   # faster debug build
```

Requires Node.js, Rust toolchain, and macOS 13+. The current build
is ad-hoc signed (local use only; not notarised). See
[`packaging/desktop.md`](packaging/desktop.md) for full build and
signing documentation.

### Self-test firewall (learning)

`argos_agent/learning/` promotes only *verified* runs into skill memory:
a `passed` run triggers distillation and an A/B promotion gate;
`failed` / `unverifiable` runs produce a reflection entry for the memory
layer only (never promoted). `argos_agent/verify/` adds an opt-in
self-test generator (`ARGOS_SELF_TEST=1`) that tries to synthesise a
candidate verify command when none was declared — the canary guard
ensures the generated command can actually fail (a trivial always-pass
command is discarded, keeping the `unverifiable` verdict honest).

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
| `/trust` | View or set the Trust Dial level (`/trust [l0\|l1\|l2\|l3\|l4\|status]`). L0 = confirm every step; L4 = full auto; HARD RULES always enforced. Replaces `/yolo`. |
| `/yolo` | Legacy alias for `/trust l4`. |
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
3. **OS sandbox** — Seatbelt enforces the workspace cage and the
   network policy at the kernel boundary, regardless of what the
   model says.
4. **Audit trail** — every action is signed, persisted, and visible
   in the activity panel. The JSONL journal is the source of truth.
5. **Memory privacy** — memory never leaves the local filesystem
   unless the user explicitly exports it. Embeddings are computed
   by the active provider, not by a third party.

The trust-outs that remain (and the user is told about each):

- **Hooks and LSP servers run outside the Seatbelt sandbox** at the
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
- **Desktop shell (ACP channel)** — the Tauri desktop shell connects to
  `argosd` via a Unix socket on the local machine only. The ACP
  protocol does not expose the socket over the network. Trust boundary
  is the local user account.

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
