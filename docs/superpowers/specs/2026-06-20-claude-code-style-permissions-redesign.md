# Spec: Claude Code / Codex-style permissions redesign

**Date:** 2026-06-20
**Status:** approved, executing
**Driver:** owner — "make it as smooth as Claude Code/Codex; stop positioning around 'verify governance for cheap models'; just be a normal coding agent."

## Positioning change

Argos is **a normal coding agent in the Claude Code / Codex lineage** — an OS-sandboxed
CodeAct loop with a smooth, get-out-of-your-way permission model. Drop the
"verify governance for cheap models" product story from docs/README. The verify gate,
receipts, etc. remain as quiet, non-intrusive features — not the headline.

## The core finding (2026 research, latest)

The OS sandbox (Seatbelt child, **network off by default**, **writes caged to the
workspace**) is **NOT over-aggressive** — it is the convergent 2026 norm:
- **Codex** ships sandbox + net-off + workspace-write **by default** (Argos's exact posture).
- **Cursor 2.0/3.6** migrated *to* this design to eliminate prompts while improving safety.
- **Claude Code** has the same Seatbelt/bubblewrap cage (opt-in) and reports **~84% fewer prompts** when it is on.
- **Hermes** (denylist, no cage) states in its own SECURITY.md that the denylist "is NOT a security boundary; the only boundary is the OS." Cautionary tale, not a model.

The friction users feel is **not the cage** — it is the layers stacked **on top** of it:
the `run_command` binary allowlist, the dead egress valve, the lying "always allow"
button, and a default that **prompts AND cages**. The fix is to **relax the layers above
the OS boundary so the boundary can do the prompt-dropping work** (Codex's "auto-run
inside the cage", Claude Code's "84% fewer prompts").

## Target design

**Axis 1 — Sandbox (what's possible):** unchanged. Seatbelt cage, net-off, write-cage. Always on.

**Axis 2 — Approval mode (when to ask):** 5-level Trust Dial → **3 modes**, each mapping
1:1 to a distinct `ApprovalLevel` so the dial round-trips honestly:

| Mode | = ApprovalLevel | Behavior |
|---|---|---|
| **Cautious** (default) | CONFIRM + low_risk_auto ON | Reads + **in-workspace writes/edits + sandboxed shell auto-pass**. Prompt only at the cage wall: network egress (first-time-per-host), out-of-workspace write, HARD-rule hits. |
| **Trusted (session)** | ACCEPT_EDITS | + auto-approve the session's repeated patterns. |
| **Autonomous** | AUTO | No prompts; boundary is the only control. |

- L0 (every-step) → hidden `/trust paranoid`. L2 (irreversible-only) → folded into a
  HARD-rule that applies under all modes (not a dial position).
- **Denylist-as-only-hard-block:** a tiny set of always-confirm/deny guards (financial
  computer-use, secret-write, out-of-workspace write, network egress, destructive shell)
  under an otherwise-frictionless default.

## Phases

**Phase 0 — credential read-denylist (prereq, blocks Phase 2).**
Seatbelt profile currently `(allow file-read*)` whole-disk → `~/.ssh`/`~/.aws` readable.
Harmless while net is off, but the egress valve (Phase 2) makes it a live exfil risk.
Add a read-denylist for credential dirs to the Seatbelt profile **before** the egress valve.

**Phase 1 — kill the friction (the 80% win).**
- Flip the default `ApprovalGate(CONFIRM)` → **Cautious with low_risk_auto ON** (app_factory, tui/app, daemon). In-workspace writes/edits + sandboxed shell auto-pass.
- Fix the lying "always": `respond("always")` derives a pattern `RuleEntry` and **persists** it to `~/.argos/permissions.json` `allow[]` (engine + loader already exist; only the write-back is missing). Widen session-cache from exact-payload-hash to per-action.

**Phase 2 — egress valve + drop the command allowlist.**
- Wire the dead `EgressPolicy.allow(host)` to an approval card ("agent wants to reach <host> — once/session/always") with one-tap retry on egress-deny; persist "always" to permissions.json.
- Drop the `run_command` binary allowlist as a **hard gate** (the cage is the boundary). Keep arg-inspection (git -c, inline-eval) as defense-in-depth warnings, not denials. Route net-needing commands (pip/git push/clone/curl) through the egress escalation.

**Phase 3 — collapse the dial.** 5 levels → 3 modes (1:1 ApprovalLevel mapping). Hide L0 as `/trust paranoid`. Move "irreversible-always-confirm" to a HARD-rule. Update status line + cycling.

  *Done (2026-06-20):* User-facing surface is now 3 modes — **Cautious** (default, =L1) / **Trusted**
  (=L3) / **Autonomous** (=L4). Added `mode_name` + `TRUST_CYCLE` + `next_in_cycle` to `trust_dial.py`;
  bare `/trust` cycles Cautious→Trusted→Autonomous (Claude-Code Shift+Tab feel); `/trust status` shows
  without switching; `/trust paranoid` selects the hidden L0; mode names + `l0–l4`/`auto` accepted as
  args. Status display + dial header show the mode name. Folded in Phase 4's dead-code removal:
  deleted `suggest_escalation` / `EscalationSuggestion` / `_SUGGEST_THRESHOLD` (zero production callers).
  Fixed a test-isolation bug Phase 1 surfaced: an autouse fixture now isolates `permissions.config`
  (`_config` singleton + `CONFIG_PATH`) so tests can't pollute each other or the user's real
  `~/.argos/permissions.json`.

  *Deliberate deviations (lower risk, same user-facing result):* the `TrustLevel` L0–L4 enum and its
  `ApprovalLevel` mapping + reversible plumbing are **kept internally** (not torn out) — L2 is simply
  unadvertised/deprecated and the existing destructive-shell / system-path / financial HARD-rules
  already provide the "don't silently do irreversible things" protection, so no new blanket
  irreversible-confirm rule was added (it would re-introduce friction the redesign is removing). The
  5-row dial **widget** is left intact (header now names the mode) rather than rebuilt to 3 rows —
  that visual teardown is deferred until it can be verified against a live TUI.

**Phase 4 — delete the dead weight (pure subtraction).**
Cut: `intent/` + ARGOS_INTENT (disavowed, off); `suggest_escalation`/`EscalationSuggestion`/`_SUGGEST_THRESHOLD` (dead); empty `_FORCE_CONFIRM_ACTIONS` + branch; make per-step routing opt-in (skip categorize/select when tier maps empty; keep `effort.py`); replace `conductor/` engine with a launchd/cron or daemon-timer for nightly Dream.

  *Status (2026-06-20):*
  - ✅ **`suggest_escalation` machinery** deleted (folded into Phase 3 — zero production callers).
  - ✅ **`_FORCE_CONFIRM_ACTIONS`** set + dead `level_override` branch + unused `ApprovalLevel` import removed (commit `dc28ee0`-adjacent).
  - ✅ **per-step routing is opt-in** — `RoutingConfig.is_active()` gates router construction; `router=None` (the original loop path) when no routing table is configured.
  - ✅ **`intent/` + ARGOS_INTENT** deleted end to end (package, widget, protocol events, daemon route, loop registry, TUI handlers, TS SDK mirror, tests, docs; −2880 lines).
  - ⊘ **`conductor/` → launchd/cron — DECLINED.** On inspection the premise doesn't hold: the conductor is *already* a daemon-internal `asyncio` tick loop with a zero-dependency cron-lite parser — i.e. the spec's preferred "daemon-timer" option, not an external dependency. OS launchd/cron would be *less* portable (three platform mechanisms), add fragility, and lose the in-process ProactiveSuggestion / standing-order feature it also powers. Keeping the lean, framework-free, cross-platform daemon-timer is the correct call.

**Phase 5 — harden + reduce surface (follow-up).**
Collapse broker dual gating into a shared `_preflight(action,args)` called by both `request()` and `execute_sync()`. Make `_pick_strategy_cmd` infer pytest only when collectable tests exist for changed files. Feature-flag WorkflowSpec DSL + best-of-N + fanout off the default path (keep `git_worktree`). Trim `HONESTY_SYSTEM` prose. (Lower priority: halve auto-memory to 2 tiers; defer nightly Dream synthesis.)

  *Status (2026-06-20):*
  - ✅ **broker `_preflight`** — request()/execute_sync() now share one `_preflight(action,args)` (action-validation + file-write gate-only + egress); a parity test locks that the two paths can't diverge. (The real correctness win — closes the sync-bridge governance-divergence the audit flagged.)
  - ✅ **`_pick_strategy_cmd` / pytest** — `probe_workspace` only flags `has_pytest` when collectable test files exist (deliberate `pytest.ini`/`conftest.py` still count); fixes the "pyproject.toml-only project → pytest exits 5 → false failure" bug.
  - ✅ **workflows off the default path** (`ARGOS_WORKFLOWS=1` opt-in) — `WORKFLOW_PROMPT` moved out of the baked `HONESTY_SYSTEM`, injected conditionally like `COMPUTER_USE_PROMPT`. This *is* the real prompt trim (default stable prompt 3141 → 2923 chars) — no risky prose-nitpicking of the honesty invariants.
  - ⊘ **auto-memory 4→2 tiers — DEFERRED** (the spec's own "lower priority"). The 4-tier model works and recall / consolidation / Dream all depend on tier identity; halving it is a semantic change to a working subsystem with real regression risk and marginal benefit. Not worth it now.

**Docs:** reframe README/docs as a Claude Code/Codex-style coding agent; drop the cheap-model-verify-governance headline.

## Non-negotiables (keep)

Seatbelt cage / net-off / write-cage (the norm, done right, on-by-default), signed receipts
(single choke point), the verify gate as a quiet non-intrusive feature (already gated on
made_changes), StreamingContextScrubber + untrusted-fence ordering lock, computer-use
financial HARD-rule, the evaluator rule-layering engine, lean skills.py.
