# Argos TUI Design — Implementation Reference (Appendix)

> Auto-generated from the read-only design-analysis workflow (wf_0048261a-a94) on 2026-06-14.
> Source design bundle: `design_handoff_argos_tui` (黑曜石之眼 / Obsidian Eye, v3→v4).
> This appendix backs `2026-06-14-tui-design-implementation-design.md`. It is the verbatim,
> field-verified spec each widget implements. Colours: CSS uses `$token`; Rich Text uses the
> hex constant equal to that token (Rich cannot resolve `$token`). NEVER hardcode hex in CSS.


---

## Part A — Verified backend data shapes

Confirmed. Here is the exact backend data shape extraction.

---

## 1. Intent

**`IntentCard`** — `from argos.intent import IntentCard` (defined `argos/intent/card.py`). `@dataclass(frozen=True, slots=True)`. Field order matters (slots, defaults last):

| field | type | default |
|---|---|---|
| `utterance` | `str` | (required) |
| `goal` | `str` | (required) |
| `deliverable` | `str` | `""` |
| `constraints` | `tuple[str, ...]` | `field(default_factory=tuple)` |
| `not_doing` | `tuple[str, ...]` | `field(default_factory=tuple)` |
| `risk_flags` | `tuple[str, ...]` | `field(default_factory=tuple)` |
| `confirmation_required` | `bool` | `False` |
| `questions` | `tuple[str, ...]` | `field(default_factory=tuple)` |

All 8 prompt-listed fields exist with exact names/types. No `to_dict`/`from_dict` on the card itself — serialization is via `dataclasses.asdict()` (see event below).

**`IntentConfirmRequest`** — `from argos.protocol.events import IntentConfirmRequest` (`argos/protocol/events.py:252`). `@dataclass(frozen=True, slots=True)`. Class attr `kind = "intent_confirm_request"` (not a field). Fields:
- `call_id: str` — 12 hex, pairs with `IntentConfirmResponse.call_id`
- `confirmation_text: str` — from `IntentEngine.render_confirmation()`
- `risk_flags: tuple[str, ...]` — copy of `IntentCard.risk_flags`
- `card_json: dict` — `IntentCard` `asdict()` serialization

**`IntentConfirmResponse`** (client→kernel, `events.py:272`): `kind = "intent_confirm_response"`; `call_id: str`, `confirmed: bool`, `revised_goal: str | None = None`.

---

## 2. Trust Dial — `argos/permissions/trust_dial.py`

**`TrustLevel(enum.IntEnum)`** — int values are load-bearing (escalation compares `int(...)`):

| member | int | `.label_human` | `.description` (truncated) |
|---|---|---|---|
| `L0_EVERY_STEP` | `0` | "每一步都问我" | "最保守模式。每一个工具调用都会暂停等你确认，包括只读操作。…" |
| `L1_DANGEROUS_ONLY` | `1` | "只有危险操作才问" | "只对高风险操作（删除文件、执行 shell 命令、网络请求等）暂停…" |
| `L2_IRREVERSIBLE_ONLY` | `2` | "只有不可逆操作才问" | "只对不可逆操作暂停等确认（依赖 P2 能力 manifest 的 reversible 字段）…" |
| `L3_SESSION_TRUSTED` | `3` | "同类操作批准后本会话放行" | "同一类操作在本次会话内批准一次后自动放行…" |
| `L4_AUTONOMOUS` | `4` | "全自治（HARD RULES 仍拦）" | "全自治模式：所有工具调用自动放行…HARD RULES…仍然强制拦截…" |

Note the `.label_human` vs `.description` tables for L1/L2 differ slightly in wording from the enum-comment text — use the `_HUMAN_LABELS` / `_DESCRIPTIONS` dicts (exposed via the two properties), not the inline comments.

**Functions / types (module-level):**
- `escalation_warning(from_level: TrustLevel, to_level: TrustLevel) -> str` — note params are named `from_level`/`to_level`, NOT `cur`/`target`. Returns `""` for downgrade (`int(to) <= int(from)`), non-empty `⚠ …` warning for upgrade; L4 gets a stronger special-case string.
- `to_approval_semantics(level: TrustLevel) -> dict[str, Any]` — returns dict with keys: `hard_rules_immune` (always `True`), `approval_level` (str: one of `"observe"`/`"confirm"`/`"accept_edits"`/`"auto"` — maps to `ApprovalLevel` values), `description` (str), `reversible_check` (bool, `True` only for L2), `ask_readonly` (bool, `True` only for L0). L4 additionally sets `show_yolo_indicator: True`. (L0 ApprovalLevel maps to `confirm` + `ask_readonly`, not `observe`.)
- `suggest_escalation(history: list[dict[str, Any]], *, current_level: TrustLevel = TrustLevel.L0_EVERY_STEP, threshold: int = 5) -> EscalationSuggestion | None` — never auto-escalates; never suggests above L3; needs `threshold` (default `_SUGGEST_THRESHOLD = 5`) consecutive `"approved"` of same `kind`. History dict shape: `{"action": str, "decision": "approved"|"denied"|"asked", "kind": optional str}`.
- `hard_rules_immune() -> bool` — always returns `True` (no false branch).
- **`EscalationSuggestion`** `@dataclass(frozen=True, slots=True)`: `from_level: TrustLevel`, `suggested_level: TrustLevel`, `warning: str` (asserted non-empty in `__post_init__`), `reason: str`, `trigger_count: int`.

---

## 3. Ledger — `argos/ledger/`

**`LedgerEntry`** — `from argos.ledger.entry import LedgerEntry, Reversible, UndoState` (`entry.py`). `@dataclass(frozen=True, slots=True)`. Literal type aliases:
- `Reversible = Literal["yes", "no", "unknown"]`
- `UndoState = Literal["available", "done", "impossible"]`

Fields (exact order):

| field | type | notes |
|---|---|---|
| `ts` | `float` | from `Receipt.ts` |
| `run_id` | `str` | |
| `seq` | `int` | per-run, from 1 |
| `action` | `str` | |
| `summary_human` | `str` | template-generated |
| `risk` | `str` | `"low"`/`"medium"`/`"high"` (plain `str`, not a Literal) |
| `reversible` | `Reversible` | `"yes"`/`"no"`/`"unknown"` |
| `undo_token` | `str \| None` | abs tar path when reversible=yes else None |
| `receipt_sig` | `str` | `Receipt.sig[:16]` truncated |
| `undo_state` | `UndoState` | `"available"`/`"done"`/`"impossible"` |

Methods: `to_dict() -> dict`, `from_dict(d) -> LedgerEntry` (static), `with_undo_state(state: UndoState) -> LedgerEntry`.

**`LedgerStore`** — `from argos.ledger.store import LedgerStore` (`store.py`). `__init__(self, ledger_dir: Path | None = None)`; default root `~/.argos/ledger/<run_id>.jsonl`. Methods:
- `replay(self, run_id: str) -> list[LedgerEntry]` — sorted by `(seq, ts)`; missing file → `[]`.
- `append(entry)`, `undo_complete(run_id) -> bool` (writes an `undo_done` marker, `seq=0`), `is_undo_done(run_id) -> bool`, `get_entry(run_id, seq) -> LedgerEntry | None`, `mark_entry_done(run_id, seq) -> bool`.

**`summarize`** — `from argos.ledger.summary import summarize`; signature `summarize(action: str, args: dict) -> str` (file is `summary.py`, function name is `summarize`, NOT `summary`). Deterministic Chinese templates per action family; unknown → `f"执行了 {action}"`. Helpers `_short_path`, `_short_url` are private.

**`build_entry`** — `from argos.ledger.builder import build_entry`; keyword-only `build_entry(*, receipt, run_id, seq, args=None, undo_token=None) -> LedgerEntry`. Derives `risk` (irreversible→high, shell→medium, else low) and `reversible` from action name + token presence.

**`LedgerEntryEvent`** (`events.py:200`, `kind = "ledger_entry"`) — the broadcast subset: `ts`, `run_id`, `seq`, `action`, `summary_human`, `risk`, `reversible`, `undo_state`. **Deliberately omits `receipt_sig` and `undo_token`** (internal audit only). `reversible`/`risk`/`undo_state` are plain `str` here.

---

## 4. Routing — `argos/routing/`

**8 categories — `TaskCategory(enum.Enum)`** (`categorizer.py`), member → `.value`:
`FILE_EDIT="file_edit"`, `REFACTOR="refactor"`, `TEST_WRITE="test_write"`, `VERIFY="verify"`, `PLAN="plan"`, `LONG_RUN="long_run"`, `AUTO_CAPTURE="auto_capture"`, `SIMPLE_READ="simple_read"`. Entry point `categorize(*, tool=None, code=None, phase="act", step=0) -> TaskCategory`; `LONG_RUN_THRESHOLD = 20`; never raises (falls back to `SIMPLE_READ`).

**Tier names — NOT an enum.** There is no `cheap`/`default`/`strong` enum anywhere. Tiers are free-form strings keyed by the user's `config.models` profile names. The only hardcoded constant is the default tier string `"default"` (`RoutingConfig.default = "default"`). **Flag:** the README config example (README.md:530–538) uses `"cheap"`/`"strong"` — these are illustrative user profile names, not source-enforced tier identifiers. A TUI must read tier names dynamically from config, not assume a cheap/default/strong triplet.

**`RouteDecision`** — `from argos.routing.resolver import RouteDecision` `@dataclass(frozen=True, slots=True)`: `category: TaskCategory`, `tool: str | None`, `tier: str`, `source: str` (`"by_tool"`/`"by_category"`/`"default"`), `step: int = 0`.

**`resolve(config, *, category, tool) -> RouteDecision`** — 3-layer priority: `by_tool` > `by_category` > `default`.

**`ModelRouter`** (`router.py`): `__init__(self, *, routing: RoutingConfig, client_factory: ClientFactory)`; `select(self, *, category, tool, step=0) -> tuple[ModelClient, RouteDecision]` (lazy client construction, thread-locked); `history() -> list[RouteDecision]` (deque maxlen 10, run-scoped, not persisted); `.routing` property.

**`RoutingConfig`** (`config.py`) `@dataclass(frozen=True, slots=True)`: `default: str = "default"`, `by_category: dict[str, str]`, `by_tool: dict[str, str]`, `tier_force_confirm: list[str]`; method `is_force_confirm(tier) -> bool`.

**Config read/set:** `load_routing(config_dir: Path) -> RoutingConfig` (reads `<dir>/config.json` `routing` block; missing → safe default; validates category keys against the 8 enum values, fail-closed). `set_category(config_dir, category: TaskCategory, tier: str) -> RoutingConfig` — atomic `.tmp` + `os.replace`; `_validate_tier` rejects a tier not present in `config.models`.

**Effort (`effort.py`):** `EffortLevel(enum.Enum)` = `LOW="low"`, `MEDIUM="medium"`, `HIGH="high"`. `EffortSettings(max_steps: int, approval_level: ApprovalLevel)`. `EFFORT_PRESETS`: LOW→`max_steps=8, AUTO`; MEDIUM→`40, CONFIRM`; HIGH→`80, CONFIRM`. `effort_settings(level) -> EffortSettings`.

---

## 5. Conductor — `argos/conductor/`

**`ProactiveSuggestion`** — `from argos.conductor.proposals import ProactiveSuggestion` `@dataclass(frozen=True, slots=True)`:
- `id: str`, `order_id: str`, `goal: str`, `reason_human: str`, `suggested_at: float`, `requires_confirmation: bool` (asserted `True` in `__post_init__` — constructing `False` raises `ValueError`), `action: OrderAction = "run"`.
- `action` is `Literal["run", "dream"]` (imported as `OrderAction` from `orders.py`); `__post_init__` rejects other values.
- Note: `requires_confirmation` is a **required positional field here** (no default), unlike the event where it defaults to `True`.
- Factory: `propose(order, context, *, clock=None) -> ProactiveSuggestion`.

**`StandingOrder`** — `from argos.conductor.orders import StandingOrder, OrderKind, OrderAction` `@dataclass(frozen=True, slots=True)`:
- `id: str`, `utterance: str`, `kind: OrderKind`, `schedule: str | None`, `trigger_glob: str | None`, `goal_template: str`, `enabled: bool`, `created_at: float`, `last_fired_at: float | None`, `action: OrderAction = "run"`.
- **Trigger kinds:** `OrderKind = Literal["schedule", "file_trigger"]`. `schedule` requires `schedule` field; `file_trigger` requires `trigger_glob` (enforced in `__post_init__`).
- `OrderAction = Literal["run", "dream"]`.
- Methods: `to_dict`, `from_dict` (static; tolerates missing `action`→`"run"`), `with_last_fired(ts)`, `with_enabled(enabled)`.
- `OrderStore(orders_dir=None)` persists to `~/.argos/conductor/orders.jsonl`; `list()` (sorted by `created_at`), `get`, `add`, `update`, `delete`, `.path`.
- Related: `FileTriggerFact` (`triggers.py`): `path: str`, `mtime: float`, `glob: str`, `detected_at: float`.

**`ProactiveSuggestionEvent`** — `from argos.protocol.events import ProactiveSuggestionEvent` (`events.py:286`), `kind = "proactive_suggestion"`:
- `suggestion_id: str`, `order_id: str`, `goal: str`, `reason_human: str`, `suggested_at: float`, `requires_confirmation: bool = True` (protocol-level always True, client read-only), `action: Literal["run", "dream"] = "run"` (validated in `__post_init__`).
- Note field name is `suggestion_id` on the event vs `id` on the dataclass.

---

## 6. Dream — `argos/learning/dream.py`

**`DreamReport`** — `from argos.learning.dream import DreamReport` `@dataclass(frozen=True, slots=True)`, all fields default `0`/`""`:
`units_total: int = 0`, `promoted: int = 0`, `rejected: int = 0`, `skipped: int = 0`, `memory_merged: int = 0`, `memory_archived: int = 0`, **plus `report_path: str = ""`** (a 7th field not in your prompt list — exists in source). All six listed fields confirmed exact.

**Phase / stage names** — emitted via `DreamProgressEvent.stage`, the real sequence is **6 stages, not 4**: `scan → cluster → synthesize → promote → memory → done`. (Your prompt listed scan/cluster/promote/done; source additionally emits `synthesize` and `memory`.)

**`DreamProgressEvent`** (`events.py:347`, `kind = "dream_progress"`): `stage: str`, `detail: str`, `ts: float`.

**`DreamReportEvent`** (`events.py:361`, `kind = "dream_report"`): `units_total: int`, `promoted: int`, `rejected: int`, `skipped: int`, `memory_merged: int`, `memory_archived: int`, `report_path: str`, `ts: float` (one-to-one with `DreamReport` plus `ts`).

`DreamPipeline` drives it; `has_material(candidates_root, *, min_units=1) -> bool` is the material gate.

---

## 7. Computer use — `argos/perception/`

**`ComputerAction`** — `from argos.perception import ComputerAction, ActionKind, TEXT_MAX_LEN` (`actions.py`) `@dataclass(frozen=True, slots=True)`:
- `kind: ActionKind`, `x: int | None = None`, `y: int | None = None`, `text: str | None = None`, `app: str | None = None`.
- `ActionKind = Literal["screenshot", "click", "double_click", "type_text", "key", "scroll", "open_app"]`.
- `TEXT_MAX_LEN = 2000`; `__post_init__` validates coords ≥0, text length, app-name charset `^[A-Za-z0-9 _.\-]+$`, and per-kind required fields. For `scroll`, `text=str(dy)`.

**The 7 tool names** (broker-gated `action=` strings, registered in `argos/capability/builtins.py` and `argos/tools/__init__.py`, dotted namespace):
`computer.screenshot`, `computer.click`, `computer.double_click`, `computer.type_text`, `computer.key`, `computer.scroll`, `computer.open_app`. (Distinct from the bare `ActionKind` literals — broker actions carry the `computer.` prefix.)

**Risk / reversible invariants** (capability manifest, `builtins.py:185`): all `computer.*` are `risk="high"` + `reversible=False`. In the ledger (`builder.py`), all seven `computer.*` actions are in `_IRREVERSIBLE_ACTIONS` → `reversible="no"`, `undo_state="impossible"`, `risk="high"`. README (line 388–391) states these always require **CONFIRM regardless of Trust Dial level** — governance is Seatbelt-free here, so receipts/ledger/audit are the only controls.

**`ARGOS_COMPUTER_USE` gate:** opt-in env flag (`_ENV_FLAG = "ARGOS_COMPUTER_USE"` in `executor.py:52`). `ComputerExecutor.dispatch()` returns an honest `ComputerActionResult(ok=False, detail=_DISABLED_MSG)` when `os.environ.get("ARGOS_COMPUTER_USE") != "1"`. Default OFF.

**`ComputerActionResult`** (`executor.py:72`): `ok: bool`, `detail: str`, `artifact_path: str | None = None`, `size: tuple[int, int] | None = None`.

**`ComputerActionEvent`** (`events.py:315`, `kind = "computer_action"`): `kind_action: str`, `x: int | None`, `y: int | None`, `text_preview: str` (text truncated to 80 chars), `ok: bool`, `detail: str`, `artifact_path: str | None = None`. Note the event uses `kind_action` (string), `text_preview`, and omits `size`.

---

## Drift flags (README vs source)

1. **Routing tiers `cheap`/`default`/`strong`** — README config example (README.md:530–538) and `by_category`/`by_tool` examples use `"cheap"`/`"strong"`; these are **user-defined profile names, not a source enum**. Only `"default"` is hardcoded. A widget must enumerate tiers from `config.models` at runtime.
2. **Dream phases** — your task brief said 4 phases (scan/cluster/promote/done); source emits **6**: `scan/cluster/synthesize/promote/memory/done`. The README (line 477) describes "clusters → synthesizes → A/B promotes → consolidates memory", consistent with the 6-stage source.
3. **`DreamReport.report_path`** — a real 7th field not in your prompt's expected list (present in both `DreamReport` and `DreamReportEvent`).
4. **`escalation_warning` parameter names** — source uses `from_level`/`to_level`, not `cur`/`target` as your brief named them.

No README-mentioned field was found that is *absent* from source.


---

## Part B — New / audited widget specs (screens 09–16)


### 09 Intent 确认环 → `IntentCardChoice`

- **File**: `/Users/zc/Projects/argos/argos/tui/widgets/intent_card_choice.py`
- **New widget**: True
- **Reuses / base**: Subclass argos/tui/widgets/inline_choice.py::InlineChoice — inherit _on_key (↑↓/Enter/digit/Esc fail-closed), _confirm, _finish (idempotent self-destruct to ◕ summary + focus #prompt), _options_text (▸ cursor + 1/2/3 labels), on_mount (focus+bell), and the risk-class CSS. Override compose() to inject the gold ◉ title + field-grid Statics (label col $ink-faint + per-field value colors) + risk-pill line ($unverif/$fail) + spacer + '? ' question lines ($plan) ABOVE the inherited #ic-options/#ic-hint. Override DEFAULT_CSS so border-left is thick $eye and #ic-title color is $eye (Intent card is gold-chrome, not the orange-$unverif of approval cards).
- **Tokens**: $raise, $eye, $eye-glow, $ink-bright, $ink, $ink-dim, $ink-faint, $unverif, $unverif-deep, $plan, $fail, $hairline-lit
- **Glyphs**: ◉ U+25C9 FISHEYE — card title (执行前回显, 注视实瞳) ▸ U+25B8 — current option cursor ◕ U+25D5 — self-destruct summary (阅毕眼) ? ASCII question mark prefix — clarify questions ($plan) 、 U+3001 — CJK enumeration comma joining constraints/not_doing · U+00B7 — hint separators
- **Data fields**: card_json['goal'] (IntentCard.goal) — always; 目标; $ink-bright, card_json['deliverable'] (IntentCard.deliverable) — if non-empty; 交付物; $ink, card_json['constraints'] (IntentCard.constraints tuple) — if non-empty, 、-joined; 约束; $ink, card_json['not_doing'] (IntentCard.not_doing tuple) — if non-empty, 、-joined; 不做; $ink, card_json['risk_flags'] OR ev.risk_flags (IntentCard.risk_flags tuple) — if non-empty as pills; 风险; $unverif (or $fail for high-irreversible flags); else dim '(无高危标记)' $ink-dim, card_json['questions'] (IntentCard.questions tuple, ≤3) — if non-empty as '? ' lines; $plan, card_json['confirmation_required'] (IntentCard.confirmation_required bool) — GATE: widget only mounts when True; rendered as caption, card_json['utterance'] (IntentCard.utterance) — NOT rendered in card body (already echoed as the user's › line above the card), ev.confirmation_text (IntentConfirmRequest.confirmation_text) — render_confirmation() text; used as fallback body only if card_json missing/unparseable
- **Backend source**: argos/intent/card.py::IntentCard (frozen dataclass: utterance, goal, deliverable, constraints, not_doing, risk_flags, confirmation_required, questions). argos/intent/engine.py::IntentEngine.parse() builds the card; render_confirmation() produces the flat text. The event carrying it: argos/protocol/events.py::IntentConfirmRequest (fields verified line 265-269: kind='intent_confirm_request', call_id:str, confirmation_text:str, risk_flags:tuple, card_json:dict=dataclasses.asdict(IntentCard)). Constructed in argos/core/loop.py:1053-1058 only when _card.confirmation_required is True. Risk word→flag table is argos/intent/engine.py::_RISK_WORDS (delete_files/financial_transfer/purchase/send_message/send_email/send_sms/uninstall/format_disk/elevated_privilege/permission_change) — these are the only real flag strings; 'write_files' in the design HTML is illustrative and is NOT in _RISK_WORDS (widget must render whatever flags the backend supplies, never invent 'write_files').

**Visual layout**

NEW widget = field-grid decision card. A Vertical (height:auto, margin:0 0 1 0, padding:1 2, background:$raise, border-left: thick $eye) — left edge is GOLD $eye (this card is chrome/attention, NOT the orange-$unverif of an approval card; this is the visual contract that distinguishes Intent confirm from Smart approval). Compose order, every Static markup=False (goal/constraints can contain `[...]`):

ROW 1 — title Static, text-style bold, color $eye, EXACT text: "◉ 意图确认 — 执行前回显"
   (◉ = U+25C9 FISHEYE = 注视实瞳 "execute-before echo". NOT ◓/◔/◕/◍ — those belong to approval/verdict eyes. Use ◉ verbatim per visual + prototype line 403.)

ROW 2..N — FIELD GRID, one Static line per present field. Rich Text per line: a 4-char-wide label column in $ink-faint (#525A73), then 2 spaces, then value. Label/value EXACT strings & colors:
   "目标    " ($ink-faint) + <card.goal>            value color $ink-bright (#ECEEF5)   ← always shown
   "交付物  " ($ink-faint) + <card.deliverable>     value color $ink (#C8CCDA)          ← only if deliverable non-empty
   "约束    " ($ink-faint) + "、".join(constraints)  value color $ink (#C8CCDA)          ← only if constraints non-empty
   "不做    " ($ink-faint) + "、".join(not_doing)    value color $ink (#C8CCDA)          ← only if not_doing non-empty
   "风险    " ($ink-faint) + <risk pills>            ← only if risk_flags non-empty (see ROW R); if EMPTY render NO 风险 line (or, matching prototype fallback line 408, a single dim line "风险    (无高危标记)" in $ink-dim — pick the dim-fallback so the field grid stays honest about "no high-risk flags detected").
   (Label is fixed 4 CJK-display-width — "目标"=2 glyphs+2 spaces, "交付物"=3 glyphs+1 space, "不做"=2+2, "约束"=2+2, "风险"=2+2 — pad to EAW display-width 4 + 2-space gutter, NOT str-len, because CJK is double-width. Compute pad with the existing EAW helper used elsewhere in tui; do not naive-ljust.)

ROW R — RISK PILLS (only if risk_flags): one Rich Text line. Each flag rendered as a rounded-pill token. In terminal there is no border-radius, so emulate the design pill as a bracketed chip: " write_files " styled foreground $unverif (#FF9E64) on a faint bordered look — concretely append Text(f" {flag} ", style="#FF9E64") with no background, separated by a single space; the design's pill border #9A6E2E maps to $unverif-deep (use it only if you draw an actual box-char chip; the simplest honest form is colored text in $unverif). Multiple flags = space-joined chips on one line. Color MUST be $unverif (orange "truth-uncertain/risk"), NEVER $eye gold and NEVER $fail red unless a flag is in the high-irreversible set (see honesty_rules — computer.* / delete_files / format_disk / financial_transfer escalate the chip to $fail).

ROW S — spacer Static of one blank line (the design's height:4px gap before questions).

ROW Q (0..3) — CLARIFY QUESTIONS, only if card.questions non-empty. One Static per question, EXACT prefix "? " then the question text, whole line color $plan (#7AA2F7). Cap at 3 (questions ≤ 3 contract). Example line: "? 澄清:同名 .md 已存在时覆盖还是跳过?"

ROW O — OPTIONS block (reuse InlineChoice's exact option renderer style). Three fixed options, current row prefix "▸ " (U+25B8) in bold $eye, non-current rows 2-space indent. "{n}  {label}", current row bold $ink-bright, others $ink-dim. EXACT labels & order (prototype lines 410-414):
   1  确认开始   value="confirm"   (cursor starts here, cursor=0)
   2  修改目标   value="edit"
   3  取消       value="cancel"

ROW H — hint Static, color $ink-faint, EXACT text: "↑↓ 选择 · ↵ 确认 · 数字直选 · Esc 取消"
   (visual footer also shows meta strings "confirmation_required = true · questions ≤ 3" and "argos/intent · IntentCard" — these are spec captions, render them ONLY as the hint context; the load-bearing one is the Esc=取消 fail-closed cue. Optionally a second dim caption line "confirmation_required = true · questions ≤ 3" in $ink-faint.)

DECISION SUMMARY (self-destruct to one line) — on decide, mount a single Static in parent (markup=False) and remove self, EXACTLY like InlineChoice: prefix ◕ (U+25D5 阅毕眼). Text:
   confirm → "◕ 意图确认 → 已确认 · 转为 run"
   edit    → "◕ 意图确认 → 修改目标 · 已取回到输入"
   cancel  → "◕ 意图确认 → 已取消 · 未执行任何动作"
Then return focus to #prompt (app.query_one("#prompt").focus()), draft preserved.

This is NOT InlineChoice because InlineChoice renders only title+body+options (flat). Intent needs a typed field-grid (label column + per-field colors + risk pills + question lines) driven by card_json. The OPTION + cursor + key + self-destruct machinery is identical to InlineChoice — factor it by SUBCLASSING InlineChoice and overriding compose() to inject the field-grid + question rows above the options, OR copy the ~80-line key/cursor/finish core. Recommended: subclass InlineChoice, keep its _on_key/_confirm/_finish/_options_text verbatim, override compose() to yield the gold title + field-grid Statics + question Statics + super's #ic-options + #ic-hint. Set escape_value="cancel", risk derived from risk_flags (low if none, high if any flag in high-irreversible set, else medium). Override DEFAULT_CSS border-left to thick $eye (NOT $unverif) and #ic-title color to $eye.

**Behavior**

Mounts via app._enqueue_choice(lambda: IntentCardChoice(...)) → _mount_next_choice → Transcript.mount_block. on_mount: self.focus() + app.bell() (inherited from InlineChoice). Input is LOCKED while card pending (app._set_blocked_status(True) set by _mount_next_choice; StatusBar left eye → ◓ 审批挂起). Key handling (inherited InlineChoice._on_key): ↑/↓ wrap cursor over 3 options; Enter confirms current; digit 1-3 direct-selects + confirms; ALL other keys swallowed (no leak to input). FAIL-CLOSED Esc = escape_value='cancel' → same as option 3 取消 → loop.respond_intent_confirm(call_id, confirmed=False) / daemon POST confirmed=false → run never starts. confirm → respond_intent_confirm(call_id, True) (+ optional revised_goal). edit → respond confirmed=False (do NOT start run) AND app re-populates #prompt with card.goal/utterance for the user to revise ('◌ 已取回目标'), then user re-submits. cancel → confirmed=False, honest '未执行任何动作'. AUTO/YOLO (gate.level is ApprovalLevel.AUTO): widget is NOT mounted at all — handler short-circuits to respond confirmed=True (preserve current _handle_intent_confirm YOLO branch lines 2702-2712). Idempotent _finish (inherited): never double-responds the call_id. After decide: self-destruct to one ◕ summary line, focus back to #prompt (draft kept). Timeout: loop-side wait_for fail-closes to Error after intent_confirm_timeout_s (~120s) — widget needs no timer; if loop times out the run is cancelled honestly.

**Wiring (app.py)**

Rewire argos/tui/app.py::_handle_intent_confirm (currently ~line 2691-2753). Keep the AUTO/YOLO short-circuit (2702-2712), the _is_daemon detection (2714-2719), the _decide closure, and the daemon/inline respond split (2721-2738) UNCHANGED. Change ONLY the rendering: replace the InlineChoice(title='意图确认 — 请确认...', body=body_text, options=[('confirmed','确认,继续执行'),('cancel','取消')]) at lines 2746-2753 with: parse ev.card_json into the field-grid and mount IntentCardChoice with options [('confirm','确认开始'),('edit','修改目标'),('cancel','取消')], escape_value='cancel', on_decide=_decide. Update _decide to map value: 'confirm'→confirmed=True; 'edit'→confirmed=False + set #prompt value to card goal/utterance ('已取回目标 · 修改后回车'); 'cancel'→confirmed=False. (NOTE current _decide checks value=='confirmed' — must change to value=='confirm' to match new option values, AND add the 'edit' branch.) Pass card_json=ev.card_json, confirmation_text=ev.confirmation_text (fallback), risk_flags=ev.risk_flags. Mount path stays _enqueue_choice (works because IntentCardChoice subclasses InlineChoice/Vertical → mount_block accepts it; _choice_done() still called in _decide). daemon path _daemon_intent_confirm_post already supports revised_goal kwarg for a future inline-edit variant.

**Honesty rules**

1) FAIL-CLOSED Esc: Esc and timeout both = cancel = confirmed=False = run NEVER starts (never default to confirm). 2) confirmation_required GATE: widget renders ONLY when card.confirmation_required is True; loop never yields IntentConfirmRequest otherwise — do not synthesize a confirm card for direct-out intents. 3) RISK COLOR LADDER: risk_flags pills in $unverif (orange) by default; escalate a chip to $fail (red) for high-irreversible flags (delete_files, format_disk, financial_transfer, purchase, uninstall, elevated_privilege, and any computer.* perception flag); NEVER paint risk pills $eye gold (gold = chrome, not danger) and NEVER paint them $pass/$pass-weak green. 4) NO INVENTED FLAGS: render exactly the strings in card.risk_flags / ev.risk_flags from _RISK_WORDS; 'write_files' from the HTML mock is illustrative only — if backend gives no flags, show dim '(无高危标记)' ($ink-dim), do not fabricate a risk. 5) computer.* ALWAYS high+irreversible regardless of trust level — its risk chip is $fail and never auto-confirmed even under AUTO if a perception/computer-use flag is present (the widget itself does not auto-escalate; it only renders — but the high-irreversible color set must include computer.*). 6) suggest_escalation NEVER auto-escalates: this is an Intent confirm card, not a trust-dial; selecting 'confirm' starts the run at the CURRENT trust level — it must not raise trust or bypass hard rules. 7) $pass-weak ≠ $pass and neither appears here (no verdict on this screen) — do not borrow verdict greens for the confirm option. 8) EDIT ≠ CONFIRM: 'edit' must respond confirmed=False (run does not start) and only re-populate the prompt; never let 'edit' silently start the run. 9) error/honesty: if card_json is missing or unparseable, fall back to rendering ev.confirmation_text as a single dim body line — never blank-render and never auto-confirm; an unrenderable card still defaults Esc=cancel.

**Open questions**

- 'edit' flow: prototype just re-populates #prompt and user re-submits (no inline edit field). daemon _daemon_intent_confirm_post already accepts revised_goal — confirm whether v1 ships the simple re-populate (recommended) or an inline edit Input. Spec assumes re-populate.
- Risk pill rendering fidelity: terminal can't do border-radius; spec recommends colored bracketed/spaced chips in $unverif. Confirm whether a box-char chip (using $unverif-deep border) is wanted or plain colored text suffices.
- Whether to keep the dim fallback line '风险 (无高危标记)' (prototype line 408) vs omitting the 风险 row entirely when no flags — spec recommends keeping the dim line for honest 'no high-risk detected' signal.
- EAW label padding helper: confirm the exact existing tui util to compute CJK display-width for the 4-wide label column (activity_panel / status_bar likely have one) so labels align.


### 10 Trust Dial · L0–L4 信任拨盘 → `TrustDial`

- **File**: `/Users/zc/Projects/argos/argos/tui/widgets/trust_dial.py`
- **New widget**: True
- **Reuses / base**: InlineChoice (for the escalation-upgrade decision card — BLOCK B; already wired in _trust_cmd via _enqueue_choice, no new code needed). The NEW TrustDial widget is for BLOCK A (the 5-row dial status table) only.
- **Tokens**: $ink, $ink-bright, $ink-dim, $ink-faint, $eye, $fail, $unverif, $stream, $raise, $raise-2, $hairline-lit
- **Glyphs**: ▸ (U+25B8 current-row cursor, $eye bold — same glyph InlineChoice uses) ⏻ (U+23FB POWER SYMBOL, L4 红灯 indicator, $fail) · (U+00B7 middle dot separator, $ink-dim) ⚠ (warning, escalation card title — $unverif; NOTE: prototype uses bare ⚠ U+26A0 here, but for honesty-critical/secret副标 InlineChoice mandates ⚠︎ U+26A0+U+FE0E VS15; the dial card title uses the plain ⚠ from trust_dial.escalation_warning output verbatim — do not rewrite the backend string's glyph)
- **Data fields**: TrustLevel (IntEnum L0_EVERY_STEP=0 … L4_AUTONOMOUS=4), TrustLevel.name (e.g. 'L1_DANGEROUS_ONLY' → split('_')[0] = 'L1'), TrustLevel.label_human (人话标签, e.g. '只有危险操作才问'), TrustLevel.description (full说明, for /trust status verbose line), escalation_warning(from_level, to_level) -> str (non-empty on upgrade, '' on downgrade), EscalationSuggestion.warning (str, never empty), EscalationSuggestion.reason (str, e.g. '操作类别「read_file」已连续被允许 5 次(阈值 5)'), EscalationSuggestion.trigger_count (int), EscalationSuggestion.from_level / suggested_level (TrustLevel), to_approval_semantics(level)['show_yolo_indicator'] (bool, True only for L4), to_approval_semantics(level)['hard_rules_immune'] (bool, ALWAYS True), hard_rules_immune() -> bool (always True)
- **Backend source**: argos/permissions/trust_dial.py — TrustLevel (IntEnum, L0_EVERY_STEP/L1_DANGEROUS_ONLY/L2_IRREVERSIBLE_ONLY/L3_SESSION_TRUSTED/L4_AUTONOMOUS), TrustLevel.label_human / .description / .name; escalation_warning(from_level, to_level); suggest_escalation(history, current_level, threshold) -> EscalationSuggestion|None; EscalationSuggestion(from_level, suggested_level, warning, reason, trigger_count); to_approval_semantics(level) -> dict (keys: approval_level, description, reversible_check, ask_readonly, hard_rules_immune always True, show_yolo_indicator for L4); hard_rules_immune() -> bool always True. Current trust read from gate via argos/approval.py ApprovalLevel mapping in app.py _trust_cmd (gate._trust_level preferred, else gate.level reverse-map, else gate._ask_readonly → L0).

**Visual layout**

The screen renders as TWO separate stream blocks, NOT one. Split responsibility:

═══ BLOCK A — TrustDial table widget (NEW; this is the `/trust` / `/trust status` render) ═══
A `Static`-based block widget (subclass `Static`, markup=False, like VerdictBadge — verdict.detail / labels can contain `[...]`). Container is a vertical block in the Transcript stream (mount via `log.mount_block(...)`). Visual structure, top to bottom, EXACT text:

Line 1 (header line): `信任拨盘 · 当前 L1`  — where `L1` is the current `TrustLevel.name.split('_')[0]` (L0/L1/L2/L3/L4). The literal prefix text `信任拨盘 · 当前 ` is $ink ($C8CCDA); the level token `L1` is $ink-bright ($ECEEF5) bold. (Visual spec line 592.)

Lines 2-6 (the 5-row dial, ONE row per TrustLevel, in enum order L0→L4). Each row is a 3-column grid: [marker 2-wide][label 168px-equiv col][hint col]. Use a fixed-width layout: marker(2 cols) + level-label padded + 2-space gap + right hint. EXACT strings per row (from visual spec 594-598 + prototype dial array 770-776):
  L0:  `L0 每一步都问我`            | `全量确认(含只读)`
  L1:  `L1 只有危险操作才问`        | `高风险暂停 · 低风险放行`
  L2:  `L2 只有不可逆操作才问`      | `依赖能力 reversible 字段`
  L3:  `L3 同类批准后本会话放行`    | `= ACCEPT_EDITS 扩展`
  L4:  `L4 全自治`                  | `⏻ 红灯 · HARD RULES 仍拦`  (the `⏻ 红灯` substring is $fail ($F7768E); rest of L4 hint is $ink-faint)

Row coloring rule (current vs non-current):
  - CURRENT row: marker prefix `▸ ` (U+25B8 + space) in $eye ($D9A85C) bold; the level-label text in $ink-bright ($ECEEF5) bold; the hint text in $ink ($C8CCDA). Row background = $raise-2-equivalent highlight if feasible (visual spec uses bg #1B1D29 = $raise on the current row — render the current row label in $ink-bright as the selection signal; bg highlight optional since Static markup can't easily bg a sub-line — prefer the ▸ + brightness contrast).
  - NON-CURRENT rows: marker = 2 spaces (no triangle); level-label AND hint both in $ink-faint ($525A73).

Line 7 (dashed separator + HARD RULES iron-law line, visual spec 600 + 781). Render as: a thin top rule then text `HARD RULES 永不降级:危险 shell · 系统路径 · secret 检测`. Base text `HARD RULES 永不降级:` in $ink-dim ($7E869C); the three protected categories `危险 shell` / `系统路径` / `secret 检测` EACH in $fail ($F7768E) (three $fail spans, separator ` · ` in $ink-dim). README §10 line 150 mandates "三处 $fail".

Footer (visual spec 610-612, optional — render as a $ink-faint line): left `升档必带警示 · 绝不静默自动升`, right-ref `permissions/trust_dial`. Both $ink-faint ($525A73). This footer is decorative provenance; may render as single dim line.

Implementation note: because Static renders one Rich `Text`, build the whole block as a multi-line Rich Text with per-span styles using the hex constants pattern already used in inline_choice.py (_COL_EYE etc.) — but the WIDGET's DEFAULT_CSS must use $token names (background: $stream; padding: 0 2; the block sits on $stream Transcript bg). For sub-line span colors that Rich Text needs as hex, mirror inline_choice.py's documented exception: "DEFAULT_CSS 一律用 $token 名;Rich Text style 用 hex(Rich 不解析 $token)" — define module hex constants annotated with their $token name (e.g. _COL_FAIL = '#F7768E'  # $fail).

═══ BLOCK B — escalation warning decision card (REUSE InlineChoice; this is `/trust l<n>` upgrade) ═══
This is ALREADY correctly implemented in app.py _trust_cmd (884-891) via `_enqueue_choice(lambda: InlineChoice(...))`. Visual spec 602-608 shows it as: left-edge 4px $unverif ($FF9E64 → border-left: thick $unverif) bar on $raise bg. EXACT content the card must carry:
  - title: `升档确认 — 切换到 {target_label}` (target_label = target_trust.label_human). Visual spec title variant: `⚠ 切换到「全自治」?` — keep the app.py title OR adopt the visual `⚠ 切换到「{Ln 标签}」?`; the ⚠ + $unverif title color is the visual intent. InlineChoice title uses $unverif by default (risk-medium) which matches.
  - body: `escalation_warning(current_trust, target_trust)` — the REAL non-empty warning string from trust_dial.py (NEVER fabricated). For L4 it is the strong variant ending "如有任何疑虑,建议保持当前档位。".
  - If a `suggest_escalation` result exists, append its `reason` line styled $ink-faint: visual spec 606 = `建议来源:类别「read_file」已连续允许 5 次(阈值 5)`. This maps to EscalationSuggestion.reason = `操作类别「{top_kind}」已连续被允许 {top_count} 次(阈值 {threshold})`.
  - options EXACT (visual spec 607): `1  确认升档` / `2  保持 L1` (label `保持 {current_trust 标签}`). Mapped to InlineChoice options `[("confirm","确认升档"),("cancel","取消，保持当前档位")]`. Current cursor on option 1 (▸ prefix, $eye bold).
  - hint line (prototype 759): `↑↓ 选择 · ↵ 确认 · 升档必带警示 · 绝不静默自动升`.
  - risk: "high" for L4 (border-left thick $fail), else "medium" (border-left thick $unverif). InlineChoice already maps risk→border via .risk-high/.risk-low CSS.
  - escape_value="cancel" (fail-closed).

DECISION: BLOCK B needs NO new widget — it correctly reuses InlineChoice. The NEW widget is ONLY BLOCK A (the dial table), which today is dumb `log.append_line` plain text and loses all the per-cell coloring + current-row highlight + three-$fail iron-law line.

**Behavior**

TrustDial widget (BLOCK A) is display-only, NOT focusable (can_focus=False) — it is a rendered status block in the stream, not an interactive picker (switching levels is done by typing `/trust l<n>`, mirroring current /trust UX; do not invent in-widget arrow selection that would diverge from the command flow). It exposes a constructor/`show(current: TrustLevel)` that takes the resolved current level and renders the 5-row table with the current row highlighted. No key handling on the dial itself.

BLOCK B (the upgrade card) keeps InlineChoice's existing key handling verbatim: ↑/↓ move ▸ cursor, Enter confirm, digits 1-2 direct-select, Esc = escape_value 'cancel' (FAIL-CLOSED: Esc on a trust-upgrade card = keep current level, never auto-escalate — matches README §10 'Trust 升档=保持'). On decide, on_decide(value, feedback) fires; 'confirm' → gate.set_trust_level(target), self._yolo=(target is L4), refresh subtitle+topbar, append done line; anything else (incl. 'cancel'/Esc) → append '已取消升档操作，保持当前档位' system line. Card self-destructs to a one-line `◕ 审批 <action_label> → <value>` summary (InlineChoice._finish), then _choice_done() unblocks the queue.

Downgrade path (target < current): NO card, applies silently (no warning) — escalation_warning returns '' for downgrades; app.py already does this (846-856). suggest_escalation NEVER auto-applies — it only feeds the reason line into a card the user must still confirm.

**Wiring (app.py)**

app.py method `_trust_cmd` (lines 776-892). Two rewire points:
1) STATUS render (lines 806-820): currently builds a plain `lines` list and calls `await log.append_line("\n".join(lines), kind="system")`. REPLACE the dial-table portion (the loop at 816-818 over TrustLevel + the header) with `await log.mount_block(TrustDial(current=current_trust))`. Keep the verbose current-level description line (808-810) as a preceding append_line OR fold into the widget's header area — preference: widget renders the 5-row dial + iron-law line; the one-line current description can stay a separate $ink line above it. The current-level resolution logic (789-803: gate._trust_level preferred → reverse-map gate.level → gate._ask_readonly L0 fallback) stays in _trust_cmd and is passed into TrustDial(current=...).
2) UPGRADE card (lines 858-891): NO change — already reuses InlineChoice via _enqueue_choice correctly. Optionally enrich body by appending an EscalationSuggestion.reason line when suggest_escalation(...) is available (today the warning body comes only from escalation_warning; the '建议来源:...' line from visual spec 606 is not yet wired — add it only if a real suggestion exists, never fabricate).
Import the new widget at top of app.py alongside InlineChoice/VerdictBadge.

**Honesty rules**

1) hard_rules_immune() is ALWAYS True — the iron-law line `HARD RULES 永不降级:危险 shell · 系统路径 · secret 检测` MUST render on every dial state, all three categories in $fail; the widget must never omit or soften it regardless of current level (even L4). 2) suggest_escalation NEVER auto-escalates — its reason only populates a confirmation card body; the widget must not change the current-row highlight based on a suggestion. 3) Upgrade requires a non-empty escalation_warning rendered as the card body; if escalation_warning returns '' (a downgrade/no-op) there must be NO card and NO 'upgraded' claim. 4) Esc on the upgrade card = keep current (fail-closed); confirm is the ONLY path that calls gate.set_trust_level — the widget/handler must not set the level on cancel/Esc. 5) L4 honesty: when current==L4, the L4 row's `⏻ 红灯` is $fail and the warning text must still say HARD RULES 仍强制拦截无法绕过 (do not imply full bypass). show_yolo_indicator drives the topbar ⏻ red lamp via _refresh_topbar; the dial must agree with the topbar (never show L4 active without ⏻). 6) Color discipline: $eye (gold) is ONLY chrome/current-cursor (▸); $unverif (orange) is ONLY the upgrade-warning left-edge/title; $fail (red) is ONLY for HARD RULES categories + L4 红灯 — never mix gold with risk semantics. 7) Reverse-mapping loss: current level must prefer gate._trust_level (stored) so L2 is never misreported as L1 (app.py 800-803 comment '不许对用户失真') — the widget renders whatever current it is handed; the handler must hand the un-lossy value.

**Open questions**

- Visual spec line 595 highlights the current row with a $raise background (#1B1D29) spanning the full row; Static/Rich Text cannot easily background a single sub-line within a multi-line block. Confirm whether full-row bg is required or if ▸ + $ink-bright brightness contrast (as InlineChoice does for its cursor row) is an acceptable equivalent. Recommend the brightness-contrast approach to stay within Static; a true per-row bg would need a Vertical of per-row Static widgets.
- The '建议来源:类别「read_file」已连续允许 5 次(阈值 5)' line (visual spec 606) is shown inside the upgrade card but is currently NOT wired (app.py passes only escalation_warning as body). Confirm whether to call suggest_escalation against real history and append EscalationSuggestion.reason when present — and where that history comes from (ledger/audit). If no real history source is available yet, this line must be OMITTED, not faked.
- Should the verbose current-level TrustLevel.description (app.py 808-810) live inside TrustDial or remain a separate append_line above it? Spec only mandates the 5-row table + iron-law line; recommend keeping description as a separate $ink line to keep the widget focused on the dial.


### 11 Dynamic Workflows · 进度树 → `WorkflowPanel`

- **File**: `/Users/zc/Projects/argos/argos/tui/widgets/workflow_panel.py`
- **New widget**: False
- **Reuses / base**: InlineChoice (argos/tui/widgets/inline_choice.py) — already used by _handle_workflow_proposed for the workflow APPROVAL card (options once/always/deny, escape_value='deny', risk='medium', mounted via _enqueue_choice). The progress tree itself is the existing WorkflowPanel (Static subclass). No new widget class needed for screen 11 — this is an audit+polish of WorkflowPanel plus the already-wired InlineChoice approval. (The 5-shape legend, if ever built, would be a plain Static, not a new interactive widget.)
- **Tokens**: $accent, $eye, $pass, $pass-weak, $unverif, $fail, $ink-bright, $ink, $ink-dim, $ink-faint, $ink-ghost, $eye-soft, $well, $abyss, $hairline, $hairline-lit, $border
- **Glyphs**: ◔ plan/规划 ◉ act/执行 + error/失败 ❂ verify/验证 ◕ report/汇总 + done/完成 ─ 综合结论前缀 · 注记项目符 ▸ (inline_choice cursor, only if reused for approval card) ◓ (approval pending title prefix, inline_choice) ⚠︎ U+26A0+FE0E (secret hit, inline_choice only)
- **Data fields**: WorkflowProposed.name, WorkflowProposed.description, WorkflowProposed.preview (= render_preview(spec)), WorkflowProposed.call_id, WorkflowProgress.stage_id, WorkflowProgress.agent_id, WorkflowProgress.phase, WorkflowProgress.note, WorkflowDone.name, WorkflowDone.synthesis, WorkflowDone.notes (tuple[str,...]), WorkflowPanel ctor: name, WorkflowPanel.update_progress(agent_id, phase, note), WorkflowPanel.finish(synthesis, notes), WorkflowPanel.rendered_text (test read API), WorkflowSpec.name, WorkflowSpec.description, WorkflowSpec.stages, Stage.id, Stage.op (fan_out|pipeline|panel|loop_until|synthesize|best_of_n), Stage.voters, Stage.n (best_of_n), AgentTask.model, AgentTask.tool_scope (read|full), AgentTask.isolation (none|worktree), AgentTask.role (explorer|planner|coder|reviewer)
- **Backend source**: argos/protocol/events.py: WorkflowProposed (kind='workflow_proposed', fields name/description/preview/call_id), WorkflowProgress (kind='workflow_progress', fields stage_id/agent_id/phase/note), WorkflowDone (kind='workflow_done', fields name/synthesis/notes:tuple). argos/workflow/spec.py: WorkflowSpec(name, description, stages:tuple[Stage]), Stage(id, op, agent, over, voters, threshold, target, n, ...), AgentTask(prompt, model, tool_scope, isolation, verify, role, ...), _OPS={fan_out,pipeline,panel,loop_until,synthesize,best_of_n}, _ROLES=(explorer,planner,coder,reviewer). argos/workflow/result.py: WorkflowResult(name, stages, synthesis, total_tokens_in, total_tokens_out, notes), StageResult(stage_id, results, candidates), AgentResult(agent_id, ok, output, verdict, error, tokens_in, tokens_out, diff_ref, diff_summary, diff_file_count), render_preview(spec)→preview string. Existing widget: argos/tui/widgets/workflow_panel.py (_PHASE_GLYPH, _PHASE_TEXT, WorkflowPanel).

**Visual layout**

EXISTING widget, AUDIT + POLISH. Do NOT break _PHASE_GLYPH / _PHASE_TEXT dicts or the update_progress()/finish()/rendered_text API (app.py:2287-2291 + tests depend on them).

Outer container (CSS, already correct): `border: round $accent; padding: 0 1; margin: 0 1 1 1; height: auto;`. $accent == $eye gold per theme.py. The visual spec's outer 1px #2E3142 card + window-chrome dots + footer bar are the design-doc's "screenshot frame" decoration only — they are NOT part of the Textual widget; the round gold border IS the WorkflowPanel boundary inside the transcript stream. Do not add chrome dots.

Multi-line text body, rendered as ONE Static. Lines top→bottom:
  Line 1 (head, BOLD $ink-bright): `工作流:<name>` — when finished append `(完成)` → `工作流:三审制安全评审(完成)`. (Visual shows shape suffix `(panel · 3 voters)` in the prototype title; backend name has no shape, so keep just the name unless app.py passes a decorated name. Do not invent shape text.)
  Per-agent rows (one per agent, in first-seen order), format EXACTLY: two leading spaces + `<glyph> <agent_id> <phase文字>` and when note non-empty ` — <note>`. Literal example rows from the visual:
     `  ◕ voter-1 完成 — 通过:无高危依赖`
     `  ◉ voter-2 执行 — 扫描 dangerous APIs…`
     `  ❂ voter-3 验证 — pip-audit 子进程`
  On finish, append:
     synthesis line ($ink-dim/$ink-faint): `  ─ 综合结论:<synthesis>` e.g. `  ─ 综合结论:2/3 通过,1 项待复核`
     each note ($ink-faint), 4-space indent + `· `: `    · voter-2 标记 subprocess shell=True 风险`

GLYPHS per phase (FROZEN, _PHASE_GLYPH): plan ◔ / act ◉ / verify ❂ / report ◕ / done ◕ / error ◉. TEXT (_PHASE_TEXT): plan 规划 / act 执行 / verify 验证 / report 汇总 / done 完成 / error 失败.

POLISH GAP (the only real change): TODAY the body is one plain Static with markup=False → the ENTIRE panel renders in default foreground; per-glyph color is LOST. The visual spec REQUIRES per-glyph coloring: done/passed glyph ◕ in $pass green (#9ECE6A), in-progress glyphs (◔◉❂◕-report) in $eye gold (#D9A85C), a FLAGGED-but-done agent's ◕ in $unverif orange (#FF9E64, voter-2 "标记 1 项待复核"), error ◉ in $fail red. Because markup=False is a hard honesty law (note may contain `[...]`), per-glyph color MUST be done via a Rich `rich.text.Text` object with explicit per-span `style=` (NO markup), exactly the pattern in inline_choice._options_text(). Switch _compose_text() to build a Text: append the glyph with a status-derived style, then append the rest of the row as plain text. Decide glyph color from phase: error→$fail, done/report→$pass UNLESS the row is a flagged completion. Flagged-vs-clean done is NOT in the current data model — to honor the orange-◕ case, accept an optional per-agent flag (e.g. note-prefix convention or a new param to update_progress like `flag: str = ""` with values ""/"warn"/"fail"); if you cannot get the flag honestly from the engine, render done as $pass green and DO NOT fake the orange — better honest-green than invented-orange. Rich color constants already exist as module hex consts in inline_choice (_COL_EYE etc.); mirror that — DEFAULT_CSS uses $token names, Rich Text styles use the matching hex (Rich does not resolve $token). Add hex consts: _COL_PASS="#9ECE6A", _COL_EYE="#D9A85C", _COL_UNVERIF="#FF9E64", _COL_FAIL="#F7768E", _COL_INK_BRIGHT="#ECEEF5", _COL_INK_DIM="#7E869C", _COL_INK_FAINT="#525A73".

Companion (NEW, OPTIONAL, design-doc right column "五种形态 · WorkflowSpec.shape"): a static legend listing the 5 shapes: `fan_out 每项一个 agent · 并行扇出`, `pipeline 逐阶段顺序流转 · 无屏障`, `panel N 名 voter · 对抗式验证泛化`, `loop_until 累积到目标 / 连续空轮停 · 硬上限`, `synthesize 汇总成一份报告`. Header `五种形态 · WorkflowSpec.shape` in $eye-soft bold. Shape names $eye, descriptions $ink-dim. This is documentation/help surface, NOT part of the live progress tree — only build it if a /workflow help command is wired; otherwise skip (out of scope for _handle_workflow_proposed).

**Behavior**

Progress tree is display-only inside the transcript stream; it does NOT take focus or key input (can_focus stays default-false; it is a Static subclass). Lifecycle driven entirely by app.py event handler: WorkflowProposed→mount WorkflowPanel(name) + store self._workflow_panel (app.py:2498-2500); WorkflowProgress→self._workflow_panel.update_progress(agent_id, phase, note) (2287-2288); WorkflowDone→self._workflow_panel.finish(synthesis, notes) (2290-2291). Out-of-order / panel-missing events are silently ignored (the `if self._workflow_panel is not None` guard) — never crash. update_progress appends new agent_id to self._order on first sight, then mutates self._agents[agent_id]=(phase,note) and re-renders; finish sets _done=True and re-renders with synthesis+notes. _compose_text MUST stay tolerant of unknown phase (falls back to glyph '·' and the raw phase text). markup=False is mandatory (note/synthesis may contain `[...]`); per-glyph coloring must use Rich Text spans, never markup.

FAIL-CLOSED: The approval gate is handled SEPARATELY by an InlineChoice card (reuse, see reuses field), NOT by WorkflowPanel. _handle_workflow_proposed enqueues an InlineChoice with escape_value='deny' → Esc = deny = loop's gate.await never released = workflow NOT started. AUTO level: loop auto-releases the gate, so the handler mounts the panel only and renders NO choice card (2501-2502). InlineChoice keys: ↑/↓ move ▸ cursor, Enter confirm, digit 1-N direct-select, Esc→escape_value('deny'), self-destruct to one-line `◕ 审批 <action_label> → <decision>` summary on decide, focus returns to #prompt.

**Wiring (app.py)**

app.py _handle_workflow_proposed (defined ~2492-2521): mounts WorkflowPanel(name=ev.name) and stores self._workflow_panel (2498-2500); then for non-AUTO levels enqueues an InlineChoice (2514-2521, options once/always/deny, escape_value='deny', risk='medium') whose on_decide calls self.gate.respond(call_id, value). Progress/Done routed in the main event dispatcher at app.py:2283-2291 (WorkflowProposed→_handle_workflow_proposed, WorkflowProgress→panel.update_progress, WorkflowDone→panel.finish + log.append_line synthesis). Imports already in place: WorkflowPanel (app.py:72), WorkflowProgress/WorkflowDone (app.py:50-51). The polish (per-glyph Rich color) is fully internal to workflow_panel._compose_text — NO app.py rewiring needed; the API surface (ctor name, update_progress, finish, rendered_text) is unchanged so app.py:2287-2291 keeps working as-is. Only add the optional flag param if engine can supply flagged-done honestly (default '' preserves current callers).

**Honesty rules**

1. error phase MUST render 「失败」 (text) with glyph ◉ in $fail red — NEVER render a failed agent as 完成/passed. done MUST render 「完成」. This is the frozen _PHASE_TEXT/_PHASE_GLYPH contract; test_tui_markup_safety + workflow_panel tests lock it. 2. done glyph ◕ defaults to $pass green; only color it $unverif orange when the engine HONESTLY signals a flagged/under-review completion (voter flagged a risk) — if no honest flag signal exists, render $pass green; NEVER invent the orange state from prose heuristics. 3. $pass-weak (self-verified weak) ≠ $pass (strong) — if individual agent verdicts ever surface here, weak pass must use $pass-weak desaturated green, never the strong $pass. 4. markup=False is absolute: agent_id/phase/note/synthesis may contain `[...]` (traces, command args, list literals) — must render as literal text via Rich Text spans, never parsed as markup (parsing would crash the whole TUI). 5. Approval gate is fail-closed: Esc on the InlineChoice = deny = workflow does not start (escape_value='deny'); AUTO level releases the gate loop-side but the SPEC text "批准后在 OS 沙箱边界内自动执行(网络 OFF、写限工作区)" from render_preview must remain truthful. 6. confirmation_required is enforced by the gate.await in the loop, not the widget — the widget must not draw a 'started' state before the gate resolves. 7. synthesis/notes shown by finish() are the engine's actual WorkflowResult.synthesis/notes — do not embellish; partial-failure / cap-truncation notes (e.g. '2/3 通过,1 项待复核') must be shown verbatim, not summarized to success.

**Open questions**

- Flagged-done orange ◕ (voter-2 '标记 1 项待复核'): backend currently exposes no per-agent 'flagged but ok' bit on the WorkflowProgress event — phase is just done. To honor the visual orange state, either (a) add an optional flag param to update_progress (''/warn/fail) wired from the engine's AgentResult.verdict, or (b) keep done=$pass green. Recommend (a) only if engine can supply it honestly; (b) otherwise. Needs engine-side confirmation of AgentResult.verdict→flag mapping.
- Should WorkflowPanel head show the shape (panel · 3 voters) like the prototype title? Backend WorkflowProposed.name has no shape; would require app.py to pass a decorated name or the panel to read spec. Out of scope unless product wants it — currently render plain name.
- Per-agent token/cost (AgentResult.tokens_in/out, diff_summary, diff_file_count) and best_of_n candidates (StageResult.candidates) are in the result model but NOT in the WorkflowProgress/Done events the widget receives — surfacing them would need new event fields. Confirm whether v1 wants per-agent diff/cost in the tree or keep it minimal.


### 12 Conductor 自治面 → `OrdersPanel (NEW table widget) + reuse InlineChoice (suggestion decision card)`

- **File**: `/Users/zc/Projects/argos/argos/tui/widgets/orders_panel.py (NEW for the standing-orders table); the ProactiveSuggestion decision card REUSES /Users/zc/Projects/argos/argos/tui/widgets/inline_choice.py (no new file)`
- **New widget**: True
- **Reuses / base**: InlineChoice (argos/tui/widgets/inline_choice.py) for the ProactiveSuggestion decision card — adds a `.conductor` CSS variant (border-left $plan, title $plan, ◔ glyph) and escape_value='dismiss'; mounted via existing _enqueue_choice. Glyph/honesty conventions follow verdict_badge.py.
- **Tokens**: $eye, $ink, $ink-faint, $abyss, $stream, $ink-dim, $eye-soft, $ink-ghost, $raise, $plan, $ink-bright, $pass, $fail, $hairline-lit
- **Glyphs**: ⏱ (U+23F1) schedule order ⊙ (U+2299) file_trigger order ◔ (U+25D4) suggestion title — awaiting/quarter eye ▸ (U+25B8) option cursor ◕ (U+25D5) post-decision read-eye summary › (U+203A) prompt echo → (U+2192) action arrow ◌ (U+25CC) dismissed/idle summary
- **Data fields**: StandingOrder.id, StandingOrder.utterance, StandingOrder.kind ('schedule'|'file_trigger'), StandingOrder.schedule, StandingOrder.trigger_glob, StandingOrder.action ('run'|'dream'), StandingOrder.enabled, ProactiveSuggestionEvent.suggestion_id, ProactiveSuggestionEvent.order_id, ProactiveSuggestionEvent.goal, ProactiveSuggestionEvent.reason_human, ProactiveSuggestionEvent.action ('run'|'dream'), ProactiveSuggestionEvent.requires_confirmation (read-only, always True)
- **Backend source**: Standing orders table: argos/conductor/orders.py → StandingOrder (frozen dataclass, fields id/utterance/kind/schedule/trigger_glob/goal_template/enabled/created_at/last_fired_at/action) + OrderStore.list(). Today /orders renders o.to_dict() dicts (daemon GET /orders or local OrderStore). Suggestion card: argos/protocol/events.py:287 ProactiveSuggestionEvent (suggestion_id/order_id/goal/reason_human/suggested_at/requires_confirmation=True/action); produced from argos/conductor/proposals.py → ProactiveSuggestion via propose(). Decision plumbing: daemon POST /suggestions/{id}/confirm (201→run_id+worktree, server pins isolation=worktree + trust_level=L1_DANGEROUS_ONLY) and POST /suggestions/{id}/dismiss (200). House widget pattern: argos/tui/widgets/inline_choice.py (InlineChoice), argos/tui/widgets/verdict_badge.py (honesty/glyph pattern), mounted via app.py _enqueue_choice (2469) / _mount_next_choice (2474) / _choice_done (2484).

**Visual layout**

SOURCE: 视觉稿.dc.html lines 676-709. Two distinct pieces — a read-only orders TABLE (new OrdersPanel) and a decision CARD (reuse InlineChoice).

=== SECTION HEADER (rendered by app/transcript, not the widget) ===
Baseline row, 3 spans gap≈12px:
  "12"        color #D9A85C → $eye
  "Conductor · 自治面"  16px bold  color #C8CCDA → $ink
  "standing orders · 永远要确认"  color #525A73 → $ink-faint

=== OrdersPanel (NEW) — the /orders read-only listing ===
Outer card: border 1px #2E3142 → $hairline-lit (Textual: `border: round $hairline-lit` or tall; design uses radius 10 + shadow which TUI can't do — use a simple round border), background #0B0C10 → $abyss. Mono, 13px / line-height 20.
(The 3 chrome traffic-light dots at lines 684-686, bg #3A4055 → $ink-ghost, are pure web chrome — DO NOT replicate in TUI.)

Body background conceptually #13141B → $stream (transcript prose surface). Rows top-to-bottom:
  Row 1 (prompt echo):  "› /orders"      color #7E869C → $ink-dim   (the "›" is U+203A; keep as plain prompt-echo line, NOT $eye)
  Row 2 (count):        "standing orders (2)"   color #C8CCDA → $ink     — format: f"standing orders ({n})"
  Row 3..N (one per StandingOrder), 4-column grid template "22px 152px 1fr 52px":
     col0 GLYPH:  "⏱" if kind=="schedule" else "⊙" if kind=="file_trigger"   color #A8854A → $eye-soft
     col1 TRIGGER:  schedule kind → human schedule e.g. "每天 09:00";  file_trigger kind → trigger_glob e.g. "requirements.txt 变更"   color #C8CCDA → $ink
     col2 UTTERANCE (flex 1fr):  the order.utterance, e.g. "整理昨日 CHANGELOG" / "审计依赖漏洞"   color #7E869C → $ink-dim
     col3 ACTION:  "→ run" or "→ dream"  (from order.action)   color #525A73 → $ink-faint
     HONESTY: disabled orders (enabled==False) must be visually demoted — prefix dim/strike marker, NEVER hidden, NEVER shown as if active. Use $ink-ghost #3A4055 for the whole row when disabled.
  Footer (split row, padding 4 16 6, bg #0B0C10 → $abyss, 12px, color #525A73 → $ink-faint):
     left:  "cron-lite 调度 · 文件触发监视"
     right: "argos/conductor"

EXACT format strings to copy verbatim into OrdersPanel:
  count line   = f"standing orders ({len(orders)})"
  schedule row = f"⏱ {schedule_human:<…} {utterance} → {action}"
  trigger  row = f"⊙ {trigger_label} {utterance} → {action}"
  footer L     = "cron-lite 调度 · 文件触发监视"
  footer R     = "argos/conductor"
Use a textual.widgets.DataTable OR a Rich Table inside a Static for the 4-col grid; left-align col0/col1/col2, the "→ run/dream" right-cell dim.

=== ProactiveSuggestion CARD (REUSE InlineChoice) — 视觉稿 lines 696-703 ===
This maps 1:1 onto InlineChoice but the LEFT-EDGE COLOR and TITLE GLYPH differ from the approval/escalation reuse, so a new CSS variant class `conductor` is added.
Card: margin "4px 18px 0", background #1B1D29 → $raise, border-left 4px #7AA2F7 → $plan  (NOT $unverif default, NOT $fail). In Textual: `border-left: thick $plan`.
  TITLE (#ic-title):  "◔ 主动建议 · 待确认"   color #7AA2F7 → $plan, bold (font-weight 700).  GLYPH is ◔ (U+25D4 scanning quarter-eye), matching VerdictBadge unverifiable/"awaiting" semantics — NOT ◓.
  BODY line 1 (#ic-body): reason_human, e.g. "定时触发（每天 09:00）：整理昨日 CHANGELOG"  color #C8CCDA → $ink
  BODY line 2: "建议执行 → " + short goal preview, e.g. "建议执行 → 生成 2026-06-13 变更摘要"  color #7E869C → $ink-dim
  BODY line 3 (the iron-law line): "requires_confirmation = true · 绝不自动执行"  color #525A73 → $ink-faint  (ALWAYS present; this is the honesty contract made visible)
  OPTIONS (#ic-options, ▸ cursor U+25B8 bold $eye like InlineChoice):
     1  确认执行  /confirm <id8>     value="confirm"   label color when picked $pass #9ECE6A
     2  忽略      /dismiss <id8>      value="dismiss"   label color $fail #F7768E
     where <id8> = suggestion_id[:8] (matches existing app.py sid_short pattern; 视觉稿 shows "7f3a" as illustrative short id)
  HINT (#ic-hint):  "↑↓ 选择 · ↵ 确认 · 数字直选 · Esc 忽略"   color #525A73 → $ink-faint
  After decision, InlineChoice self-destructs to one line "◕ 审批 主动建议 → confirm|dismiss" (◕ U+25D5 read-eye) — pass action_label="主动建议".

GLYPH LAW (v3 字形铁律): only ⏱ ⊙ ◔ ▸ ◕ ◌ appear. FORBIDDEN: ◎ ⊙(as bullet) ● ○ ◐ ◑ ◇ ◆ ▶ • — but note ⊙ U+2299 IS the sanctioned file_trigger glyph here (README line 93), keep it. "✓/✗" enabled markers from today's plain-text handler should be replaced by row dimming, not kept as ASCII checks.

**Behavior**

OrdersPanel: pure read-only render of OrderStore.list() / daemon GET /orders dicts. No focus, no key handling, no execution. Empty list → honest empty-state line "无常驻指令" (keep existing copy), NEVER fabricate the 2 sample orders from the design (those are mock illustrations). Disabled orders dimmed, not dropped.

Suggestion card (InlineChoice reuse): on ProactiveSuggestionEvent arrival, app mounts it via _enqueue_choice → it grabs focus + rings app.bell(); ↑/↓ move ▸ cursor; ↵ confirm current; digits 1-2 direct-select; Esc = escape_value="dismiss" (Conductor fail-closed semantics per README line 197 = 「忽略」, NOT execute). While the card is pending, input is LOCKED (_set_blocked_status(True) via _enqueue_choice → StatusBar left-eye shows 审批挂起). on_decide(value): value=="confirm" → call _confirm_suggestion_cmd(suggestion_id) (POST /suggestions/{id}/confirm); value=="dismiss" → _dismiss_suggestion_cmd(suggestion_id). Card self-destructs to one-line ◕ summary; focus returns to #prompt; _choice_done() unblocks. Idempotent: InlineChoice._finish guards double-fire. confirm result (201) prints run_id + "隔离：worktree" + "信任档：L1_DANGEROUS_ONLY（写死，不可升级）"; 404/503 print honest error, never success.

**Wiring (app.py)**

app.py four handlers to rewire:
(1) _orders_cmd (1282-1325): replace the manual `lines.append(...)` plain-text loop with OrdersPanel(orders=orders) mounted via `await self.query_one('#transcript', Transcript).mount_block(OrdersPanel(orders))`. Keep the daemon-vs-local OrderStore fetch (1288-1305) and the empty-state branch (1307-1312) as-is.
(2) _on_proactive_suggestion (1416-1435): replace the plain `log.append_line(...)` block with `await self._enqueue_choice(lambda: InlineChoice(title='◔ 主动建议 · 待确认', body=<reason_human + goal preview + 'requires_confirmation = true · 绝不自动执行'>, options=[('confirm', f'确认执行  /confirm {sid8}'), ('dismiss', f'忽略      /dismiss {sid8}')], on_decide=self._on_suggestion_decide(ev), escape_value='dismiss', risk='medium', action_label='主动建议', classes='conductor'))`. Add CSS class `InlineChoice.conductor { border-left: thick $plan; } InlineChoice.conductor #ic-title { color: $plan; }` (override the default $unverif left-edge).
(3) _confirm_suggestion_cmd (1327-1377) and (4) _dismiss_suggestion_cmd (1379-1412): keep AS-IS — wire the InlineChoice on_decide callback to call these by value. They are the daemon POST endpoints and already honest about 201/404/503.
Add new method _on_suggestion_decide(ev) returning a closure (value, feedback)->None that dispatches confirm/dismiss using ev.suggestion_id.

**Honesty rules**

1. requires_confirmation is protocol-const True and READ-ONLY — the card MUST render the line "requires_confirmation = true · 绝不自动执行" and MUST never auto-confirm; suggestion → run only via explicit user /confirm.
2. Esc = fail-closed = DISMISS (忽略), per README line 197 Conductor column — NOT execute, NOT keep-pending. escape_value MUST be "dismiss".
3. confirm result honesty: 404/503/non-201 from daemon must render as error (kind='error'), never as a success/run-created line. A dismiss 404 likewise renders error, not "已忽略".
4. confirm always shows the server-pinned guardrails verbatim: "隔离：worktree" + "信任档：L1_DANGEROUS_ONLY（写死，不可升级）" — TUI cannot and must not claim higher trust.
5. action ('run' vs 'dream') is shown truthfully in both table col3 and card; never relabel a dream order as run.
6. Empty orders → honest empty-state, NEVER render the design's sample "每天 09:00 / requirements.txt" rows (those are mock data).
7. disabled (enabled==False) orders dimmed to $ink-ghost, shown but visually inactive — never hidden, never shown as active.
8. Color discipline: suggestion left-edge + title = $plan (plan-mode blue, plan≠act); confirm option = $pass; dismiss option = $fail; order glyphs = $eye-soft (weak gold for non-active markers, per theme rule 金橙分家). Do NOT use $eye (strong gold) for orders. Title glyph is ◔ (awaiting), never ◉ (which is verdict passed/failed). No raw hex anywhere in CSS — $token only.

**Open questions**

- StandingOrder.schedule is a raw cron-lite expr ('09:00'/'every 1h'/'@daily'/'0 9 * * *'); the design shows humanized '每天 09:00'. Need a tiny schedule→human formatter (or render raw with a 'cron:' prefix) — confirm whether a humanizer exists in cronlite.py or render verbatim to stay honest.
- Daemon GET /orders returns dicts (to_dict); OrdersPanel should accept either StandingOrder objects or dicts — recommend a from-dict normalizing constructor so both daemon and local paths feed it.
- _confirm/_dismiss currently require daemon mode (return error otherwise). The InlineChoice card will still mount in inline mode — confirm the on_decide should surface the existing 'confirm 需要 daemon 模式' honest error rather than silently no-op.
- Section header (12 / title / subtitle) — is it drawn by OrdersPanel or by the screen host? Recommend host draws header, OrdersPanel draws only the bordered table body + footer, matching how other panels compose.


### 13 Dream 夜间整固 → `DreamReportCard`

- **File**: `/Users/zc/Projects/argos/argos/tui/widgets/dream_report.py`
- **New widget**: True
- **Tokens**: $stream, $raise, $hairline-lit, $hairline, $well, $abyss, $eye, $ink, $ink-bright, $ink-dim, $ink-faint, $ink-ghost, $pass, $fail, $unverif
- **Glyphs**: ◔ (U+25D4 scan/memory stage glyph, $eye) ◉ (U+25C9 cluster/synthesize stage glyph, $eye) ❂ (U+2742 promote stage glyph, $eye) ◕ (U+25D5 done stage glyph, $pass — the only green stage) ─ (U+2500 report sub-card title prefix) · (U+00B7 middot separator) › (U+203A prompt echo prefix) ≥ (U+2265 in Jaccard label)
- **Data fields**: DreamReport.units_total, DreamReport.promoted, DreamReport.rejected, DreamReport.skipped, DreamReport.memory_merged, DreamReport.memory_archived, DreamReport.report_path, DreamProgressEvent.stage, DreamProgressEvent.detail, DreamProgressEvent.ts, DreamReportEvent.units_total, DreamReportEvent.promoted, DreamReportEvent.rejected, DreamReportEvent.skipped, DreamReportEvent.memory_merged, DreamReportEvent.memory_archived, DreamReportEvent.report_path, DreamReportEvent.ts
- **Backend source**: argos/learning/dream.py — @dataclass(frozen=True, slots=True) DreamReport (lines 299-308): fields units_total, promoted, rejected, skipped, memory_merged, memory_archived, report_path (all int except report_path:str). Emitted by DreamPipeline._run_locked() (lines 406-462) which also broadcasts dream_progress at stages scan/cluster/promote/memory/done and a final dream_report. SSE event dataclasses: argos/protocol/events.py — DreamProgressEvent (lines 348-358: stage, detail, ts; stage ∈ scan|cluster|synthesize|promote|memory|done) and DreamReportEvent (lines 361-376: units_total, promoted, rejected, skipped, memory_merged, memory_archived, report_path, ts). The promoted-skill name (Row D) is NOT a DreamReport field — see open_questions; it is derivable from dream.py _merged_name()/synthesize() (slug "dream-" + slugify_goal) but is not currently surfaced in DreamReport/DreamReportEvent.

**Visual layout**

NEW widget — a read-only progress-stream + honest-count report card (NOT a decision card; no InlineChoice). It is mounted INLINE in the Transcript via log.mount_block(), replacing today's plain ap.append_line() / append_line text.

Composition is a Vertical(id="dream-card") with border (matches the v3 obsidian-eye card chrome the design uses for all command cards). Outer block left-edge / border = $hairline-lit (#2E3142, the visual's `border:1px solid #2E3142`). Body background = $stream (#13141B). The HTML mock draws a fake titlebar with 3 traffic-light dots ($ink-ghost #3A4055) on a $well (#0E0F15) bar with a $hairline (#23252E) bottom border — in Textual we DO NOT recreate macOS traffic-lights; render the card with `border: round $hairline-lit` and a one-line border-title instead. Keep all real content.

EXACT line-by-line content (top to bottom), each a Static, markup=False unless noted:

1. Echo line (Static, $ink-dim #7E869C → token $ink-dim):  "› /dream"

2. STAGE STREAM — a Vertical(id="dream-stages") appended one row at a time as dream_progress SSE arrives (gap 1px in mock → no margin in Textual, height:auto each). Each row is one Static. The 6 backend stages map to glyph+label rows. EXACT format strings copied from the .dc.html / prototype `_runDream`:
   - scan:    "◔ scan    候选区 {N} 条未消费"      glyph ◔ = $eye (#D9A85C), text = $ink (#C8CCDA)
   - cluster: "◉ cluster {M} 簇(Jaccard ≥ 0.35)"  glyph ◉ = $eye, text = $ink
   - synthesize: (backend emits this stage; visual omits it) "◉ synthesize …" treat like cluster row, glyph $eye text $ink  (do NOT drop it — honest: render whatever stage the daemon sends)
   - promote: "❂ promote A/B 晋升门…"              glyph ❂ = $eye, text = $ink. When DreamProgressEvent.detail carries promote reason, append " · {detail}" in $ink-dim.
   - memory:  "◔ memory 记忆整理…"                  glyph $eye text $ink (visual has no memory row but backend emits stage=memory; render it honestly)
   - done:    "◕ done"                             glyph ◕ AND text BOTH = $pass (#9ECE6A) — the only green stage row. Per README §13: 前三 $ink，done $pass.
   Spacing in labels uses real single spaces (the mock's &nbsp; padding is just HTML alignment; use one space after glyph + tab-aligned label, do not hardcode nbsp).

   Glyph→stage table is FIXED (anti-fake): {scan:◔, cluster:◉, synthesize:◉, promote:❂, memory:◔, done:◕}. The streamed value N/M/detail comes verbatim from DreamProgressEvent.detail (e.g. detail="3 units" for cluster). NEVER fabricate counts — if detail is empty, render the bare label with no number.

3. REPORT SUB-CARD — a Vertical(id="dream-report-box") with bg $raise (#1B1D29), rounded, padding 1 2 (mock: `border-radius:6px;padding:9px 14px`), margin-top 1. Mounted only on dream_report (DreamReportEvent) / final DreamReport. Rows (each a Static):
   - Row A (title, Static, text-style bold, $ink-bright #ECEEF5):  "─ 报告"
   - Row B (Rich Text, markup-built so 3 counts get 3 distinct colors):
       "整合单元 {units_total} · " + ("晋升 {promoted}" in $pass #9ECE6A) + " · " + ("驳回 {rejected}" in $fail #F7768E) + " · " + ("跳过 {skipped}" in $unverif #FF9E64). Leading/plain text = $ink (#C8CCDA).
   - Row C (Static, $ink):  "记忆合并 {memory_merged} · 归档 {memory_archived}"
   - Row D (Static, $ink-dim #7E869C, margin-top small):  "晋升:{promoted_name}(综合自 {n} 次已验证 run)" — ONLY rendered when promoted >= 1. promoted_name is the dream-* skill slug (see open question on source). If promoted==0, OMIT row D entirely (do not show a fake promotion line).

4. Caption (Static, $ink-faint #525A73, font small):  "可执行内容逐字来自源材料 · 模型只写叙述"

5. Footer row (optional, Static, $ink-faint #525A73): left "失败安全降级 · 全建议需用户确认"  right "argos/learning/dream" — the visual shows a two-column footer on $abyss; in TUI render as a single muted line "失败安全降级 · 全建议需用户确认 · argos/learning/dream".

Header line shown above the card (section header in the visual: "13  Dream · 夜间整固   03:00 cron · 只整固已验证 run") is a screen-catalog artifact, NOT part of the inline card — do not render the "13" number; optionally the card border-title may read "Dream · 夜间整固".

DEFAULT_CSS uses ONLY $token names: `DreamReportCard { height: auto; margin: 0 0 1 0; padding: 1 2; background: $stream; border: round $hairline-lit; }` ; `#dream-report-box { background: $raise; padding: 1 2; margin: 1 0 0 0; }` ; title classes color $ink-bright; caption color $ink-faint. Per-count colors in Row B are applied via Rich Text style hex constants (Rich does not parse $token), following the house pattern in inline_choice.py (_COL_* constants) — keep a small _COL map mirroring theme.py: PASS=#9ECE6A, FAIL=#F7768E, UNVERIF=#FF9E64, EYE=#D9A85C, INK=#C8CCDA, INK_DIM=#7E869C, INK_FAINT=#525A73, INK_BRIGHT=#ECEEF5.

**Behavior**

PURELY DISPLAY — no key handling, no focus, no Esc/decision flow. This is the one Dream surface that is NOT a decision card (contrast: Conductor §12 proactive-suggestion IS an InlineChoice with /confirm /dismiss). Lifecycle: (a) on `/dream` (POST /dream/run → 202) the card is mounted with the echo line + an empty stage stream; (b) each DreamProgressEvent appends ONE stage row to #dream-stages (call_after_refresh to avoid compose race, mirroring InlineChoice mount); (c) the final DreamProgressEvent stage=done flips that row to $pass; (d) DreamReportEvent (or /dream status → GET /dream/report) mounts/updates the #dream-report-box with honest counts. Provide methods: append_stage(stage:str, detail:str) and show_report(report:dict|DreamReport). Idempotent done row. Fail-closed semantics here are not about user keys but about HONEST DEGRADATION: inline (non-daemon) mode never mounts the card — it shows the existing honest refusal text ("Dream 需要 daemon 模式…"); HTTP 409 → "已有 Dream 在跑" (no card); HTTP 503 → error line with daemon-supplied reason (no fabricated success). If DreamReportEvent never arrives (daemon crash), the card stays at last real stage — never auto-completes to a green report. markup=False on all plain Statics (report_path / detail may contain `[...]`); Row B uses Rich Text with explicit styles, not markup parsing.

**Wiring (app.py)**

argos/tui/app.py. Three edit sites: (1) _dream_cmd (def at line 1777) — on 202 (lines 1831-1834) replace `await log.append_line("Dream 已启动…")` with mounting a DreamReportCard via log.mount_block() and stashing a ref (e.g. self._dream_card); keep 409/503/inline-refusal branches as honest text (lines 1788-1794 inline refusal, 1835-1843). (2) SSE handler DreamProgressEvent branch (lines 2333-2339) — replace `ap.append_line(f"[dream] {ev.stage}{detail}")` (activity-bar one-liner) with self._dream_card.append_stage(ev.stage, ev.detail) when a card is mounted (keep ap.append_line as fallback when no card). (3) SSE handler DreamReportEvent branch (lines 2340-2353) — replace the _fmt_dream_report(...) + ap.append_line(summary_line) plain summary with self._dream_card.show_report({units_total:…, promoted:…, …}). (4) _dream_cmd status branch (line 1816) `await log.append_line(self._fmt_dream_report(report), kind="done")` — mount a DreamReportCard.show_report(report) instead of the one-line text. _fmt_dream_report (static, line 1765) can remain as a fallback/text-mode formatter. Mounting follows the established pattern at app.py:2234-2235 (VerdictBadge: construct then `await log.mount_block(badge)` then badge.show(...)).

**Honesty rules**

1) The 6-stage glyph map is FIXED and the done glyph ◕ + done text are the ONLY $pass (green) elements in the stage stream — scan/cluster/synthesize/promote/memory rows are $eye glyph + $ink text (README §13: 前三 $ink, done $pass). A non-done stage must NEVER render green. 2) Counts (units_total/promoted/rejected/skipped/memory_merged/memory_archived) are rendered VERBATIM from DreamReport/DreamReportEvent — never recomputed, never defaulted to a flattering number; missing → render 0 honestly. 3) Row B three-color contract: 晋升=$pass, 驳回=$fail, 跳过=$unverif — these three semantic colors must stay distinct (promoted green ≠ rejected red ≠ skipped orange); rejected/skipped must NEVER be shown green to look like success. 4) Row D (promotion name) renders ONLY when promoted>=1 — zero promotions must show NO promotion line (no fake "晋升:…"). 5) The caption "可执行内容逐字来自源材料 · 模型只写叙述" must always be present — it states the dream.py iron law (executable content verbatim from sources, model writes narrative only; _strip_code_blocks enforces it). 6) Failure / non-daemon / 409 / 503 must render their honest text/error paths and must NOT mount a report card that implies a successful run. 7) Stage stream is append-only from real SSE; the card never auto-fills stages it hasn't received — if the daemon stops mid-run, the card freezes at the last real stage rather than fabricating done.

**Open questions**

- Row D promotion name ("晋升:dream-fix-replay-order(综合自 3 次已验证 run)"): DreamReport / DreamReportEvent do NOT carry the promoted skill name or its source-run count. dream.py _merged_name()/synthesize() build the slug ("dream-"+slugify_goal) but it is not surfaced. Options: (a) extend DreamReport with promoted_name:str|None + promoted_sources:int (cleanest, honest), or (b) omit Row D entirely until backend surfaces it (safest — never fabricate). Recommend (b) for v1: render Row D only if the daemon supplies the name; otherwise drop it.
- Whether to keep the activity-bar (right panel) one-line dream echo in addition to the inline card, or move dream entirely to the inline card. Current app.py uses ap.append_line (activity bar). Suggest: inline card is primary, keep a single activity-bar summary line as a peripheral cue.
- synthesize and memory stages are emitted by the backend but absent from the visual mock — confirm with design whether to render them (honest) or collapse synthesize into cluster. Spec assumes render-all-stages-honestly.


### 14 Behaviour Ledger + /undo → `LedgerTable`

- **File**: `/Users/zc/Projects/argos/argos/tui/widgets/ledger_table.py`
- **New widget**: True
- **Tokens**: $eye, $ink, $ink-dim, $ink-faint, $hairline, $pass, $pass-weak, $fail, $unverif, $stream, $abyss
- **Glyphs**: ─ (U+2500 header under-rule / column separators) ↩ (U+21A9 undo success line) ◌ (U+25CC empty-undo no-op marker) — (U+2014 em-dash undo sentinel) › (U+203A command echo prefix, already used by Transcript)
- **Data fields**: LedgerEntry.run_id (12 hex; header `run {run_id}`), LedgerEntry.seq (int; col 1), LedgerEntry.summary_human (str from ledger/summary.py; col 2), LedgerEntry.risk (str 'low'|'medium'|'high'; col 3, display 'medium'→'med'), LedgerEntry.reversible (Literal['yes','no','unknown']; col 4), LedgerEntry.undo_state (Literal['available','done','impossible']; col 5), LedgerEntry.action (used ONLY to filter out action=='undo_done' sentinel rows; not displayed), LedgerEntry.undo_token (used to detect file-granular undo: startswith('file:'); drives optional [可撤·文件] hint, NOT a column), LedgerEntry.receipt_sig (NOT rendered per-row in this screen — referenced only in footer text '每条回执签名'; truncated 16ch), RestoreResult.restored / RestoreResult.errors (from RunSnapshot.restore via app._snapshot, drives /undo line: count + success vs partial)
- **Backend source**: argos/ledger/entry.py (LedgerEntry frozen dataclass: ts, run_id, seq, action, summary_human, risk, reversible, undo_token, receipt_sig, undo_state; Reversible=Literal['yes','no','unknown']; UndoState=Literal['available','done','impossible']). argos/ledger/store.py (LedgerStore.replay(run_id)->sorted list, undo_complete, mark_entry_done, is_undo_done, get_entry). argos/ledger/builder.py (build_entry: risk='high' for irreversible/network/browser/computer.*, 'medium' for shell, 'low' for file rw — NOTE stores 'medium' full-word). argos/ledger/summary.py (summarize(action,args)->人话, deterministic, no model). /undo restore: argos.core.snapshot RunSnapshot.restore(workspace)->result with .restored/.errors, accessed via app._snapshot.

**Visual layout**

NEW widget `LedgerTable(Static, markup=False)`. NOT a real Textual DataTable — render with rich.text.Text in one Static for pixel control of per-cell color (DataTable can't color cells independently here cleanly). Mounted into Transcript via the same flow as _ledger_cmd uses log.append_line today; replaces the plain-text block.

OVERALL CARD (the chrome dots + title bar in the .dc.html are MOCKUP-ONLY browser-window decoration; do NOT recreate the 3 traffic-light dots or the title bar in the TUI — they are HTML-prototype framing, not part of the in-stream render). The TUI render is the BODY only (the #13141B/$stream region), mounted inline in the transcript like other system blocks.

EXACT in-stream layout, top to bottom (copy text verbatim):
1. Echo line (already emitted by command dispatch, not by widget): `› /ledger` in $ink-dim.
2. Header summary line: `行为账本 · run {run_id} · {N} 条` in $ink  (.dc.html shows `行为账本 · run 4f9c · 6 条`; run_id is the real LedgerEntry.run_id (12 hex), N = count of VISIBLE entries after filtering out action=="undo_done" sentinels).
3. The table block (rendered inside this widget), 5 columns. Column widths exactly as .dc.html grid-template-columns: 28px 1fr 56px 60px 80px → in TUI use fixed char widths: seq col = 4 chars right-pad, action col = flex/remaining, risk col = 7 chars, reversible col = 8 chars, undo col = 11 chars. Separate columns with 1-2 spaces.
   3a. Header row (cells, ALL in $ink-faint), with a hairline rule under it. Header cell texts VERBATIM: `seq`  `动作 · 人话`  `风险`  `可逆`  `撤销`. The under-rule = a full-width line of $hairline glyphs (e.g. repeat "─" colored $hairline) OR a blank Static with border-bottom: $hairline; simplest: one Text line of "─"*width in $hairline.
   3b. One data row per visible LedgerEntry, columns:
       - seq cell: str(entry.seq) in $ink-faint.
       - action/人话 cell: entry.summary_human in $ink. Examples VERBATIM from spec: `读取了 replay.py`, `编辑了 replay.py(+1/-1)`, `跑了命令: pytest -q`, `写入了 report.md(+120 行)`. (These come from ledger/summary.py templates — do NOT reformat.)
       - 风险 cell: SHORT risk label. Map backend value→display + color: low → text `low` in $ink-dim; medium → text `med` in $unverif; high → text `high` in $fail. CRITICAL: backend LedgerEntry.risk stores the FULL word "medium" (builder.py line 99) but the .dc.html displays `med` — the widget MUST map "medium"→"med" for display while keeping color logic keyed on the canonical value. Unknown risk → fall back to text as-is in $ink-dim.
       - 可逆 cell: entry.reversible (Literal yes|no|unknown). Color: yes → `yes` in $pass-weak; no → `no` in $fail; unknown → `unknown` in $unverif. (.dc.html row1 yes/$pass-weak, row2 yes/$pass-weak, row3 no/$fail.)
       - 撤销 cell: entry.undo_state (Literal available|done|impossible). Color+text: available → `available` in $pass; impossible → `impossible` in $ink-faint; done → `done` in $ink-dim. ALSO: when undo_state is not applicable / not yet relevant for a non-reversible row the .dc.html shows a literal `—` in $ink-faint (row1 read_file shows undo `—` because reversible=yes but it is a read with nothing to undo) — preserve a `—` ($ink-faint) sentinel for entries the backend leaves without a meaningful undo state. Rule of thumb to match .dc.html: undo_state=="available"→`available`/$pass; =="impossible"→`impossible`/$ink-faint; =="done"→`done`/$ink-dim; else→`—`/$ink-faint.
4. Footer-status line (system, emitted after table by the handler, NOT inside widget — but spec it here so it's not lost): `每条回执签名 · summary 模板生成不调模型` in $ink-faint. (The .dc.html right-aligned `argos/ledger` tag is mockup attribution — skip in TUI.)

/UNDO render (separate, see _undo wiring): two lines:
  `› /undo` in $ink-dim (echo), then the result line:
  SUCCESS: `↩ 回滚到 run 起点快照 · {N} 个文件已还原 · receipt_sig 一致` in $pass  (N = count of entries with reversible=="yes" AND undo_state=="available" that were restored).
  EMPTY (nothing reversible+available): `◌ 无可回滚的改动(可逆且未撤销)` in $ink-faint.
  PARTIAL/ERROR (snapshot restore had errors — real backend RunSnapshot.restore can fail): MUST render in $fail (kind="error"), never $pass. Format the existing app.py _undo error path (`部分还原(成功 X / 失败 Y): …`) — keep error color. Honesty: a failed/partial restore must NOT render the green `receipt_sig 一致` success line.

EMPTY-LEDGER state for /ledger: when no visible entries → single $ink-faint line `行为账本为空 · 先输入一个目标跑一个 run` (matches prototype _sys) OR keep existing honest variants ("当前会话无行为账本…" when no store/run_id; "run {id} 尚无账本记录…"; "所有动作均已撤销。"). These are existing honest fallbacks in app.py — preserve them.

**Behavior**

RENDER-ONLY widget (no key handling, no focus, no self-destruct). Unlike InlineChoice/decision-cards this screen takes no decisions — it is a read-out table mounted in the transcript, so it does NOT reuse InlineChoice and has no Esc/fail-closed semantics of its own. The data mutation (/undo marking entries done) happens in the command handler, not in the widget. /undo is the only state-changing action: it restores via RunSnapshot.restore AND (in daemon path) flips reversible=yes & undo_state=available entries to done via store.undo_complete/mark_entry_done; both are gated by reversible=='yes' AND undo_state=='available' (prototype line 800-802; README §14 '只回滚 reversible=yes 且 undo_state=available 的条目'). Filter action=='undo_done' sentinel rows out before render. No model call anywhere (summary templates are deterministic).

**Wiring (app.py)**

app.py _ledger_cmd (currently lines 893-965): replace the `lines=[...]; for e in visible: lines.append(...)` plain-text block (lines 942-956) with construction of a LedgerTable(entries=visible, run_id=run_id) and mount it into the transcript via the existing transcript mount path (the same `log`/Transcript object). Keep ALL existing honest fallbacks (no store/run_id; empty entries; all-undone) as-is — they emit $ink-faint/system lines. Keep the has_file_undo hint (lines 934-940, 958-963) as a trailing $ink-faint line below the table. After the table, emit footer `每条回执签名 · summary 模板生成不调模型` ($ink-faint, kind='system'). app.py _undo (lines 745-774): keep logic; ensure success line uses $pass via kind='done' and partial/error via kind='error'/$fail (already correct at 762-774) — the green success line must only appear on full restore (result.errors empty). Do NOT introduce a fabricated `receipt_sig 一致` claim on the error path. Mount mechanism mirrors how other system blocks reach Transcript (log.append_line today); for a custom widget use the transcript's widget-mount entrypoint analogous to _enqueue_choice's mount_block, but WITHOUT focus-stealing/bell.

**Honesty rules**

1. Error/partial /undo MUST render $fail (kind='error'), NEVER the green $pass `receipt_sig 一致` success line — a failed restore is not a success. 2. risk colors are fixed and distinct: low=$ink-dim, med=$unverif (orange = truth-uncertain), high=$fail (red) — never recolor. 3. reversible yes=$pass-weak (DELIBERATELY the weak desaturated green, E4 firewall) — must NOT use $pass; reversible 'yes' is a weaker claim than verify-passed and must not borrow the strong green. no=$fail, unknown=$unverif (honest 'don't know' = orange, never green). 4. undo_state available=$pass (strong, it IS actionable), impossible=$ink-faint (greyed, can't lie that it's undoable), done=$ink-dim, '—'=$ink-faint sentinel. 5. /undo only acts on reversible=='yes' AND undo_state=='available'; impossible/no rows are immutable — never claim to undo them. 6. summary_human comes verbatim from deterministic templates (summary.py) — no model, no embellishment; unknown actions degrade to `执行了 {action}` honestly. 7. computer.* actions are classified high+irreversible in builder.py (_IRREVERSIBLE_ACTIONS) regardless of trust → they ALWAYS show risk high/$fail, reversible no/$fail, undo impossible/$ink-faint; the widget must faithfully render these (never soften OS-control rows). 8. receipt_sig truncated to 16ch and only referenced in footer ('每条回执签名') — never claim full-signature verification was performed in this view.

**Open questions**

- Backend stores risk='medium' (full word) but .dc.html shows 'med' — confirm display mapping medium→med is desired (spec'd here) vs changing builder.py to store 'med' (would ripple into existing tests). Recommend display-only mapping in the widget.
- Transcript currently only exposes append_line (plain text) for ledger; need to confirm the exact transcript API to mount a custom Static-based widget inline (mirror _enqueue_choice/mount_block path) vs rendering the whole table as a single pre-formatted Rich Text via append_line — the latter needs no new mount API and may be simpler/lower-risk.
- Per-row receipt_sig is captured by backend but the design (§14) does NOT show it as a column — confirm it stays footer-only and is not surfaced per row.
- File-granular undo (undo_token startswith 'file:') currently only hinted as trailing text + daemon endpoint; confirm no per-row 撤销=available variant like [可撤·文件] should appear inside the table column (current app.py shows it in plain-text marks but .dc.html column does not).


### 15 Per-task routing → `RoutingTable`

- **File**: `/Users/zc/Projects/argos/argos/tui/widgets/routing_table.py`
- **New widget**: True
- **Tokens**: $border, $abyss, $stream, $hairline, $ink-dim, $ink, $cyan, $ink-bright, $unverif, $eye, $ink-faint, $pass, $fail, $ink-ghost
- **Glyphs**: › (U+203A, command-echo prefix) → (U+2192, category→tier arrow) ❂ (U+2742, force-confirm marker) · (U+00B7, separator in caption/footer) ✓ (U+2713, set-success echo, $pass) ✗ (U+2717, set-error echo, $fail)
- **Data fields**: RoutingConfig.default (str), RoutingConfig.by_category (dict[str,str]) — the category→tier map; the 8 TaskCategory enum names are the canonical row keys, RoutingConfig.by_tool (dict[str,str]) — optional by-tool overrides, RoutingConfig.tier_force_confirm (list[str]) — drives the ❂ force confirm trailer via RoutingConfig.is_force_confirm(tier), TaskCategory enum 8 values: plan/file_edit/refactor/test_write/verify/long_run/auto_capture/simple_read (categorizer.py — DO NOT rename), ModelRouter.routing (RoutingConfig property), ModelRouter.history() -> list[RouteDecision] (deque maxlen=10, run-local, NOT persisted), RouteDecision.category (TaskCategory), RouteDecision.tool (str|None), RouteDecision.tier (str), RouteDecision.source (str: by_tool|by_category|default), RouteDecision.step (int)
- **Backend source**: argos/routing/config.py (RoutingConfig: default, by_category, by_tool, tier_force_confirm, is_force_confirm; load_routing; set_category — atomic config.json rewrite, fail-closed _validate_tier). argos/routing/categorizer.py (TaskCategory 8-value enum). argos/routing/resolver.py (RouteDecision frozen dataclass + resolve). argos/routing/router.py (ModelRouter.routing property + .history()). Wired via argos/tui/app.py _current_router() -> loop._router.

**Visual layout**

A read-only mono table block mounted into the Transcript stream (NOT a decision card — routing has no approve/deny flow; `/routing set` is a one-line echo). Structure top-to-bottom, recreating the `.dc.html` lines 802-827 inside a single bordered container:

CONTAINER (the bordered card, lines 802-807):
- A `Vertical` with `border: round $border` (= $hairline-lit #2E3142, matches `border:1px solid #2E3142;border-radius:10px`), `background: $abyss` (#0B0C10), `padding: 0`.
- Textual cannot render the 3-dot mac titlebar chrome (lines 804-806, three 11px circles `#3A4055`=$ink-ghost) cheaply; OMIT the 3 dots (they are pure decoration in the HTML mock). Keep just the bordered body. If a header strip is desired, a single dim `$hairline` rule line is acceptable but not required.

BODY (inner, background `$stream` #13141B per line 808; set on an inner `Static`/`Vertical` region, `padding: 1 2`):
Row 1 (echo of the invoking command, line 809): text `› /routing` colored `$ink-dim` (#7E869C=`#7E869C`). The `›` is U+203A.
Row 2 (caption, line 810): text `按任务路由 · 最近 10 次` colored `$ink` (#C8CCDA). Header altitude variant per README uses `按任务路由 · 8 类别 · cheap / default / strong` — render the README/prototype caption `按任务路由 · 8 类别 · cheap / default / strong` colored `$ink`.
Row 3..N (the 8 category→tier rows, lines 811-820): one Static line per category, a 2-column grid emulated with fixed-width padding. EXACT format string per row (copy verbatim from prototype line 821):
  `"  " + (category + "             ")[:13] + "→ " + tier + ("  ❂ force confirm" if force_confirm else "")`
  i.e. left col = category name left-padded to 13 chars (Python: `f"  {cat:<13}→ {tier}"`), then if the tier is force-confirm append `  ❂ force confirm`.
  - The category-name segment (`plan`, `file_edit`, …) is colored `$ink-dim` (#7E869C) per visual lines 812-819 (`color:#7E869C` on the left span).
  - The `→ <tier>` segment is colored BY TIER (the right span color in lines 812-819):
      cheap   → `$cyan`       (#7DCFFF)
      default → `$ink`        (#C8CCDA)
      strong  → `$ink-bright` (#ECEEF5)
  - Force-confirm trailer: the visual mock shows two distinct trailers — `plan → strong  ❂` uses `❂` colored `$eye` (#D9A85C, line 812), while `verify → strong  force confirm` uses the words `force confirm` colored `$unverif` (#FF9E64, line 816). README §15 (line 175) is the spec-of-record: render `❂ force confirm` with the `❂` glyph + words `force confirm` colored `$unverif` (#FF9E64). One consistent trailer for ALL force-confirm tiers: `  ❂ force confirm` in `$unverif`.
  Because a single Static line needs per-segment color, render each row as a `rich.text.Text` (markup=False) with three appends: category in `$ink-dim` hex #7E869C, `→ <tier>` in tier hex, optional `  ❂ force confirm` in #FF9E64.
Row N+1 (set hint, prototype line 823 / visual line 821): `/routing set <类别> <档位> 修改` colored `$ink-faint` (#525A73). Visual line 821 also shows a literal example `› /routing set verify strong` (#7E869C) followed by the success echo line 822 `✓ verify → strong` (#9ECE6A=$pass) — those two are the ECHO of a prior `set` invocation, NOT part of the static table; they are produced by the `/routing set` path (see behavior), not by RoutingTable. RoutingTable renders only the table + the set-hint.

FOOTER (lines 824-826, background `$abyss`, `$ink-faint` #525A73, flex space-between):
- left:  `启发式分类 · 0 token · 异常兜底 simple_read`  colored `$ink-faint` (#525A73)
- right: `argos/routing`  colored `$ink-faint` (#525A73)
Render as one Static line with the two strings; left-justified label + right module tag (single line `启发式分类 · 0 token · 异常兜底 simple_read` then `argos/routing` — pad-to-width or two Statics in a Horizontal).

OPTIONAL history sub-section: the current handler (`_routing_cmd`) ALSO lists `[最近 10 步决策]` (router.history(), up to 10 RouteDecision rows). The visual mock omits a history table (caption says `最近 10 次` but shows the config map, not decisions). Render history as a secondary `$ink-dim` block UNDER the config table if `router.history()` is non-empty, one line per decision using the existing handler format: `f"  step {d.step:3}  cat={d.category.value:13} tool={d.tool or '-':14} → {d.tier:8} ({d.source})"`, tier-colored. Empty history → one `$ink-faint` line `(无;本 run 尚未调模型)`.

All text mono (Textual default in this app); no font-family needed.

**Behavior**

READ-ONLY widget — RoutingTable has NO key handling, NO focus, NO decision flow (it is NOT an InlineChoice). It is a static mounted block in the transcript stream; the user dismisses nothing. Therefore no Esc/fail-closed semantics inside the widget.

The `/routing set <category> <tier>` MUTATION path stays in the app handler (`_routing_set`, app.py 1845), unchanged in mechanism: it writes via set_category() which is FAIL-CLOSED — `_validate_tier` rejects any tier not in config.models (ConfigError "防拼写退化"), and TaskCategory(cat_name) raises ValueError for any of the non-8 category names. On success the handler emits a one-line echo `✓ <cat> → <tier>` (kind="done", $pass); on unknown category/tier or ConfigError it emits `✗ ...` (kind="error", $fail). These echoes are plain transcript lines, NOT re-renders of RoutingTable; the new table is re-rendered on the next bare `/routing` call (config is re-read from disk by load_routing, so the row reflects the change next run / next invocation).

History is run-local and ephemeral: `router.history()` empties when the run terminates (deque not persisted). If no router is injected (demo/fake mode, `_current_router()` returns None) the handler must NOT mount RoutingTable — it emits the existing honest line `/routing 不可用(无 router 注入;demo/fake 模式)。` (kind="system"). RoutingTable is only mounted when a real RoutingConfig is available.

**Wiring (app.py)**

app.py `_routing_cmd` (currently lines 1701-1739). Rewire the bare-`/routing` branch (lines 1708-1739): instead of building a plain `lines` list and calling `log.append_line("\n".join(lines), kind="system")`, construct `RoutingTable(routing=router.routing, history=router.history())` and mount it via `await self.query_one("#transcript", Transcript).mount_block(widget)` (same mount path as InlineChoice via _enqueue_choice's _mount_next_choice, but RoutingTable does NOT go through the choice queue since it is non-interactive — mount it directly). Keep the `router is None` guard (1710-1714) and the `set` dispatch (1705-1707) exactly as-is. `_routing_set` (1845-1879) is UNCHANGED. The footer string `启发式分类 · 0 token · 异常兜底 simple_read` encodes the categorizer's D9 invariant (categorize() catches all exceptions → SIMPLE_READ) and the 0-token heuristic guarantee.

**Honesty rules**

1. Tier coloring must distinguish the three tiers and NEVER conflate them: cheap=$cyan, default=$ink, strong=$ink-bright — a strong route must read as strong, never silently shown as cheap (false-economy lie). 2. The ❂ force-confirm trailer ($unverif #FF9E64) MUST appear for every tier in tier_force_confirm — a force-confirm tier rendered without the marker would hide a governance gate (e.g. verify→strong force confirm). is_force_confirm(tier) is the single source; never hardcode which tiers force-confirm. 3. The set-mutation echo must use ✓/$pass ONLY on actual successful config write; any ConfigError, unknown category (not in the 8 enum), or unknown tier (not in config.models) must render ✗/$fail — never a green ✓ for a rejected/unwritten change (fail-closed _validate_tier 防拼写退化 / 防假绿). 4. The 8 category NAMES are canonical and immutable (categorizer.py enum) — render them verbatim; a misspelled key in by_category would silently fall back to default at resolve-time, so the table must show the real config keys, not invent rows. 5. History is run-local/ephemeral and must be labeled honestly — empty history shows `(无;本 run 尚未调模型)`, never fabricated decision rows. 6. The footer claim `0 token · 异常兜底 simple_read` is a real invariant (categorize() is pure-regex, no LLM, catches all and returns SIMPLE_READ) — keep it. 7. Routing tier coloring is orthogonal to verdict colors — do NOT reuse $pass/$fail (verdict-only) for tiers; tiers use $cyan/$ink/$ink-bright. (Note: $pass-weak vs $pass and risk low/med/high apply to VerdictBadge/InlineChoice, not to this read-only routing table; computer.* always-high-irreversible is the Screen 16 hard-confirm concern, not routing.)

**Open questions**

- Visual mock caption says `最近 10 次` but the body shows the config map (8 rows), not 10 decision rows — README §15 describes only the config table. Confirm whether the history (router.history() up to 10 RouteDecision) should render at all, or only the config map. Spec'd here as an optional secondary block to preserve the current handler's information.
- Visual lines 821-822 show an inline `› /routing set verify strong` + `✓ verify → strong` echo embedded in the same card. Confirmed these are the prior set-echo (transcript lines from _routing_set), not part of RoutingTable. If a single combined card is desired, _routing_set would need to re-mount RoutingTable after writing — out of scope unless requested.
- The 3-dot mac-window chrome (visual lines 804-806) is decorative; omitted. Confirm acceptable, or whether a faux titlebar strip should be added for fidelity.
- Tier set is cheap/default/strong in the prototype, but RoutingConfig.default defaults to the literal string 'default' and tiers are free strings validated against config.models — the widget should color any tier not in {cheap,default,strong} with a neutral fallback ($ink). Confirm fallback color.


### 16 Computer use · 硬确认 → `HardConfirmCard`

- **File**: `/Users/zc/Projects/argos/argos/tui/widgets/hard_confirm_card.py`
- **New widget**: True
- **Reuses / base**: InlineChoice (subclass): reuses container CSS (.risk-high → border-left thick $fail, #ic-title color $fail), _on_key key handling, on_mount focus+bell, _finish idempotent self-destruct to '◕ 审批 … → …', _confirm, on_input_submitted, and the _enqueue_choice/_mount_next_choice/_choice_done FIFO mounting + StatusBar set_blocked plumbing. Overrides: __init__ (force risk='high', escape_value='deny', fixed 2 options, store action/x/y/description), _options_text (literal '4' for deny + ▸ cursor), compose (insert #hc-gov governance Static after #ic-body and #hc-foot footer Static after #ic-options), title string ('⛔ 计算机控制 · 硬确认 [high · 不可逆]'), digit-select map (1→once, 4→deny).
- **Tokens**: $fail, $raise, $ink-bright, $ink-faint, $ink-dim, $eye, $unverif, $abyss, $hairline-lit
- **Glyphs**: ⛔ U+26D4 (title, hard-confirm — replaces stock ◓) ▸ U+25B8 (option cursor, from InlineChoice) ◓ U+25D3 (StatusBar blocked eye, existing — not in this widget) · U+00B7 (separators) — U+2014 (em-dash in action/governance lines) 「」 U+300C/U+300D (button-name quotes in description)
- **Data fields**: ComputerAction.kind (e.g. 'click') — rendered as 'computer.{kind}' i.e. capability name 'computer.click', ComputerAction.x (int|None) — coord in body line, ComputerAction.y (int|None) — coord in body line, ComputerAction.text (str|None) — for type_text/key/scroll; preview-truncated, NOT shown raw in title, ComputerAction.app (str|None) — for open_app body line, ApprovalRequest.action (str) — the capability name 'computer.*' passed to gate.request, ApprovalRequest.args (dict) — carries x/y/text/app for body formatting, ApprovalRequest.description (str) — human '点击「发送」按钮' tail of body line, ApprovalRequest.risk (RiskLevel) — ALWAYS 'high' for computer.* (from Capability.risk), ApprovalRequest.call_id — gate.respond/daemon POST target, Capability.risk='high' (builtins.py:192-240, all 7 computer.* caps), Capability.reversible=False (builtins.py:193-241, all 7), Capability.kind='computer' (builtins.py:191-239), Capability.verify_hint ('GUI 动作无机检通道,验证走 L5 留痕…') — drives governance note rationale, not rendered verbatim
- **Backend source**: argos/perception/actions.py::ComputerAction (frozen dataclass; kind ActionKind Literal of 7 values screenshot|click|double_click|type_text|key|scroll|open_app, x/y int|None, text str|None, app str|None); argos/perception/executor.py::ComputerExecutor.dispatch → ComputerActionResult(ok, detail, artifact_path, size); argos/capability/builtins.py:189-244 register_builtins() — 7 Capability(name='computer.<kind>', kind='computer', risk='high', reversible=False, visibility='all', verify_hint=...); argos/approval.py::ApprovalGate.request(action, args, *, description, risk, timeout) → ApprovalRequest(action, args, description, risk, call_id, trigger?, secret_pattern?); argos/protocol/events.py:315 ComputerActionEvent(kind_action, x, y, text_preview, ok, detail, artifact_path) — the EXECUTION-result event (post-approval), distinct from the approval card.

**Visual layout**

A flow-mounted decision card (NOT a centered modal) that subclasses InlineChoice and overrides only its rendered content; the InlineChoice container chrome is reused verbatim.

OUTER CARD (from InlineChoice.DEFAULT_CSS + .risk-high):
  - container: `InlineChoice { height: auto; margin: 0 0 1 0; padding: 1 2; background: $raise; }`
  - left edge: `.risk-high { border-left: thick $fail; }` → 4px-equivalent thick rule in $fail (#F7768E). This reproduces the design's `border-left: 4px solid #F7768E`.
  - NOTE design HTML shows card bg `#1B1D29` = $raise — matches InlineChoice's `background: $raise` exactly. No override needed.

ROW-BY-ROW (top to bottom inside the card), each a child Static, markup=False:

1. TITLE (#ic-title, CSS `.risk-high #ic-title { color: $fail; text-style: bold }`):
   EXACT string: "⛔ 计算机控制 · 硬确认 [high · 不可逆]"
   (design: color #F7768E font-weight 700 → $fail bold. The stock InlineChoice title `◓ 审批请求 [risk]` is REPLACED — ⛔ not ◓, plus the "[high · 不可逆]" suffix.)

2. BODY (#ic-body, CSS `#ic-body { color: $ink-bright }`):
   EXACT string: the action line, e.g. "computer.click (412, 280) — 点击「发送」按钮"
   Format string: f"{action} ({x}, {y}) — {description}" for coord actions;
                  f"{action} — {description}" for screenshot/open_app (no coords);
   ($ink-bright #ECEEF5 — design line `computer.click (412, 280) — 点击「发送」按钮` color #ECEEF5.)

3. GOVERNANCE NOTE (new Static id="hc-gov", CSS `color: $ink-faint`):
   EXACT verbatim string (design line, #525A73 = $ink-faint):
   "Seatbelt 无法约束全局屏幕/鼠标资源 — 审批门、账本、审计是唯一治理层"

4. SPACER: one blank line (design has a 6px gap div). Achieve via `margin-top: 1` on the options block, OR a 1-high empty Static. Prefer CSS margin to avoid an extra widget.

5. OPTIONS (#ic-options, Rich Text via _options_text override):
   Line 1 (cursor here by default): "▸ 1  仅此一次"  — prefix "▸ " in `bold $eye` (#D9A85C), label "1  仅此一次" in `bold $ink-bright` (#ECEEF5).
   Line 2:                          "  4  拒绝"     — two-space indent, label "4  拒绝" in `$ink-dim` (#7E869C).
   CRITICAL: deny is numbered "4" (literal, NOT 2). Stock InlineChoice._options_text auto-numbers with f"{i+1}" → would render "2  拒绝". MUST override _options_text so option[1] shows digit "4". Keep glyph ▸ (U+25B8) and the cursor/non-cursor color logic identical to stock.

6. FOOTER INVARIANT (new Static id="hc-foot", CSS `color: $ink-faint`):
   EXACT verbatim string (design line, #525A73 = $ink-faint, margin-top 4px → CSS `margin-top: 1`):
   "每个 computer.* 动作恒 risk=high + reversible=False · 不受 Trust Dial 降级"

7. HINT (#ic-hint, from stock, CSS `#ic-hint { color: $ink-faint }`): stock renders "↑↓ 选择 · ↵ 确认 · 数字直选 · Esc 拒绝". Keep stock _hint_text() (escape_value is set so " · Esc 拒绝" appears). This is honest (Esc = deny = fail-closed).

WINDOW-CHROME HEADER (design rows 840-846: traffic-light dots + "ARGOS_COMPUTER_USE=1 · 需 macOS 辅助功能权限") and the bottom StatusBar line (row 861-863) are NOT part of this widget — they belong to the screen frame / StatusBar. The card itself is rows 850-859 only.

STATUSBAR (separate, existing widget — see wiring): while this card is mounted, StatusBar left-eye must show ◓ blocked. Stock _set_blocked_status(True) already does this via set_blocked → renders "◓ ... · 审批挂起 ..." in $unverif. Design row 862 shows the act-line in $fail ("◓ act · 硬确认挂起 · screenshot/click/type/key/scroll/open_app"); the existing StatusBar.-blocked class uses $unverif (orange ◓), which is the v3 spec §8.4 contract for blocked — keep StatusBar as-is (do NOT recolor it to $fail; the card's $fail left-edge carries the high-risk signal, StatusBar carries the blocked signal). No StatusBar change required.

**Behavior**

Reuses InlineChoice's full interaction core unchanged: on_mount dovetails focus + app.bell(); ↑/↓ moves ▸ cursor with wraparound; Enter confirms cursor option; digit keys 1/4 (must accept literal "4" → maps to option index 1, NOT key 2) direct-select; Esc → escape_value. FAIL-CLOSED: escape_value is HARDCODED to 'deny' in HardConfirmCard.__init__ (caller cannot override) — Esc, timeout, or any ambiguity = deny, never执行. Decision flow: _finish(value, '') is idempotent (_decided guard prevents double gate.respond), calls on_decide(value, '') (which does gate.respond(call_id, value) inline OR daemon POST /runs/{id}/approval/{call_id}), then self-destructs into a one-line summary Static "◕ 审批 computer.click → once" (or → deny) mounted after the card, removes itself, returns focus to #prompt. _choice_done() unblocks the FIFO queue and clears StatusBar blocked state when queue empties. Only ONE card active on screen at a time (FIFO via _choice_queue/_mount_next_choice). Options are FIXED to exactly [("once","仅此一次"),("deny","拒绝")] — no 'session'/'always' offered (an irreversible OS action must never be granted session/always-wide). digit-direct-select map override: '1'→once, '4'→deny; other digits ignored.

**Wiring (app.py)**

Rewire app.py::ApplicationsApp._handle_approval (defined ~line 2523, body ~2523-2582). Today it builds ONE stock InlineChoice with 4 options [once/session/always/deny] for ALL approvals via format_approval_title. Add a branch at the top of the non-AUTO path: `if req.action.startswith("computer."):` mount HardConfirmCard via the SAME `await self._enqueue_choice(lambda: HardConfirmCard(action=req.action, x=req.args.get('x'), y=req.args.get('y'), description=req.description, on_decide=_decide))` — _decide closure and _is_daemon branching (gate.respond vs _daemon_approval_post) are reused verbatim; only the widget class and its option set differ. Import: add `from argos.tui.widgets.hard_confirm_card import HardConfirmCard` near line 59 (next to InlineChoice import). The AUTO-level early-return at line 2530 STILL applies syntactically but is moot for computer.* because Capability.risk='high'+reversible=False means the gate must not auto-pass — confirm in _handle_approval that computer.* is never short-circuited by AUTO (if gate currently auto-passes AUTO for computer.*, that is a separate honesty bug to flag, not fixed here). No change to StatusBar (set_blocked already wired via _mount_next_choice→_set_blocked_status). No change to _on_computer_action (line 1439, renders post-execution ComputerActionEvent, unrelated to the approval card).

**Honesty rules**

1. risk is HARDCODED 'high' in the widget (add_class('risk-high')) — caller cannot pass a lower risk; computer.* is ALWAYS high+irreversible regardless of Trust Dial level (Capability.reversible=False at builtins.py, L2_IRREVERSIBLE_ONLY can never auto-pass it). 2. Title MUST contain '[high · 不可逆]' and the ⛔ glyph — never the soft ◓/审批请求 wording, so an irreversible OS action is never visually conflated with a routine approval. 3. Footer invariant line '每个 computer.* 动作恒 risk=high + reversible=False · 不受 Trust Dial 降级' is non-removable, non-parameterized text — states the governance contract truthfully. 4. Options offer ONLY 仅此一次/拒绝 — NO session/always; granting an irreversible global-screen action 'always' would be a fail-open lie. 5. Esc/timeout/ambiguity = deny (escape_value hardcoded 'deny') — fail-closed; never执行 on doubt. 6. The card is APPROVAL-time only; it never claims success. Execution success/failure is a SEPARATE ComputerActionEvent rendered by _on_computer_action with ✓/✗ from result.ok — ok=False MUST render '✗ … 失败:<detail>' (red/error kind_str='error'), never as success; screenshot ok=True records artifact path only and never emits a 'passed' verdict (spec §10 VLM red line). 7. risk-color discipline if ever generalized: low→$ink-dim, med→$unverif, high→$fail (from prototype riskC map); $pass-weak ≠ $pass firewall is irrelevant here (no verdict in this card) but must not be violated if a verdict ever appears. 8. confirmation_required is implicit-always for computer.* — the gate must reach this card (no silent allow); suggest_escalation/auto-escalation is N/A (the card never auto-escalates; it only ever asks the user).

**Open questions**

- Confirm _handle_approval's AUTO-level early-return (app.py:2530) does NOT auto-approve computer.* — if gate.level is AUTO it currently respond's 'always' for everything; computer.* must be exempt (high+irreversible should never YOLO-pass). Verify/flag separately.
- The 7th tool double_click is absent from the design's StatusBar enumeration 'screenshot/click/type/key/scroll/open_app' (6 listed) — backend has 7 (double_click included). StatusBar text is cosmetic; confirm whether to list all 7 or keep the design's 6-item abbreviation.
- Design body example uses 'computer.click' but Capability.name is also 'computer.click' — confirm ApprovalRequest.action passes the dotted capability name (it does, per builtins) so body line needs no remapping from ActionKind 'click' → 'computer.click'.


---

## Part C — Audit findings for existing widgets (screens 01–08)


### StartupSplash (启动 splash · 睁眼仪式) — `/Users/zc/Projects/argos/argos/tui/widgets/splash.py` — **minor_drift**
_maps to_: 视觉稿 screen 02「启动 splash」(.dc.html L179-204) + README §「02 · 启动 splash(睁眼仪式)」(L109-111) + §字形铁律 (L75-87)

- **[MEDIUM]** Color tokens are NOT applied per-segment. The design colors each element with a distinct token: eye ◉ = $eye-glow (#F0C078, with 18px glow per README L110), subtitle line = $ink-dim (#7E869C), hint line = $ink-faint (#525A73), the LIVE word = $pass (#9ECE6A). The widget instead renders the ENTIRE composed string (_compose_text) as one plain-text Static colored $ink-bright (DEFAULT_CSS L96: `color: $ink-bright`), or $eye-soft in plan mode (L97). So no per-segment token differentiation exists — every line is the same color. The eye is the worst case: design's focal gold-glow ◉ ($eye-glow) renders as flat $ink-bright with no glow.
  - _fix_: Stop emitting one flat string. Either (a) split the splash into child widgets / Rich markup spans so each segment carries its own token, or (b) build the text with Rich console markup, e.g. wrap the eye as `[$eye-glow]{eye}[/]`, the subtitle as `[$ink-dim]…[/]`, the LIVE/DEMO badge as `[$pass]LIVE[/]` / `[$unverif]DEMO 脚本演示[/]`, and the hint line as `[$ink-faint]…[/]`, and render with markup enabled. At minimum color the eye `$eye-glow` and the LIVE badge `$pass` to match the design's two load-bearing accents. Do not introduce raw hex — use the $token names from theme.py.
- **[LOW]** Subtitle leading label differs from the mock: design (L195) says `终端超级智能体`, code (L83) says `百眼智能体`. This is DESIGN drift, not code drift — the project was rebranded to 百眼智能体 / hundred-eyed agent on 2026-06-13, which post-dates the v0.9.2 mock. README L110 only specifies the subtitle abstractly as `副标题(版本 · 模型 · LIVE/DEMO)` and does not pin the brand word, so the code is the current source of truth. No code change needed; the mock string is stale.
  - _fix_: Leave code as-is (百眼智能体 is the current brand). If the design handoff HTML is regenerated, update L195 `终端超级智能体` → `百眼智能体` to match the rebrand so future audits don't re-flag it.
- **[LOW]** DEMO badge text elaborated beyond the mock: design/README show bare `DEMO`, code (L68) emits `DEMO 脚本演示`. Minor wording elaboration; consistent with the honesty-annotation intent (README L202 `DEMO 模式徽标橙…绝不假装有数据`).
  - _fix_: Acceptable as-is. If strict mock parity is wanted, shorten to `DEMO`; but the `脚本演示` suffix is honest and harmless. No action required.


### InlineChoice — `/Users/zc/Projects/argos/argos/tui/widgets/inline_choice.py` — **minor_drift**
_maps to_: 03 审批挂起 · 流内 InlineChoice (README §03); 06 plan mode · 规划审批 (README §06)

- **[MEDIUM]** Plan-mode left-edge + title color drift (breaks §06 'plan ≠ act, 冷靛蓝与金系分家'). README §06 requires the plan InlineChoice to have border-left $plan (#7AA2F7) and title in $plan. The widget's DEFAULT_CSS only defines three risk classes — risk-low ($hairline-lit #2E3142), risk-medium ($unverif #FF9E64), risk-high ($fail #F7768E) — with NO $plan variant. The plan call site (argos/tui/app.py:2670) passes risk="low", so the plan card renders a gray #2E3142 left edge and (via 'InlineChoice #ic-title { color: $unverif }' at inline_choice.py:88) an ORANGE #FF9E64 title — instead of the spec's cool-indigo $plan #7AA2F7 for both. Note format_approval_title is also not used for plan (it would force the act-domain '◓ 审批请求' prefix), so the title color must come from CSS, which has no plan branch.
  - _fix_: Add a plan variant to DEFAULT_CSS in inline_choice.py (after the risk-high rules, line 87-89): 'InlineChoice.risk-plan { border-left: thick $plan; }' and 'InlineChoice.risk-plan #ic-title { color: $plan; }'. Then extend __init__ (line 127) so risk=='plan' adds class 'risk-plan' (currently only low/high are special-cased, everything else falls to risk-medium). Finally change the plan call site argos/tui/app.py:2670 from risk="low" to risk="plan".
- **[LOW]** Plan-mode title string drift. Design screen 06 (视觉稿 line 372) shows the plan InlineChoice title as '◓ 计划已就绪 — 如何继续?' (◓ 半阖眼 prefix + that wording). The plan call site argos/tui/app.py:2658 passes title="Plan 审批" — missing the ◓ glyph entirely and using different wording. The widget renders title verbatim (Static markup=False at inline_choice.py:131), so the glyph/string must come from the caller.
  - _fix_: Change argos/tui/app.py:2658 to title="◓ 计划已就绪 — 如何继续?" to match the design string and supply the mandated ◓ glyph (consistent with the §字形铁律 — ◓ = 等用户决策).
- **[LOW]** Self-destruct summary line has no color token wired in this widget. README §03 (line 115) and 视觉稿 line 235/247 specify the post-decision summary '◕ 审批 python → once' must be $ink-faint (#525A73). _finish (inline_choice.py:248) mounts Static(summary_text, markup=False, classes="ic-summary") into the PARENT, but inline_choice.py's DEFAULT_CSS has no '.ic-summary' selector, so its color depends on an external/global rule or falls back to the parent's default foreground rather than being guaranteed $ink-faint.
  - _fix_: Either add a rule to the parent/global TUI CSS for '.ic-summary { color: $ink-faint; }', or build the summary as a Rich Text with explicit style $ink-faint hex (#525A73) like the option-text path does (inline_choice.py:144-157). Verify the actual rendered color in the live app — if a global .ic-summary rule already supplies $ink-faint elsewhere, this is satisfied and can be downgraded.
- **[LOW]** Plan-mode option labels are English, design shows Chinese. 视觉稿 lines 374-377 list the 4 plan options as '批准,开始执行 / 批准 + 自动接受编辑 / 继续规划 / 补充反馈后再规划'. The plan call site argos/tui/app.py:2661-2664 uses 'Approve and start' / 'Approve and accept edits' / 'Keep planning' / 'Refine with feedback'. Glyphs/structure (▸, numbering, ↑↓ hint) match; only the label language differs. The approval path (app.py:2576) by contrast uses Chinese labels matching §03, so this is an inconsistency within the same widget's callers.
  - _fix_: If the TUI's house language for transcript-facing labels is Chinese (the approval path already is), change app.py:2661-2664 labels to the design's Chinese strings: ('approve_start','批准,开始执行'), ('approve_accept_edits','批准 + 自动接受编辑'), ('keep_planning','继续规划'), ('refine','补充反馈后再规划'). If English is an intentional product decision, leave as-is and update the design spec instead — but the two callers should agree.


### VerdictBadge — `/Users/zc/Projects/argos/argos/tui/widgets/verdict_badge.py` — **minor_drift**
_maps to_: 视觉稿 "04 verify 四态" (HTML 253-278) + README §04 (118-123); §字形铁律 (75-91); §语义色 (55-62). Confirmed matching: glyphs ◉/◉/◔/◍ identical to design; tokens $pass/$fail/$unverif/$pass-weak are $token refs (no hardcoded hex) and theme.py hex (#9ECE6A/#F7768E/#FF9E64/#73A857) match design exactly; passed/failed=bold, unverifiable=normal as designed; label strings (verify passed / verify FAILED / 无法验证 / 自验证通过(较弱) / ⤷ 注解) match; markup=False per honesty rule; no left-edge border (design has none for verdict rows).

- **[MEDIUM]** self-verified 态缺斜体。设计明确要求 self-verified 为斜体:视觉稿 HTML line 275 用 `font-style: italic`;README line 122 写「`$pass-weak` 斜体」;连本文件 docstring line 7 也声明 `◍ $pass-weak italic`。但 DEFAULT_CSS line 29 `VerdictBadge.verdict-self { color: $pass-weak; }` 只设颜色,未设 `text-style: italic`。这是真实 drift:E4 防火墙靠『斜体(弱通过) vs 加粗(强通过)』在视觉上区隔两者,缺斜体削弱了该诚实区隔(实现与其自身 docstring 也不一致)。对应 HTML line 275 / README line 122。
  - _fix_: verdict_badge.py line 29 改为 `VerdictBadge.verdict-self { color: $pass-weak; text-style: italic; }`。颜色 token 不动 —— $pass-weak 已正确(theme.py line 56 = #73A857,与设计一致),仅补 text-style;修后 CSS / docstring / 设计稿 三处一致。
- **[LOW]** failed 态两行都复用同一个 `verdict.detail`(line 97 line1 与 line 98 line2 均插 `{verdict.detail}`)。设计稿两行内容不同:line1 = `1 failed: test_resume_order`(本轮失败用例),line2 = `AssertionError: 事件顺序错位`(重试后根因)。当前实现使同一句话出现两次,不符合设计『首行=失败用例,注解行=根因』的信息层级。属内容层级 drift,非 token/glyph/label-string 硬错。对应 HTML line 267 / README line 120。
  - _fix_: line2 改用独立字段(如 verdict.failure_reason/root_cause);若 Verdict 数据类无此字段,则去掉 line 98 尾部 `· {verdict.detail}`,仅保留 `  ⤷ 重试 {verdict.attempts} 次后仍 failed`,避免逐字重复首行。


### TabStrip — `/Users/zc/Projects/argos/argos/tui/widgets/tab_strip.py` — **minor_drift**
_maps to_: 05 组件变体 (TabStrip · daemon 多 run, line 311) + 07 daemon 多 run · idle 视图 (TabStrip, line 440); README §05 (line 125-127), §07 (line 133), §字形铁律 (lines 75-93)

- **[MEDIUM]** Missing bottom border. In the real daemon view (screen 07, line 440) the TabStrip carries `border-bottom: 1px solid #23252E` (= $hairline) to separate it from the transcript below. The widget's DEFAULT_CSS has no border at all — only `height: 1; background: $well; color: $ink-dim; padding: 0 2`. The component-variant card in screen 05 omits the border, but the canonical daemon layout (07) requires it.
  - _fix_: Add a bottom hairline to DEFAULT_CSS: `border-bottom: hkey $hairline;` (or `border-bottom: solid $hairline;` for a full rule) on the `TabStrip` selector, matching the #23252E ($hairline) separator under the TabStrip in screen 07. Use the $token, never the raw hex, in CSS.
- **[LOW]** Failed-tab glyph color is documented but never applied — internal contradiction. The module docstring (line 12) and `_STATE_ICON` comment (line 29) both state `◉` failed = "注视眼(红,$fail 色)", and theme.py reserves $fail (#F7768E) as "唯一的红" for failed verdicts (README §字形铁律 line 90: `error ◉ 失败`). But `render()` (lines 116-133) only ever colorizes the ACTIVE tab (bold #ECEEF5 on #23263A); every non-active tab — including a `failed`/`◉` run — falls through to the widget default `color: $ink-dim` (#7E869C), so a failed run renders gray, not red. The code does not do what its own docstring promises.
  - _fix_: Either (a) wrap the failed glyph in $fail markup in render() — e.g. for a non-active failed tab emit `[#F7768E]◉[/#F7768E] {title} {cost}` (hex is acceptable here because Rich Text markup cannot reference CSS $token names, matching the house pattern in status_bar.py's `_STYLE_EYE`), OR (b) if the intended design is that non-active TabStrip text stays uniformly $ink-dim (which is what screens 05/07 literally show — glyphs there are not individually tinted), delete the misleading '红/$fail 色' claims from lines 12 and 29. Pick one; today the code and its comments disagree.
- **[LOW]** `pending` maps to `◌`, which §字形铁律 (README line 80) defines as the *idle phase eye* ($eye-soft), not a run badge. README line 93 enumerates run badges as exactly `⏵运行 ⏸挂起 ⏹停止` — there is no pending/cancelled/completed run badge defined there (completed `◕` comes from the report-eye, lines 84 + screens 05/07). Reusing the idle eye `◌` for a pending run is defensible (pending ≈ not-yet-running ≈ idle) and no design screen shows a pending tab, but it is a glyph borrowed from the phase-eye dictionary rather than the run-badge set.
  - _fix_: Acceptable as-is, but if strictness is wanted, note that no design surface shows a `pending` tab; consider documenting that `◌` for pending is an intentional reuse of the $eye-soft idle eye (and ideally render it in $eye-soft rather than $ink-dim to match its dictionary color), or confirm pending tabs never reach the strip in daemon mode.


### StatusBar (always-on bottom status bar) — `/Users/zc/Projects/argos/argos/tui/widgets/status_bar.py` — **matches**
_maps to_: 视觉稿 05 组件变体 (StatusBar variants, lines 313-328) + 08 /context 可视化 ctx-warn StatusBar (lines 516-519); README sections 01 (line 106), 04 (line 116), 05 (line 127), 06 (line 130), 07 (line 133), 08 (line 136), §字形铁律 (lines 77-93), token table (lines 28-67)

- **[LOW]** Blocked-state eye glyph color drift vs the proto. Design screen 05 (视觉稿 line 316) renders the blocked row with text in $unverif (#FF9E64) but paints the ◓ eye glyph itself in $eye gold (color: #D9A85C). The code colors the blocked eye orange instead: status_bar.py line 239 `eye_style = _STYLE_BLOCKED if self._blocked else _STYLE_EYE` forces the ◓ to _STYLE_BLOCKED (#FF9E64 / $unverif). Net effect: in blocked state the eye is orange in code vs gold in the proto. Note this is genuinely ambiguous — the design's other warn/crit/alert rows (lines 315/317/318 act/verify) keep the eye gold $eye while the line goes orange/red, and README line 116 only says '眼 ◓' without specifying the eye color, so the proto's own gold ◓ on line 316 is the only concrete reference. Severity low: the whole bar is already $unverif via the -blocked CSS class, so an orange eye is internally consistent and arguably more legible; it just doesn't reproduce the proto's exact two-tone (gold eye + orange text).
  - _fix_: To match the proto exactly, keep the blocked eye gold like every other phase eye: change status_bar.py line 239 to always use _STYLE_EYE for the glyph, i.e. `eye_style = _STYLE_EYE` (drop the `_STYLE_BLOCKED if self._blocked` branch). The surrounding -blocked CSS class already tints the rest of the line $unverif, so the result is gold ◓ on an orange bar, exactly as 视觉稿 line 316 shows. Alternatively, leave as-is and confirm with design that an all-orange blocked bar (eye included) is the intended honest-emphasis treatment — both are defensible; flagging only because it diverges from the one explicit proto render.


### top_bar (TopBar) — `/Users/zc/Projects/argos/argos/tui/widgets/top_bar.py` — **minor_drift**
_maps to_: 视觉稿 screen 01 (act, lines 58-62), screen 04 (plan, lines 351-355), screen 07 (daemon idle, lines 433-437); README §188 "通用终端布局 · 2. TopBar" + §字形铁律 (glyph dictionary, README lines 75-91) + design-token tables (README lines 28-64)

- **[MEDIUM]** Trust 徽标 missing entirely. README §188 (通用终端布局 · 2. TopBar) spells the right side as '模式徽标 + LIVE/DEMO + Trust 徽标(Ln · 标签,L4 红 ⏻)'. The code's badges() (lines 84-106) only emits plan / YOLO / DEMO 脚本演示 / 未配 key / LIVE — there is no Trust-level badge ('Ln · 标签' e.g. 'L1 · 只有危险操作才问'), and no L4-red '⏻' indicator. README §152 also makes the L4-red TopBar light a behavior 铁律 ('升 L4 顶栏亮红灯'). So a required design element of this exact widget is absent.
  - _fix_: Add a trust-level state to TopBar: extend set_state() with a trust_level/trust_label pair (or a TrustState), and in badges()/render() append a final badge 'L{n} · {label}'. Style it $eye-soft (#A8854A) for L0–L3 and $fail (#F7768E) with a leading '⏻ ' glyph for L4, per README §152/§188. Order it last (after LIVE/DEMO), matching '模式徽标 + LIVE/DEMO + Trust 徽标'.
- **[MEDIUM]** Glyph-dictionary gap: 'blocked' phase ◓ is unmapped. §字形铁律 (README line 85) defines '◓ | blocked(审批/硬确认挂起) | $unverif'. _PHASE_GLYPH (lines 33-40) has no 'blocked' key and render() has no $unverif branch, so a blocked phase falls through _PHASE_GLYPH.get(self._phase, '◌') to the idle glyph ◌ in $eye-soft — silently rendering a hard-confirm-pending state as idle. This violates the honesty intent of the status eye (a pending-approval state must read as blocked, not idle).
  - _fix_: Add 'blocked': '◓' (U+25D3) to _PHASE_GLYPH, and in render() color it $unverif (#FF9E64 / _UNVERIF) — e.g. eye_color = _UNVERIF if self._phase == 'blocked' else (_EYE_SOFT if self._phase == 'idle' else _EYE).
- **[LOW]** TopBar background is declared via the $surface slot (DEFAULT_CSS line 45: 'background: $surface') rather than the spec's $well token. README §188 and screens 01/04/07 (background: #0E0F15) require $well. The inline comment notes the $surface slot holds the $well value (#0E0F15) so the rendered color is correct, but it is token indirection rather than a direct $well reference — the README color 铁律 says widgets should reference the semantic $token.
  - _fix_: If the theme exposes a $well CSS variable, change DEFAULT_CSS to 'background: $well;' so the token name matches the spec. If only the Textual base slot $surface is resolvable in the bare-App test path (as the comment implies), keep $surface but the value is already #0E0F15 — no visual drift, leave the comment in place.


### Transcript (UserMessage / AssistantMessage / SystemLine / Transcript container) — `/Users/zc/Projects/argos/argos/tui/widgets/transcript.py` — **matches**
_maps to_: 视觉稿 screen "01 act 主界面" lines 64-96 (Transcript column); README §"01 · act 主界面" Transcript 内容 (line 104), §Design Tokens (lines 28-64), §字形铁律 (lines 75-93)

- **[LOW]** AssistantMessage delegates all rendering to Textual's built-in Markdown widget (DEFAULT_CSS only sets background: transparent; margin; padding) and never pins body/emphasis colors. Body prose IS correct by inheritance — theme.py sets foreground="#C8CCDA" (= $ink), matching the design's assistant prose color $ink (#C8CCDA, visual稿 line 71). But the design's inline strong-emphasis identifiers (visual稿 lines 71/82/90: `replay.py`, `resume()`, `seq` rendered $ink-bright #ECEEF5 per README line 104 'assistant 强调 → $ink-bright') are left to Markdown's own bold styling rather than being pinned to $ink-bright. This is the only spot where a design-specified token ($ink-bright) is not explicitly bound in the widget; it relies on Textual's Markdown default for emphasis instead.
  - _fix_: Optionally add an explicit emphasis rule to AssistantMessage.DEFAULT_CSS to pin Markdown strong/bold to the design token, e.g. `AssistantMessage .markdown--em, AssistantMessage strong { color: $ink-bright; }` (confirm the exact Textual Markdown emphasis selector against the installed textual version). No change needed to body color — $ink is already correct via theme foreground. Do NOT hardcode #ECEEF5; use $ink-bright.
- **[LOW]** Default thinking label is the hardcoded string '思考中…' in show_thinking(), whereas the design's screen-01 example shows a contextual label '⠼ 回归测试中… 12s' ($eye) (visual稿 line 94, README line 104). This is not a drift in the transcript widget — the spinner glyph/color/elapsed-time live in ThinkingIndicator (separate file, out of audit scope) and the label is caller-supplied; '思考中…' is only the generic fallback. Flagged for completeness only.
  - _fix_: No fix required in transcript.py. Verify the live caller (loop/app event handler) passes a contextual label + elapsed seconds so the rendered line reads like the design's '回归测试中… 12s' rather than the bare default. The $eye color and ⠼ Braille spinner are ThinkingIndicator's responsibility — audit that widget separately.


### code_action — `/Users/zc/Projects/argos/argos/tui/widgets/code_action.py` — **minor_drift**
_maps to_: 01 act 主界面 — CodeActionBlock (视觉稿 lines 73-91); README §字形铁律 + Design Tokens + screen 01 mapping

- **[LOW]** Module docstring header art (line 6) is stale and misdescribes the widget's own render. It reads `⎿ ✓ 结果 ← ✓ muted / ✗ 红` — branch glyph `⎿` (U+23BF) and check/cross glyphs `✓`/`✗`. The actual implementation (line 60 placeholder, lines 74-75 result) renders the branch as `└` (U+2514) and the result glyphs as `◕` (ok=True) / `◉` (ok=False) — which is exactly what the design uses (视觉稿 lines 78 and 90: `└ ◕ …`). The class docstring (lines 27-28) already correctly states `└ ◕` / `└ ◉`, so the file contradicts itself. This is internal doc drift only; the rendered output matches the design.
  - _fix_: Edit line 6 from `  ⎿ ✓ 结果              ← ✓ muted / ✗ 红;>12 行折叠` to `  └ ◕ 结果              ← ◕ 阅毕眼 $pass / ◉ 红瞳 $fail;>12 行折叠`. No render/code change is needed — the implementation already matches the design's `└ ◕` / `└ ◉`.


### ThinkingIndicator (思考态 spinner) — `/Users/zc/Projects/argos/argos/tui/widgets/thinking.py` — **minor_drift**
_maps to_: 视觉稿 screen "01 act 主界面" line 94 (ThinkingIndicator: `⠼ 回归测试中… 12s`, color #D9A85C); README §字形铁律 line 93 (Braille spinner) + line 104 (思考态 `⠼ 回归测试中… 12s`, `$eye`) + line 85 (`◓` reserved for blocked/`$unverif`)

- **[HIGH]** The widget renders a `◓` glyph during its ~4s 'eye slow-blink' (_BLINK_GLYPHS = ("◉", "◓"); render() swaps the Braille frame to ◓ while _blink_ticks_left > 0). The design handoff — declared the highest-priority spec source (README line 217) — describes the thinking spinner ONLY as the cycling Braille set `⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏` (README line 93) with NO eye-blink. Worse, `◓` is a RESERVED glyph in the Glyph Dictionary (README line 85): it means 'blocked (审批/硬确认挂起)' and must be colored `$unverif` (orange). Rendering `◓` in `$eye` gold inside a normal act-thinking spinner collides with that reserved semantics and violates the 金橙分家 color law (金系 $eye = chrome/attention only; 橙系 $unverif = '真相不确定' only). A user trained on the dictionary will read a flashed `◓` as 'approval pending / blocked', not 'thinking'.
  - _fix_: Remove the blink overlay entirely so the spinner is pure cycling Braille per spec. Concretely: delete `_BLINK_GLYPHS`, `_BLINK_INTERVAL_TICKS`, `_BLINK_HOLD_TICKS`, the `_blink_ticks_left` field, and the blink branches in `_tick()` and `render()`; `render()` becomes `glyph = _FRAMES[self._frame]` unconditionally. If an eye-blink behavior is genuinely wanted, it must come from a real spec section (the cited '§6.1 §6.2' does not exist anywhere in this design handoff) and must NOT reuse the reserved `◓`/blocked glyph.
- **[MEDIUM]** The widget's module docstring and class docstring cite 'TUI v3 spec §6.1 §6.2' and '§6.2' as the source for the braille frames AND the eye slow-blink. No §6.1/§6.2 (and no '慢眨'/'眼慢眨'/blink) exists in the design handoff (README.md or 视觉稿.dc.html). This is a phantom-spec citation justifying behavior the actual spec does not contain — an honesty/provenance drift in the doc itself.
  - _fix_: Drop the §6.1/§6.2 and 眼慢眨 references. Point the docstring at the real source: README §字形铁律 line 93 (Braille spinner) and the 01-act 视觉稿 line 94 (`⠼ 回归测试中… 12s`, `$eye`).
- **[LOW]** Default label is `思考中…` while the design's screen-01 reference string is `回归测试中…`. This is contextual (the label is caller-supplied via set_label), so it is a soft default rather than a hard mismatch — but if no caller sets a context-specific label, the on-screen text will not match the visual's exemplar.
  - _fix_: Acceptable as a generic default since the design string is task-specific; ensure callers pass a context label (e.g. the loop sets '回归测试中…' / '思考中…' as appropriate). No code change strictly required.


### PromptArea + SlashMenu — `/Users/zc/Projects/argos/argos/tui/widgets/prompt.py` — **minor_drift**
_maps to_: 视觉稿 01 act 主界面 (PromptArea, lines 161-165) + 05 组件变体 Slash 菜单 (lines 289-305); README §05 Slash 菜单 (line 126), §快照 PromptArea (line 191), §字形铁律 / 颜色铁律

- **[MEDIUM]** Slash 菜单选中行缺少设计要求的 $raise-2 背景色块。视觉稿 line 293 把整条选中行(▸ + 命令名 + 描述)包在 background:#23263A(=$raise-2)里;README §126「选中行 bg $raise-2 + ▸ 前缀」、§304「▸ $eye 选中 + $raise-2 底色块」也明确要求底色块。但代码里定义的 `SlashMenu .menu-selected { background: $raise-2; ... }`(prompt.py:179-183)是死规则:SlashMenu 是单个 Static,_render_items() 把所有行拼成一个 Rich Text 并 self.update(t)(prompt.py:226-238),没有任何 per-row 子 widget 去承载 menu-selected 类,所以 $raise-2 底色块从不渲染。实际选中态只靠 ▸ 前缀 + bold bright 文字表现,与设计的「整行高亮块」不符。
  - _fix_: 在 _render_items() 里给选中行的 Text span 直接加背景。例如把选中行的前缀/命令名/描述统一用带 bgcolor 的 Rich Style 渲染:t.append('▸ ', style=Style(color=_EYE, bgcolor='#23263A', bold=True)),命令名 style=Style(color=_INK_BRIGHT, bgcolor='#23263A', bold=True),描述 style=Style(color=_INK_DIM, bgcolor='#23263A');非选中行保持无背景。背景色保持与 $raise-2(#23263A)一致(已在文件顶部 hex 常量风格内补一个 _RAISE_2 = '#23263A' 注明对应 $raise-2)。删除失效的 .menu-selected CSS 块,避免误导。
- **[LOW]** PromptArea 输入框带了 `border: tall $eye-soft`(app.py:108,#prompt),但设计中 PromptArea 无边框——视觉稿 line 162-165 的输入区只是 bg #0E0F15(=$well)+ 顶部一条 border-top:1px #23252E(=$hairline 发丝);README §191「PromptArea:bg $well,顶发丝」、line 162 同样只画顶发丝,没有四面 tall 边框,更没有 $eye-soft 金色边。注:该样式位于 app.py 而非被审计的 prompt.py 文件本身,但属于同一 PromptArea 渲染表面,故一并标出。
  - _fix_: 在 app.py:108 把 `#prompt { border: tall $eye-soft; }` 改为只画顶发丝以贴合设计:`#prompt { border: none; border-top: solid $hairline; background: $well; }`(Textual 支持单边 border)。$well 背景可保留在 PromptArea.DEFAULT_CSS(prompt.py:50 已有 background: $well)。


### ActivityPanel (右侧诚实活动栏) — `/Users/zc/Projects/argos/argos/tui/widgets/activity_panel.py` — **minor_drift**
_maps to_: 01 act 主界面 (HTML lines 98-158) / 06 plan mode ActivityPanel (HTML lines 383-405) / 07 daemon idle 视图 ActivityPanel (HTML lines 451-482); README §字形铁律 + §01/§06/§07

- **[HIGH]** Verdict 区段未做三态语义着色。设计稿 idle 视图 (HTML line 478) 把 `passed` 染 `#9ECE6A`=`$pass`;README §裁决 (lines 119-121) 规定 passed→`$pass`、failed→`$fail`、unverifiable→`$unverif`。代码 on_verdict (line 324) 发的是纯文本 `f"{status}{tag}\n{cmd}\n{detail}"`,因 _Section 全程 markup=False (line 50),三种状态都渲染成默认 $ink 同色,丢失了诚实铁律要求的颜色冗余(unverif 是『永远三重冗余』之一)。
  - _fix_: Verdict 行按状态注入 token 颜色:passed→$pass、failed→$fail、unverifiable→$unverif、self-verified→$pass-weak。由于 _Section 用 markup=False,需改用富文本渲染(如对该行用 Text/Rich Segment 着色,或单独一个允许 markup 的子 Static 只放 status 词),不能直接开 markup=True(正文 detail 可能含 [...] 会崩)。
- **[MEDIUM]** 缓存 sparkline 未用 $cyan。设计稿 act 视图 (HTML line 149) `cache ▁▃▄▆▇▆▇▇ 9216` 整行染 `#7DCFFF`=`$cyan`(冷色=省钱语义)。代码 on_cost (line 299) 发纯文本 `cache {spark} {cache_read}`,无颜色 token,渲染成默认 ink。字形 ▁▂▃▄▅▆▇ 与文案对,仅缺色。
  - _fix_: 把 `cache {spark} {cache_read}` 这一行用 $cyan 着色(同 Verdict 那样走富文本渲染绕开 markup=False)。
- **[MEDIUM]** 上下文进度条未着色。设计稿 (HTML line 155) 填充格 `▓▓▓`=`$eye`(#D9A85C)、空格 `░░░░░░░`=`$ink-ghost`(#3A4055,代码 theme 同值),百分比 `34%`=`$ink-dim`。代码 on_context (line 308-311) 发纯文本 `{bar} {pct}%`,▓/░ 字符正确但全是默认色,丢失金/幽灵双色对比。
  - _fix_: 进度条填充段染 $eye、空段染 $ink-ghost、尾部百分比染 $ink-dim(富文本分段着色)。
- **[LOW]** 任务进度条目 (TODO/phase) 字形正确但未按 dim/bright/faint 着色。README §字形铁律 line 87 规定『◕ 完成(dim)· ◉ 进行中(bright)· ◌ 待办(faint)』;设计稿 act 视图 (HTML lines 105-107) 把 in_progress 行染 `#ECEEF5`=`$ink-bright`、completed/pending 行染 `$ink-dim`/`$ink-faint`。代码 _render_todos (lines 246-250) 与 _render_phases (line 236) 字形对 (◕/◉/◌、◔/◉/❂/◕),但发纯文本无亮度分级。
  - _fix_: 进行中条目整行染 $ink-bright、完成染 $ink-dim、待办染 $ink-faint(富文本逐行着色)。
- **[LOW]** 成本行 token 数未做 k 缩写。设计稿 (HTML line 147) 显示 `↑12.4k ↓3.1k`,代码 on_cost (line 300) 发原始整数 `↑{tokens_in} ↓{tokens_out}`(如 ↑12400 ↓3100),宽度与设计稿不一致。注意:tier 短标签 `[son]`、$ 成本格式均与设计一致,仅 token 计数缺千分缩写。
  - _fix_: 对 tokens_in/tokens_out 加千分缩写(≥1000 → `{n/1000:.1f}k`),与设计稿 `↑12.4k ↓3.1k` 对齐;StatusBar 同口径也用同一格式化。


### workflow_panel — `/Users/zc/Projects/argos/argos/tui/widgets/workflow_panel.py` — **minor_drift**
_maps to_: 视觉稿 screen 11 「Dynamic Workflows · 进度树」 (lines 619-668) + README §11 (lines 154-157) + README §字形铁律 (lines 75-91)

- **[MEDIUM]** No per-glyph Rich color. The whole progress tree is emitted as one flat plain-text string (`_compose_text` returns '\n'.join(lines), passed to Static with markup=False). The 视觉稿 (screen 11) explicitly colors each phase glyph: done `◕` = #9ECE6A ($pass) [line 643], act `◉` = #D9A85C ($eye) [line 644], verify `❂` = #D9A85C ($eye) [line 645]. README §字形铁律 confirms the token mapping: `◉` act → $eye, `❂` verify → $eye, `◕` report/done → $eye or $pass [lines 82-84]. Current code renders all glyphs in the default border-inherited foreground with zero differentiation, so a 'done/pass' glyph and an 'error' glyph look identical in color — exactly the kind of state-blindness the honesty rule warns against. This matches the 'WorkflowPanel Polish Spec — Per-Glyph Rich Color' design intent flagged today.
  - _fix_: Switch _compose_text to build a Rich `rich.text.Text` (not a plain str) so each glyph can be stylized independently while keeping the surrounding agent_id/phase/note literal. Because markup=False is a hard TUI rule (agent_id/note may contain `[...]`), do NOT switch to markup; instead use Text.append(glyph, style=...) for the glyph and Text.append(plain_text) for the rest. Map: error glyph `◉` → theme $fail (#F7768E); done/report `◕` → $pass (#9ECE6A); act `◉` and verify `❂` and plan `◔` → $eye (#D9A85C). Build a per-phase style dict (e.g. `_PHASE_STYLE = {'plan': 'eye', 'act': 'eye', 'verify': 'eye', 'report': 'pass', 'done': 'pass', 'error': 'fail'}`) referencing theme tokens, never raw hex literals.
- **[LOW]** Synthesis line and honest-notes lines have no dim styling. 视觉稿 renders `─ 综合结论:…` in #7E869C ($ink-dim) [line 646] and each `· …` note in #525A73 ($ink-faint) [line 647]; README §11 calls notes the '诚实注记' tier [line 155]. Current code appends '  ─ 综合结论:' + synthesis and '    · ' + note as undifferentiated default-foreground text (lines 95-97), losing the visual hierarchy that marks synthesis/caveats as secondary metadata.
  - _fix_: When emitting the synthesis line, style it with $ink-dim and each note line with $ink-faint via Text.append(..., style='ink-dim' / 'ink-faint') in the same Rich-Text refactor. Use theme token names, not hex.
- **[LOW]** Header '工作流:<name>' is not bold/$ink-bright. README §11 specifies the first line `工作流:<name>` is `$ink-bright` 加粗 (bold) [line 155], and 视觉稿 line 642 renders it color #ECEEF5 ($ink-bright) with font-weight:700. Current code (line 82) emits the header as plain default-foreground, non-bold text.
  - _fix_: Style the header line with bold + $ink-bright in the Rich-Text build (Text.append(head, style='bold #ECEEF5') — preferably reference the theme $ink-bright token rather than the literal hex).


### DiffView — `/Users/zc/Projects/argos/argos/tui/widgets/diff_view.py` — **minor_drift**
_maps to_: README §Tokens (颜色铁律) + §字形铁律; screen 01 "act 主界面" diff result line `└ ◕ 已写入 argos/replay.py(+1 −1)` (视觉稿 line 90). No standalone diff screen exists; DiffView is the code's own v3 widget per its docstring (spec §4.5).

- **[MEDIUM]** Diff body colors bypass theme tokens. The widget renders the unified diff via rich.syntax.Syntax(self._unified, "diff", theme="monokai"). Monokai's diff palette is OFF-token: added lines render as #A6E22E and removed lines as #FF4689. The README §Tokens color iron-rule (颜色铁律) states ① 禁止在 widget 里硬编码 hex,一律引用 $token, and that the ONLY green is $pass #9ECE6A and the ONLY red is $fail #F7768E. Monokai's #A6E22E / #FF4689 match neither. The docstring even advertises '红绿 diff 高亮' (red/green diff) but routes it through a third-party theme instead of the project's $pass / $fail tokens.
  - _fix_: Do not delegate diff add/remove coloring to Monokai. Either (a) build a custom Rich Syntax theme that maps Generic.Inserted -> theme $pass (#9ECE6A) and Generic.Deleted -> theme $fail (#F7768E), or (b) render the diff line-by-line as Rich Text, coloring '+' lines with the $pass hex and '-' lines with the $fail hex pulled from theme.py (single source). Keep context/hunk lines on $ink / $ink-dim. Goal: the only green in the diff is $pass and the only red is $fail, per the iron-rule.
- **[LOW]** Added-line green (#A6E22E from Monokai) collides with the design's function-name highlight color. In screen 01 (视觉稿 line 76) #A6E22E is the Monokai color used for FUNCTION names in CodeActionBlock code highlighting (e.g. `run`, `patch`). Using that same #A6E22E for 'added line' makes 'added' and 'function call' visually identical, which the token system deliberately separates ($pass is semantic 'good/added', not a syntax color).
  - _fix_: Resolved by the same fix above — map added lines to $pass #9ECE6A (distinct from the function-name green) rather than reusing Monokai's #A6E22E.
