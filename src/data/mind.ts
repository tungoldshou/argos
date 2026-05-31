// mind.ts — Hermes's knowledge graph (the agent's mind).
import type { Cluster, CategoryStyle, GrowthSpec, NodeMeta, NodeType } from './types';

// Categories — bioluminescent palette, evenly spaced hues, harmonized L/C
export const CATS: Record<NodeType, CategoryStyle> = {
  self: { color: '#ffcf8f', glow: '#ffb152', label: 'Hermes' },
  topic: { color: '#ffb4a0', glow: '#ff7a5c', label: 'Domain' },
  memory: { color: '#6fe6da', glow: '#22c9b8', label: 'Memory' },
  skill: { color: '#c4a0ff', glow: '#9b6cff', label: 'Skill' },
  person: { color: '#8fe6a8', glow: '#3ed178', label: 'Person' },
  source: { color: '#86bcff', glow: '#4f93ff', label: 'Source' },
};

// Cluster authoring — members deduped by label, so shared nodes wire across domains
export const CLUSTERS: Cluster[] = [
  { topic: 'atlas-core', members: [
    ['repo: atlas-core', 'source'], ['CI · github actions', 'source'],
    ['deploy → ssh atlas-box', 'memory'], ['fixed memory-eviction race', 'memory'],
    ['prefer terse PR summaries', 'memory'],
    ['summarize-pull-requests', 'skill'], ['generate-release-notes', 'skill'], ['deploy-staging', 'skill'],
    ['streaming gateway', 'topic'], ['@you', 'person'], ['@lin · eng lead', 'person'],
  ] },
  { topic: 'long-horizon agents', members: [
    ['writing a paper on this', 'memory'], ['prefer terse PR summaries', 'memory'],
    ['scrape-arxiv-cs-ai', 'skill'], ['summarize-paper', 'skill'],
    ['arXiv · cs.AI', 'source'], ['Discord #research', 'source'],
    ['memory architectures', 'topic'], ['tool use', 'topic'], ['streaming gateway', 'topic'], ['@you', 'person'],
  ] },
  { topic: 'deploy & ops', members: [
    ['deploy-staging', 'skill'], ['backup-postgres', 'skill'],
    ['on fail → rollback + ping #ops', 'memory'], ['vault creds · never log', 'memory'],
    ['SSH · atlas-box', 'source'], ['Docker', 'source'], ['@ops', 'person'],
  ] },
  { topic: 'comms & inbox', members: [
    ['triage-inbox', 'skill'], ['transcribe-voice-note', 'skill'], ['morning-briefing', 'skill'],
    ['Telegram', 'source'], ['Slack', 'source'], ['Email', 'source'], ['WhatsApp', 'source'],
    ['standup 9:15 — brief before', 'memory'], ['@you', 'person'],
  ] },
  { topic: 'finance', members: [
    ['finance-monthly-report', 'skill'], ['Stripe', 'source'], ['Bank API', 'source'],
    ['P&L on the 1st', 'memory'],
  ] },
  { topic: 'knowledge ingest', members: [
    ['watch-rss-feeds', 'skill'], ['scrape-arxiv-cs-ai', 'skill'],
    ['RSS feeds', 'source'], ['Web search', 'source'], ['daily digest', 'topic'], ['arXiv · cs.AI', 'source'],
  ] },
  { topic: 'tools & MCP', members: [
    ['execute_code', 'skill'], ['browser automation', 'skill'], ['voice-mode', 'skill'],
    ['MCP · github', 'source'], ['MCP · postgres', 'source'], ['MCP · puppeteer', 'source'],
    ['Web search', 'source'], ['tool use', 'topic'], ['@you', 'person'],
  ] },
  { topic: 'who you are', members: [
    ['SOUL.md · terse, dry wit', 'memory'], ['prefer terse PR summaries', 'memory'],
    ['peer, not assistant', 'memory'], ['you ship on Fridays', 'memory'], ['@you', 'person'],
  ] },
];

// extra cross-links (by label) that give the brain connective tissue
export const CROSS: [string, string][] = [
  ['prefer terse PR summaries', 'summarize-pull-requests'],
  ['morning-briefing', 'arXiv · cs.AI'], ['morning-briefing', 'RSS feeds'], ['morning-briefing', 'Telegram'],
  ['deploy-staging', 'CI · github actions'], ['deploy-staging', 'Docker'], ['deploy-staging', 'SSH · atlas-box'],
  ['summarize-pull-requests', 'repo: atlas-core'], ['generate-release-notes', 'streaming gateway'],
  ['scrape-arxiv-cs-ai', 'Discord #research'], ['summarize-paper', 'memory architectures'],
  ['triage-inbox', 'Email'], ['transcribe-voice-note', 'WhatsApp'], ['watch-rss-feeds', 'daily digest'],
  ['backup-postgres', 'vault creds · never log'], ['finance-monthly-report', 'Stripe'],
  ['@lin · eng lead', 'summarize-pull-requests'], ['tool use', 'memory architectures'],
  ['execute_code', 'deploy-staging'], ['browser automation', 'scrape-arxiv-cs-ai'],
  ['MCP · github', 'summarize-pull-requests'], ['MCP · postgres', 'backup-postgres'],
  ['browser automation', 'Web search'], ['voice-mode', 'transcribe-voice-note'],
  ['SOUL.md · terse, dry wit', 'prefer terse PR summaries'], ['MCP · puppeteer', 'browser automation'],
];

// metadata for the detail panel, keyed by label (sparse — engine fills defaults)
export const META: Record<string, NodeMeta> = {
  'execute_code': { detail: 'Programmatic Tool Calling — collapses multi-step pipelines into one inference call.', uses: 142, learned: 'core tool', src: 'built-in' },
  'browser automation': { detail: 'Headless browser via the puppeteer MCP server — navigate, click, extract, screenshot.', uses: 96, learned: 'via MCP', src: 'mcp' },
  'voice-mode': { detail: 'Real-time speech in/out: Whisper STT + Nous Portal TTS, across CLI, Telegram, and Discord VC.', uses: 63, learned: 'feature', src: 'built-in' },
  'MCP · github': { detail: 'Model Context Protocol server exposing 14 GitHub tools — issues, PRs, repos, actions.', uses: 188, learned: 'connected via stdio', src: 'mcp' },
  'MCP · postgres': { detail: 'Read-only query access to the prod replica through MCP.', uses: 31, learned: 'connected via stdio', src: 'mcp' },
  'SOUL.md · terse, dry wit': { detail: 'Global personality file — terse, dry wit, no preamble, treats you as a peer.', uses: 1240, learned: 'from ~/.hermes/SOUL.md', src: 'personality' },
  'summarize-pull-requests': { kind: 'skill', detail: 'Reads merged PRs, clusters by theme, posts a terse digest.', uses: 214, learned: 'from Slack · #eng, 38d ago', src: 'self-authored' },
  'morning-briefing': { detail: 'Overnight messages + calendar + arXiv, delivered before standup.', uses: 41, learned: 'scheduled, 38d ago', src: 'self-authored' },
  'scrape-arxiv-cs-ai': { detail: 'Pulls new cs.AI papers, ranks by relevance to your projects.', uses: 188, learned: 'self-initiated, 36d ago', src: 'self-authored' },
  'deploy-staging': { detail: 'CI-gated deploy to atlas-box over SSH inside a hardened sandbox.', uses: 27, learned: 'from Discord · #ops, 29d ago', src: 'taught by @you' },
  'prefer terse PR summaries': { detail: 'Bullet points, no preamble, always link the diff.', uses: 188, learned: 'inferred from feedback', src: 'preference' },
  'on fail → rollback + ping #ops': { detail: 'When a deploy fails, roll back automatically and alert #ops.', uses: 27, learned: 'standing rule', src: 'rule' },
  'vault creds · never log': { detail: 'Prod secrets live in vault://atlas/pg and must never be logged.', uses: 31, learned: 'standing rule', src: 'rule' },
  'standup 9:15 — brief before': { detail: 'Daily standup is 9:15 AM PT; the briefing must land before it.', uses: 41, learned: 'preference', src: 'preference' },
  'writing a paper on this': { detail: 'You are drafting a paper on long-horizon agents — flag relevant work.', uses: 140, learned: 'project context', src: 'project' },
  '@you': { detail: 'Primary operator. Reachable on Telegram, Slack, WhatsApp, Email.', uses: 1240, learned: 'owner', src: 'person' },
};

// growth backlog — nodes that "bloom" into the graph over time
export const GROWTH: GrowthSpec[] = [
  { label: 'cache arXiv embeddings', type: 'skill', near: 'knowledge ingest' },
  { label: 'detect flaky CI tests', type: 'skill', near: 'atlas-core' },
  { label: 'you ship on Fridays', type: 'memory', near: 'atlas-core' },
  { label: 'summarize-thread', type: 'skill', near: 'comms & inbox' },
  { label: 'retrieval-augmented memory', type: 'topic', near: 'long-horizon agents' },
];

export interface RawNode {
  id: number;
  label: string;
  type: NodeType;
  topic: string | null;
}
export type RawEdge = [a: number, b: number, weight: number];

export interface BuiltMind {
  nodes: RawNode[];
  edges: RawEdge[];
  self: RawNode;
}

// Build node + edge lists (dedupe members by label)
export function buildMind(): BuiltMind {
  const nodes: RawNode[] = [];
  const edges: RawEdge[] = [];
  const byLabel = new Map<string, RawNode>();
  const add = (label: string, type: NodeType): RawNode => {
    const existing = byLabel.get(label);
    if (existing) return existing;
    const n: RawNode = { id: nodes.length, label, type, topic: null };
    nodes.push(n);
    byLabel.set(label, n);
    return n;
  };
  const self = add('Hermes', 'self');
  CLUSTERS.forEach((cl) => {
    const tn = add(cl.topic, 'topic');
    tn.topic = cl.topic;
    edges.push([self.id, tn.id, 1]);
    cl.members.forEach(([label, type]) => {
      const n = add(label, type);
      if (!n.topic) n.topic = cl.topic;
      edges.push([tn.id, n.id, 0.6]);
    });
  });
  const E = new Set(edges.map((e) => e[0] + '-' + e[1]));
  CROSS.forEach(([a, b]) => {
    const na = byLabel.get(a);
    const nb = byLabel.get(b);
    if (na && nb) {
      const k = na.id + '-' + nb.id;
      const k2 = nb.id + '-' + na.id;
      if (!E.has(k) && !E.has(k2)) {
        edges.push([na.id, nb.id, 0.5]);
        E.add(k);
      }
    }
  });
  return { nodes, edges, self };
}

/**
 * Merge several BuiltMinds into one cross-agent graph.
 * Nodes are deduped by label, so a file/tool/person mentioned in more than one
 * source becomes a SINGLE shared node — that shared node is exactly what wires
 * the different agents' lobes together (the Context Lens "one mind" effect).
 * All sources collapse under a single `self` node (the first non-null's label,
 * or "Your agents").
 */
export function mergeMinds(parts: (BuiltMind | null | undefined)[], selfLabel = 'Your agents'): BuiltMind | null {
  const valid = parts.filter(Boolean) as BuiltMind[];
  if (valid.length === 0) return null;
  if (valid.length === 1) return valid[0];

  const nodes: RawNode[] = [];
  const edges: RawEdge[] = [];
  const byLabel = new Map<string, RawNode>();
  const add = (label: string, type: NodeType, topic: string | null): RawNode => {
    const existing = byLabel.get(label);
    if (existing) {
      // promote to self if any source treats it as self; keep first topic
      if (type === 'self') existing.type = 'self';
      if (!existing.topic && topic) existing.topic = topic;
      return existing;
    }
    const n: RawNode = { id: nodes.length, label, type, topic };
    nodes.push(n);
    byLabel.set(label, n);
    return n;
  };

  const self = add(selfLabel, 'self', null);
  const seenEdge = new Set<string>();

  for (const part of valid) {
    // map this part's node ids → merged ids (folding the part's self into ours)
    const remap = new Map<number, number>();
    for (const n of part.nodes) {
      const merged = n.id === part.self.id ? self : add(n.label, n.type, n.topic);
      remap.set(n.id, merged.id);
    }
    for (const [a, b, w] of part.edges) {
      const ma = remap.get(a)!;
      const mb = remap.get(b)!;
      if (ma === mb) continue;
      const k = ma < mb ? `${ma}-${mb}` : `${mb}-${ma}`;
      if (seenEdge.has(k)) continue;
      seenEdge.add(k);
      edges.push([ma, mb, w]);
    }
  }
  return { nodes, edges, self };
}
