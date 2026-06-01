// memoryToMind.ts — 把 Argos 自己跑过的任务记忆变成中央"记忆大脑"图。
//
// 这是真实的记忆知识图谱:每条记忆 = agent 跑完的一个任务。结构:
//   Argos (self) → 每个任务一个节点 (topic) → 该任务的 verdict(principle/memory)
//   + 用到的模型 (component/source)。共享的模型在多个任务间桥接成一个节点。
//
// 没有记忆时返回 null —— 独立 agent 还没积累记忆,调用方据此显示诚实空态,
// 而不是编造假记忆填满画面(那违反产品的诚实原则)。
import type { NodeType } from './types';
import type { BuiltMind, RawNode } from './mind';

/** 一条记忆 = agent 跑完的一个任务(来自 Python 侧 /memory 端点)。 */
export interface MemoryRecord {
  id: string;
  goal: string;
  /** verify 裁决:passed / failed / unverifiable / none(无 verify) */
  verdict?: string | null;
  model?: string | null;
  /** 任务沉淀的简短事实/结论(可选,agent 学到的东西) */
  fact?: string | null;
  ts?: number | null;
}

// 任务标题:goal 截断到可读长度。
function goalLabel(m: MemoryRecord): string {
  const g = (m.goal ?? '').replace(/\s+/g, ' ').trim();
  if (!g) return `task ${m.id.slice(0, 8)}`;
  return g.length > 46 ? g.slice(0, 46) + '…' : g;
}

// verdict → 人类可读的记忆节点文案(只有真有 verdict 时才建)。
function verdictMemory(m: MemoryRecord): string | null {
  switch (m.verdict) {
    case 'passed': return '✓ 通过验证';
    case 'failed': return '✗ 未通过(已诚实记录)';
    case 'unverifiable': return '? 无法验证(未假装通过)';
    default: return null;
  }
}

/**
 * 从真实任务记忆构建大脑图。
 * 无记忆 → 返回 null,调用方回退到空态。
 */
export function memoryToMind(records: MemoryRecord[]): BuiltMind | null {
  if (!records || records.length === 0) return null;

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

  const self = add('Argos', 'self', null);
  const seen = new Set<string>();
  const link = (a: number, b: number, w: number) => {
    if (a === b) return;
    const k = a < b ? `${a}-${b}` : `${b}-${a}`;
    if (seen.has(k)) return;
    seen.add(k);
    edges.push([a, b, w]);
  };

  // newest first,限量保持图可读
  const ordered = [...records]
    .sort((a, b) => (b.ts ?? 0) - (a.ts ?? 0))
    .slice(0, 40);

  for (const m of ordered) {
    const task = add(goalLabel(m), 'topic', m.id);
    task.topic = m.id;
    link(self.id, task.id, 1);

    const vm = verdictMemory(m);
    if (vm) {
      const vn = add(vm, 'memory', m.id);
      link(task.id, vn.id, 0.6);
    }

    if (m.fact && m.fact.trim()) {
      const fn = add(m.fact.trim().slice(0, 44), 'memory', m.id);
      link(task.id, fn.id, 0.5);
    }

    if (m.model && m.model.trim()) {
      // 模型节点共享(同一模型跑多个任务 → 一个节点桥接它们)
      const mn = add(m.model.trim(), 'source', null);
      link(task.id, mn.id, 0.4);
    }
  }

  return { nodes, edges, self };
}
