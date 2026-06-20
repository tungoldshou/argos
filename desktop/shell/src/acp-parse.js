/**
 * ACP envelope and event parsing.
 *
 * Design contract:
 *   - Unknown event kinds → { kind: "unknown", raw } forward-compatible fallback.
 *     Never throws, never drops.
 *   - parseEnvelope returns null for structurally invalid JSON or missing v/seq/kind.
 */
// AUTO-SYNCED from sdk — do not edit; regenerate with: npm run sync-to-shell
const KNOWN_KINDS = new Set([
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
export function parseEnvelope(raw) {
    let obj;
    try {
        obj = JSON.parse(raw);
    }
    catch {
        return null;
    }
    if (obj === null || typeof obj !== "object" || Array.isArray(obj)) {
        return null;
    }
    const o = obj;
    // Minimal structural check: v, seq, kind required.
    if (typeof o["v"] !== "number")
        return null;
    if (typeof o["seq"] !== "number")
        return null;
    if (typeof o["kind"] !== "string")
        return null;
    return o;
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
export function parseEvent(kind, data) {
    if (!KNOWN_KINDS.has(kind)) {
        const unknown = { kind: "unknown", raw: data };
        return unknown;
    }
    // For all known kinds the Python daemon serializes the event as a flat dict
    // whose keys match the dataclass fields exactly.  We merge kind + data fields
    // into a single object (the TypedEvent discriminated union shape).
    return { kind, ...data };
}
/**
 * Convenience: parse a full SSE data line (the JSON string after "data: ")
 * into an Envelope and its typed event in one call.
 *
 * Returns null when the envelope cannot be parsed.
 */
export function parseSSELine(line) {
    const envelope = parseEnvelope(line);
    if (envelope === null)
        return null;
    const event = parseEvent(envelope.kind, envelope.data);
    return { envelope, event };
}
