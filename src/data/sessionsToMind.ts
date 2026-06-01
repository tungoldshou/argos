// sessionsToMind.ts — turn real Hermes sessions (/api/sessions) into the central
// "memory brain" graph for the browser, where local files (~/.hermes, transcripts)
// are unreachable and the REST API is the only real data source.
//
// Structure: Hermes (self) → one node per session (topic), each session linked to
// its model (source) and a short preview memory (memory). Shared models bridge
// sessions, so the same model used across sessions becomes one connective node.
import type { NodeType } from './types';
import type { BuiltMind, RawNode } from './mind';

/** A row from Hermes GET /api/sessions (only the fields we use). */
export interface RawSession {
  id: string;
  model?: string | null;
  title?: string | null;
  preview?: string | null;
  message_count?: number;
  tool_call_count?: number;
  started_at?: number | null;
  last_active?: number | null;
}

// A readable session title: explicit title → trimmed preview → short id.
function sessionLabel(s: RawSession): string {
  const t = (s.title ?? '').trim();
  if (t) return t.slice(0, 48);
  const p = (s.preview ?? '').replace(/\s+/g, ' ').trim();
  if (p) return p.slice(0, 48) + (p.length > 48 ? '…' : '');
  return `session ${s.id.slice(0, 8)}`;
}

// First clause of the preview, used as a short "what was recalled" memory node.
// Strips a leading "原目标:" / "goal:" label so the node carries the actual goal,
// not the label word. Splits on sentence punctuation (Chinese colon ：kept as a
// label separator, not a clause break).
function previewMemory(s: RawSession): string | null {
  let p = (s.preview ?? '').replace(/\s+/g, ' ').trim();
  if (!p) return null;
  p = p.replace(/^(原目标|目标|goal|task)\s*[:：]\s*/i, '');
  const clause = p.split(/[。．;\n]|(?<![a-zA-Z0-9]):\s/)[0].trim();
  return clause ? clause.slice(0, 44) : null;
}

/**
 * Build the brain from real Hermes sessions.
 * Returns null when there are no sessions so the caller can fall back to seed.
 */
export function sessionsToMind(sessions: RawSession[]): BuiltMind | null {
  if (!sessions || sessions.length === 0) return null;

  const nodes: RawNode[] = [];
  const edges: [number, number, number][] = [];
  const byLabel = new Map<string, RawNode>();
  const add = (label: string, type: NodeType, topic: string | null): RawNode => {
    const existing = byLabel.get(label);
    if (existing) return existing;
    const n: RawNode = { id: nodes.length, label, type, topic };
    nodes.push(n);
    byLabel.set(label, n);
    return n;
  };

  const self = add('Hermes', 'self', null);
  const seen = new Set<string>();
  const link = (a: number, b: number, w: number) => {
    if (a === b) return;
    const k = a < b ? `${a}-${b}` : `${b}-${a}`;
    if (seen.has(k)) return;
    seen.add(k);
    edges.push([a, b, w]);
  };

  // newest first, cap so the graph stays legible
  const ordered = [...sessions]
    .sort((a, b) => (b.last_active ?? b.started_at ?? 0) - (a.last_active ?? a.started_at ?? 0))
    .slice(0, 40);

  for (const s of ordered) {
    const sess = add(sessionLabel(s), 'topic', s.id);
    sess.topic = s.id;
    link(self.id, sess.id, 1);

    if (s.model) {
      const model = add(s.model, 'source', null);
      link(sess.id, model.id, 0.6);
    }
    const mem = previewMemory(s);
    if (mem) {
      const m = add(mem, 'memory', s.id);
      link(sess.id, m.id, 0.5);
    }
  }

  return { nodes, edges, self };
}
