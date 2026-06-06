// swarmStage.ts — 蜂群运行在知识图上的「临时叠加层」。
//
// 「图作为编排主界面」的数据层:蜂群跑起来时,契约/worker/冲突/修复以临时节点的形式
// 实时长在中央知识图上;跑完一键 clear,只把交付物 learn() 进永久图。临时节点与永久
// nodes 完全隔离(独立数组),不进力导向、不触发 autoThought、不污染记忆 —— 这样
// 蜂群过程「瞬时生长不沉淀」,图不被临时过程节点搞乱。
//
// 这里只管数据与状态(纯逻辑,可测);MindGraph 负责把这些临时节点画到 canvas 上。

export type StageKind = 'goal' | 'contract' | 'worker' | 'verdict';
export type StageState = 'active' | 'conflict' | 'resolved';

export interface StageNode {
  id: number;
  kind: StageKind;
  label: string;
  state: StageState;
  /** 0→1 生长动画进度;0 表示刚长出 */
  spawn: number;
  /** 视觉发热(脉冲/高亮),随帧衰减 */
  heat: number;
  /** 围绕中心的极坐标布局,由 MindGraph 转成屏幕坐标 */
  angle: number;
  radius: number;
}

export interface StageLink {
  from: number;
  to: number;
}

/** 围绕目标节点环形铺开 worker 的角度步进。 */
const TWO_PI = Math.PI * 2;

export class SwarmStage {
  nodes: StageNode[] = [];
  links: StageLink[] = [];
  private seq = 0;
  private contractId: number | null = null;

  private add(kind: StageKind, label: string, radius: number, angle: number): StageNode {
    const node: StageNode = { id: this.seq++, kind, label, state: 'active', spawn: 0, heat: 1, angle, radius };
    this.nodes.push(node);
    return node;
  }

  /** 阶段①:契约冻结 —— 中心长出 contract 节点。 */
  beginContract(domainLabel: string): StageNode {
    const c = this.add('contract', `契约 · ${domainLabel}`, 0, 0);
    this.contractId = c.id;
    return c;
  }

  /** 阶段②:每个子任务长出一个 worker 节点,环形铺开,连到 contract。 */
  addWorker(_taskId: string, task: string): StageNode {
    const workers = this.nodes.filter((n) => n.kind === 'worker');
    const idx = workers.length;
    // 角度按已有 worker 数均匀铺开(后续 worker 加入时不重算已有的,够用且稳定)。
    const angle = (idx / Math.max(3, idx + 1)) * TWO_PI;
    const w = this.add('worker', task, 1, angle);
    if (this.contractId != null) this.links.push({ from: this.contractId, to: w.id });
    return w;
  }

  /** 交叉验证发现冲突:相关 worker 标红闪烁。 */
  markConflict(): void {
    for (const n of this.nodes) if (n.kind === 'worker') { n.state = 'conflict'; n.heat = 1; }
  }

  /** 定点修复成功:worker 转绿收拢并发脉冲。 */
  markResolved(): void {
    for (const n of this.nodes) if (n.kind === 'worker') { n.state = 'resolved'; n.heat = 1; }
  }

  /** 一键清空临时层(跑完调用)。seq 不回退,避免清空后新节点复用旧 id 造成渲染残影错配。 */
  clear(): void {
    this.nodes = [];
    this.links = [];
    this.contractId = null;
  }
}
