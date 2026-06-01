import { describe, it, expect } from 'vitest';
import { reduceEvent, startTurn, type Turn } from './chatReducer';
import type { AgentEvent } from './agent';

const ev = (type: AgentEvent['type'], data: Record<string, unknown> = {}): AgentEvent => ({ type, data });

describe('chatReducer', () => {
  it('startTurn 追加一个带用户输入的空 turn', () => {
    const turns = startTurn([], 'hi', 't1');
    expect(turns).toHaveLength(1);
    expect(turns[0]).toMatchObject({ id: 't1', user: 'hi', blocks: [] });
  });

  it('token 累积进同一个 streaming text block', () => {
    let t = startTurn([], 'q', 't1');
    t = reduceEvent(t, ev('token', { text: 'Hel' }));
    t = reduceEvent(t, ev('token', { text: 'lo' }));
    expect(t[0].blocks).toEqual([{ kind: 'text', text: 'Hello', streaming: true }]);
  });

  it('message 把当前 streaming text 定稿（覆盖文本、streaming=false）', () => {
    let t = startTurn([], 'q', 't1');
    t = reduceEvent(t, ev('token', { text: 'Hel' }));
    t = reduceEvent(t, ev('message', { text: 'Hello world' }));
    expect(t[0].blocks).toEqual([{ kind: 'text', text: 'Hello world', streaming: false }]);
  });

  it('message 无前置 token 时直接 push 定稿 text block', () => {
    let t = startTurn([], 'q', 't1');
    t = reduceEvent(t, ev('message', { text: 'done' }));
    expect(t[0].blocks).toEqual([{ kind: 'text', text: 'done', streaming: false }]);
  });

  it('tool_call 先封档 streaming text，再为每个调用 push activity block', () => {
    let t = startTurn([], 'q', 't1');
    t = reduceEvent(t, ev('token', { text: '思考中' }));
    t = reduceEvent(t, ev('tool_call', { calls: [{ name: 'web_search', args: { q: 'x' } }] }));
    expect(t[0].blocks).toEqual([
      { kind: 'text', text: '思考中', streaming: false },
      { kind: 'activity', call: 'web_search({"q":"x"})', result: undefined },
    ]);
  });

  it('tool_result 补全最近一个无 result 的 activity', () => {
    let t = startTurn([], 'q', 't1');
    t = reduceEvent(t, ev('tool_call', { calls: [{ name: 'web_search', args: {} }] }));
    t = reduceEvent(t, ev('tool_result', { content: '结果文本' }));
    const act = t[0].blocks.find((b) => b.kind === 'activity');
    expect(act).toMatchObject({ kind: 'activity', result: '结果文本' });
  });

  it('verify_failed / escalation 生成 honesty block', () => {
    let t = startTurn([], 'q', 't1');
    t = reduceEvent(t, ev('verify_failed', { detail: '验证未过' }));
    t = reduceEvent(t, ev('escalation', { detail: '卡住了' }));
    const honesty = t[0].blocks.filter((b) => b.kind === 'honesty');
    expect(honesty).toEqual([
      { kind: 'honesty', type: 'verify_failed', detail: '验证未过' },
      { kind: 'honesty', type: 'escalation', detail: '卡住了' },
    ]);
  });

  it('tampering 把 files 数组归一成 detail 文本', () => {
    let t = startTurn([], 'q', 't1');
    t = reduceEvent(t, ev('tampering', { files: ['a_test.py', 'b_test.py'] }));
    expect(t[0].blocks).toEqual([
      { kind: 'honesty', type: 'tampering', detail: 'a_test.py、b_test.py' },
    ]);
  });

  it('error 生成 error block', () => {
    let t = startTurn([], 'q', 't1');
    t = reduceEvent(t, ev('error', { message: '炸了' }));
    expect(t[0].blocks).toEqual([{ kind: 'error', text: '炸了' }]);
  });

  it('session / start 不改 blocks', () => {
    let t = startTurn([], 'q', 't1');
    t = reduceEvent(t, ev('session', { session_id: 's1' }));
    t = reduceEvent(t, ev('start', { goal: 'q' }));
    expect(t[0].blocks).toEqual([]);
  });

  it('不可变：reduceEvent 返回新数组，不改原 turns', () => {
    const t0 = startTurn([], 'q', 't1');
    const t1 = reduceEvent(t0, ev('token', { text: 'x' }));
    expect(t1).not.toBe(t0);
    expect(t0[0].blocks).toEqual([]);
  });
});
