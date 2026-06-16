# Sync-Bridge Interactive Approval — Design + Delivery Note

_Date: 2026-06-15 · Status: implemented, verified, merged-pending_

Phase-2 foundation (the prerequisite surfaced while designing computer-use reachability): sandbox-issued
tool calls must go through the **full approval gate**, not the approval-skipping `execute_sync` bridge.
Closes the 2026-06-14 audit's #1 finding (governance hollow on the daemon main path) and unblocks safe
computer use. See `2026-06-15-codex-like-trust-agent-research.md`.

## 1. Problem

The sandbox child issues tool calls (`run_command`, `web_*`, `browser_*`, `mcp_call`, `computer.*`) over a
JSON-RPC `broker_call`. The host handled them via `broker_handler → CapabilityBroker.execute_sync`, which —
by its own docstring — **skips ② interactive approval** because `exec_code` runs synchronously and blocks
the event loop (`loop.py` called `self._sandbox.exec_code(code)` with no `await`), so a mid-exec
`await gate.request(...)` could never get a UI response. Result: every sandbox tool call ran with egress +
receipt but **no interactive approval and no evaluator hard-rules** — the governance moat was structurally
absent on the real path. `run_command`'s "never silently run shell" (`_FORCE_CONFIRM`) was unenforced from
the sandbox; `computer.*` (high-risk, irreversible) would run ungoverned once made reachable.

## 2. Mechanism (the one move)

Free the event loop during sandbox execution so the gate can prompt:

1. **Thread `exec_code`** — `loop.py` now does `result = await asyncio.to_thread(self._sandbox.exec_code, code)`.
   The model's Python + the blocking child I/O run off-loop; the event loop stays free. (One sandbox
   subprocess per run, serial exec — `to_thread` adds no concurrency.)
2. **Inject the host loop** — `AgentLoop.run()` captures `asyncio.get_running_loop()` at run start and calls
   `broker.set_host_loop(loop)` (cleared to `None` in `finally`). Guarded by `hasattr` so stub brokers in
   tests are tolerated.
3. **Bridge in `broker_handler`** — now calls `broker.request_blocking(action, args)`. From the worker
   thread it does `asyncio.run_coroutine_threadsafe(self.request(action, args), host_loop).result(timeout)`:
   `request()` runs on the now-free main loop with the **full pipeline** — egress → **gate.request
   (interactive approval)** → execute → HMAC receipt. The worker thread blocks on `.result()` until the
   main loop settles it.
4. **Reuse the gate's existing cross-loop wake** — `gate.respond` (TUI) → `_settle` →
   `p.loop.call_soon_threadsafe(_resolve, …)` (`approval.py:366`) resolves the future on its own loop. This
   machinery already existed (built for the 2026-06-02 approval gate); the bridge reuses it.

## 3. Decisions

- **No-host-loop → fall back to `execute_sync`** (headless / old tests / no interactive UI). The bridge
  improves the real path; the fallback preserves current behavior → zero regression. (A "no-loop ⇒
  fail-closed deny" alternative would break legitimate headless automation.)
- **Spike-first.** Per the 2026-06-02 lesson ("async integration: spike for ground truth first"), the first
  artifact was a spike proving `run_coroutine_threadsafe(gate.request)` from a `to_thread` worker, resolved
  by `gate.respond` on the main loop, returns approve/deny with no deadlock (`tests/test_approval_bridge_spike.py`).
- **Bridge timeout 300s** (`gate.request` self-times-out at 60s → deny; 300s is a safe upper bound against a
  wedged loop). Bridge exception/timeout → fail-closed refusal string (model sees it, re-routes; never
  silently runs).

## 4. Files

| File | Change |
|---|---|
| `argos/sandbox/broker.py` | `import asyncio`; `__init__` adds `_host_loop=None`, `_bridge_timeout=300.0`; new `set_host_loop()` + `request_blocking()` (bridge with execute_sync fallback). |
| `argos/app_factory.py` | `broker_handler` now returns `broker.request_blocking(action, args)`. |
| `argos/core/loop.py` | `run()` sets/clears `broker.set_host_loop` (hasattr-guarded); act phase `exec_code` → `await asyncio.to_thread(...)`. |
| `tests/test_approval_bridge_spike.py` | spike: cross-thread gate wake (approve/deny). |
| `tests/test_broker_request_blocking.py` | bridge: interactive approve → executes+receipt; deny → refusal+no receipt; no-loop → execute_sync fallback. |

## 5. Behavior change + verification

Sandbox tool calls now hit the gate: under `AUTO` they auto-approve (no pending) except `run_command`
(`_FORCE_CONFIRM` → prompts); under `CONFIRM` they prompt per policy (soft-allow/session rules still
short-circuit). The TUI's existing `gate.respond` wiring drives it; tests simulate the responder.

Verified: bridge unit tests + spike (7 passed); real-bridge suites (e2e + workflow + sandbox + loop) **150
passed, no hangs** (AUTO fixtures don't block); **full suite 4120 passed, coverage 81.55%**. The only
failures are the known pre-existing Docker test and a parallel-flake of the slow real-binary version test
(passes in isolation; causally unrelated — this change touches no version/binary code).

## 6. Out of scope (next)

- `write_file`/`edit_file` → broker (item 3): still `_pure` (not brokered); the bridge applies to the
  already-gated tools. When item 3 lands, file writes get the same interactive approval for free.
- Synchronous evaluator hard-rules on the no-loop fallback path (item-3-style): the fallback still skips
  `evaluate()`; acceptable (zero regression, and the real path now has full approval).
- `_execute` runs on the main loop (blocks it during the actual command, *after* approval). The loop is now
  free *during exec* (model code + child I/O run off-loop) but still blocks for the command's own duration —
  so a slow `run_command` on the daemon's shared loop still stalls other runs for that command's duration.
  Threading `_execute` too is the natural next optimization (matters most when computer-use, which can be
  slow, lands).
- Computer-use reachability + vision loop + coordinate scaling (the original Phase-2 slice) — now unblocked.

## 7. Adversarial review + fixes (opus, 2026-06-15)

Verdict **SHIP** — deadlock-freedom validated end-to-end (real loop + concurrent responder: approve
executes + receipt, deny refuses, no deadlock). Two Important cancel-path defects found and **fixed**:

- **Slow teardown on cancel-mid-approval.** A cancelled run leaves the child parked mid-`broker_call`, so
  `SeatbeltExecutor.close()`'s `proc.wait` always timed out → 5s synchronous stall (stalling *all* concurrent
  daemon runs on the shared loop). Fix: reduced `proc.wait` timeout 5s → 1s (`executor.py`). (Threading
  `close()` off-loop was considered but rejected — `await` in a generator `finally` under cancellation is
  fragile; bounding the timeout is the safe fix.)
- **Orphaned approval leak.** `run_coroutine_threadsafe(request())` is an independent task that doesn't
  cancel with the run, so an in-flight approval stayed `pending` until its 60s timeout. Fix: `run()`'s
  `finally` now calls `broker.gate.cancel_all()` (existing machinery) to settle orphans immediately
  (per-run gate → doesn't touch concurrent runs). Verified by `test_cancel_mid_approval_settles_orphan`.

Tests added beyond the unit/spike layer: `tests/e2e/test_approval_bridge_e2e.py` (slow) drives the **real
executor → `broker_call` → bridge → interactive approval** path (approve-executes + cancel-settles-orphan),
via a new `gated=True` option on the `build_real_loop` fixture; plus an AUTO-force-confirm unit test. Full
suite: 4124 passed, coverage 81.59% (only the known pre-existing Docker failure).
