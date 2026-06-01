// AgentPanel.tsx — Argos agent 交互面板(编排层)。
// 目标 → Python agent 服务(FastAPI+LangGraph)→ 流式事件 → reduceEvent 归并成 blocks → 渲染。
// 两栏:左/中聊天主列(限宽居中) + 右侧露出背景脑图 canvas 当"活记忆"栏。
// 智能在 Python 侧;本面板只负责发起、归并、可视化。
import { useEffect, useRef, useState } from 'react';
import { useNarrow } from '../lib/responsive';
import { Icon } from '../lib/icons';
import { agentHealth, runAgent } from '../lib/agent';
import { reduceEvent, startTurn, type Turn } from '../lib/chatReducer';
import { Message } from './chat/Message';
import { Composer } from './chat/Composer';
import { TaskSetup } from './chat/TaskSetup';

const EXAMPLES = [
  '列出一个 REST 分页响应该包含的字段名,每行一个',
  '用一句话解释幂等性,然后只回那一句',
  '设计一个 TODO 数据模型的字段名与类型,逐行列出',
];

// 生成稳定 turn id(不依赖 Date.now/随机,用自增计数)。
let _turnSeq = 0;
const nextTurnId = () => `turn-${++_turnSeq}`;

export function AgentPanel({ onClose, initialGoal, onComplete }: { onClose: () => void; initialGoal?: string; onComplete?: () => void }) {
  const narrow = useNarrow();
  const [goal, setGoal] = useState(initialGoal ?? '');
  const [verifyCmd, setVerifyCmd] = useState('');
  const [projectDir, setProjectDir] = useState('');
  const [guardFiles, setGuardFiles] = useState('');
  const [turns, setTurns] = useState<Turn[]>([]);
  const [running, setRunning] = useState(false);
  const [health, setHealth] = useState<{ ok: boolean; model?: string } | null>(null);
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const started = turns.length > 0 || running;
  const abortRef = useRef<(() => void) | null>(null);
  const runRef = useRef<() => void>(() => {});
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    agentHealth().then((h) => { if (alive) setHealth({ ok: h.ok, model: h.model }); });
    return () => { alive = false; abortRef.current?.(); };
  }, []);

  // 首页带 goal 打开 → 自动开跑(微延迟 + cleanup 防 StrictMode 双挂载误触发)。
  useEffect(() => {
    if (!initialGoal || !initialGoal.trim()) return;
    const id = setTimeout(() => runRef.current(), 0);
    return () => clearTimeout(id);
  }, [initialGoal]);

  const run = () => {
    const g = goal.trim();
    if (!g || running) return;
    setTurns((ts) => startTurn(ts, g, nextTurnId()));
    setGoal('');
    setRunning(true);
    abortRef.current = runAgent(
      g,
      (e) => {
        if (e.type === 'session') { setSessionId(String(e.data.session_id || '')); return; }
        setTurns((ts) => reduceEvent(ts, e));
      },
      (err) => {
        if (err) setTurns((ts) => reduceEvent(ts, { type: 'error', data: { message: err } }));
        setRunning(false);
        abortRef.current = null;
        if (!err) onComplete?.();
      },
      {
        sessionId,
        verifyCmd: verifyCmd.trim() || undefined,
        projectDir: projectDir.trim() || undefined,
        guardFiles: guardFiles.trim() ? guardFiles.split(',').map((s) => s.trim()).filter(Boolean) : undefined,
      },
    );
  };
  runRef.current = run;

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [turns, running]);

  const stop = () => { abortRef.current?.(); setRunning(false); abortRef.current = null; };

  // 两栏:窄屏铺满;宽屏左聊天列(弹性,右留出 ~320px 露出背景脑图)。
  const shellStyle: React.CSSProperties = narrow
    ? { position: 'absolute', top: 8, left: 8, right: 8, bottom: 62, zIndex: 11, display: 'flex', flexDirection: 'column', overflow: 'hidden', animation: 'slidein .35s cubic-bezier(0.16,1,0.3,1) both' }
    : { position: 'absolute', top: 16, left: 16, bottom: 16, width: 'min(62vw, 860px)', zIndex: 11, display: 'flex', flexDirection: 'column', overflow: 'hidden', animation: 'slidein .35s cubic-bezier(0.16,1,0.3,1) both' };

  return (
    <div className="mind-panel" style={shellStyle}>
      {/* header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '14px 18px', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
        <div style={{ width: 32, height: 32, borderRadius: 9, display: 'grid', placeItems: 'center', background: 'color-mix(in oklab, var(--accent), transparent 84%)', color: 'var(--accent)' }}>
          <Icon name="sparkle" size={17} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 15, fontWeight: 700 }}>Agent</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, fontFamily: 'var(--mono)', color: health?.ok ? 'var(--live, #45e0a0)' : 'var(--text-3)', marginTop: 1 }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: health?.ok ? 'var(--live, #45e0a0)' : 'var(--text-3)', boxShadow: health?.ok ? '0 0 6px var(--live, #45e0a0)' : 'none' }} />
            {health === null ? '检测中…' : health.ok ? `就绪 · ${health.model}` : '未连接'}
          </div>
        </div>
        <button onClick={onClose} className="mind-link" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, height: 30, padding: '0 11px', borderRadius: 8, border: '1px solid var(--border)', background: 'none', color: 'var(--text-2)', cursor: 'pointer', fontFamily: 'var(--mono)', fontSize: 11 }}>
          <Icon name="chevron" size={13} style={{ transform: 'rotate(180deg)' }} /> 返回记忆
        </button>
      </div>

      {/* 消息滚动区(限宽居中) */}
      <div ref={scrollRef} style={{ flex: 1, overflow: 'auto', padding: '16px 18px' }}>
        <div style={{ maxWidth: 760, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 16 }}>
          {!started && (
            <>
              <TaskSetup verifyCmd={verifyCmd} projectDir={projectDir} guardFiles={guardFiles}
                onChange={(p) => { if (p.verifyCmd !== undefined) setVerifyCmd(p.verifyCmd); if (p.projectDir !== undefined) setProjectDir(p.projectDir); if (p.guardFiles !== undefined) setGuardFiles(p.guardFiles); }} />
              <div>
                <div style={{ fontSize: 12, color: 'var(--text-3)', marginBottom: 8 }}>试试:</div>
                {EXAMPLES.map((ex) => (
                  <button key={ex} onClick={() => setGoal(ex)} style={{ display: 'block', width: '100%', textAlign: 'left', marginBottom: 6, padding: '9px 12px', borderRadius: 9, border: '1px solid var(--border)', background: 'none', color: 'var(--text-2)', fontSize: 12.5, cursor: 'pointer' }}>
                    {ex}
                  </button>
                ))}
              </div>
            </>
          )}
          {started && (verifyCmd.trim() || projectDir.trim()) && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {verifyCmd.trim() && <span style={{ fontSize: 10.5, fontFamily: 'var(--mono)', color: 'var(--accent)', border: '1px solid color-mix(in oklab,var(--accent),transparent 70%)', borderRadius: 6, padding: '2px 8px' }}>🛡 verify: {verifyCmd.trim()}</span>}
              {projectDir.trim() && <span style={{ fontSize: 10.5, fontFamily: 'var(--mono)', color: 'var(--text-3)', border: '1px solid var(--border)', borderRadius: 6, padding: '2px 8px' }}>📁 {projectDir.trim()}</span>}
            </div>
          )}
          {turns.map((turn, i) => (
            <div key={turn.id}>
              {i > 0 && <div style={{ height: 1, background: 'var(--border)' }} />}
              <Message turn={turn} />
            </div>
          ))}
          {running && turns.length > 0 && turns[turns.length - 1].blocks.length === 0 && (
            <div style={{ fontFamily: 'var(--mono)', fontSize: 11.5, color: 'var(--text-3)' }}>
              <span style={{ animation: 'blink-caret 1s step-end infinite', color: 'var(--accent)' }}>▋</span> 运行中…
            </div>
          )}
        </div>
      </div>

      {/* sticky composer */}
      <div style={{ flexShrink: 0, padding: '12px 18px', borderTop: '1px solid var(--border)' }}>
        <div style={{ maxWidth: 760, margin: '0 auto' }}>
          <Composer value={goal} onChange={setGoal} onSend={run} onStop={stop} running={running}
            placeholder={started ? '继续追问…' : '给 Argos 一个目标…'} />
        </div>
      </div>
    </div>
  );
}
