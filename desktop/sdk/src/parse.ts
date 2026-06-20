/**
 * ACP envelope and event parsing.
 *
 * Design contract:
 *   - Unknown event kinds → { kind: "unknown", raw } forward-compatible fallback.
 *     Never throws, never drops.
 *   - parseEnvelope returns null for structurally invalid JSON or missing v/seq/kind.
 */

import type { Envelope, ParsedEvent, TypedEvent, UnknownEvent } from "./types.js";

const KNOWN_KINDS = new Set<string>([
  "token_delta", "code_action", "code_result", "file_diff", "tool_receipt",
  "verify_verdict", "phase_change", "cost_update", "approval_request",
  "approval_response", "escalation", "error", "plan_update",
  "workflow_progress", "workflow_proposed", "workflow_done", "plan_rendered",
  "plan_decision_request", "memory_recall", "hook_fired",
  "lsp_server_event", "lsp_diagnostic_event",
  "skill_run_start", "skill_run_end",
  "compacted", "pruned", "ledger_entry",
  "proactive_suggestion",
  "computer_action",
]);

/**
 * Parse a raw JSON string into an Envelope.
 * Returns null if the string is not valid JSON or is missing required fields.
 */
export function parseEnvelope(raw: string): Envelope | null {
  let obj: unknown;
  try {
    obj = JSON.parse(raw);
  } catch {
    return null;
  }
  if (obj === null || typeof obj !== "object" || Array.isArray(obj)) {
    return null;
  }
  const o = obj as Record<string, unknown>;
  // Minimal structural check: v, seq, kind required.
  if (typeof o["v"] !== "number") return null;
  if (typeof o["seq"] !== "number") return null;
  if (typeof o["kind"] !== "string") return null;
  return o as unknown as Envelope;
}

/**
 * Parse the `data` payload of an Envelope into a typed event.
 *
 * Forward-compatible: unknown kinds yield { kind: "unknown", raw: data }
 * rather than throwing, so older SDK versions survive new server event kinds.
 *
 * @param kind - the kind discriminant from the envelope
 * @param data - the raw data payload (from envelope.data)
 */
export function parseEvent(kind: string, data: unknown): ParsedEvent {
  if (!KNOWN_KINDS.has(kind)) {
    const unknown: UnknownEvent = { kind: "unknown", raw: data };
    return unknown;
  }
  // For all known kinds the Python daemon serializes the event as a flat dict
  // whose keys match the dataclass fields exactly.  We merge kind + data fields
  // into a single object (the TypedEvent discriminated union shape).
  return { kind, ...(data as Record<string, unknown>) } as unknown as TypedEvent;
}

/**
 * Convenience: parse a full SSE data line (the JSON string after "data: ")
 * into an Envelope and its typed event in one call.
 *
 * Returns null when the envelope cannot be parsed.
 */
export function parseSSELine(line: string): { envelope: Envelope; event: ParsedEvent } | null {
  const envelope = parseEnvelope(line);
  if (envelope === null) return null;
  const event = parseEvent(envelope.kind, envelope.data);
  return { envelope, event };
}
