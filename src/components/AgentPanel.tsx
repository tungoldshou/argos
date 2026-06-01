// AgentPanel.tsx — Argos 的真 agent 交互面板。
//
// 输入一个目标 → 调 Python agent 服务(FastAPI+LangGraph)→ 流式渲染它的每一步:
// 模型决策 / 工具调用 / 工具结果 / 最终答案。这是 Argos 作为独立通用智能体的入口。
// 智能在 Python 侧(agent loop + 护城河),本面板只负责发起与可视化事件流。
import { useEffect, useRef, useState } from 'react';
import { Overlay } from './overlays';
import { Icon } from '../lib/icons';
import { agentHealth, runAgent, type AgentEvent } from '../lib/agent';

interface LogLine {
  kind: AgentEvent['type'];
  text: string;
}

const EXAMPLES = [
  '列出一个 REST 分页响应该包含的字段名,每行一个',
  '用一句话解释幂等性,然后只回那一句',
  '设计一个 TODO 数据模型的字段名与类型,逐行列出',
];

export function AgentPanel({ onClose, initialGoal, onComplete }: { onClose: () => void; initialGoal?: string; onComplete?: () => void }) {
  const [goal, setGoal] = useState(initialGoal ?? '');
  const [verifyCmd, setVerifyCmd] = useState('');
  const [projectDir, setProjectDir] = useState('');
  const [guardFiles, setGuardFiles] = useState('');
  // 聊天记录:每一项是一轮(用户输入 + 该轮 agent 事件流)。
  const [turns, setTurns] = useState<{ user: string; lines: LogLine[] }[]>([]);
  const [running, setRunning] = useState(false);
  const [health, setHealth] = useState<{ ok: boolean; model?: string } | null>(null);
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const started = turns.length > 0 || running; // 会话已开始 → 锁定 setup、折叠示例
  const abortRef = useRef<(() => void) | null>(null);
  const runRef = useRef<() => void>(() => {});
  const scrollRef = useRef<HTMLDivElement>(null);

  // 面板打开时探一次 agent 服务健康,驱动「就绪 / 未连接」提示。
  useEffect(() => {
    let alive = true;
    agentHealth().then((h) => { if (alive) setHealth({ ok: h.ok, model: h.model }); });
    return () => { alive = false; abortRef.current?.(); };
  }, []);

  // 首页大输入框直连真 agent:带着 goal 打开面板时,自动开跑(不再走假演示)。
  // 用微延迟启动 + cleanup 清定时器:StrictMode 的"假卸载-重挂载"周期里定时器会被清掉,
  // 只有真正稳定的挂载才跑到 run,避免连接刚建就被卸载 cleanup 中止(那会显示 AbortError)。
  useEffect(() => {
    if (!initialGoal || !initialGoal.trim()) return;
    const id = setTimeout(() => runRef.current(), 0);
    return () => clearTimeout(id);
  }, [initialGoal]);

  const push = (kind: AgentEvent['type'], text: string) =>
    setTurns((ts) => {
      if (ts.length === 0) return ts;
      const copy = ts.slice();
      const last = copy[copy.length - 1];
      copy[copy.length - 1] = { ...last, lines: [...last.lines, { kind, text }] };
      return copy;
    });

  const run = () => {
    const g = goal.trim();
    if (!g || running) return;
    setTurns((ts) => [...ts, { user: g, lines: [] }]);
    setGoal('');
    setRunning(true);
    abortRef.current = runAgent(
      g,
      (e) => {
        if (e.type === 'session') { setSessionId(String(e.data.session_id || '')); return; }
        if (e.type === 'start') return;
        else if (e.type === 'tool_call') {
          const calls = (e.data.calls as { name: string; args: unknown }[]) ?? [];
          calls.forEach((c) => push('tool_call', `调用工具 ${c.name}(${JSON.stringify(c.args)})`));
        } else if (e.type === 'tool_result') push('tool_result', `工具返回:${e.data.content}`);
        else if (e.type === 'verify_failed') push('verify_failed', `验证未通过 — Argos 拦截了一次"假完成":\n${e.data.detail}`);
        else if (e.type === 'escalation') push('escalation', `Argos 卡住了,诚实求助:\n${e.data.detail}`);
        else if (e.type === 'tampering') {
          const files = (e.data.files as string[]) ?? [];
          push('tampering', `⚠ Argos 改动了被保护的测试文件(篡改可见):${files.join('、')}。请人工核对它有没有为了"通过"而改测试。`);
        } else if (e.type === 'message') push('message', String(e.data.text ?? ''));
      },
      (err) => {
        if (err) push('error', err);
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

  return (
    <Overlay title="Agent" icon="sparkle" sub="独立通用智能体 · LangGraph" onClose={onClose}>
      {/* 服务状态条 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 12, fontSize: 11.5, fontFamily: 'var(--mono)', color: health?.ok ? 'var(--live, #45e0a0)' : 'var(--text-3)' }}>
        <span style={{ width: 7, height: 7, borderRadius: '50%', background: health?.ok ? 'var(--live, #45e0a0)' : 'var(--text-3)', boxShadow: health?.ok ? '0 0 7px var(--live, #45e0a0)' : 'none' }} />
        {health === null ? '检测 agent 服务…' : health.ok ? `agent 就绪 · ${health.model}` : 'agent 服务未连接(确认 Python 服务已启动)'}
      </div>

      {/* 任务设置:仅会话开始前可改;开始后折叠为只读摘要(首轮锁定可见) */}
      {!started ? (
        <div style={{ marginBottom: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
          <input value={verifyCmd} onChange={(e) => setVerifyCmd(e.target.value)}
            placeholder='验证命令(可选,如 python3 check.py)— 给了它,"完成"必须过验证'
            style={{ width: '100%', boxSizing: 'border-box', height: 32, padding: '0 11px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface-2, rgba(255,255,255,.02))', color: 'var(--text-2)', fontSize: 12, fontFamily: 'var(--mono)' }} />
          <input value={projectDir} onChange={(e) => setProjectDir(e.target.value)}
            placeholder="项目目录(可选,如 /Users/you/myproject)— 在你自己的项目里干活"
            style={{ width: '100%', boxSizing: 'border-box', height: 32, padding: '0 11px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface-2, rgba(255,255,255,.02))', color: 'var(--text-2)', fontSize: 12, fontFamily: 'var(--mono)' }} />
          {projectDir.trim() && (
            <input value={guardFiles} onChange={(e) => setGuardFiles(e.target.value)}
              placeholder="监控的测试文件(逗号分隔)— agent 改了会警告"
              style={{ width: '100%', boxSizing: 'border-box', height: 30, padding: '0 11px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface-2, rgba(255,255,255,.02))', color: 'var(--text-3)', fontSize: 11.5, fontFamily: 'var(--mono)' }} />
          )}
        </div>
      ) : (verifyCmd.trim() || projectDir.trim()) ? (
        <div style={{ marginBottom: 12, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {verifyCmd.trim() && <span style={{ fontSize: 10.5, fontFamily: 'var(--mono)', color: 'var(--accent)', border: '1px solid color-mix(in oklab,var(--accent),transparent 70%)', borderRadius: 6, padding: '2px 8px' }}>🛡 verify: {verifyCmd.trim()}</span>}
          {projectDir.trim() && <span style={{ fontSize: 10.5, fontFamily: 'var(--mono)', color: 'var(--text-3)', border: '1px solid var(--border)', borderRadius: 6, padding: '2px 8px' }}>📁 {projectDir.trim()}</span>}
        </div>
      ) : null}

      {/* 空态示例:仅未开始时 */}
      {!started && (
        <div style={{ marginTop: 4 }}>
          <div style={{ fontSize: 12, color: 'var(--text-3)', marginBottom: 8 }}>试试:</div>
          {EXAMPLES.map((ex) => (
            <button key={ex} onClick={() => setGoal(ex)}
              style={{ display: 'block', width: '100%', textAlign: 'left', marginBottom: 6, padding: '9px 12px', borderRadius: 8, border: '1px solid var(--border)', background: 'none', color: 'var(--text-2)', fontSize: 12.5, cursor: 'pointer' }}>
              {ex}
            </button>
          ))}
        </div>
      )}

      {/* 聊天记录:逐轮渲染(用户气泡 + 该轮事件流) */}
      <div ref={scrollRef} style={{ display: 'flex', flexDirection: 'column', gap: 14, maxHeight: '48vh', overflow: 'auto', marginBottom: 12 }}>
        {turns.map((turn, ti) => (
          <div key={ti} style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
            <div style={{ alignSelf: 'flex-end', maxWidth: '85%', padding: '8px 12px', borderRadius: 12, background: 'color-mix(in oklab,var(--accent),transparent 86%)', color: 'var(--text-1)', fontSize: 13, lineHeight: 1.5 }}>{turn.user}</div>
            {turn.lines.map((l, i) => <LogRow key={i} line={l} />)}
          </div>
        ))}
        {running && (
          <div style={{ fontFamily: 'var(--mono)', fontSize: 11.5, color: 'var(--text-3)' }}>
            <span style={{ animation: 'blink-caret 1s step-end infinite', color: 'var(--accent)' }}>▋</span> 运行中…
          </div>
        )}
      </div>

      {/* 常驻 composer:run 结束后保持可用,可继续追问(持续对话核心) */}
      <div style={{ display: 'flex', gap: 8 }}>
        <input value={goal} onChange={(e) => setGoal(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && run()}
          placeholder={started ? '继续追问…' : '给 Argos 一个目标…'} disabled={running}
          style={{ flex: 1, height: 38, padding: '0 12px', borderRadius: 9, border: '1px solid var(--border)', background: 'var(--surface-2, rgba(255,255,255,.03))', color: 'var(--text-1)', fontSize: 13 }} />
        <button onClick={running ? stop : run} disabled={!running && !goal.trim()}
          style={{ height: 38, padding: '0 16px', borderRadius: 9, border: 'none', background: running ? '#ff7a4d' : 'var(--accent)', color: '#1a1205', fontWeight: 700, fontSize: 13, cursor: 'pointer', whiteSpace: 'nowrap' }}>
          {running ? '停止' : started ? '发送' : '运行'}
        </button>
      </div>
    </Overlay>
  );
}

function LogRow({ line }: { line: LogLine }) {
  const style: Record<LogLine['kind'], { icon: 'sparkle' | 'activity' | 'memory' | 'layers'; color: string; bg?: string }> = {
    session: { icon: 'memory', color: 'var(--text-3)' },
    start: { icon: 'sparkle', color: 'var(--text-3)' },
    tool_call: { icon: 'activity', color: 'var(--accent)' },
    tool_result: { icon: 'layers', color: '#86bcff' },
    message: { icon: 'memory', color: 'var(--text-1)' },
    // verify 硬门禁拦截:橙色,强调"被拦下了一次假完成"。
    verify_failed: { icon: 'activity', color: '#ffb152', bg: 'color-mix(in oklab, #ffb152, transparent 90%)' },
    // 诚实升级:红色,强调"agent 卡住、需人工"。这是产品灵魂的可见时刻。
    escalation: { icon: 'memory', color: '#ff7a4d', bg: 'color-mix(in oklab, #ff7a4d, transparent 86%)' },
    // 篡改警告:红色高亮,提醒用户 agent 动了测试文件(可能为通过而作弊)。
    tampering: { icon: 'activity', color: '#ff5c5c', bg: 'color-mix(in oklab, #ff5c5c, transparent 84%)' },
    done: { icon: 'sparkle', color: 'var(--live, #45e0a0)' },
    error: { icon: 'activity', color: '#ff7a4d' },
  };
  const s = style[line.kind];
  return (
    <div style={{ display: 'flex', gap: 9, padding: '9px 11px', borderRadius: 8, border: `1px solid ${s.bg ? s.color : 'var(--border)'}`, background: s.bg ?? 'var(--surface-2, rgba(255,255,255,.02))' }}>
      <Icon name={s.icon} size={14} style={{ color: s.color, flexShrink: 0, marginTop: 1 }} />
      <span style={{ fontSize: 12.5, color: s.color, whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.5 }}>{line.text}</span>
    </div>
  );
}
