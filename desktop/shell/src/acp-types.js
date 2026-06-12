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
export {};
