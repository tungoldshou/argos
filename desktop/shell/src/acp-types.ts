/**
 * Argos ACP (Argos Client Protocol) TypeScript types.
 *
 * Hand-aligned to argos_agent/protocol/events.py (v6 P0-P5b).
 * Each Event type comment marks the corresponding Python source line.
 *
 * Design invariants (from argos-v6-design.md §2.2 + §4):
 *   - VerdictStatus is a three-state enum; "unverifiable" MUST be rendered as-is.
 *     The SDK provides NO API to map it to success/green.
 *   - Envelope.seq is monotonically increasing; clients MUST use it to detect
 *     dropped/out-of-order frames.
 */
// AUTO-SYNCED from sdk — do not edit; regenerate with: npm run sync-to-shell

// ── Primitive aliases ────────────────────────────────────────────────────────

/** Wire-level verdict three-state. "unverifiable" MUST be rendered honestly.
 *  Python source: protocol/events.py → core/types.py VerdictStatus line ~13 */
export type VerdictStatus = "passed" | "failed" | "unverifiable";

/** AgentLoop phase. Python source: core/types.py Phase line ~14 */
export type Phase = "plan" | "act" | "verify" | "report";

/** Risk level. Python source: core/types.py RiskLevel line ~17 */
export type RiskLevel = "low" | "medium" | "high";

/** Approval decision. Python source: core/types.py DecisionKind line ~16 */
export type DecisionKind = "deny" | "once" | "session" | "always";

// ── Envelope ─────────────────────────────────────────────────────────────────

/**
 * ACP wire envelope. Python source: protocol/events.py §4 ACP Envelope line ~96
 *
 * v  – protocol version (currently 1)
 * seq – monotonically increasing frame counter; use to detect drops/reorder
 * kind – discriminant matching EventKind
 * id  – stable UUID for this event instance
 * ts  – Unix timestamp (float seconds)
 * session – session_id from POST /sessions
 * run – run_id this event belongs to (null for session-level events)
 * data – deserialized Event payload
 */
export interface Envelope<D = unknown> {
  v: number;
  seq: number;
  kind: string;
  id: string;
  ts: number;
  session: string;
  run: string | null;
  data: D;
}

// ── Verdict dataclass (nested inside VerifyVerdict) ──────────────────────────

/** Python source: core/types.py Verdict lines ~18-68 */
export interface Verdict {
  status: VerdictStatus;
  detail: string;
  verify_cmd: string | null;
  attempts: number;
  tampered: string[];
  self_verified: boolean;
}

// ── Receipt dataclass (nested inside ToolReceipt) ────────────────────────────

/** Python source: tools/receipts.py Receipt (HMAC-signed broker receipt) */
export interface Receipt {
  action: string;
  args: Record<string, unknown>;
  result: string;
  exit_code: number | null;
  ts: number;
  sig: string;
}

// ── Event payload types ──────────────────────────────────────────────────────

/** protocol/events.py TokenDelta line ~51 */
export interface TokenDeltaData {
  text: string;
}

/** protocol/events.py CodeAction line ~57 */
export interface CodeActionData {
  code: string;
  step: number;
}

/** protocol/events.py CodeResult line ~63 */
export interface CodeResultData {
  step: number;
  stdout: string;
  value_repr: string;
  exc: string;
  ok: boolean;
}

/** protocol/events.py FileDiff line ~73 */
export interface FileDiffData {
  path: string;
  added: number;
  removed: number;
  unified: string;
}

/** protocol/events.py ToolReceipt line ~83 */
export interface ToolReceiptData {
  receipt: Receipt;
}

/** protocol/events.py VerifyVerdict line ~88 */
export interface VerifyVerdictData {
  verdict: Verdict;
}

/** protocol/events.py PhaseChange line ~94 */
export interface PhaseChangeData {
  phase: Phase;
  actions: number;
}

/** protocol/events.py CostUpdate line ~101 */
export interface CostUpdateData {
  tokens_in: number;
  tokens_out: number;
  /** null when unit price is unknown — do NOT invent a cost figure */
  cost_usd: number | null;
  elapsed_s: number;
  cache_read: number;
  context_used: number;
  tier_name: string;
}

/** protocol/events.py ApprovalRequest line ~114 */
export interface ApprovalRequestData {
  call_id: string;
  action: string;
  args: Record<string, unknown>;
  description: string;
  risk: RiskLevel;
  trigger: string;
  secret_pattern: string | null;
}

/** protocol/events.py ApprovalResponse line ~131 */
export interface ApprovalResponseData {
  call_id: string;
  decision: DecisionKind;
}

/** protocol/events.py Escalation line ~138 */
export interface EscalationData {
  reason: string;
  attempts: number;
  last_failure: string;
}

/** protocol/events.py Error line ~145 */
export interface ErrorData {
  message: string;
  chain: string[];
}

/** protocol/events.py PlanUpdate line ~153 */
export interface PlanUpdateData {
  todos: Array<{
    content: string;
    status: "pending" | "in_progress" | "completed";
    activeForm?: unknown;
  }>;
}

/** protocol/events.py WorkflowProgress line ~161 */
export interface WorkflowProgressData {
  stage_id: string;
  agent_id: string;
  phase: string;
  note: string;
}

/** protocol/events.py WorkflowProposed line ~171 */
export interface WorkflowProposedData {
  name: string;
  description: string;
  preview: string;
  call_id: string;
}

/** protocol/events.py WorkflowDone line ~231 */
export interface WorkflowDoneData {
  name: string;
  synthesis: string;
  /** JSON serializes tuple as array; clients receive string[] */
  notes: string[];
}

/** protocol/events.py PlanRendered line ~241 */
export interface PlanRenderedData {
  plan_md: string;
}

/** protocol/events.py PlanDecisionRequest line ~302 (v6 §4 ACP) */
export interface PlanDecisionRequestData {
  call_id: string;
  plan_md: string;
}

/** protocol/events.py MemoryRecallEvent line ~317 (v6 §4 ACP) */
export interface MemoryRecallEventData {
  hits: string[];
}

/** hooks/events.py HookFired line ~27 */
export interface HookFiredData {
  event_name: string;
  command: string;
  success: boolean;
  returncode: number | null;
  elapsed_ms: number;
  timed_out: boolean;
  not_found: boolean;
  stop_reason: string | null;
  error: string | null;
  stdout: string;
}

/** lsp/events.py LspServerEvent line ~21 */
export interface LspServerEventData {
  server_name: string;
  status: "spawn" | "ready" | "crash" | "disabled" | "restart" | "exit";
  command: string;
  exit_code: number | null;
  elapsed_ms: number;
  error: string | null;
  cwd: string;
  timestamp_ms: number;
}

/** lsp/events.py LspDiagnosticEvent line ~33 */
export interface LspDiagnosticEventData {
  server_name: string;
  uri: string;
  count: number;
  severity_counts: Record<string, number>;
  cached: boolean;
  cwd: string;
}

/** skills_runtime/events.py SkillRunStart line ~33 */
export interface SkillRunStartData {
  skill_name: string;
  args: Record<string, unknown>;
  cwd: string;
  timestamp_ms: number;
}

/** skills_runtime/events.py SkillRunEnd line ~42 */
export type SkillVerdict = "passed" | "failed" | "partial" | "n_a" | "skipped";
export interface SkillRunEndData {
  skill_name: string;
  verdict: SkillVerdict;
  duration_ms: number;
  finding_count: number;
  error_count: number;
  cwd: string;
  timestamp_ms: number;
}

/** protocol/events.py CompactedEvent line ~183 */
export interface CompactedEventData {
  before: number;
  after: number;
  reduction_pct: number;
  triggered_by: "proactive" | "error";
  session_id: string;
}

/** protocol/events.py PrunedEvent line ~217 */
export interface PrunedEventData {
  before: number;
  after: number;
  removed: number;
  reduction_pct: number;
  aggressiveness: number;
  session_id: string;
}

/** protocol/events.py LedgerEntryEvent line ~198 (P3b §6) */
export interface LedgerEntryEventData {
  ts: number;
  run_id: string;
  seq: number;
  action: string;
  summary_human: string;
  risk: "low" | "medium" | "high";
  reversible: "yes" | "no" | "unknown";
  undo_state: "available" | "done" | "impossible";
}

/** protocol/events.py IntentConfirmRequest line ~250 (P4 §7) */
export interface IntentConfirmRequestData {
  call_id: string;
  confirmation_text: string;
  /** JSON serializes tuple as array; clients receive string[] */
  risk_flags: string[];
  card_json: Record<string, unknown>;
}

/** protocol/events.py IntentConfirmResponse line ~269 (P4 §7) */
export interface IntentConfirmResponseData {
  call_id: string;
  confirmed: boolean;
  revised_goal: string | null;
}

/** protocol/events.py ProactiveSuggestionEvent line ~283 (P5b §9)
 *
 * INVARIANT: requires_confirmation is ALWAYS true at the protocol level.
 * The SDK renders this field as-is and provides no API to override it.
 */
export interface ProactiveSuggestionEventData {
  suggestion_id: string;
  order_id: string;
  goal: string;
  reason_human: string;
  suggested_at: number;
  /** Protocol-level constant: always true. Clients MUST NOT treat as optional. */
  requires_confirmation: true;
}

/** protocol/events.py ComputerActionEvent line ~304 (P6a §10 computer use)
 *
 * Emitted by ComputerExecutor after each OS-level action execution.
 * text_preview is truncated to 80 chars to avoid leaking sensitive input.
 * ok=false means execution failed; detail contains a human-readable reason
 * (including permission guidance) but NOT the raw stack trace.
 */
export interface ComputerActionEventData {
  kind_action: string;
  x: number | null;
  y: number | null;
  text_preview: string;
  ok: boolean;
  detail: string;
  artifact_path: string | null;
}

// ── Discriminated union ───────────────────────────────────────────────────────

/**
 * All known event kinds.  Matches Python EventKind Literal
 * at protocol/events.py line ~28.
 */
export type EventKind =
  | "token_delta"
  | "code_action"
  | "code_result"
  | "file_diff"
  | "tool_receipt"
  | "verify_verdict"
  | "phase_change"
  | "cost_update"
  | "approval_request"
  | "approval_response"
  | "escalation"
  | "error"
  | "plan_update"
  | "workflow_progress"
  | "workflow_proposed"
  | "workflow_done"
  | "plan_rendered"
  | "plan_decision_request"
  | "memory_recall"
  | "hook_fired"
  | "lsp_server_event"
  | "lsp_diagnostic_event"
  | "skill_run_start"
  | "skill_run_end"
  | "compacted"
  | "pruned"
  | "ledger_entry"
  | "intent_confirm_request"
  | "intent_confirm_response"
  | "proactive_suggestion"
  | "computer_action";

/** Typed event — discriminated on `kind`. */
export type TypedEvent =
  | ({ kind: "token_delta" } & TokenDeltaData)
  | ({ kind: "code_action" } & CodeActionData)
  | ({ kind: "code_result" } & CodeResultData)
  | ({ kind: "file_diff" } & FileDiffData)
  | ({ kind: "tool_receipt" } & ToolReceiptData)
  | ({ kind: "verify_verdict" } & VerifyVerdictData)
  | ({ kind: "phase_change" } & PhaseChangeData)
  | ({ kind: "cost_update" } & CostUpdateData)
  | ({ kind: "approval_request" } & ApprovalRequestData)
  | ({ kind: "approval_response" } & ApprovalResponseData)
  | ({ kind: "escalation" } & EscalationData)
  | ({ kind: "error" } & ErrorData)
  | ({ kind: "plan_update" } & PlanUpdateData)
  | ({ kind: "workflow_progress" } & WorkflowProgressData)
  | ({ kind: "workflow_proposed" } & WorkflowProposedData)
  | ({ kind: "workflow_done" } & WorkflowDoneData)
  | ({ kind: "plan_rendered" } & PlanRenderedData)
  | ({ kind: "plan_decision_request" } & PlanDecisionRequestData)
  | ({ kind: "memory_recall" } & MemoryRecallEventData)
  | ({ kind: "hook_fired" } & HookFiredData)
  | ({ kind: "lsp_server_event" } & LspServerEventData)
  | ({ kind: "lsp_diagnostic_event" } & LspDiagnosticEventData)
  | ({ kind: "skill_run_start" } & SkillRunStartData)
  | ({ kind: "skill_run_end" } & SkillRunEndData)
  | ({ kind: "compacted" } & CompactedEventData)
  | ({ kind: "pruned" } & PrunedEventData)
  | ({ kind: "ledger_entry" } & LedgerEntryEventData)
  | ({ kind: "intent_confirm_request" } & IntentConfirmRequestData)
  | ({ kind: "intent_confirm_response" } & IntentConfirmResponseData)
  | ({ kind: "proactive_suggestion" } & ProactiveSuggestionEventData)
  | ({ kind: "computer_action" } & ComputerActionEventData);

/** Forward-compatible fallback for unknown event kinds */
export interface UnknownEvent {
  kind: "unknown";
  raw: unknown;
}

export type ParsedEvent = TypedEvent | UnknownEvent;

// ── ACP Command payloads (client → daemon) ────────────────────────────────────

export interface CreateSessionResponse {
  session_id: string;
}

export interface CreateRunRequest {
  goal: string;
  workspace?: string;
  model?: string;
  approval_level?: "observe" | "propose" | "confirm" | "auto";
  isolation?: "worktree" | "none";
  approval_timeout_s?: number;
  trust_level?: string;
}

export interface CreateRunResponse {
  run_id: string;
}

export interface ApprovalBody {
  decision: DecisionKind;
}

export interface PlanDecisionBody {
  call_id: string;
  action: string;
  feedback?: string;
}

export interface IntentConfirmBody {
  call_id: string;
  confirmed: boolean;
  revised_goal?: string | null;
}
