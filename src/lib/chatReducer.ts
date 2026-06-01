// chatReducer.ts — 把 agent SSE 事件流归并成有序 Block 序列(纯函数、不可变)。
// 一个 turn = 一次用户输入 + agent 该轮产生的 blocks(文字/活动/诚实/错误,按到达顺序)。
// 渲染层负责把"连续 activity blocks"折叠成一个 ActivityTrail。
import type { AgentEvent } from './agent';

export type Block =
  | { kind: 'text'; text: string; streaming: boolean }
  | { kind: 'activity'; call: string; result?: string }
  | { kind: 'honesty'; type: 'verify_failed' | 'escalation' | 'tampering'; detail: string }
  | { kind: 'error'; text: string };

export interface Turn {
  id: string;
  user: string;
  blocks: Block[];
}

/** 追加一个新 turn(用户输入)。返回新数组。 */
export function startTurn(turns: Turn[], user: string, id: string): Turn[] {
  return [...turns, { id, user, blocks: [] }];
}

// 不可变地替换最后一个 turn 的 blocks。
function withBlocks(turns: Turn[], blocks: Block[]): Turn[] {
  if (turns.length === 0) return turns;
  const last = turns[turns.length - 1];
  return [...turns.slice(0, -1), { ...last, blocks }];
}

// 把当前正在流式的 text block 定稿(streaming=false)。没有 streaming block 时直接返回原数组(无 alloc)。
function sealStreaming(blocks: Block[]): Block[] {
  if (!blocks.some((b) => b.kind === 'text' && b.streaming)) return blocks;
  return blocks.map((b) => (b.kind === 'text' && b.streaming ? { ...b, streaming: false } : b));
}

/** 把一个事件归并进 turns。返回新 turns(不改原数组)。 */
export function reduceEvent(turns: Turn[], e: AgentEvent): Turn[] {
  if (turns.length === 0) return turns;
  const blocks = turns[turns.length - 1].blocks;

  switch (e.type) {
    case 'session':
    case 'start':
    case 'done':
      return turns;

    case 'token': {
      const text = String(e.data.text ?? '');
      if (!text) return turns;
      const last = blocks[blocks.length - 1];
      if (last && last.kind === 'text' && last.streaming) {
        const next = [...blocks.slice(0, -1), { ...last, text: last.text + text }];
        return withBlocks(turns, next);
      }
      return withBlocks(turns, [...blocks, { kind: 'text', text, streaming: true }]);
    }

    case 'message': {
      const text = String(e.data.text ?? '');
      const last = blocks[blocks.length - 1];
      if (last && last.kind === 'text' && last.streaming) {
        const next = [...blocks.slice(0, -1), { kind: 'text' as const, text, streaming: false }];
        return withBlocks(turns, next);
      }
      return withBlocks(turns, [...blocks, { kind: 'text', text, streaming: false }]);
    }

    case 'tool_call': {
      const calls = (e.data.calls as { name: string; args: unknown }[]) ?? [];
      const sealed = sealStreaming(blocks);
      const added: Block[] = calls.map((c) => ({
        kind: 'activity',
        call: `${c.name}(${JSON.stringify(c.args)})`,
        result: undefined,
      }));
      return withBlocks(turns, [...sealed, ...added]);
    }

    case 'tool_result': {
      const content = String(e.data.content ?? '');
      // 反向 for 找最近一个无 result 的 activity,避免 reverse+findIndex 的全数组克隆。
      let realIdx = -1;
      for (let i = blocks.length - 1; i >= 0; i--) {
        const b = blocks[i];
        if (b.kind === 'activity' && b.result === undefined) { realIdx = i; break; }
      }
      if (realIdx === -1) return turns;
      const next = [...blocks];
      const target = next[realIdx] as Extract<Block, { kind: 'activity' }>;
      next[realIdx] = { ...target, result: content };
      return withBlocks(turns, next);
    }

    case 'verify_failed':
    case 'escalation': {
      const detail = String(e.data.detail ?? '');
      return withBlocks(turns, [...sealStreaming(blocks), { kind: 'honesty', type: e.type, detail }]);
    }

    case 'tampering': {
      const files = (e.data.files as string[]) ?? [];
      return withBlocks(turns, [
        ...sealStreaming(blocks),
        { kind: 'honesty', type: 'tampering', detail: files.join('、') },
      ]);
    }

    case 'error': {
      const text = String(e.data.message ?? e.data.detail ?? '出错了');
      return withBlocks(turns, [...sealStreaming(blocks), { kind: 'error', text }]);
    }

    default:
      return turns;
  }
}
