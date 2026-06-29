# Task 1.1 Report: Stagnation / Stuck-State Detection

## What was implemented

Added a stagnation guard in the `AgentLoop` act loop (`argos/core/loop.py`):

- **Module constant** `STAGNATION_LIMIT = 2` (consecutive identical failing steps before escalation).
- **Per-run tracking variables** `_last_fp: str | None` and `_fp_run: int` initialized alongside the other per-run guards at ~line 1313.
- **Guard logic** immediately after `yield CodeResult(...)`: on each failing (`not result.ok`) execution, compute `SHA-256(code + "\x00" + stdout)`. If the fingerprint matches the previous step, increment the run-length counter; otherwise reset it. When `_fp_run >= STAGNATION_LIMIT`, emit `Escalation(reason=..., attempts=_fp_run, last_failure="stagnant: identical (code, stdout) repeated N times")` via `self._hbus.emit` + drain, set `escalated = True`, and break.
- **Successful executions reset the counter** — identical-but-ok code (idempotent setups) is not stagnation. This was required to avoid a regression in `test_loop_user_goal.py` where `_DoneModel` emits the same successful code block 5 times before declaring done.
- Added `import hashlib` and `Escalation` to the top-level imports.

## TDD Evidence

### RED (before implementation)

```
$ /Users/zc/Projects/argos/.venv/bin/pytest tests/test_loop_stagnation.py -v -p no:cacheprovider
FAILED tests/test_loop_stagnation.py::test_identical_code_block_triggers_stagnation_escalation
1 failed, 1 passed in 2.96s
```

Positive test failed (no Escalation emitted, ran to max_steps). Negative (false-positive guard) already passed by definition since there was no guard logic.

### GREEN (after implementation)

```
$ /Users/zc/Projects/argos/.venv/bin/pytest tests/test_loop_stagnation.py -v -p no:cacheprovider
2 passed in 2.84s
```

### Full suite

```
$ /Users/zc/Projects/argos/.venv/bin/pytest -n auto --dist loadgroup -q -p no:cacheprovider
13 failed, 4357 passed, 9 skipped | coverage 82.15%
```

All 13 failures are pre-existing (confirmed by stashing changes and running the same set — identical failures on the baseline). Zero regressions introduced.

## Files changed

- `argos/core/loop.py` — added `import hashlib`, `Escalation` import, `STAGNATION_LIMIT = 2` const, two per-run variables, and the stagnation guard block (~20 lines).
- `tests/test_loop_stagnation.py` — new test file with 2 test cases.

## Self-review

**Correctness:** The guard correctly fires at the 2nd consecutive identical failing (code, stdout) pair. The `_fp_run >= STAGNATION_LIMIT` check (not `>`) means it fires when the run-length equals 2 (i.e., after seeing the same pair for the 2nd time), matching "2 consecutive repeats".

**YAGNI / simplicity:** No new classes, no new files. The fingerprint is a stdlib SHA-256; the run-length tracking is two scalars. The guard is ~20 lines total.

**Test hygiene:** Two tests — positive (fires) and negative (false-positive guard). The negative test uses a rotating model where each call has a unique step baked in, ensuring it can never falsely trigger.

**Edge case caught during implementation:** `test_loop_user_goal.py::test_user_goal_is_captured_on_passed_run` uses a `_DoneModel` that emits the identical `# act` code block 5 times (all succeeding). Initial implementation without the `not result.ok` guard incorrectly triggered stagnation on that run. Fixed by only tracking failing executions.

**Design deliberation on `not result.ok` guard:** The brief's example uses a `print(1/0)` block (which raises `ZeroDivisionError` → `ok=False`). The semantics "stuck on a failing block" is the real stagnation signal; a model deliberately repeating an idempotent successful action is a different pattern and should not be penalized.

## Concerns

None. The change is purely additive: no existing behavior changes for non-stagnating runs.

## Review fixes

Applied findings from reviewer after Task 1.1 approval.

**M1 — Canonical test imports**
Changed `tests/test_loop_stagnation.py` line 12 from `from argos.tui.events import ...` to
`from argos.protocol.events import CodeResult, Escalation, EventBus`.
`argos.tui.events` is a backward-compat shim; `argos.protocol.events` is the canonical source per CLAUDE.md.
Production `loop.py` already imports from the canonical path — tests now match.

**M2 — Local variable naming**
Renamed per-run guard variables from `_last_fp`/`_fp_run` to `last_fp`/`fp_run` in `argos/core/loop.py`.
The `_` prefix signals instance/module-private; these are plain loop-scoped locals, consistent with
`step`, `escalated`, `noaction_nudged`, etc. Updated all references (init + guard body, 6 sites total).

**M3 — Failing-path negative test**
Added `test_rotating_blocks_with_failing_sandbox_do_not_trigger_stagnation` in
`tests/test_loop_stagnation.py`. Uses `_RotatingModel` (different fingerprint each turn) with
`_FixedSandbox(ok=False)` and `max_steps=5`. Asserts no stagnation `Escalation` fires.
This exercises the accumulation path — proves different fingerprints reset the counter even when
`result.ok` is False, so the counter only grows on truly identical `(code, stdout)` pairs.

**I1 — Success-path ceiling comment**
Added a Chinese `ponytail:` comment at the `if not result.ok:` guard in `argos/core/loop.py`
naming the ceiling (成功路径以 max_steps 兜顶) and the upgrade path (扩展到 ok=True 分支).

**I2 — Escalation message wording**
Changed `f"stagnant: identical (code, stdout) repeated {fp_run} times"` to
`f"stagnant: identical (code, stdout) repeated {fp_run} consecutive times"`.
Makes it unambiguous that N counts consecutive occurrences, not total occurrences.
The stagnation marker words (`stagnant`, `identical`, `repeated`) are preserved so all existing
test assertions still match.

### Test command run

```
/Users/zc/Projects/argos/.venv/bin/pytest tests/test_loop_stagnation.py -v --no-cov -p no:cacheprovider
3 passed in 0.31s

/Users/zc/Projects/argos/.venv/bin/pytest tests/test_loop_user_goal.py -q --no-cov -p no:cacheprovider
2 passed in 0.33s
```

All 3 stagnation tests (including the new M3 test) pass. `_DoneModel` regression still green.
