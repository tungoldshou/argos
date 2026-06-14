# Argos Strategic Pivot — Verify/Governance Moat + Conversation-Loop Architecture

_Date: 2026-06-15 · Status: direction approved, architecture design pending review_

Triggered by an adversarial 4-dimension comparison against **NousResearch/hermes-agent**
(workflow `wf_5a056a89-b20`, 4 agents reading both codebases). This document records the
strategic finding, the approved direction, and the architecture design + decomposition.

## 1. The comparison (evidence-backed)

| Dimension | Finding |
|---|---|
| **Governance / honesty** | **Argos-only; Hermes has no equivalent.** (1) OS-kernel sandbox (Seatbelt/bwrap) — Hermes has no local isolation, and its Docker mode *bypasses all approval checks*. (2) verify three-state hard-gate (host-side, reads exit codes, tamper detection, fail-closed, anti-fake-green) — in Hermes "completed" is purely model-self-reported. (3) HMAC receipt chain per brokered action. |
| **Agent loop** | verify hard-gate is sound & unique. **But the four-phase `plan→act→verify→report` pipeline applied to *every* input (incl. conversation) is over-engineered** — real bug trail ("你好"→pytest), and it **breaks prompt-cache reuse** (Hermes treats caching as sacred: build system prompt once, store, replay; Argos rebuilds it per-run, dynamic part is goal-keyed). |
| **Learning / memory** | Argos's verify-gated A/B skill promotion is a real correctness differentiator (Hermes writes skills with no gate). **But Hermes is far broader**: real-time per-turn conversational learning, skill lifecycle mgmt (curator.py 1835 lines), 8 pluggable memory backends + Honcho user modeling, usage-analytics dashboard. |
| **Capability breadth** | **Argos is a strict subset of Hermes** — platforms 0 vs 15+, terminal backends 2 vs 6, desktop walking-skeleton vs shipping Electron, skills local-md vs agentskills.io/hub/scanner, no training-trajectory pipeline, no Windows. Hermes leads 3–10×. |

## 2. The finding

**Argos's only real moat is one thing, and it is hard: trustworthy verification + honest
governance** — verify hard-gate + honesty protocol + OS sandbox + receipt chain. Hermes AND
Claude Code lack this entirely; they trust the model's self-reported completion. This is a
genuine vacuum, not marketing.

**What is wrong (user agreed):**
1. **Applying the hard-gate to *all* input** (incl. conversation) → over-engineering, the
   "你好→pytest" bug class, and broken prompt caching. The verify hard-gate only has value for
   runs that **actually make engineering changes**; for conversation/Q&A it is pure noise + cost.
2. **Chasing Hermes's breadth** (platforms / backends / desktop / learning / memory) → a
   permanent subset. Hermes is a large, mature, "aggressively expand the edges" project.

## 3. Approved strategic direction

**Double down on the moat; flip the architecture; stop chasing breadth.**

- **Positioning**: focus the *"trustworthy verification + honest governance"* vertical — let a
  user *trust* a cheap model's output (independently verified, not faked, sandbox-isolated,
  auditable, undoable). Do NOT pursue multi-platform / multi-backend / desktop breadth (Hermes
  territory; unwinnable as a subset).

## 4. Architecture: conversation-loop default + verify-on-changes

The core flip. Today `_drive()` (argos/core/loop.py) forces `plan→act→verify→report` on every
run. Target:

- **Default = conversation loop** (understand-then-act, like Hermes/Claude Code): the model reads
  the message and acts; no forced phases, no forced verify, for conversation / Q&A / read-only.
- **Verify hard-gate triggers ONLY when `made_changes`** (the run actually called
  `write_file`/`edit_file` — already detected at loop.py:1338 by code text, broker-independent).
  A run that mutates code → the moat engages: independent host-side verify, three-state verdict,
  tamper detection, bounce/escalate. A run that doesn't → honest conversational completion, no
  "✅ 完成 / 未机检验证" noise.
- This is the architectural generalization of the patches already landed 2026-06-14
  (smart-nudge + strategy-inference `made_changes` guard): promote `made_changes` from a patch
  to the *organizing principle* of when the moat applies.
- **Net effect**: removes conversation over-engineering, fixes the bug class at its root (not by
  patching), and keeps Argos's only moat exactly where it has value (coding tasks).

## 5. Cache fix (Hermes "caching is sacred")

Argos rebuilds the system prompt per-run; the `dynamic` half (skill bodies + memory recall) is
goal-keyed so the cached prefix the model sees is reconstructed every turn — structurally
incompatible with cross-turn prefix caching. Target (Hermes pattern): **build the session system
prompt once, store it, replay verbatim**; move per-goal skill/memory recall out of the cached
prefix (e.g. into the user turn, or a stable session-level block). Needs its own design pass.

## 6. Moat completeness

Close the confirmed gap: **`write_file` in the sandbox child bypasses the broker/receipt path**
(P2 hard-shell rules + secret detection + receipt don't cover it). Route file mutations through
the broker so the receipt chain + hard rules are complete. (Also: Linux sandbox depends on
optional `bwrap` — document/handle the no-isolation fallback honestly.)

## 7. Decomposition (each its own spec → plan → TDD)

1. **Architecture flip** — conversation-loop default + verify-on-changes. *Core, largest.* Must
   preserve the verify gate for coding tasks (the moat) + keep all governance tests green.
2. **Cache fix** — per-session system prompt; recall out of the cached prefix.
3. **`write_file` broker gap** — route file mutations through the broker (moat completeness).
4. **Positioning / narrative** — README + docs reframed to the verification-governance vertical;
   stop implying breadth parity with Hermes-class agents.

Suggested order: 3 (small, completes moat) → 1 (core flip) → 2 (cache) → 4 (narrative).

## 8. Risks

- (1) is a refactor of `loop.py` (core). Risk: regressing the verify gate that IS the moat. TDD
  + the existing governance test suite are the guardrails; preserve three-state verdict + tamper
  detection + Seatbelt unchanged.
- Many tests assume the four-phase pipeline; the flip will touch them. Distinguish "tests that
  encode the moat" (keep) from "tests that encode four-phase-on-conversation" (update).

## 9. Out of scope

Multi-platform adapters, multi-backend execution, serverless, desktop maturity, training-
trajectory pipeline, external memory backends — all Hermes territory. Not Argos's moat.

## 10. Decision log

- Strategic direction: consolidate the verify/governance moat + flip to conversation-loop;
  do not chase breadth. _(user, 2026-06-15, after Hermes comparison)_
- Conversation fast-path is subsumed by the architecture flip (it was the shallow version). _(user)_
