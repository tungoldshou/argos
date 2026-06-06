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

Built as one Python process on Textual. Model-agnostic (Anthropic-Messages
and OpenAI-compatible endpoints are both first-class). Designed to make
honest results cheap, not to make a single model cleverer.

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
4. A long-running daemon (opt-in via `--with-daemon`) lets 5+ minute
   tasks survive a closed terminal, a power loss, or a model upgrade —
   state, checkpoints, and the event journal all live on disk, so the
   next session picks up exactly where the last left off.

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

Four approval levels (`Observe` / `Propose` / `Confirm` / `Auto`) are
configurable per session, but **certain hard rules never bypass** even
at AUTO:

- Destructive shell operations (`rm -rf`, system paths, format
  commands).
- Writes outside the declared workspace.
- Reads or writes matching secret patterns (private keys, credential
  files, anything in `~/.ssh`).
- Outbound network access to non-allowlisted hosts.

The approval modal itself is a real keyboard-driven prompt, not a
decorative pause: `1` deny, `2` once, `3` session, `4` always, with a
visible diff of what the tool would do.

### Long-running daemon

A 7-state machine (`pending` / `running` / `paused` / `suspended` /
`completed` / `failed` / `cancelled`) lives in an opt-in daemon process.
Keyboard bindings on the TUI:

- **`Ctrl+B`** — background the current run. It enters `suspended`
  state on disk; you can start a new goal immediately and resume the old
  one later.
- **`Esc`** — pause at the next step boundary. The worker only blocks at
  well-defined step entry, so the pause is deterministic, not
  interrupt-the-LLM-token.
- **`Esc Esc`** (within 1.5s) — cancel.
- **`Ctrl+C`** — soft interrupt. The TUI exits; the daemon keeps the
  run alive, persisted to JSONL.

When the daemon is enabled (`--with-daemon`), a startup modal lists
suspended runs and lets you resume any of them. State survives TUI
exit, terminal close, machine reboot, and even a model upgrade (the
worker reattaches from the last checkpoint).

### 22 broker-gated tools

Every tool call — from the agent or from a sub-agent — flows through the
capability broker. The broker is the only path to the sandbox; it
checks the action against the egress policy, asks the approval gate
when needed, signs a receipt, and only then hands off to the executor.

Tools span the breadth of an engineer's day:

- **Files** — `read_file`, `write_file`, `edit_file`, `search_files`
- **Shell** — `run_command` (allowlist + Seatbelt + workspace cage)
- **Verification** — `propose_verify` (declare-then-execute, isolated
  from the agent's own code path)
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
- **Skill** — built-in skills (`/verify`, `/security-review`,
  `/simplify`) callable on demand without re-using the agent's code

The tool count shown in `/tools` is always the real number from
`ALL_TOOL_NAMES`. No padding, no "60+ tools" lies.

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

---

## Commands

Slash commands live in the TUI. Tab completion is built in.

| Command | Purpose |
|---|---|
| `/plan` | Enter "look at the plan, then act" mode. The agent writes a markdown plan (task breakdown / files touched / risks / approval gates) and the host presents a 4-option approval modal: `1` approve and start, `2` approve and accept edits, `3` keep planning, `4` refine with feedback. Plan-mode tool dispatch blocks `write_file` / `edit_file` / `run_command` until you exit. |
| `/hooks` | List the active `~/.argos/hooks.json` lifecycle hooks. `/hooks reload` re-reads the config without restarting. |
| `/lsp` | List the language servers currently in scope. `/lsp reload` re-reads `~/.argos/lsp.json`. |
| `/verify` | Run `Verifier.verify` against the configured `verify_cmd`. The user-facing path; never goes through `propose_verify`. Without a `verify_cmd` configured, the verdict is `n_a` and the TUI prompts you to set one. |
| `/security-review` | Three passes: secrets (9 regexes incl. `sk-ant-`), dependency vulnerabilities (shells out to `npm` / `pip-audit` / `cargo-audit` — missing tools are reported as `error`, never silently skipped), dangerous APIs (Python `eval` / JS-TS `eval` / `innerHTML` / `child_process`). Read-only — never modifies code. |
| `/simplify` | Three passes: token-shingle duplicate detection, function-complexity hotspots, dead-code heuristics. Read-only. |
| `/permissions` | Inspect or change the current approval level. Hard rules are always shown. |
| `/runs` | List persisted runs. `/runs {id} resume\|cancel\|info` acts on one. |
| `/eval` | Self-eval harness. `/eval` lists recent runs + 7d pass rate. `/eval run <task_id>` runs a corpus task. `/eval compare <a> <b>` runs an A/B (md report into transcript). CLI twin: `argos eval list \| run \| compare \| corpus`. |
| `/model` | List configured profiles and switch `active` (takes effect on next launch). |
| `/help`, `/tools`, `/skills`, `/mcp` | Discovery: what can this thing actually do right now? |

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
uv run argos                  # launch TUI
uv run argos setup            # provider + key + format-probe wizard
uv run argos --selftest       # offline self-check, prints verdicts
uv run argos --version        # version (single source: importlib.metadata)
uv run argos self-update      # check GitHub for new version, notify only
uv run argos --with-daemon    # opt into the long-running run daemon
uv run argos --project <path> # confine to a specific project directory
uv run argos --model <name>   # use a specific config profile for this run
uv run argos --effort=low|medium|high   # task effort tier (default: medium)
uv run argos --resume         # reattach to the last session
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
uv run argos --compact-threshold=0.7   # tighten / loosen the auto-compact trigger
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

The two trust-outs that remain (and the user is told about both):

- **Hooks and LSP servers run outside the Seatbelt sandbox** at the
  user's permission level, since they are user-controlled code by
  design. Argos logs a warning at startup for every configured hook
  and LSP server, and the docs tell you to audit third-party code
  before installing it.
- **Browser-based tools** can reach any URL the user is willing to
  approve. The visible-window default is deliberate: you should
  *see* the browser doing what the agent claims.

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
