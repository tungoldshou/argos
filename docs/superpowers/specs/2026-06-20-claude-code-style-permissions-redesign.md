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

**Phase 4 — delete the dead weight (pure subtraction).**
Cut: `intent/` + ARGOS_INTENT (disavowed, off); `suggest_escalation`/`EscalationSuggestion`/`_SUGGEST_THRESHOLD` (dead); empty `_FORCE_CONFIRM_ACTIONS` + branch; make per-step routing opt-in (skip categorize/select when tier maps empty; keep `effort.py`); replace `conductor/` engine with a launchd/cron or daemon-timer for nightly Dream.

**Phase 5 — harden + reduce surface (follow-up).**
Collapse broker dual gating into a shared `_preflight(action,args)` called by both `request()` and `execute_sync()`. Make `_pick_strategy_cmd` infer pytest only when collectable tests exist for changed files. Feature-flag WorkflowSpec DSL + best-of-N + fanout off the default path (keep `git_worktree`). Trim `HONESTY_SYSTEM` prose. (Lower priority: halve auto-memory to 2 tiers; defer nightly Dream synthesis.)

**Docs:** reframe README/docs as a Claude Code/Codex-style coding agent; drop the cheap-model-verify-governance headline.

## Non-negotiables (keep)

Seatbelt cage / net-off / write-cage (the norm, done right, on-by-default), signed receipts
(single choke point), the verify gate as a quiet non-intrusive feature (already gated on
made_changes), StreamingContextScrubber + untrusted-fence ordering lock, computer-use
financial HARD-rule, the evaluator rule-layering engine, lean skills.py.
