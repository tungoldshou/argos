# Computer-Use Vision Loop (2b) + Coordinate Scaling (2c) — Plan

> Continuation of the computer-use functional slice. **2a (reachability) is DONE** on branch
> `feat/computer-use-functional` (computer tools are valid-identifier `computer_*` names, single canonical
> naming across registry/broker/risk/ledger/AUTO-bypass, documented under `ARGOS_COMPUTER_USE`, read_only
> scope excludes OS writes; full suite green). This plan finishes the minimal-usable slice: the model can
> actually **see** the screen (2b) and clicks **land** (2c).

**Why checkpointed here:** 2b touches mid-loop message-payload materialization (image content blocks) and
is a security-sensitive OS-control path that cannot be end-to-end verified in CI (no vision model wired into
tests, no macOS Screen Recording/Accessibility perms for the test runner). It deserves careful execution +
mocked-OS plumbing tests, not a rushed tail-of-session push.

## Mapped mechanics (verified by reading)

- `ComputerActionResult` (`perception/executor.py:73-83`) carries `ok`, `detail`, `artifact_path` (PNG path
  for screenshots), `size` (w,h via Pillow, or `(0,0)`). `_screenshot` returns all four (`executor.py:209-214`).
- Broker computer dispatch (`broker.py:357-374`) instantiates `ComputerExecutor().dispatch(ca)` and returns
  ONLY `result.detail` + exit code — **discards `artifact_path` + `size`**.
- Attachments ride as a sidecar field on a message: `_user_msg["attachments"] = list(attachments)`
  (`loop.py:~1118-1122`, currently only the FIRST user message). The model client's `payload()` materializes
  attachments → image content blocks, gated by `ModelTier.multimodal` (per CLAUDE.md; `input/attachments.py`
  has `ImageAttachment`, `from_path/from_bytes`, `to_base64`, `sniff_media_type`).
- Loop post-exec hooks live at `loop.py:~1454` (`take_receipt` → `ToolReceipt`). `exec_code` now runs in
  `asyncio.to_thread`; the computer dispatch runs on the main loop via the approval bridge, so any broker
  stash set during the bridged `request()` is readable right after `await asyncio.to_thread(...)` returns.
- Vision-capability probe: `core/vision_capability.resolve_vision_capability(tier, model, cache)` +
  `ModelTier.multimodal` (loop already uses it for first-message attachments at `loop.py:~756-770`).

## 2b — screenshot → vision loop

### Task 2b.1 — Broker stashes the screenshot artifact
**Files:** `argos/sandbox/broker.py`; test `tests/test_broker_computer_artifact.py`
- `__init__`: add `self.last_computer_artifact: tuple[str, tuple | None] | None = None`.
- In the `computer_` dispatch (broker.py:357-374), after `result = ComputerExecutor().dispatch(ca)`:
  `if result.ok and getattr(result, "artifact_path", None): self.last_computer_artifact = (result.artifact_path, getattr(result, "size", None))`
- Add `take_computer_artifact(self)` → returns + clears (mirror `take_receipt`).
- Test: a fake ComputerExecutor returning a result with `artifact_path` → after `request_blocking`/`_execute`
  for `computer_screenshot`, `take_computer_artifact()` returns the path then None. Non-screenshot actions
  leave it None.

### Task 2b.2 — Loop attaches the screenshot to the next feedback message
**Files:** `argos/core/loop.py`; test `tests/test_loop_computer_vision.py`
- After the `take_receipt` block (~1454), if `hasattr(self._broker, "take_computer_artifact")`:
  `art = self._broker.take_computer_artifact()`; stash on `self._pending_screenshot = art`.
- At the feedback-append site (`messages.append({"role":"user","content":feedback})`), if
  `self._pending_screenshot` AND tier multimodal AND vision-capable (reuse the `resolve_vision_capability`
  gate already used for first-message attachments): read the PNG bytes, build `ImageAttachment.from_path` (or
  `from_bytes`), set `_fb_msg["attachments"] = [att]` (the SAME sidecar mechanism as the first message), then
  clear `self._pending_screenshot`. On non-multimodal / not-vision-capable: do NOT attach (the model gets the
  text `detail` only) — honest degradation, no fabrication.
- **Verify** `payload()` materializes attachments on ANY message carrying the sidecar (not just the first) —
  read the model client's `payload()`; extend if it only handles the first message. (This is the one spot
  that needs confirmation before coding.)
- Test (mocked): drive a run where a fake broker's `take_computer_artifact` returns a path + a multimodal
  tier; assert the next user message gets an `attachments` entry with an `ImageAttachment`. Non-multimodal →
  no attachment. (OS capture mocked; this tests the plumbing, not real pixels.)

## 2c — coordinate scaling (model-agnostic)

### Task 2c.1 — Tell the model the coordinate space; map back if downscaled
**Files:** `argos/perception/executor.py` or the broker dispatch; `argos/core/honesty.py` (prompt note);
test `tests/test_computer_coord_scaling.py`
- Model-agnostic approach (Argos runs arbitrary vision models with unknown coordinate conventions): send the
  screenshot and **tell the model the image's pixel dimensions** in the screenshot tool result text (e.g.
  "screenshot 1512x982; give click coordinates in this pixel space"). The model returns coords in the
  image's pixel space; the host clicks at those pixels.
- Optional downscale to a configurable max long-edge (default e.g. 1280 to bound tokens): if downscaled by
  factor `s`, record `s`, and map model-returned `(x,y)` → `(x/s, y/s)` before `ComputerExecutor` clicks.
  Implement the mapping as a **pure function** `scale_coords(model_xy, sent_dims, screen_dims) -> screen_xy`
  and unit-test the math (no real screen needed).
- Note in the prompt (`COMPUTER_USE_PROMPT`): "coordinates are in the most recent screenshot's pixel space."
- **Retina/DPR**: macOS `screencapture` produces 2x pixel images on Retina; logical click coords differ from
  pixel coords. Full DPR calibration needs a real screen (can't verify in CI) — implement the scale-factor
  pathway + document that DPR calibration is validated manually on first real use.

## Out of scope / honesty
- Real end-to-end "agent sees screen and clicks accurately" is verified by the USER on real hardware
  (ARGOS_COMPUTER_USE=1 + a vision model + Screen Recording/Accessibility perms). CI verifies plumbing only.
- 2d (GUI verify primitive — screenshot-and-evaluate / expected-text-on-screen, à la `propose_dom_verify`)
  is the NEXT slice after this — extends the verify moat to GUI work.

## Merge note
2a is currently UNMERGED on `feat/computer-use-functional` because its prompt doc promises visual feedback
("截图会作为图像回给你看") that only becomes true once 2b lands — merge 2a+2b+2c together so the prompt's
promise is honest. (Until then, do not merge 2a alone.)
