# Argos TUI Design Implementation — Design

_Date: 2026-06-14 · Status: proposed · Author: implementation pairing session_

Detailed, field-verified widget specs live in the companion appendix:
[`2026-06-14-tui-widget-specs-appendix.md`](./2026-06-14-tui-widget-specs-appendix.md).
This document is the architecture, scope, decisions, and plan; the appendix is the verbatim spec.

## 1. Goal

Implement the "黑曜石之眼 / Obsidian Eye" TUI design handoff (`design_handoff_argos_tui`,
v3→v4, 16 screens) faithfully in the existing Python + Textual TUI under `argos/tui/`. The
handoff is HTML/CSS/JS prototypes; the task is to **recreate the visual hierarchy and
interaction semantics** in Textual using `theme.py` tokens — not to port HTML.

"Faithful" for a terminal means fidelity of **glyphs, colour tokens, depth layering, alignment,
and interaction semantics**, not pixel/CSS reproduction (handoff README §Fidelity).

## 2. Context — what exists vs the gap

Already in place (no work needed):
- `argos/tui/theme.py` `argos-night` tokens — **exact match** to the design token table.
- All slash commands parse + dispatch (`commands.py`, `app.py::_dispatch_slash`).
- Backends for every feature: `intent/`, `permissions/trust_dial.py`, `ledger/`, `routing/`,
  `conductor/`, `learning/dream.py`, `perception/`.
- Proper widgets for screens **01–08** (splash, inline_choice, verdict_badge, status_bar,
  tab_strip, top_bar, transcript, code_action, thinking, prompt, activity_panel, workflow_panel,
  diff_view).

The gap:
- Screens **09–16** (Intent, Trust Dial, Conductor, Dream, Ledger, Routing, Computer-use) render
  as **plain text** via `log.append_line(...)`. The design wants styled cards/tables/badges.
- Screens **01–08** widgets have **32 audited drifts** (2 high / 12 medium / 18 low) vs the
  visual spec.

## 3. Architecture decision

**One widget per capability panel; decision cards subclass/reuse `InlineChoice`.**

Rejected alternatives: (B) inline render helpers in `app.py` — doesn't match house style, hard to
unit-test, no CSS depth; (C) one multi-mode mega-widget — violates small-file / single-purpose.

Each change is mechanical at the call site: the handler in `app.py` stops calling
`log.append_line(<plain text>)` and instead mounts the dedicated widget (display widgets via
`transcript.mount_block`, decision cards via the existing `_enqueue_choice` FIFO).

House-style invariants every new widget obeys (from `inline_choice.py` / `status_bar.py`):
- Base class: `Static` for single-block displays (tables, report cards), subclass `InlineChoice`
  (which is a `Vertical`) for decision cards.
- `DEFAULT_CSS` references colours **only** via `$token`. Rich `Text` styling uses module-level
  hex constants annotated with the token name (`_COL_EYE = "#D9A85C"  # $eye`).
- **`markup=False`** on every Static that carries model/tool/user/verify text (honesty: bodies
  contain `[...]`; markup parsing crashes the TUI — tested invariant `test_tui_markup_safety`).
- Card rhythm: `height: auto; margin: 0 0 1 0; padding: 1 2;`. Risk encoded by border-left token.
- Decision cards self-destruct to a one-line `◕ …` summary and return focus to `#prompt`.

## 4. Data-source decision (confirmed with user)

Widgets render **real backend fields/events**, not the prototype's simplified demo data. The
prototype is a preview; three of its shortcuts diverge from source and we follow **source**:

1. Ledger: real `summary_human` / `reversible` / `undo_state`, risk `"medium"` (not demo
   `sum`/`rev`/`undo`, `"med"`).
2. Routing tiers are **free-form profile names read from `config.models`** — NOT a fixed
   cheap/default/strong enum. Colour the known names (cheap `$cyan` / default `$ink` /
   strong `$ink-bright`) when present; render any other tier name in `$ink` (graceful fallback).
3. Dream is **6 stages** (`scan→cluster→synthesize→promote→memory→done`), not the demo's 4;
   `DreamReport` has a 7th field `report_path`.

Also follow source where README/prototype disagree: `escalation_warning(from_level, to_level)`
param names; `ProactiveSuggestionEvent.suggestion_id` vs dataclass `.id`.

Confirmed out of scope: aligning `--demo` / `fakeloop.py` to the prototype's scripted demo
storyline. New widgets wire into the **real** run/command paths only.

## 5. The new widgets (screens 09–16)

Full per-widget contract (layout, exact strings, tokens, glyphs, behavior, wiring, honesty) is in
the appendix Part B. Summary:

| # | Widget (new file under `argos/tui/widgets/`) | Base | Visual contract anchor | Wires into |
|---|---|---|---|---|
| 09 | `intent_card_choice.py::IntentCardChoice` | subclass `InlineChoice` | left-edge **gold `$eye`** (distinguishes from orange approval cards), title `◉ 意图确认 — 执行前回显`, 4-char `$ink-faint` label grid, risk pills (border `$unverif-deep` / text `$unverif`), `? ` questions `$plan`, options 1/2/3 | `_handle_intent_confirm` |
| 10 | `trust_dial.py::TrustDial` | `Static` | 5-row dial (3-col: marker/label/desc), current row `▸ $eye` + `$raise` bg, L4 `⏻ 红灯 $fail`, dashed divider + HARD RULES three `$fail`. Escalation card already uses `InlineChoice` | `_trust_cmd` (status branch) |
| 11 | _audit only_ — existing `workflow_panel.py` + wired `InlineChoice` approval | `Static` | per-glyph colour, bold header, dim synthesis/notes | `_handle_workflow_proposed` |
| 12 | `orders_panel.py::OrdersPanel` + `InlineChoice.conductor` variant | `Static` / `InlineChoice` | orders table (`⏱ schedule` / `⊙ file_trigger`); suggestion card left-edge `$plan`, `◔` title, `escape_value='dismiss'` | `_orders_cmd`, `_on_proactive_suggestion`, `_confirm/_dismiss` |
| 13 | `dream_report.py::DreamReportCard` | `Static` | 6-stage stream (`◔/◉/❂/…/◕`), report card: promoted `$pass` / rejected `$fail` / skipped `$unverif` | `_dream_cmd`, `DreamReportEvent` |
| 14 | `ledger_table.py::LedgerTable` | `Static` | 5-col grid (seq/人话/风险/可逆/撤销); reversible 3-state + undo 3-state colours | `_ledger_cmd`, `_undo` |
| 15 | `routing_table.py::RoutingTable` | `Static` | 8-category → tier table; tier colours (dynamic), `force confirm` `$unverif` | `_routing_cmd` |
| 16 | `hard_confirm_card.py::HardConfirmCard` | subclass `InlineChoice` | left-edge **`$fail`**, title `⛔ 计算机控制 · 硬确认 [high · 不可逆]`, governance line + footer, options 1 once / 4 deny; **always high+irreversible, immune to Trust Dial** | computer-use action path; StatusBar blocked |

## 6. Audit fixes for existing widgets (screens 01–08)

32 findings (appendix Part C). Highlights:

- **HIGH (2)**:
  - `thinking.py` renders `◓` during its eye-blink — `◓` is reserved for **blocked** (glyph/honesty
    collision). Use a non-colliding blink frame.
  - `activity_panel.py` Verdict section is not three-state coloured (passed `$pass` / failed `$fail`
    / unverifiable `$unverif`) — honesty law.
- **MEDIUM (12)**: splash per-segment tokens (eye `$eye-glow`, LIVE `$pass`); InlineChoice plan-mode
  left-edge + title `$plan`; VerdictBadge self-verified italic; TabStrip bottom border; TopBar Trust
  pill + blocked `◓` mapping; PromptArea slash selected-row `$raise-2` bg; ActivityPanel cache
  sparkline `$cyan` + ctx bar `$eye`/`$ink-faint`; WorkflowPanel per-glyph colour; DiffView via tokens.
- **LOW (18)**: strings, `k` abbreviation, dim styling, etc.

Stale-mock notes (e.g. splash brand word `百眼智能体` is current, mock's `终端超级智能体` is stale) are
**not** fixed — code is correct.

## 7. Cross-cutting honesty invariants (must hold in every widget)

- `error`/`failed` never renders as success; `$pass-weak` (self-verified) ≠ `$pass` (E4 firewall).
- Risk colours: low `$ink-dim` · medium `$unverif` · high `$fail`.
- `confirmation_required` / `requires_confirmation` gate execution; `suggest_escalation` never
  auto-escalates (≥5 same-kind approvals only suggests, ≤L3).
- `computer.*` always `risk=high` + irreversible, CONFIRM regardless of Trust Dial.
- Empty state shows zeros / honest "no data", never fabricated content.
- `markup=False` everywhere user/model/tool text is shown.

## 8. Testing strategy

Per new widget, a unit test under `tests/tui/`:
- Render-snapshot assertions on the load-bearing glyphs + token segments (build the widget, inspect
  its `render()`/composed `Static` text/Rich `Text` spans).
- `markup=False` safety (feed a body containing `[...]`, assert no crash).
- Honesty invariants (error→失败, weak≠strong, `requires_confirmation` True, computer.* high).
For audit fixes, add a regression assertion pinning the corrected glyph/token/string.
Gate: full `uv run pytest` keeps the 80% coverage floor. Mark any real-subprocess test `slow`.

## 9. Implementation sequencing (TDD batches)

Each item: RED test → GREEN widget → wire `app.py` handler → full regression.

1. **Governance-critical cards**: 16 HardConfirm, 09 Intent, 10 TrustDial.
2. **Read-only tables/cards**: 14 Ledger, 15 Routing, 12 Orders+suggestion, 13 Dream.
3. **Audit 01–08**: 2 HIGH first, then MEDIUM, then LOW; 11 WorkflowPanel polish here.

## 10. Out of scope (YAGNI)

- Porting prototype HTML/CSS or `support.js`.
- Aligning `--demo`/`fakeloop` to the prototype storyline.
- The 5-shape workflow legend (a static doc artifact, not an interactive widget).
- Re-theming; tokens already match.

## 11. Files

- **New**: `argos/tui/widgets/{intent_card_choice,trust_dial,orders_panel,dream_report,ledger_table,routing_table,hard_confirm_card}.py` + matching tests under `tests/tui/`.
- **Edited**: `argos/tui/app.py` (rewire ~10 handlers); existing widgets per audit
  (`thinking,activity_panel,splash,inline_choice,verdict_badge,tab_strip,top_bar,prompt,workflow_panel,diff_view`).
- **Unchanged**: `theme.py`, `commands.py`, all backends.

## 12. Decision log

- Scope: all 8 new panels (09–16) + audit/fix existing 01–08. _(user)_
- Data source: real backend fields over prototype demo shortcuts. _(user)_
- Demo: new widgets wire to real paths only; no fakeloop alignment. _(user)_
- Architecture: per-panel widget, reuse `InlineChoice` for decision cards. _(recommended)_
- Computer-use trust policy: kept existing evaluator behaviour — only financial / payment / OTP
  `computer.*` is force-confirmed; plain `computer.*` (click/screenshot/scroll) is allowed under
  AUTO / Trust-Dial L4. Deliberate, documented deviation from README §16 ("all `computer.*`
  confirm regardless of Trust Dial") for practicality — computer use is opt-in
  (`ARGOS_COMPUTER_USE=1`) and the evaluator/tests intentionally encode this stance. _(user)_
- TUI fail-safe (added, independent of the above): a financial-domain force-ask `computer.*`
  is never silently bypassed by `_handle_approval`'s AUTO short-circuit — it always mounts
  `HardConfirmCard`. _(adversarial review finding)_
