# 2d — GUI Verify Primitive (`propose_gui_verify`) Plan

Extends the verify hard-gate to computer-use/GUI work: a GUI task gets an **independent machine verdict**
(screenshot + OCR shows the expected on-screen text) instead of the model's self-report. Mirrors the
existing `propose_dom_verify` / `DomProber` lane (L3).

## DONE (this session)
- **`argos/verify/gui_probe.py` — `GuiProber` + `GuiProbeResult`** (committed). Screenshot (via injected
  `ComputerExecutor`) → **OCR (pytesseract, independent/deterministic)** → three-state:
  `expected_text` in OCR → passed; absent → failed; OCR-unavailable / screenshot-fail / no-executor /
  exception → **unverifiable** (honest, never fake-passed). `tests/test_gui_probe.py` (7 tests, all green).
- **Honesty design locked**: the verifier is OCR (independent of the agent's model), **NOT** the same model
  asked "did you succeed?" — that would be circular self-judgment and hollow the moat.

## REMAINING WIRING (mirror `propose_dom_verify`, the proven L3 lane)

### Task 1 — registration stub + tool catalog
- `argos/tools/__init__.py`: add `_propose_gui_verify_pure(expected_text: str) -> str` (mirrors
  `_propose_dom_verify_pure`, ~line 287) returning a registration receipt; add `"propose_gui_verify"` to
  `_pure()` (it's a host-parsed declaration桩, like propose_verify/propose_dom_verify — stays pure) and to
  `ALL_TOOL_NAMES`.
- `argos/capability/builtins.py`: register `propose_gui_verify` capability (risk=low, reversible=True,
  dispatch=None) — keeps `ALL_TOOL_NAMES == registry.names()` (the one-manifest rule) + count honest.
- Update the count assertions in `tests/test_tools_namespace.py` + `tests/test_lsp_error.py`
  (`len(ALL_TOOL_NAMES)` 30 → 31) + `tests/capability/test_one_manifest_rule.py` count.

### Task 2 — loop parses the declaration + runs the prober at verify time
- `argos/core/loop.py`: study how `propose_dom_verify` is (a) parsed from the model's code text (the regex /
  `extract_*` near where `propose_verify` is parsed) and (b) executed in the verify phase (the
  `_run_dom_probe`-style method ~732-743 that yields `VerifyVerdict`, and the strategy ladder
  `_pick_strategy_cmd`). Add a parallel `propose_gui_verify(expected_text=...)` parse → store the declared
  expected_text → at verify time, if a GUI declaration exists and `self._gui_prober` is set, call
  `self._gui_prober.probe(expected_text)` → map `GuiProbeResult` to `Verdict`:
  found → `Verdict.passed`; `error==""` & not found → `Verdict.failed`; error non-empty → `Verdict.unverifiable`
  (mirror the DomProber→Verdict mapping at loop.py:~720-743).
- `AgentLoop.__init__`: accept `gui_prober=None` (like `dom_prober=None`).

### Task 3 — app_factory injects the prober
- `argos/app_factory.py`: construct `GuiProber(ComputerExecutor())` (or the per-run executor) and pass
  `gui_prober=` into the loop (mirror the `dom_prober` injection ~245-261). `None` when computer-use is off →
  GUI strategy simply skipped (honest, like DomProber when browser=None).

### Task 4 — prompt note + tests + full suite
- `argos/core/honesty.py` `COMPUTER_USE_PROMPT`: add a line — "做完 GUI 操作后,用
  `propose_gui_verify(expected_text='...')` 声明屏上应出现的文本,host 会独立截图+OCR 判定(三态);
  看不清/无 OCR → unverifiable,别假装成功。"
- Integration test (mock the prober): a run that declares `propose_gui_verify` → verify phase yields a
  `VerifyVerdict` from the GuiProber (passed/failed/unverifiable). Full suite green + coverage ≥ 80%.

## Out of scope / honesty boundary
- Real OCR accuracy is user-side (needs `pytesseract` + `tesseract` installed + a real screen). CI verifies
  the prober's three-state logic + the lane wiring with mocked OCR/screenshot — same boundary as computer-use
  and the DOM lane.
- No model-as-judge (circular). OCR only. If OCR is unavailable, the honest verdict is `unverifiable`, which
  bounces back to the agent exactly like a missing verify_cmd.
