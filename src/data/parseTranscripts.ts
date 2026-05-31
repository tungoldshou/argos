// parseTranscripts.ts — turn Claude Code (and future Codex/Hermes) session
// traces into a cross-agent "mind" graph: what the agent touched, recalled, used.
//
// This is the Context Lens data layer. Input is the aggregated per-session traces
// the Rust backend extracts from ~/.claude/projects/*.jsonl (zero-install, local).
import type { NodeType } from './types';
import type { BuiltMind, RawNode } from './mind';

export interface ToolHit {
  tool: string;
  file?: string | null;
}
export interface SessionTrace {
  source: string; // "claude-code" | "codex" | "hermes"
  project: string;
  session: string;
  mtime: number;
  user_turns: number;
  assistant_turns: number;
  hits: ToolHit[];
}

// pretty project label from the encoded dir name (-Users-zc-Projects-argos → argos)
function projectLabel(project: string): string {
  const parts = project.replace(/^-+/, '').split('-').filter(Boolean);
  return parts[parts.length - 1] || project;
}

const SOURCE_LABEL: Record<string, string> = {
  'claude-code': 'Claude Code',
  codex: 'Codex',
  hermes: 'Hermes',
};

/**
 * Build a cross-agent graph from session traces.
 * Structure: each agent source is a topic (lobe). Projects, files, and tools
 * become nodes; sessions wire a project to the files/tools it touched.
 * Touch-frequency drives node radius downstream (degree-based, already in engine).
 */
export function parseTranscripts(traces: SessionTrace[]): BuiltMind | null {
  if (!traces || traces.length === 0) return null;

  const nodes: RawNode[] = [];
  const edges: [number, number, number][] = [];
  const byLabel = new Map<string, RawNode>();
  const add = (label: string, type: NodeType): RawNode => {
    const existing = byLabel.get(label);
    if (existing) return existing;
    const n: RawNode = { id: nodes.length, label, type, topic: null };
    nodes.push(n);
    byLabel.set(label, n);
    return n;
  };

  const self = add('Your agents', 'self');

  // one lobe per agent source present
  const sourceNode = (src: string): RawNode => {
    const label = SOURCE_LABEL[src] || src;
    const n = add(label, 'topic');
    if (!n.topic) {
      n.topic = label;
      edges.push([self.id, n.id, 1]);
    }
    return n;
  };

  // de-dupe edges
  const seenEdge = new Set<string>();
  const link = (a: RawNode, b: RawNode, w: number) => {
    if (a.id === b.id) return;
    const k = a.id < b.id ? `${a.id}-${b.id}` : `${b.id}-${a.id}`;
    if (seenEdge.has(k)) return;
    seenEdge.add(k);
    edges.push([a.id, b.id, w]);
  };

  for (const t of traces) {
    const lobe = sourceNode(t.source);
    const proj = add(projectLabel(t.project), 'source'); // project = a place it works
    if (!proj.topic) proj.topic = lobe.label;
    link(lobe, proj, 0.7);

    // files touched in this session → memory-ish nodes (what it "knows about")
    const fileCount = new Map<string, number>();
    const toolCount = new Map<string, number>();
    for (const h of t.hits) {
      if (h.file) fileCount.set(h.file, (fileCount.get(h.file) || 0) + 1);
      if (h.tool) toolCount.set(h.tool, (toolCount.get(h.tool) || 0) + 1);
    }
    // top files this session reached for (cap to keep the graph readable)
    [...fileCount.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8)
      .forEach(([file]) => {
        const fn = add(file, 'memory');
        if (!fn.topic) fn.topic = lobe.label;
        link(proj, fn, 0.5);
      });
    // tools it used → skill nodes (shared across sessions → cross-links lobes)
    [...toolCount.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6)
      .forEach(([tool]) => {
        const tn = add(tool, 'skill');
        if (!tn.topic) tn.topic = lobe.label;
        link(proj, tn, 0.4);
      });
  }

  if (nodes.length < 3) return null;
  return { nodes, edges, self };
}
