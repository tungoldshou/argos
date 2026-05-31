// parseMemory.ts — turn the agent's real MEMORY.md / USER.md into a knowledge graph.
//
// Hermes stores memory as flat blocks separated by a "§" line. There are no
// headings, bullets, or wikilinks — so we derive structure: each block becomes a
// memory node, and we extract entities it mentions (URLs, @people, platforms,
// file paths, project/repo names) into shared nodes that wire blocks together.
// Shared entities appearing in multiple blocks are what give the brain density.
import type { NodeType } from './types';
import type { BuiltMind, RawNode } from './mind';

interface Extracted {
  label: string;
  type: NodeType;
}

// Platforms / tools the agent talks about — recognized case-insensitively.
const PLATFORM_WORDS: [RegExp, string][] = [
  [/飞书|feishu|lark/i, '飞书 Feishu'],
  [/微信|weixin|wechat/i, '微信 Weixin'],
  [/telegram/i, 'Telegram'],
  [/discord/i, 'Discord'],
  [/slack/i, 'Slack'],
  [/支付宝|蚂蚁财富|alipay/i, '支付宝'],
  [/知乎/i, '知乎'],
  [/v2ex/i, 'V2EX'],
  [/掘金/i, '掘金'],
  [/github/i, 'GitHub'],
  [/得物/i, '得物'],
];

const TOOL_WORDS: [RegExp, string][] = [
  [/\bmmx\b/i, 'mmx'],
  [/tavily/i, 'tavily-search'],
  [/akshare/i, 'akshare'],
  [/claude/i, 'Claude'],
  [/codex/i, 'Codex'],
  [/doubao|豆包/i, '豆包'],
  [/minimax|m2\.7/i, 'MiniMax'],
  [/hyperframes/i, 'HyperFrames'],
  [/hindsight/i, 'Hindsight'],
  [/mempalace/i, 'MemPalace'],
];

function extractEntities(text: string): Extracted[] {
  const out: Extracted[] = [];
  const seen = new Set<string>();
  const push = (label: string, type: NodeType) => {
    const key = type + ':' + label.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    out.push({ label, type });
  };

  // URLs / domains → source nodes
  for (const m of text.matchAll(/https?:\/\/([a-z0-9.-]+)[^\s)]*/gi)) {
    push(m[1].replace(/^www\./, ''), 'source');
  }
  for (const m of text.matchAll(/\b([a-z0-9-]+\.(?:com|cn|dev|sh|io|org|net))\b/gi)) {
    push(m[1], 'source');
  }
  // file paths → source nodes
  for (const m of text.matchAll(/(?:\/Users\/[^\s,，。)]+|~\/[^\s,，。)]+)/g)) {
    const p = m[0];
    push(p.length > 40 ? '…' + p.slice(-36) : p, 'source');
  }
  // people: David / Alex / @handles
  for (const m of text.matchAll(/\b(David|Alex)\b/g)) push(m[1], 'person');
  for (const m of text.matchAll(/@([A-Za-z0-9_一-龥-]+)/g)) push('@' + m[1], 'person');
  // platforms & tools
  for (const [re, label] of PLATFORM_WORDS) if (re.test(text)) push(label, 'source');
  for (const [re, label] of TOOL_WORDS) if (re.test(text)) push(label, 'skill');

  return out;
}

// Coarse topic for a block, from keyword presence — clusters blocks into lobes.
const TOPIC_RULES: [RegExp, string][] = [
  [/基金|投资|止盈|持仓|半导体|电网|股|quant|量化|stripe|p&l/i, '投资与基金'],
  [/飞书|微信|telegram|discord|slack|消息|群|bot|cookie|发布|推广|知乎|掘金|v2ex/i, '沟通与运营'],
  [/简历|resume|外贸|采购|得物|salomon|萨洛蒙|lululemon|远程|平台/i, '个人事务'],
  [/api|relay|中转|gateway|sub2api|proxy|备案|合规/i, 'API 网关业务'],
  [/skill|mcp|claude|codex|hermes|vision|mmx|model|memory|记忆|prompt|第一性/i, '智能体与工具'],
];
function topicOf(text: string): string {
  for (const [re, t] of TOPIC_RULES) if (re.test(text)) return t;
  return '其他记忆';
}

function shortLabel(block: string): string {
  // first sentence-ish, capped — used as the memory node's label
  const firstLine = block.split('\n')[0].trim();
  const clause = firstLine.split(/[。.，,；;：:]/)[0].trim() || firstLine;
  return clause.length > 26 ? clause.slice(0, 24) + '…' : clause;
}

/**
 * Build a knowledge graph from the raw MEMORY.md (+ optional USER.md).
 * Returns the same {nodes, edges, self} shape the engine consumes, or null
 * if there's nothing to parse (caller falls back to the seed graph).
 */
export function parseMemory(memory: string, user = ''): BuiltMind | null {
  const raw = [memory, user].filter(Boolean).join('\n§\n');
  const blocks = raw
    .split(/\n?§\n?/)
    .map((b) => b.trim())
    .filter((b) => b.length > 0);
  if (blocks.length === 0) return null;

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

  const self = add('Hermes', 'self');

  // topic (lobe) nodes are created lazily as blocks reference them
  const topicNode = (name: string): RawNode => {
    const n = add(name, 'topic');
    if (!n.topic) {
      n.topic = name;
      edges.push([self.id, n.id, 1]);
    }
    return n;
  };

  blocks.forEach((block, i) => {
    const topic = topicOf(block);
    const tn = topicNode(topic);
    const label = shortLabel(block) || `memory ${i + 1}`;
    // de-dupe identical memory labels by suffixing
    let memLabel = label;
    if (byLabel.has(memLabel)) memLabel = `${label} ·${i}`;
    const mem = add(memLabel, 'memory');
    mem.topic = topic;
    edges.push([tn.id, mem.id, 0.6]);

    // wire the memory to every entity it mentions (shared entities cross-link lobes)
    for (const e of extractEntities(block)) {
      if (e.label === memLabel) continue;
      const en = add(e.label, e.type);
      if (!en.topic) en.topic = topic;
      edges.push([mem.id, en.id, 0.5]);
    }
  });

  // drop self-less degenerate graphs
  if (nodes.length < 3) return null;
  return { nodes, edges, self };
}
