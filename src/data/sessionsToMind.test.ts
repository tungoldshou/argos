import { describe, it, expect } from 'vitest';
import { sessionsToMind, type RawSession } from './sessionsToMind';

const S = (over: Partial<RawSession>): RawSession => ({ id: 'abcdef12', ...over });

describe('sessionsToMind', () => {
  it('returns null for no sessions', () => {
    expect(sessionsToMind([])).toBeNull();
  });

  it('builds a Hermes self node linked to each session', () => {
    const m = sessionsToMind([S({ id: 's1', title: 'Deploy atlas' }), S({ id: 's2', title: 'Scan arXiv' })]);
    expect(m).not.toBeNull();
    expect(m!.self.label).toBe('Hermes');
    expect(m!.self.type).toBe('self');
    const topics = m!.nodes.filter((n) => n.type === 'topic');
    expect(topics.map((n) => n.label)).toEqual(['Deploy atlas', 'Scan arXiv']);
    // each session linked to self
    expect(m!.edges.filter((e) => e[0] === m!.self.id || e[1] === m!.self.id)).toHaveLength(2);
  });

  it('dedupes a shared model into one bridging source node', () => {
    const m = sessionsToMind([
      S({ id: 's1', title: 'A', model: 'MiniMax-M2' }),
      S({ id: 's2', title: 'B', model: 'MiniMax-M2' }),
    ]);
    const models = m!.nodes.filter((n) => n.type === 'source');
    expect(models).toHaveLength(1);
    expect(models[0].label).toBe('MiniMax-M2');
  });

  it('falls back to preview, then short id, for the label', () => {
    const byPreview = sessionsToMind([S({ id: 'zz', preview: 'summarize the merged PRs and post' })]);
    expect(byPreview!.nodes.find((n) => n.type === 'topic')!.label).toMatch(/^summarize the merged PRs/);
    const byId = sessionsToMind([S({ id: 'deadbeef99' })]);
    expect(byId!.nodes.find((n) => n.type === 'topic')!.label).toBe('session deadbeef');
  });

  it('derives a memory node from the goal, stripping the 原目标 label', () => {
    const m = sessionsToMind([S({ id: 's1', title: 'T', preview: '原目标:设计一个 TODO API。其余略' })]);
    const mem = m!.nodes.find((n) => n.type === 'memory');
    expect(mem).toBeDefined();
    expect(mem!.label).toBe('设计一个 TODO API');
  });

  it('orders newest-first by last_active and caps at 40', () => {
    const many: RawSession[] = Array.from({ length: 50 }, (_, i) =>
      S({ id: `s${i}`, title: `T${i}`, last_active: i }),
    );
    const m = sessionsToMind(many);
    const topics = m!.nodes.filter((n) => n.type === 'topic');
    expect(topics).toHaveLength(40);
    expect(topics[0].label).toBe('T49'); // highest last_active first
  });
});
