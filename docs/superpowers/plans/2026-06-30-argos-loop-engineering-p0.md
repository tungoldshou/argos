# Argos → Real Loop Engineering: P0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Scope note (writing-plans §Scope Check):** This is a **multi-subsystem master plan** covering all 18 P0 gaps from the 2026-06-30 loop-engineering audit. It is batched into 5 PR-sized sub-plans (Batch 1–5), each producing working, independently-testable software. Batch 1 is specified to TDD-step granularity. Batches 2–5 are specified to **task granularity** (exact files, interfaces, affected tests, acceptance command per task); each task is expanded into red→green→commit steps by its implementer against the real code at execution time. This avoids pre-writing line-level code that drifts before it runs.

**Goal:** Turn Argos from "has the loop-engineering skeleton" into "users can actually do loop engineering" — close the four loops (core / verify / event-driven / self-improving), add cost+stagnation guardrails, expose loop authoring in the TUI, and (per user decision 2026-06-30) flip the human-in-the-loop gates to **full autonomy** (only finance stays always-confirm).

**Architecture:** Pure-additive guardrails and TUI surfaces land first (Batches 1–2, zero behavior flips). Observability/orchestration wiring next (Batch 3). Resume/state correctness fixes (Batch 4). The autonomy flips + Loop-4 wiring — which intentionally reverse prior "honest, human-on-the-loop" designs and touch many existing tests — land last in clearly-labeled Batch 5, split 5a (close the self-improvement loop) / 5b (default-on switches).

**Tech Stack:** Python 3.12, pytest (+xdist `-n auto --dist loadgroup`), Textual TUI, smolagents executor, httpx, uv. No new deps.

## Global Constraints

- `main` is PR-only, branch-protected (`strict` + `enforce_admins`). Every batch = its own branch → push → `gh pr create` → wait for green `Full test suite (Linux + bwrap sandbox)` CI → `gh pr merge`. No direct pushes. Rebase main into the branch if main moved.
- Full `uv run pytest` must stay green; coverage gate **80% on the full suite** (`--cov=argos --cov-fail-under=80`). Judge coverage against the full run, not a subset.
- House norm: **TDD** (red → green → refactor), type annotations on all signatures, PEP-8, Chinese docstrings/comments are the house norm.
- User-facing strings go through i18n (`from argos.i18n import t`; add EN+ZH to `argos/locales/*.py`; ZH value = verbatim original so `ARGOS_LANG=zh` tests stay green). Tests run under `ARGOS_LANG=zh` (conftest pins it).
- Set `ARGOS_NO_DAEMON=1` in tests that must not attach to a live daemon.
- Mark real-subprocess / real-pyright tests `@pytest.mark.slow`.
- Version is single-sourced; don't hardcode version strings.
- **Honesty invariant still holds for verdicts**: never fabricate success/tool-counts/status. "Full autonomy" changes *who triggers* work and *whether a confirm gate is shown*, NOT whether the verify gate's exit-code reading is honest. Do not weaken the 3-state verdict or anti-fake-green.

---

## File Structure

| File | Responsibility | Batches |
|---|---|---|
| `argos/core/loop.py` | `LoopConfig` (+budget fields), main `while` loop (stagnation fingerprint, cost circuit-breaker, max-steps soft-landing nudge, `RunStart`/step-budget event) | 1 |
| `argos/protocol/events.py` | new event dataclasses: `StepBudget` (or extend `PhaseChange` with `max_steps`), `BudgetWarning`, `StepLimitWarning` | 1, 2 |
| `argos/eval/runner.py` | enforce `_budget_s` / `_budget_cost_usd` (currently dead) | 1 |
| `argos/tui/commands.py` | register `loop`, `goal`, `schedule`, `watch` in `_COMMAND_KEYS` | 2 |
| `argos/tui/app.py` | dispatch new commands → daemon `POST /orders` / run submission; subscribe `_conductor` SSE; render step `N/M`; budget warning highlight | 2 |
| `argos/tui/status_bar.py` | `action N/M` denominator | 2 |
| `argos/locales/*.py` | i18n for new commands + warnings | 2 |
| `argos/core/honesty.py` | add `best_of_n` to `WORKFLOW_PROMPT` op list (line ~206) | 3 |
| `argos/app_factory.py` | instantiate `LedgerStore` in `build_components`, thread into inline loop | 3 |
| `argos/learning/distiller.py`, `argos/learning/dream.py` | consume `verify_verdict`/`cost_update`/`phase_change` from replay; rank candidates by cost-efficiency | 3 |
| `argos/daemon/server.py`, `argos/daemon/manager.py`, `argos/daemon/worker.py` | real resume-from-suspended (spawn worker from index+checkpoint); restore step counter | 4 |
| `argos/core/snapshot.py`, `argos/daemon/manager.py` | persistent snapshot root + prune terminal runs | 4 |
| `argos/daemon/worker.py`, `argos/learning/hook.py`, `argos/learning/promotion_gate.py` | Loop-4: wire `runner_factory`, auto-enable promoted skills | 5a |
| `argos/conductor/conductor_supervisor.py`, `argos/conductor/proposals.py` | Dream autonomous (no confirm), autonomous StandingOrder tier | 5a |
| `argos/routing/config.py`, `argos/verify/self_test.py` | routing default-on; production reviewer-LLM proposer | 5b |

---

# Batch 1 — Loopmaxxing guards + cost circuit-breaker (PURE ADD, low risk)

**Branch:** `feat/loop-guards` · **Closes P0:** stagnation detection (core-loop), cost hard-stop (cost-control ×2)
**Risk:** low — all additions are opt-in (new optional `LoopConfig` fields default to None/off) and emit new events; no existing behavior changes when budgets are unset.
**Affected existing tests:** none expected to break (new fields default off). Add new tests only.

### Task 1.1: Stagnation / stuck-state detection in the act loop

**Files:**
- Modify: `argos/core/loop.py` — main `while step < self._cfg.max_steps:` body (~loop.py:1315), guard init block (~loop.py:1309-1313)
- Test: `tests/test_loop_stagnation.py` (new)

**Interfaces:**
- Produces: when the same `(code_block_text, stdout)` pair repeats `>= STAGNATION_LIMIT` (=2) consecutive times, the act loop breaks early and the harness emits an `Escalation` event whose message names the detected cycle. Termination stays deterministic.

- [ ] **Step 1: Write the failing test.** Use the existing scripted-model test harness (mirror `tests/test_loop.py` setup) to feed a model that emits the *identical* code block 3 times. Assert the run stops before `max_steps` and an `Escalation` event is yielded with a "stuck"/"cycle" marker.

```python
# tests/test_loop_stagnation.py
import pytest
from argos.protocol.events import Escalation  # confirm exact name at impl time

@pytest.mark.asyncio
async def test_identical_code_block_triggers_stagnation_escalation(scripted_loop):
    # scripted model emits the same failing ```python block every turn
    loop = scripted_loop(code_blocks=["print(1/0)"] * 5, max_steps=20)
    events = [e async for e in loop.run("do x")]
    assert any(isinstance(e, Escalation) for e in events)
    # stopped early, not run to max_steps
    assert sum(1 for e in events if getattr(e, "kind", "") == "code_action") <= 3
```

- [ ] **Step 2: Run it — expect FAIL** (`uv run pytest tests/test_loop_stagnation.py -v`). Currently runs to max_steps, no Escalation.
- [ ] **Step 3: Implement.** Add `_step_fingerprints: dict[str, int]` init alongside the other per-run guards (loop.py:1309-1313). After extracting the code block + obtaining `CodeResult.stdout`, compute `fp = hashlib.sha256((code + "\x00" + stdout).encode()).hexdigest()`; increment counter; if `>= 2` consecutive (track `_last_fp` + run-length), set `escalated = True`, emit Escalation via the harness path (reuse the `_fail_count > max_rounds` escalation emission at loop.py:1820-1825), `break`. Add module const `STAGNATION_LIMIT = 2`.
- [ ] **Step 4: Run it — expect PASS.**
- [ ] **Step 5: Commit** `feat(loop): break + escalate on stagnant (code,stdout) repetition`

### Task 1.2: Cost / token circuit-breaker on `LoopConfig`

**Files:**
- Modify: `argos/core/loop.py` — `LoopConfig` (loop.py:296-312, add two fields), main loop cost accounting path (where `CostUpdate` is computed)
- Test: `tests/test_loop_budget.py` (new)

**Interfaces:**
- Produces: `LoopConfig.max_cost_usd: float | None = None`, `LoopConfig.max_tokens_in: int | None = None`. When accumulated cost (or input tokens, the cheaper guard that works for un-priced models) exceeds the ceiling after a step, the loop breaks with an `Escalation` ("budget exceeded").

- [ ] **Step 1: Failing test** — scripted loop with `max_tokens_in=10`, model that consumes >10 input tokens in one step; assert run stops with a budget Escalation before `max_steps`.
- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3: Implement** — add the two frozen-dataclass fields; after each step's cost/token accounting, compare against ceilings (skip if None); on breach set `escalated=True`, emit Escalation, break. Token guard uses the running `tokens_in` sum (already tracked for `CostUpdate`); cost guard uses the same price math as `CostUpdate`.
- [ ] **Step 4: Run — PASS.**
- [ ] **Step 5: Commit** `feat(loop): hard cost/token ceiling with budget-exceeded escalation`

### Task 1.3: Enforce `EvalRunner` budget (kill dead `--budget`)

**Files:**
- Modify: `argos/eval/runner.py` — `_drive()` (runner.py:263-288) reads `_budget_s`/`_budget_cost_usd` (currently stored, never read)
- Test: `tests/eval/test_runner_budget.py` (new)

**Interfaces:**
- Produces: `_drive()` aborts the eval run when wall-clock exceeds `_budget_s` or accumulated `cost_usd` (summed from `CostUpdate` events) exceeds `_budget_cost_usd`; result is marked timed-out/over-budget rather than silently ignoring the flag.

- [ ] **Step 1: Failing test** — runner with `budget_cost_usd=0.0001`, assert the run is aborted/flagged over-budget.
- [ ] **Step 2: FAIL.**
- [ ] **Step 3: Implement** — wrap the drive with `asyncio.wait_for(..., timeout=self._budget_s)` (when set) and accumulate `cost_usd` from streamed `CostUpdate` events, breaking when over `_budget_cost_usd`. Mark `EvalResult` accordingly.
- [ ] **Step 4: PASS.**
- [ ] **Step 5: Commit** `fix(eval): actually enforce --budget wall-clock and cost ceilings`

**Batch 1 gate:** `uv run pytest -n auto --dist loadgroup` green → PR `feat/loop-guards` → green CI → merge.

---

# Batch 2 — Loop-authoring UX surface (slash commands, low-medium risk)

**Branch:** `feat/loop-tui-commands` · **Closes P0:** `/goal --verify` (ux), `/schedule` (primitives), `/watch` (event-driven), step `N/M` (ux), conductor SSE subscribe (event-driven)
**Risk:** low-medium — adds TUI surfaces calling existing daemon endpoints; no engine behavior change. Adding to `_COMMAND_KEYS` changes `/help` snapshot + slash-menu tests.
**Affected existing tests:** `tests/tui/` command-help / slash-menu / `COMMAND_HELP` snapshot tests (e.g. anything asserting the command set or `/help` text) — update expected sets to include the 4 new commands. Grep `tests/tui` for `COMMAND_NAMES`/`COMMAND_HELP`/`_COMMAND_KEYS`/`match_commands` and update.

### Task 2.1: Register `loop`/`goal`/`schedule`/`watch` commands (parse layer)
- **Files:** `argos/tui/commands.py:15-20` (append 4 keys), `argos/locales/*.py` (add `cmd.loop`/`cmd.goal`/`cmd.schedule`/`cmd.watch` to EN+ZH catalogs), `tests/tui/test_commands.py`
- **Acceptance:** `parse_slash("/goal fix bug | verify: pytest")` → `SlashCommand(name="goal", arg="fix bug | verify: pytest", known=True)`; `match_commands("/sch")` includes `schedule`. Update affected snapshot tests.
- **Run:** `uv run pytest tests/tui/test_commands.py -v`

### Task 2.2: `/goal <text> --verify <cmd>` (or `... | verify: <cmd>`) submission with explicit exit condition
- **Files:** `argos/tui/app.py` (dispatch `goal`), wire parsed `verify_cmd` into the run submission path (inline `build_run_stack` verify_cmd / daemon run create). Test: `tests/tui/test_goal_command.py`
- **Acceptance:** submitting `/goal X | verify: <cmd>` starts a run whose `LoopConfig.verify_cmd == <cmd>` (assert via the run-stack factory or a captured submission payload). This is the first TUI path that lets a user declare a verifiable exit without relying on model `propose_verify()`.

### Task 2.3: `/schedule <when>: <goal>` and `/watch <glob> <goal-template>` → `POST /orders`
- **Files:** `argos/tui/app.py` (dispatch → daemon client `POST /orders` with `kind=cron`/`kind=file_trigger`), Test: `tests/tui/test_schedule_watch.py` (mock daemon client)
- **Acceptance:** `/schedule every 1h: summarize logs` issues a `POST /orders` with the right `kind`+payload; `/watch *.py run tests` issues `kind=file_trigger`. Assert against a mocked daemon HTTP client. (Daemon endpoint already exists at `server.py` `POST /orders`.)

### Task 2.4: Step budget `N/M` visible
- **Files:** `argos/protocol/events.py` (add `max_steps` to `PhaseChange` or new `RunStart`), `argos/core/loop.py` (populate it), `argos/tui/status_bar.py:189-200` (render `action N/M`), Test: `tests/tui/test_status_bar.py`
- **Acceptance:** status bar shows `action 7/40` not `action 7`. One field added to the event, one render change.

### Task 2.5: Subscribe idle TUI to conductor `_conductor` SSE
- **Files:** `argos/tui/app.py:403-488` `_setup_daemon_mode` (after connect, start a background worker opening `DaemonEventSource(socket_path, '_conductor', session_id)` → `_apply_event`), Test: `tests/tui/test_conductor_subscription.py`
- **Acceptance:** a `ProactiveSuggestionEvent` pushed on the `_conductor` stream reaches `_apply_event` and renders. Infra already exists (`conductor_supervisor.py:7-13`); this is the missing subscription.

**Batch 2 gate:** full suite green (esp. updated `tests/tui`) → PR → CI → merge.

---

# Batch 3 — Observability wiring + orchestration reachability (medium risk)

**Branch:** `feat/observability-orchestration` · **Closes P0:** `best_of_n` in WORKFLOW_PROMPT (orchestration), Ledger in inline path (observability), distiller consumes richer events (observability)
**Risk:** medium — touches event-replay consumption and inline assembly. **Note:** the `ARGOS_WORKFLOWS` default-on flip is deferred to Batch 5b (it's an autonomy/default flip); Batch 3 only makes `best_of_n` reachable *when workflows are on*.
**Affected existing tests:** `tests/test_honesty*`/prompt-snapshot tests asserting `WORKFLOW_PROMPT` text; `tests/learning/` distiller tests (extend, don't break); app_factory/ledger tests.

### Task 3.1: Add `best_of_n` to WORKFLOW_PROMPT op list
- **Files:** `argos/core/honesty.py:206` (op enumeration currently `fan_out / pipeline / panel / loop_until / synthesize` — append `best_of_n`), Test: update prompt-snapshot test.
- **Pre-check:** confirm engine supports `best_of_n` op (`scripts/best_of_n_demo.py` + `argos/workflow/engine.py`). One-line prompt fix; makes evaluator-optimizer reachable via `propose_workflow`.

### Task 3.2: Instantiate `LedgerStore` in the inline/app_factory path
- **Files:** `argos/app_factory.py` `build_components()` (instantiate `LedgerStore`, thread into `build_loop_factory`), `argos/core/loop.py` run-yield path (intercept `ToolReceipt`/`FileDiff` → ledger append), Test: `tests/ledger/test_inline_ledger.py`
- **Acceptance:** an inline (non-daemon) run produces ledger entries so `/ledger` works in inline TUI mode (today ledger is daemon-only; grep confirms zero `LedgerStore` refs in app_factory/loop).
- **Risk note:** keep the daemon ledger path unchanged; this only adds the inline path.

### Task 3.3: Distiller/Dream consume verify+cost+phase events
- **Files:** `argos/learning/distiller.py:177-184` (today filters `kind=='code_action'` only), `argos/learning/dream.py` synthesis/ranking, Test: `tests/learning/test_distiller_metrics.py`
- **Acceptance:** `SkillCandidate`/`CandidateUnit` carry `verdict.status`, final `tokens_in/out`, `cost_usd`, `steps`; Dream can rank/prefer lower-cost solutions. Gives Loop-4 the data it currently ignores.

**Batch 3 gate:** full suite green → PR → CI → merge.

---

# Batch 4 — Resume + snapshot correctness (medium risk, bug fixes)

**Branch:** `fix/resume-and-snapshot` · **Closes P0:** real resume-from-suspended (state), persistent snapshot root + prune (state)
**Risk:** medium — daemon control-flow; the resume gap is a **correctness bug** (docstring claims it works; `server.py:630-637` only sets an asyncio.Event, never spawns a worker).
**Affected existing tests:** `tests/daemon/` resume/manager/worker tests — some may assert the current (broken) 202 behavior; update to the corrected contract.

### Task 4.1: Real resume-from-suspended
- **Files:** `argos/daemon/server.py:630-637` `_handle_resume`, `argos/daemon/manager.py:138-145` `request_resume` / `recover()`, `argos/daemon/worker.py:247,373` (restore `_step_count` from `RunCheckpoint.last_step`), Test: `tests/daemon/test_resume_suspended.py`
- **Acceptance:** resuming a `suspended` run with no live worker **spawns a new `RunWorker`** from index metadata (goal/workspace/model/approval_level) + checkpoint `last_event_seq` (SSE replay cursor) and `last_step` (step budget continues, not restart-from-0). Honest error (`409 no_worker`) when neither live worker nor snapshot exists (reboot case) instead of a lying 202.

### Task 4.2: Persistent snapshot root + prune terminal runs
- **Files:** `argos/core/snapshot.py:25` (`SNAPSHOT_ROOT` → `~/.argos/snapshots/` not `tempfile.gettempdir()`), `argos/daemon/manager.py` `recover()` (prune snapshots for terminal-state runs), Test: `tests/test_snapshot_persist.py`
- **Acceptance:** `/undo` survives a reboot for suspended runs (snapshot under `~/.argos`); terminal runs' snapshots are pruned on recover.

**Batch 4 gate:** full suite green → PR → CI → merge.

---

# Batch 5 — ⚠️ Autonomy flips + Loop-4 wiring (HIGH risk — reverses prior honest/human-on-the-loop designs)

> **DECISION RECORD (user, 2026-06-30):** Direction = **full autonomy**. These changes intentionally reverse deliberate "human-on-the-loop / honest" defaults documented in prior memories (`requires_confirmation=True`, promoted skills `enabled:false`, routing default-off, `ARGOS_WORKFLOWS` gate). Finance-class actions stay always-confirm. **Each task below lists the existing tests that lock the old behavior and must be updated.** Do not weaken the verify gate's 3-state honesty — autonomy changes *triggers and confirm-gates*, not verdict truthfulness.

**Branch(es):** `feat/loop4-wiring` (5a) then `feat/default-on-autonomy` (5b) — two PRs.

## Batch 5a — Close the self-improvement loop (Loop 4 power-on)

### Task 5a.1: Wire `runner_factory` into the daemon learning hook
- **Files:** `argos/daemon/worker.py:752-753` (stops hardcoding `runner_factory=None, tasks=[]`), build a factory spawning a sandboxed `AgentLoop` from the already-built `build_run_stack` components; `argos/learning/hook.py:144-156` (take the promote branch instead of disk-staging-only), Test: `tests/learning/test_promote_path.py`, `tests/daemon/test_worker_learning_hook.py`
- **Acceptance:** a passed run on the daemon path actually reaches `promote()` (today every passed run only deposits a candidate). Assert promote is invoked with a real runner.
- **Affected tests:** any daemon-worker test asserting `runner_factory is None` or that learning only stages candidates.

### Task 5a.2: Auto-enable promoted skills
- **Files:** `argos/learning/promotion_gate.py:184` + `argos/learning/dream.py:221` (write `enabled: true` after the A/B gate passes — the gate already enforces improvement, the extra human gate is the redundant one being removed), also fix dead code `promotion_gate.py:73` `if False else None`, Test: `tests/learning/test_auto_enable.py`
- **Acceptance:** a skill that passes the A/B promotion gate is written `enabled: true` and is recalled on the next run. Surface a TUI/log notification ("N new skills enabled").
- **Affected tests:** `tests/learning/` tests asserting promoted skills are `enabled:false`.

### Task 5a.3: Dream nightly fully autonomous
- **Files:** `argos/conductor/conductor_supervisor.py` builtin-dream order (action='dream' → call `_start_dream()` directly in the tick when `has_material()` and not running + `cross_process_busy()` guard, instead of emitting a `requires_confirmation=True` ProactiveSuggestion), Test: `tests/conductor/test_dream_autonomous.py`
- **Acceptance:** when conditions are met, Dream runs without a user confirmation POST.
- **Affected tests:** conductor tests asserting the dream order produces a confirmation-required suggestion.

## Batch 5b — Default-on switches + production maker/checker

### Task 5b.1: Routing active by default with sane built-in mapping
- **Files:** `argos/routing/config.py:35-39` (`is_active()` defaults true with a built-in default `RoutingConfig`: SIMPLE_READ→cheap tier, LONG_RUN/REFACTOR→strong tier), Test: `tests/routing/test_default_routing.py`
- **Acceptance:** out-of-the-box `load_routing()` returns an active config; per-task cheap→expensive routing works without a user-written `config.json`.
- **Affected tests:** routing tests asserting `is_active()` is False for default config.

### Task 5b.2: Workflows on by default (remove `ARGOS_WORKFLOWS` gate) + discoverability
- **Files:** `argos/core/loop.py:1167` (prompt injection) + `argos/core/loop.py:1602-1613` (host dispatch / propose_workflow swallow) — make on by default; optional `/workflows` toggle persisting to `~/.argos/.env`, Test: `tests/test_workflow_default_on.py`
- **Acceptance:** `propose_workflow` is advertised + dispatched without `ARGOS_WORKFLOWS=1`.
- **Affected tests:** every test setting/asserting `ARGOS_WORKFLOWS` — audit `tests/` for the env var and flip expectations. (Largest test-surface task; budget for it.)

### Task 5b.3: Production reviewer-LLM proposer (maker/checker model separation)
- **Files:** `argos/verify/self_test.py:60-72` (`default_test_proposer` returns None → wire a reviewer-role LLM proposer for the `ARGOS_SELF_TEST` path), pass a real `test_generator` to the production `Verifier`, Test: `tests/verify/test_reviewer_proposer.py`
- **Acceptance:** for unverifiable runs, an independent reviewer-role model proposes a candidate test (canary guard still rejects trivial tests). The maker (coder) is no longer the only checker.
- **Note:** keep the deterministic exit-code verify gate as the primary gate — this *adds* an independent proposer for the unverifiable case, it does not replace exit-code completion.

**Batch 5 gate:** full suite green (after updating all locked-behavior tests) → PR(s) → CI → merge.

---

## Self-Review

**Spec coverage (18 P0 → tasks):**
1. stagnation detection → 1.1 ✓
2. cost circuit-breaker → 1.2 ✓
3. EvalRunner budget → 1.3 ✓
4. `/goal --verify` TUI → 2.2 ✓
5. `/schedule` TUI → 2.3 ✓
6. `/watch` TUI → 2.3 ✓
7. step N/M → 2.4 ✓
8. conductor SSE subscribe → 2.5 ✓
9. best_of_n in prompt → 3.1 ✓
10. inline Ledger → 3.2 ✓
11. distiller richer events → 3.3 ✓
12. real resume → 4.1 ✓
13. persistent snapshot → 4.2 ✓
14. runner_factory wiring → 5a.1 ✓
15. skill auto-enable → 5a.2 ✓
16. Dream autonomous → 5a.3 ✓
17. routing default-on → 5b.1 ✓ (+ workflows default-on 5b.2 ✓)
18. production maker/checker → 5b.3 ✓

All 18 mapped. (The audit's 56-item full gap list incl. P1/P2 lives in the workflow output; P1/P2 are out of scope for this plan.)

**Placeholder scan:** Batch 1 has runnable code/tests. Batches 2–5 are task-granular specs (exact files + interfaces + affected tests + acceptance) per the Scope Check decision; each is expanded to red→green→commit by its implementer against live code — not "implement later" placeholders.

**Risk ordering check:** zero-behavior-flip work (1–2) ships before flips (5); each flip task names the tests that lock the old behavior. ✓

---

## Execution Handoff

Plan saved to `docs/superpowers/plans/2026-06-30-argos-loop-engineering-p0.md`.
