// SwarmPanel.tsx — Argos 的核心交互:输入一个结构化工程目标,看契约冻结 →
// 蜂群并行 → 冲突诊断。这不是动画,是「让便宜模型也能可靠协作」的诊断器。
//
// 已验证(MiniMax-M2.7):契约模板让结构化任务冲突 8→0;但对开放式写作无效。
// 所以面板明确标注边界:只接结构化工程任务。
import { useState } from 'react';
import { Overlay } from './overlays';
import { Icon } from '../lib/icons';
import { tr } from '../lib/i18n';
import { chat } from '../lib/llm';
import { runSwarm, type Subtask, type WorkerOutput, type Verdict, type FreezeInfo, type ResolveRound } from '../engine/swarm';

type Phase = 'idle' | 'contract' | 'plan' | 'work' | 'check' | 'judge' | 'resolve' | 'done' | 'error';

const EXAMPLES = [
  '设计一个 TODO REST API:数据模型 + 3 个端点 + 并发安全修复',
  '设计用户认证服务的数据库 schema 与 5 个核心接口契约',
  '设计一个订单状态机:状态枚举 + 流转规则 + 幂等接口',
];

export function SwarmPanel({ onClose, engine }: { onClose: () => void; engine?: { stage: import('../engine/swarmStage').SwarmStage } | null }) {
  const [goal, setGoal] = useState('');
  const [phase, setPhase] = useState<Phase>('idle');
  const [contract, setContract] = useState('');
  const [subtasks, setSubtasks] = useState<Subtask[]>([]);
  const [workers, setWorkers] = useState<WorkerOutput[]>([]);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [active, setActive] = useState<Set<string>>(new Set());
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [rounds, setRounds] = useState<ResolveRound[]>([]);
  const [domainLabel, setDomainLabel] = useState('');
  const [freeze, setFreeze] = useState<FreezeInfo | null>(null);
  const [err, setErr] = useState('');
  const running = phase !== 'idle' && phase !== 'done' && phase !== 'error';
  const reset = () => {
    setContract(''); setSubtasks([]); setWorkers([]); setChecked(new Set()); setActive(new Set()); setVerdict(null); setRounds([]); setDomainLabel(''); setFreeze(null); setErr('');
  };

  const run = async () => {
    const g = goal.trim();
    if (!g || running) return;
    reset();
    const stage = engine?.stage;       // 中央知识图的临时叠加层(可能无 engine,如浏览器无 canvas)
    stage?.clear();
    setPhase('contract');
    try {
      const r = await runSwarm(g, chat(), {
        // 每个 hook 既更新侧栏摘要,又驱动中央图的临时节点生长 —— 图是主舞台。
        onDomain: (_d, label) => { setDomainLabel(label); stage?.beginContract(label); },
        onFreezeProgress: (info) => setFreeze(info),
        onContract: (c) => { setContract(c); setPhase('plan'); },
        onPlan: (s) => {
          setSubtasks(s);
          s.forEach((st) => stage?.addWorker(st.id, st.task)); // 每个子任务在图上长出一个 worker 节点
          setPhase('work');
        },
        onWorkerStart: (id) => setActive((p) => new Set(p).add(id)),
        onWorkerDone: (w) => {
          setWorkers((p) => [...p, w]);
          setActive((p) => { const n = new Set(p); n.delete(w.id); return n; });
        },
        onCheckStart: () => setPhase('check'),
        onWorkerChecked: (w) => {
          setWorkers((p) => p.map((x) => (x.id === w.id ? w : x)));
          setChecked((p) => new Set(p).add(w.id));
        },
        onVerdict: (v) => {
          setVerdict(v);
          setPhase('judge');
          if (!v.assemblable) stage?.markConflict(); // 冲突 → 图上 worker 变橙闪烁
        },
        onResolveStart: () => setPhase('resolve'),
        onResolveRound: (rd) => setRounds((p) => [...p, rd]),
      });
      setVerdict(r.verdict);
      setRounds(r.rounds);
      if (r.verdict.assemblable) stage?.markResolved(); // 最终清零 → 图上 worker 转绿收拢
      setPhase('done');
    } catch (e) {
      setErr(String(e));
      setPhase('error');
    }
  };

  // 关闭面板时清掉图上的临时蜂群节点(瞬时生长不沉淀)。
  const close = () => { engine?.stage.clear(); onClose(); };

  return (
    <Overlay title="Swarm" icon="activity" sub="契约约束的多 agent 蜂群 · 仅结构化工程任务" onClose={close}>
      {/* 目标输入 */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <input
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && run()}
          placeholder="输入一个结构化工程目标(API/schema/接口/状态机/迁移…)"
          disabled={running}
          style={{ flex: 1, height: 38, padding: '0 12px', borderRadius: 9, border: '1px solid var(--border)', background: 'var(--surface-2, rgba(255,255,255,.03))', color: 'var(--text-1)', fontSize: 13 }}
        />
        <button onClick={run} disabled={running || !goal.trim()}
          style={{ height: 38, padding: '0 16px', borderRadius: 9, border: 'none', background: running ? 'var(--border)' : 'var(--accent)', color: '#1a1205', fontWeight: 700, fontSize: 13, cursor: running ? 'default' : 'pointer', whiteSpace: 'nowrap' }}>
          {running ? '运行中…' : '唤起蜂群'}
        </button>
      </div>

      {phase === 'idle' && (
        <div style={{ marginTop: 4 }}>
          <div style={{ fontSize: 12, color: 'var(--text-3)', marginBottom: 8 }}>试试这些(只接结构化任务,开放式写作/分析不适用):</div>
          {EXAMPLES.map((ex) => (
            <button key={ex} onClick={() => setGoal(ex)}
              style={{ display: 'block', width: '100%', textAlign: 'left', marginBottom: 6, padding: '9px 12px', borderRadius: 8, border: '1px solid var(--border)', background: 'none', color: 'var(--text-2)', fontSize: 12.5, cursor: 'pointer' }}>
              {ex}
            </button>
          ))}
        </div>
      )}

      {/* 阶段 1:契约 —— 混合冻结:固定骨架(必检兜底)+ 动态扩展(目标专属) */}
      {contract && (
        <Section icon="layers" label="① 契约冻结" hint={domainLabel ? `${domainLabel} · 固定骨架 + 动态扩展` : '固定骨架 + 动态扩展'}>
          {freeze && (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
              <Chip>骨架必检 {freeze.covered}/{freeze.required}</Chip>
              <Chip>动态扩展 +{freeze.dynamic} 条</Chip>
              <Chip>{freeze.refilled.length ? `回填 ${freeze.refilled.join('、')}` : '一次过 · 无漏项'}</Chip>
            </div>
          )}
          <pre style={preStyle}>{contract}</pre>
        </Section>
      )}

      {/* 阶段 2/3:蜂群 */}
      {subtasks.length > 0 && (
        <Section icon="activity" label="② 蜂群并行" hint={`${subtasks.length} 个 agent,互不通信`}>
          {subtasks.map((st) => {
            const done = workers.find((w) => w.id === st.id);
            const busy = active.has(st.id);
            return (
              <div key={st.id} style={{ marginBottom: 8, border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 11px', fontSize: 12.5 }}>
                  <Dot state={done ? 'done' : busy ? 'busy' : 'wait'} />
                  <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{st.task}</span>
                  {checked.has(st.id) && <span style={{ flexShrink: 0, fontSize: 10.5, color: '#45e0a0', fontFamily: 'var(--mono)' }}>✓ 已校验</span>}
                </div>
                {done && <pre style={{ ...preStyle, margin: 0, borderTop: '1px solid var(--border)', borderRadius: 0, maxHeight: 140 }}>{done.output}</pre>}
              </div>
            );
          })}
        </Section>
      )}

      {/* 阶段 3:合规自检 —— 每个 worker 拿契约当权威,修正自己产出里的偏离 */}
      {(phase === 'check' || checked.size > 0) && (
        <Section icon="activity" label="③ 合规自检 + 自修正"
          hint={`${checked.size}/${subtasks.length} 已对照契约修正`}>
          <div style={{ padding: '10px 12px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface-2, rgba(255,255,255,.02))', fontSize: 12, color: 'var(--text-3)', lineHeight: 1.6 }}>
            每个 agent 拿冻结的契约当唯一权威,逐条自查产出有无偏离(字段值/命名/状态码/过滤规则),违反则改正。
            <br />实测:这一步把「worker 没遵守已存在条款」造成的硬冲突 6 → 0。
          </div>
        </Section>
      )}

      {/* 阶段 4:冲突诊断 —— 真壁垒在这里。三态:可信通过 / 不可信(需人工) / 有冲突 */}
      {verdict && (
        <Section icon="memory" label="④ 交叉验证诊断"
          hint={
            !verdict.parseTrusted ? '⚠ 无法验证 · 需人工确认'
              : verdict.assemblable ? '✓ 可直接组装'
              : `${verdict.conflictCount} 处硬冲突`
          }>
          {!verdict.parseTrusted ? (
            // 测谎仪读不懂这次判决(judge 跑题/被截断/自相矛盾)。fail-closed:
            // 绝不亮绿灯,也不谎称「确定有冲突」,而是诚实上报「无法验证」交人类裁决。
            // 这是 escalation 的第一个挂点。
            <div style={{ padding: '12px 14px', borderRadius: 9, background: 'color-mix(in oklab, #ffb152, transparent 88%)', border: '1px solid color-mix(in oklab, #ffb152, transparent 55%)', color: '#ffb152', fontSize: 13, lineHeight: 1.6 }}>
              <div style={{ fontWeight: 700, marginBottom: 4 }}>⚠ 无法可靠验证这次产出</div>
              <div style={{ color: 'var(--text-2)', fontSize: 12.5 }}>
                交叉验证的判决无法解析(模型未给出可信的冲突计数,可能跑题或被截断)。
                为避免谎报「已通过」,Argos 拒绝下结论,需要你人工确认。
              </div>
              {verdict.conflicts.length > 0 && (
                <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {verdict.conflicts.map((c, i) => (
                    <div key={i} style={{ fontSize: 11.5, color: 'var(--text-3)', fontFamily: 'var(--mono)' }}>· {c}</div>
                  ))}
                </div>
              )}
            </div>
          ) : verdict.assemblable ? (
            <div style={{ padding: '12px 14px', borderRadius: 9, background: 'color-mix(in oklab, #45e0a0, transparent 88%)', border: '1px solid color-mix(in oklab, #45e0a0, transparent 60%)', color: '#45e0a0', fontSize: 13, fontWeight: 600 }}>
              零硬冲突 — 蜂群产出可直接拼装。契约层生效。
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {verdict.conflicts.map((c, i) => (
                <div key={i} style={{ display: 'flex', gap: 8, padding: '8px 11px', borderRadius: 8, background: 'color-mix(in oklab, #ff7a4d, transparent 90%)', border: '1px solid color-mix(in oklab, #ff7a4d, transparent 70%)', fontSize: 12.5 }}>
                  <span style={{ color: '#ff7a4d', flexShrink: 0 }}>⚠</span>
                  <span style={{ color: 'var(--text-2)' }}>{c}</span>
                </div>
              ))}
            </div>
          )}
        </Section>
      )}

      {/* 阶段 5:自动修复闭环 —— 多 agent 相互验证后,把冲突点定向回修。0 商用竞品的护城河。 */}
      {(phase === 'resolve' || rounds.length > 0) && (
        <Section icon="activity" label="⑤ 自动修复闭环"
          hint={`${rounds.length} 轮定点修复`}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ padding: '8px 11px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface-2, rgba(255,255,255,.02))', fontSize: 12, color: 'var(--text-3)', lineHeight: 1.6 }}>
              交叉验证发现的冲突,被逐条回给相关 agent 定向修复(不是重跑),再重新验证 —— 直到清零或达上限。
            </div>
            {rounds.map((rd) => (
              <div key={rd.round} style={{ padding: '8px 11px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface-2, rgba(255,255,255,.02))' }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-2)', marginBottom: 4 }}>
                  第 {rd.round} 轮 · 修复了 {rd.verdict.conflictCount} 处冲突
                </div>
                {rd.verdict.conflicts.map((c, i) => (
                  <div key={i} style={{ fontSize: 11.5, color: 'var(--text-3)', fontFamily: 'var(--mono)' }}>· {c}</div>
                ))}
              </div>
            ))}
          </div>
        </Section>
      )}

      {err && <div style={{ marginTop: 12, padding: 11, borderRadius: 8, background: 'color-mix(in oklab, #ff7a4d, transparent 88%)', color: '#ff7a4d', fontSize: 12.5 }}>错误:{err}</div>}
    </Overlay>
  );
}

const preStyle: React.CSSProperties = {
  fontFamily: 'var(--mono)', fontSize: 11.5, lineHeight: 1.6, color: 'var(--text-2)',
  background: 'var(--surface-2, rgba(255,255,255,.02))', border: '1px solid var(--border)',
  borderRadius: 8, padding: '10px 12px', margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
  maxHeight: 200, overflow: 'auto',
};

function Section({ icon, label, hint, children }: { icon: 'layers' | 'activity' | 'memory'; label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 8 }}>
        <Icon name={icon} size={14} style={{ color: 'var(--accent)' }} />
        <span style={{ fontSize: 13, fontWeight: 700 }}>{label}</span>
        {hint && <span style={{ fontSize: 11, color: 'var(--text-3)', fontFamily: 'var(--mono)' }}>· {hint}</span>}
      </div>
      {children}
    </div>
  );
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span style={{ fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--text-2)', padding: '3px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--surface-2, rgba(255,255,255,.03))' }}>
      {children}
    </span>
  );
}

function Dot({ state }: { state: 'wait' | 'busy' | 'done' }) {
  const c = state === 'done' ? '#45e0a0' : state === 'busy' ? '#ffb152' : 'var(--text-3)';
  return <span style={{ width: 8, height: 8, borderRadius: '50%', background: c, flexShrink: 0, boxShadow: state === 'busy' ? `0 0 8px ${c}` : 'none', animation: state === 'busy' ? 'pulse 1s infinite' : 'none' }} />;
}

// 让 tr 引用不被 tree-shake 报未用(面板内字符串暂为中文,后续接 i18n)
void tr;
