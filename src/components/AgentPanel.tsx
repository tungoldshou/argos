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
  const [log, setLog] = useState<LogLine[]>([]);
  const [running, setRunning] = useState(false);
  const [health, setHealth] = useState<{ ok: boolean; model?: string } | null>(null);
  const abortRef = useRef<(() => void) | null>(null);
  const runRef = useRef<() => void>(() => {});

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
    setLog((l) => [...l, { kind, text }]);

  const run = () => {
    const g = goal.trim();
    if (!g || running) return;
    setLog([]);
    setRunning(true);
    abortRef.current = runAgent(
      g,
      (e) => {
        if (e.type === 'start') push('start', `目标:${e.data.goal}`);
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
        // 任务正常收尾(非报错)→ 通知上层刷新记忆,让脑图长出这次任务。
        if (!err) onComplete?.();
      },
      {
        verifyCmd: verifyCmd.trim() || undefined,
        projectDir: projectDir.trim() || undefined,
        guardFiles: guardFiles.trim() ? guardFiles.split(',').map((s) => s.trim()).filter(Boolean) : undefined,
      },
    );
  };

  runRef.current = run;

  const stop = () => { abortRef.current?.(); setRunning(false); abortRef.current = null; };

  return (
    <Overlay title="Agent" icon="sparkle" sub="独立通用智能体 · LangGraph + MiniMax" onClose={onClose}>
      {/* 服务状态条 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 12, fontSize: 11.5, fontFamily: 'var(--mono)', color: health?.ok ? 'var(--live, #45e0a0)' : 'var(--text-3)' }}>
        <span style={{ width: 7, height: 7, borderRadius: '50%', background: health?.ok ? 'var(--live, #45e0a0)' : 'var(--text-3)', boxShadow: health?.ok ? '0 0 7px var(--live, #45e0a0)' : 'none' }} />
        {health === null ? '检测 agent 服务…' : health.ok ? `agent 就绪 · ${health.model}` : 'agent 服务未连接(确认 Python 服务已启动)'}
      </div>

      {/* 目标输入 */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <input
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && run()}
          placeholder="给 Argos 一个目标…"
          disabled={running}
          style={{ flex: 1, height: 38, padding: '0 12px', borderRadius: 9, border: '1px solid var(--border)', background: 'var(--surface-2, rgba(255,255,255,.03))', color: 'var(--text-1)', fontSize: 13 }}
        />
        <button onClick={running ? stop : run} disabled={!running && !goal.trim()}
          style={{ height: 38, padding: '0 16px', borderRadius: 9, border: 'none', background: running ? '#ff7a4d' : 'var(--accent)', color: '#1a1205', fontWeight: 700, fontSize: 13, cursor: 'pointer', whiteSpace: 'nowrap' }}>
          {running ? '停止' : '运行'}
        </button>
      </div>

      {/* verify 硬门禁:可选的验证命令。给了它,agent 称"完成"必须过这条命令(退出码0),
          否则被拦回去重试,反复不过则诚实升级求助。这是 Argos 的核心护城河,在 UI 可见。 */}
      <div style={{ marginBottom: 12 }}>
        <input
          value={verifyCmd}
          onChange={(e) => setVerifyCmd(e.target.value)}
          placeholder='验证命令(可选,如 python3 check.py)— 给了它,"完成"必须过验证'
          disabled={running}
          style={{ width: '100%', boxSizing: 'border-box', height: 32, padding: '0 11px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface-2, rgba(255,255,255,.02))', color: 'var(--text-2)', fontSize: 12, fontFamily: 'var(--mono)' }}
        />
        {verifyCmd.trim() && (
          <div style={{ marginTop: 5, fontSize: 10.5, color: 'var(--accent)', fontFamily: 'var(--mono)' }}>
            🛡 verify 硬门禁已启用 — 退出码裁决,agent 无法假装完成
          </div>
        )}
      </div>

      {/* 项目模式:让 agent 在你自己的项目里干活、跑你自己的测试(懂技术用户场景)。
          留空 = 默认沙盒。填了项目路径 + 要监控的测试文件,agent 若改测试会被警告(篡改可见)。 */}
      <div style={{ marginBottom: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
        <input
          value={projectDir}
          onChange={(e) => setProjectDir(e.target.value)}
          placeholder="项目目录(可选,如 /Users/you/myproject)— 在你自己的项目里干活"
          disabled={running}
          style={{ width: '100%', boxSizing: 'border-box', height: 32, padding: '0 11px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface-2, rgba(255,255,255,.02))', color: 'var(--text-2)', fontSize: 12, fontFamily: 'var(--mono)' }}
        />
        {projectDir.trim() && (
          <input
            value={guardFiles}
            onChange={(e) => setGuardFiles(e.target.value)}
            placeholder="监控的测试文件(逗号分隔,如 tests/test_x.py)— agent 改了会警告"
            disabled={running}
            style={{ width: '100%', boxSizing: 'border-box', height: 30, padding: '0 11px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface-2, rgba(255,255,255,.02))', color: 'var(--text-3)', fontSize: 11.5, fontFamily: 'var(--mono)' }}
          />
        )}
      </div>

      {/* 空态:示例 */}
      {log.length === 0 && !running && (
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

      {/* 事件流 */}
      {log.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
          {log.map((l, i) => (
            <LogRow key={i} line={l} />
          ))}
          {running && (
            <div style={{ fontFamily: 'var(--mono)', fontSize: 11.5, color: 'var(--text-3)' }}>
              <span style={{ animation: 'blink-caret 1s step-end infinite', color: 'var(--accent)' }}>▋</span> 运行中…
            </div>
          )}
        </div>
      )}
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
