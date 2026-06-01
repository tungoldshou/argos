import { describe, it, expect } from 'vitest';
import { memoryToMind, type MemoryRecord } from './memoryToMind';

describe('memoryToMind', () => {
  it('无记忆 → null(让调用方回退到诚实空态)', () => {
    expect(memoryToMind([])).toBeNull();
  });

  it('一条记忆 → self + 任务节点,且自我节点是 Argos', () => {
    const recs: MemoryRecord[] = [
      { id: 'a1', goal: '写一个分页响应', verdict: 'passed', model: 'MiniMax-M3', ts: 1 },
    ];
    const mind = memoryToMind(recs)!;
    expect(mind).not.toBeNull();
    expect(mind.self.label).toBe('Argos');
    const labels = mind.nodes.map((n) => n.label);
    expect(labels).toContain('写一个分页响应');
    expect(labels).toContain('✓ 通过验证');
    expect(labels).toContain('MiniMax-M3');
  });

  it('同一模型跨任务 → 共享一个模型节点(桥接)', () => {
    const recs: MemoryRecord[] = [
      { id: 'a', goal: '任务A', model: 'MiniMax-M3', ts: 2 },
      { id: 'b', goal: '任务B', model: 'MiniMax-M3', ts: 1 },
    ];
    const mind = memoryToMind(recs)!;
    const modelNodes = mind.nodes.filter((n) => n.label === 'MiniMax-M3');
    expect(modelNodes.length).toBe(1); // 去重,只一个共享节点
  });

  it('verdict=failed 也诚实记录(不隐藏失败)', () => {
    const mind = memoryToMind([{ id: 'x', goal: 'g', verdict: 'failed', ts: 1 }])!;
    expect(mind.nodes.map((n) => n.label)).toContain('✗ 未通过(已诚实记录)');
  });

  it('verdict=unverifiable → 不假装通过', () => {
    const mind = memoryToMind([{ id: 'x', goal: 'g', verdict: 'unverifiable', ts: 1 }])!;
    expect(mind.nodes.map((n) => n.label)).toContain('? 无法验证(未假装通过)');
  });
});
