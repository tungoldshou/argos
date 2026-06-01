// mind.ts — Argos's knowledge graph (the agent's mind).
// 这张图讲 Argos 真实的能力,不是编的故事:护城河(verify 硬门禁 / 诚实防线)、
// 智能内核(LangGraph + MiniMax)、工具系统、契约层、运行模式 —— 每个节点都对应
// 代码库里真实存在的东西。脑图展示真有的东西,符合产品的诚实原则。
import type { Cluster, CategoryStyle, GrowthSpec, NodeMeta, NodeType } from './types';

// Categories — 记忆图谱语义(memoryToMind 用 self/topic/memory/source):
//   self=Argos · topic=跑过的任务 · memory=任务沉淀(verdict/事实) · source=用到的模型。
// skill/person 当前记忆图不产出,保留供未来扩展。
export const CATS: Record<NodeType, CategoryStyle> = {
  self: { color: '#ffcf8f', glow: '#ffb152', label: 'Argos' },
  topic: { color: '#ffb4a0', glow: '#ff7a5c', label: 'Task' },
  memory: { color: '#6fe6da', glow: '#22c9b8', label: 'Memory' },
  skill: { color: '#c4a0ff', glow: '#9b6cff', label: 'Skill' },
  person: { color: '#8fe6a8', glow: '#3ed178', label: 'Person' },
  source: { color: '#86bcff', glow: '#4f93ff', label: 'Model' },
};

// Cluster authoring — members deduped by label, so shared nodes wire across domains
export const CLUSTERS: Cluster[] = [
  { topic: 'verify gate', members: [
    ['exit code is ground truth', 'memory'], ['fail-closed by default', 'memory'],
    ['bounce fake completion', 'memory'], ['run_command', 'skill'],
    ['verify isolation', 'source'], ['three-state verdict', 'source'],
    ['contract layer', 'topic'], ['runtime modes', 'topic'],
  ] },
  { topic: 'honesty firewall', members: [
    ['never flatter', 'memory'], ['say "I am stuck" honestly', 'memory'],
    ['tampering is visible', 'memory'], ['no fake green light', 'memory'],
    ['escalation path', 'source'], ['HONESTY system prompt', 'source'],
    ['verify gate', 'topic'],
  ] },
  { topic: 'agent core', members: [
    ['LangGraph loop', 'source'], ['MiniMax-M3', 'source'],
    ['context compaction', 'skill'], ['streaming events', 'source'],
    ['replaceable provider', 'memory'], ['tool use', 'topic'],
  ] },
  { topic: 'tools', members: [
    ['read_file', 'skill'], ['write_file', 'skill'], ['edit_file', 'skill'], ['run_command', 'skill'],
    ['workspace cage', 'memory'], ['command whitelist', 'memory'],
    ['FastAPI service', 'source'], ['tool use', 'topic'],
  ] },
  { topic: 'contract layer', members: [
    ['5 domain templates', 'skill'], ['missing-field detection', 'skill'],
    ['rest-api contract', 'source'], ['db-schema contract', 'source'], ['state-machine contract', 'source'],
    ['structured goals only', 'memory'],
  ] },
  { topic: 'runtime modes', members: [
    ['sandbox isolation', 'skill'], ['project mode', 'skill'],
    ['guard files', 'memory'], ['work in your own repo', 'memory'],
    ['verify isolation', 'source'],
  ] },
];

// extra cross-links (by label) that give the brain connective tissue
export const CROSS: [string, string][] = [
  ['exit code is ground truth', 'three-state verdict'], ['fail-closed by default', 'no fake green light'],
  ['bounce fake completion', 'escalation path'], ['say "I am stuck" honestly', 'escalation path'],
  ['tampering is visible', 'guard files'], ['tampering is visible', 'project mode'],
  ['verify isolation', 'workspace cage'], ['run_command', 'command whitelist'],
  ['LangGraph loop', 'streaming events'], ['MiniMax-M3', 'replaceable provider'],
  ['context compaction', 'LangGraph loop'], ['HONESTY system prompt', 'never flatter'],
  ['5 domain templates', 'missing-field detection'], ['structured goals only', 'contract layer'],
  ['workspace cage', 'sandbox isolation'], ['project mode', 'work in your own repo'],
  ['FastAPI service', 'streaming events'], ['run_command', 'verify gate'],
];

// metadata for the detail panel, keyed by label (sparse — engine fills defaults)
export const META: Record<string, NodeMeta> = {
  'exit code is ground truth': { detail: 'verify 命令的退出码是唯一裁决标准 —— agent 说"完成"不算,命令退出 0 才算。', uses: 0, learned: 'core principle', src: 'moat' },
  'fail-closed by default': { detail: '无法确认就判定未通过。宁可 bounce 回去重试,也不放过一次假完成。', uses: 0, learned: 'core principle', src: 'moat' },
  'bounce fake completion': { detail: 'agent 称完成但 verify 不过 → 强制带着真实失败重试,而不是接受谎言。', uses: 0, learned: 'verify gate', src: 'moat' },
  'three-state verdict': { detail: '通过 / 未通过 / 无法验证 —— 第三态杜绝"沉默假绿灯"。', uses: 0, learned: 'verify gate', src: 'component' },
  'verify isolation': { detail: 'verify 文件放在 agent 写不到的目录,防止它"贿赂测谎仪"(改测试求通过)。', uses: 0, learned: 'anti-cheat', src: 'component' },
  'never flatter': { detail: '不献媚、不吹嘘、不假装完成。HONESTY 系统提示在每次调用注入。', uses: 0, learned: 'honesty firewall', src: 'soul' },
  'say "I am stuck" honestly': { detail: '反复修仍不过时,诚实升级求助人类,而非编一个能过的假答案。', uses: 0, learned: 'escalation', src: 'soul' },
  'tampering is visible': { detail: '项目模式下 agent 技术上能改测试,但改了 run 结束会警告 —— 篡改可见,而非假装隔离。', uses: 0, learned: 'project mode', src: 'soul' },
  'LangGraph loop': { detail: 'agent 主循环基于 LangGraph create_agent —— 工具调用、verify 中间件、压缩都挂在这。', uses: 0, learned: 'agent core', src: 'component' },
  'MiniMax-M3': { detail: '当前模型,经 Anthropic 兼容端接入。可替换 —— 灵魂是"让便宜模型可靠",不绑某个模型。', uses: 0, learned: 'provider', src: 'component' },
  'context compaction': { detail: '长任务上下文超阈值自动摘要压缩(LangChain SummarizationMiddleware)。', uses: 0, learned: 'agent core', src: 'tool' },
  'run_command': { detail: '白名单内执行命令(node/python/pytest/cargo/git…),关在 workspace 牢笼里。', uses: 0, learned: 'tools', src: 'tool' },
  'workspace cage': { detail: '文件工具的路径被锁在 workspace 内,越界即拒 —— agent 动不了你不让它动的地方。', uses: 0, learned: 'tools', src: 'principle' },
  '5 domain templates': { detail: 'rest-api / db-schema / state-machine / config / generic 五种契约模板,给结构化目标补漏项。', uses: 0, learned: 'contract layer', src: 'tool' },
  'project mode': { detail: '让 agent 在你自己的项目里干活、跑你自己的测试 —— 懂技术用户的真实场景。', uses: 0, learned: 'runtime', src: 'tool' },
};

// growth backlog — nodes that "bloom" into the graph over time
export const GROWTH: GrowthSpec[] = [
  { label: 'auto verify-cmd for non-coders', type: 'skill', near: 'verify gate' },
  { label: 'cost-aware routing', type: 'topic', near: 'agent core' },
  { label: 'more domain contracts', type: 'skill', near: 'contract layer' },
  { label: 'keychain key storage', type: 'memory', near: 'runtime modes' },
  { label: 'multi-step verify chains', type: 'topic', near: 'verify gate' },
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

// 空记忆大脑:只有一个 Argos 自我节点。独立 agent 还没积累记忆时用这个 ——
// 诚实地"空",等真跑出任务记忆再长出来,而不是 fallback 到编造的 seed。
export function buildEmptyMind(): BuiltMind {
  const self: RawNode = { id: 0, label: 'Argos', type: 'self', topic: null };
  return { nodes: [self], edges: [], self };
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
  const self = add('Argos', 'self');
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
