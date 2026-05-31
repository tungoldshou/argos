// swarmStage.test.ts — 锁住「蜂群事件 → 图临时节点」的纯数据映射。
// 设计:临时节点与永久 nodes 隔离(独立数组),跑完一键清空,不污染力导向/记忆。
// 这是「图作为编排主界面」的数据层,与 canvas 渲染解耦,故可纯测。
import { describe, it, expect } from 'vitest';
import { SwarmStage } from './swarmStage';

describe('SwarmStage — 临时叠加层', () => {
  it('初始为空', () => {
    const s = new SwarmStage();
    expect(s.nodes).toHaveLength(0);
  });

  it('beginContract 长出一个 contract 节点(发热)', () => {
    const s = new SwarmStage();
    s.beginContract('REST API');
    const c = s.nodes.find((n) => n.kind === 'contract');
    expect(c).toBeDefined();
    expect(c!.label).toContain('REST API');
    expect(c!.heat).toBeGreaterThan(0);
  });

  it('addWorker 为每个子任务长出 worker 节点,连到 contract', () => {
    const s = new SwarmStage();
    s.beginContract('REST API');
    s.addWorker('1', '设计数据模型');
    s.addWorker('2', '实现端点');
    const workers = s.nodes.filter((n) => n.kind === 'worker');
    expect(workers).toHaveLength(2);
    // 每个 worker 都连到 contract 节点
    const cId = s.nodes.find((n) => n.kind === 'contract')!.id;
    expect(workers.every((w) => s.links.some((l) => l.from === cId && l.to === w.id))).toBe(true);
  });

  it('markConflict 把相关 worker 标红(state=conflict)', () => {
    const s = new SwarmStage();
    s.beginContract('REST API');
    s.addWorker('1', 'A');
    s.addWorker('2', 'B');
    s.markConflict();
    expect(s.nodes.filter((n) => n.kind === 'worker').every((w) => w.state === 'conflict')).toBe(true);
  });

  it('markResolved 把 worker 转绿(state=resolved)并发脉冲', () => {
    const s = new SwarmStage();
    s.beginContract('REST API');
    s.addWorker('1', 'A');
    s.markConflict();
    s.markResolved();
    expect(s.nodes.filter((n) => n.kind === 'worker').every((w) => w.state === 'resolved')).toBe(true);
  });

  it('clear 一键清空所有临时节点与连线(不影响永久图)', () => {
    const s = new SwarmStage();
    s.beginContract('REST API');
    s.addWorker('1', 'A');
    s.clear();
    expect(s.nodes).toHaveLength(0);
    expect(s.links).toHaveLength(0);
  });

  it('节点 id 唯一且自增,clear 后不复用旧 id(避免渲染残影错配)', () => {
    const s = new SwarmStage();
    s.beginContract('x');
    const firstId = s.nodes[0].id;
    s.clear();
    s.beginContract('y');
    expect(s.nodes[0].id).not.toBe(firstId);
  });
});
