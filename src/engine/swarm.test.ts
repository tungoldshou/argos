// swarm.test.ts — 锁住蜂群编排骨架的行为(纯逻辑,不调真实模型)。
// 核心资产是 4 阶段流程(契约冻结→并行→合规自检/self-repair→严格 judge),
// 至今零测试。这里用可编程 mock ChatFn 验证编排正确,不烧 token、不依赖模型。
import { describe, it, expect, vi } from 'vitest';
import { runSwarm, parsePlan, parseVerdict, type SwarmHooks } from './swarm';
import type { ChatFn, ChatOpts } from '../lib/llm';

// judge 输出工厂:第一参数=冲突数,用于驱动「按调用次序变化的 judge」。
const judgeOutput = (n: number) =>
  n === 0 ? '无\n硬冲突数: 0' : `- 字段 A=x B=y\n硬冲突数: ${n}`;

// ── 纯解析函数 ────────────────────────────────────────────────────────────
describe('parsePlan', () => {
  it('解析编号/项目符号列表为子任务(内容须 >4 字)', () => {
    const tasks = parsePlan('1. 设计完整数据模型\n2. 实现 CRUD 端点\n- 处理并发写入冲突');
    expect(tasks.map((t) => t.task)).toEqual(['设计完整数据模型', '实现 CRUD 端点', '处理并发写入冲突']);
    expect(tasks.map((t) => t.id)).toEqual(['1', '2', '3']);
  });

  it('丢弃 ≤4 字的行(避免噪音当任务):「实现端点」4 字被丢', () => {
    // m[1].length > 4 是有意的噪音过滤,边界为「严格大于 4」。
    expect(parsePlan('1. 实现端点\n2. 这是一个足够长的子任务')).toHaveLength(1);
  });

  it('最多取 4 个子任务', () => {
    const many = Array.from({ length: 8 }, (_, i) => `${i + 1}. 子任务编号${i + 1}号内容`).join('\n');
    expect(parsePlan(many)).toHaveLength(4);
  });

  // 真模型在「不要编号前缀」约束下会输出纯文本行(无 1./-/* 前缀)。
  // parsePlan 必须也能解析这种,否则蜂群会拆出 0 个子任务退化成空跑(2026-05-31 真模型实测)。
  it('解析无任何列表前缀的纯文本行(每行一个子任务)', () => {
    const plain = '设计数据模型与持久层\n实现三个核心 REST 端点\n修复并发写入的竞态';
    const tasks = parsePlan(plain);
    expect(tasks.map((t) => t.task)).toEqual(['设计数据模型与持久层', '实现三个核心 REST 端点', '修复并发写入的竞态']);
  });

  it('混排:有前缀行与纯文本行都能解析', () => {
    const mixed = '1. 设计数据模型与持久层\n实现三个核心 REST 端点';
    expect(parsePlan(mixed)).toHaveLength(2);
  });
});

describe('parseVerdict', () => {
  it('从「硬冲突数: N」抽取计数,0 时判定可组装', () => {
    const v = parseVerdict('逐条:\n无\n硬冲突数: 0');
    expect(v.conflictCount).toBe(0);
    expect(v.assemblable).toBe(true);
  });

  it('容忍加粗数字 硬冲突数: **2**,并收集冲突行', () => {
    const v = parseVerdict('- title 上限 A=200 B=255\n- 命名 A=snake B=camel\n硬冲突数: **2**');
    expect(v.conflictCount).toBe(2);
    expect(v.assemblable).toBe(false);
    expect(v.conflicts).toHaveLength(2);
  });

  // 真实 Hermes(MiniMax 级)输出带 markdown 装饰,旧解析把 ** / -- / 标题行误当冲突。
  // 这是 2026-05-31 真模型端到端跑出的真实脏输出(scripts/swarm-real-hermes.mts)。
  it('真模型 markdown 输出:剥离 **粗体**、--分隔线、标题行,只留实质冲突', () => {
    const real = [
      '*真冲突逐条：**',
      '**Agent1**：「昵称 AND 头像」三者全要',
      '**Agent2/3/4**：「至少已填一项（OR 逻辑）」',
      '--',
      '*硬冲突数: 2**',
    ].join('\n');
    const v = parseVerdict(real);
    expect(v.conflictCount).toBe(2);          // 计数仍从「硬冲突数: 2」抓到
    expect(v.assemblable).toBe(false);
    // 分隔线 -- / 标题「真冲突逐条」/ 「硬冲突数」行都不算冲突条目
    expect(v.conflicts).not.toContain('--');
    expect(v.conflicts.some((c) => /硬冲突数/.test(c))).toBe(false);
    expect(v.conflicts.some((c) => /真冲突逐条/.test(c))).toBe(false);
    // 实质冲突行保留,且 ** 装饰被剥掉
    expect(v.conflicts.some((c) => c.includes('Agent1') && !c.includes('**'))).toBe(true);
  });

  it('「无」判定为可组装,不把「无」当冲突条目', () => {
    const v = parseVerdict('逐条检查:\n- 无\n硬冲突数: 0');
    expect(v.conflictCount).toBe(0);
    expect(v.assemblable).toBe(true);
    expect(v.conflicts).not.toContain('无');
  });
});

// ── 编排骨架:可编程 mock ChatFn ──────────────────────────────────────────
// 按 prompt/system 特征返回对应假数据,使 runSwarm 能完整跑完而不触真实模型。
// overrides.judges: 按 judge 被调用的次序依次返回的冲突数序列(实现「修复后再判」)。
function makeChat(
  overrides: Partial<{ domain: string; judge: string; judges: number[] }> = {},
) {
  let judgeCalls = 0;
  return vi.fn(async (prompt: string, opts?: ChatOpts): Promise<string> => {
    const sys = opts?.system ?? '';
    // 领域分类(maxTokens 极小 + prompt 含「契约领域」)
    if (prompt.includes('契约领域')) return overrides.domain ?? 'rest-api';
    // 契约冻结(dynamicFreezePrompt 含「冻结一份共享契约」)
    if (prompt.includes('冻结一份共享契约')) return '[C1] id: UUIDv4\n[X1] 分页: limit/offset';
    // 漏项回填
    if (prompt.includes('漏掉了必检骨架')) return '[C1] id: UUIDv4\n[X1] 分页: limit/offset';
    // 规划
    if (prompt.includes('只输出子任务列表')) return '1. 设计数据模型\n2. 实现 CRUD 端点';
    // 合规自检(complianceCheckPrompt 含稳定特征「现在做合规自检」)
    if (prompt.includes('现在做合规自检')) return 'repaired-output';
    // 定点冲突修复(resolveConflictsPrompt 含稳定特征「按以下冲突」)
    if (prompt.includes('按以下冲突')) return 'resolved-output';
    // judge:有 judges 序列则按次序返回,否则用 judge/默认
    if (prompt.includes('真冲突')) {
      if (overrides.judges) {
        const n = overrides.judges[Math.min(judgeCalls, overrides.judges.length - 1)];
        judgeCalls++;
        return judgeOutput(n);
      }
      return overrides.judge ?? '无\n硬冲突数: 0';
    }
    // worker 默认产出(规划阶段已排除,余下即 worker 子任务调用)
    void sys;
    return 'raw-worker-output';
  }) as unknown as ChatFn;
}

describe('runSwarm — 4 阶段编排', () => {
  it('完整跑通,产出含 domain/contract/subtasks/workers/checked/verdict', async () => {
    const chat = makeChat();
    const run = await runSwarm('设计一个 REST API', chat);
    expect(run.domain).toBe('rest-api');
    expect(run.contract).not.toBe('');
    expect(run.subtasks.length).toBeGreaterThan(0);
    expect(run.workers.length).toBe(run.subtasks.length);
    // self-repair 真的发生:workers 是原始产出,checked 是自检修正后的产出。
    expect(run.workers.every((w) => w.output === 'raw-worker-output')).toBe(true);
    expect(run.checked.every((w) => w.output === 'repaired-output')).toBe(true);
    expect(run.verdict.assemblable).toBe(true);
  });

  it('阶段 hook 触发:domain 最先,check/verdict 在契约+规划之后', async () => {
    const calls: string[] = [];
    const hooks: SwarmHooks = {
      onDomain: () => calls.push('domain'),
      onContract: () => calls.push('contract'),
      onPlan: () => calls.push('plan'),
      onCheckStart: () => calls.push('check'),
      onVerdict: () => calls.push('verdict'),
    };
    await runSwarm('设计一个 REST API', makeChat(), hooks);
    // domain 必先;contract 与 plan 现在并行(相对顺序不保证);check→verdict 在两者之后。
    expect(calls[0]).toBe('domain');
    expect(calls).toContain('contract');
    expect(calls).toContain('plan');
    expect(calls.indexOf('check')).toBeGreaterThan(calls.indexOf('contract'));
    expect(calls.indexOf('check')).toBeGreaterThan(calls.indexOf('plan'));
    expect(calls.indexOf('verdict')).toBeGreaterThan(calls.indexOf('check'));
  });

  it('useContract=false 时跳过契约冻结与合规自检,checked === workers', async () => {
    const calls: string[] = [];
    const hooks: SwarmHooks = {
      onContract: () => calls.push('contract'),
      onCheckStart: () => calls.push('check'),
    };
    const run = await runSwarm('设计一个 REST API', makeChat(), hooks, false);
    expect(run.contract).toBe('');
    expect(calls).not.toContain('contract');
    expect(calls).not.toContain('check'); // 无契约 → 无 self-repair
    expect(run.checked).toEqual(run.workers);
  });

  it('judge 报冲突时 verdict.assemblable 为 false', async () => {
    const run = await runSwarm('设计一个 REST API', makeChat({ judge: '- A=200 B=255\n硬冲突数: 1' }));
    expect(run.verdict.conflictCount).toBe(1);
    expect(run.verdict.assemblable).toBe(false);
  });

  it('domain 经 LLM 分类决定,语义目标也能选对模板', async () => {
    const run = await runSwarm('把用户登录流程拆开', makeChat({ domain: 'state-machine' }));
    expect(run.domain).toBe('state-machine');
  });
});

// ── 第 5 阶段:judge 定点修复闭环(9/10 真空护城河) ───────────────────────
describe('runSwarm — judge 定点修复闭环', () => {
  it('首次 judge 即清零时不进入修复回合(rounds 为空)', async () => {
    const run = await runSwarm('设计一个 REST API', makeChat({ judges: [0] }));
    expect(run.rounds).toHaveLength(0);
    expect(run.verdict.assemblable).toBe(true);
  });

  it('首轮有冲突→定点修复→再判清零:rounds=1,最终可组装', async () => {
    const onResolve = vi.fn();
    // judge 序列:第一次 2 冲突 → 修复 → 第二次 0 冲突
    const run = await runSwarm('设计一个 REST API', makeChat({ judges: [2, 0] }), {
      onResolveRound: onResolve,
    });
    expect(run.rounds).toHaveLength(1);
    expect(run.rounds[0].round).toBe(1);
    expect(run.rounds[0].verdict.conflictCount).toBe(2); // 修复前暴露的冲突
    expect(run.rounds[0].repaired.every((w) => w.output === 'resolved-output')).toBe(true);
    expect(run.verdict.assemblable).toBe(true); // 最终清零
    expect(onResolve).toHaveBeenCalledTimes(1);
  });

  it('冲突数下降但未清零时继续修(2→1→0)', async () => {
    const run = await runSwarm('设计一个 REST API', makeChat({ judges: [2, 1, 0] }), {}, true, 3);
    expect(run.rounds).toHaveLength(2); // 2→1(改善,继续)→0(清零,停)
    expect(run.verdict.assemblable).toBe(true);
  });

  it('修复后冲突不降反升 → 回退停止(防发散),被回退的轮次不计入 rounds', async () => {
    // 真模型实测:全员重写会引入新分歧,judge 1→3 越修越多。
    // 护栏:修完冲突数 >= 上一轮就丢弃这轮(不 push 进 rounds),verdict 停在较优的上一轮。
    const run = await runSwarm('设计一个 REST API', makeChat({ judges: [1, 3] }), {}, true, 3);
    expect(run.rounds).toHaveLength(0);        // 唯一一轮被回退,不采纳
    expect(run.verdict.conflictCount).toBe(1); // 停在修复前的较优值(1),不采纳变差的(3)
  });

  it('始终不下降(平台期)时不空转,不耗满 maxRounds', async () => {
    // judge 恒为 3:第一轮修完仍 3(不降)→ 回退停止,rounds 为空。
    const run = await runSwarm('设计一个 REST API', makeChat({ judges: [3] }), {}, true, 3);
    expect(run.rounds).toHaveLength(0);
    expect(run.verdict.conflictCount).toBe(3);
  });

  it('无契约模式(useContract=false)不跑修复闭环', async () => {
    const run = await runSwarm('设计一个 REST API', makeChat({ judges: [2, 0] }), {}, false);
    expect(run.rounds).toHaveLength(0);
  });
});
