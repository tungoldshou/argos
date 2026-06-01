// App.tsx — cinematic shell: memory brain at center, work + features dock in from
// the right, ⌘K command palette, voice in the command bar, EN/中, responsive.
import { useState, useEffect, useRef, type CSSProperties } from 'react';
import { MindGraph, META, type GraphNode } from './engine/MindGraph';
import { CATS, buildEmptyMind } from './data/mind';
import { memoryToMind } from './data/memoryToMind';
import type { LearnSpec, NodeType } from './data/types';
import { Icon, HermesMark, type IconName } from './lib/icons';
import { useLang } from './lib/i18n';
import { RunView } from './components/RunView';
import { OVERLAYS, type OverlayKey } from './components/overlays';
import { SwarmPanel } from './components/SwarmPanel';
import { AgentPanel } from './components/AgentPanel';
import { agentHealth, agentMemory } from './lib/agent';
import { Dot, Meta } from './components/atoms';
import { useTweaks, TweaksPanel, TweakSection, TweakToggle, TweakButton } from './components/Tweaks';
import { useViewportWidth } from './lib/responsive';

const MIND_ACCENTS = [
  { id: 'amber', hex: '#ffb152' }, { id: 'ember', hex: '#ff7a4d' },
  { id: 'ice', hex: '#5fd0ff' }, { id: 'mint', hex: '#45e0a0' }, { id: 'iris', hex: '#b48cff' },
];
const DEMO_GOAL = 'list the fields a REST pagination response should contain, one per line';
// 示例任务:都贴合 Argos 的真实场景 —— 结构化、结果可验证的工程任务(可及性边界内)。
// 体现卖点:能干活 + 可机检完成。不是 Hermes 时代的个人助理故事。
// key 用英文(i18n 约定),中文译文在 i18n.ts。
const SUGGESTIONS = [
  'List the fields a REST pagination response should contain',
  'Design a TODO data model — fields and types',
  'Explain idempotency in one sentence, then reply only that',
  'Write a palindrome check function with tests',
];

interface DockItem {
  key: string;
  icon: IconName;
  label: string;
  hint: string;
  group: string;
}
const DOCK: DockItem[] = [
  { key: 'memory', icon: 'memory', label: 'Memory', hint: 'home', group: 'Home' },
  { key: 'agent', icon: 'sparkle', label: 'Agent', hint: 'LangGraph', group: 'Work' },
  { key: 'swarm', icon: 'layers', label: 'Swarm', hint: '蜂群', group: 'Work' },
  { key: 'runs', icon: 'activity', label: 'Runs', hint: 'tasks', group: 'Work' },
  { key: 'skills', icon: 'skills', label: 'Skills', hint: '38', group: 'Capabilities' },
  { key: 'tools', icon: 'layers', label: 'Tools', hint: '7', group: 'Capabilities' },
  { key: 'mcp', icon: 'plug', label: 'MCP', hint: 'servers', group: 'Capabilities' },
  { key: 'voice', icon: 'voice', label: 'Voice', hint: 'mic', group: 'Reach' },
  { key: 'connections', icon: 'connections', label: 'Connections', hint: '20+', group: 'Reach' },
  { key: 'automations', icon: 'automations', label: 'Automations', hint: 'cron', group: 'Reach' },
  { key: 'personality', icon: 'mask', label: 'Personality', hint: 'SOUL.md', group: 'Identity' },
  { key: 'sandboxes', icon: 'sandbox', label: 'Sandboxes', hint: '6', group: 'Identity' },
  { key: 'settings', icon: 'settings', label: 'Settings', hint: 'models', group: 'Identity' },
];

function CommandPalette({ open, onClose, onPick }: { open: boolean; onClose: () => void; onPick: (key: string) => void }) {
  const { t } = useLang();
  const [q, setQ] = useState('');
  const [sel, setSel] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const items = DOCK.filter((d) => d.key !== 'memory');
  const filtered = items.filter((d) => t(d.label).toLowerCase().includes(q.toLowerCase()) || d.key.includes(q.toLowerCase()));
  useEffect(() => {
    if (open) {
      setQ('');
      setSel(0);
      setTimeout(() => inputRef.current?.focus(), 30);
    }
  }, [open]);
  useEffect(() => { setSel(0); }, [q]);
  if (!open) return null;
  const choose = (d: DockItem | undefined) => { if (d) { onPick(d.key); onClose(); } };
  return (
    <div onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{ position: 'absolute', inset: 0, zIndex: 30, display: 'grid', placeItems: 'start center', paddingTop: '14vh', background: 'oklch(0.08 0.012 270 / 0.5)', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)', animation: 'fadein .18s both' }}>
      <div className="mind-panel" style={{ width: 'min(520px, 90vw)', display: 'flex', flexDirection: 'column', overflow: 'hidden', animation: 'pop .26s cubic-bezier(0.16,1,0.3,1) both' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 11, padding: '14px 18px', borderBottom: '1px solid var(--border)' }}>
          <Icon name="sparkle" size={17} style={{ color: 'var(--accent)' }} />
          <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') { e.preventDefault(); setSel((s) => Math.min(filtered.length - 1, s + 1)); }
              else if (e.key === 'ArrowUp') { e.preventDefault(); setSel((s) => Math.max(0, s - 1)); }
              else if (e.key === 'Enter') choose(filtered[sel]);
              else if (e.key === 'Escape') onClose();
            }}
            placeholder={t('Jump to a feature…')} style={{ flex: 1, background: 'none', border: 'none', outline: 'none', color: 'var(--text)', fontSize: 15 }} />
          <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--text-3)', border: '1px solid var(--border)', borderRadius: 5, padding: '2px 6px' }}>ESC</span>
        </div>
        <div style={{ padding: 8, maxHeight: '46vh', overflow: 'auto' }}>
          {filtered.length === 0 && <div style={{ padding: '22px 12px', textAlign: 'center', color: 'var(--text-3)', fontSize: 13 }}>{t('No feature matches')}</div>}
          {filtered.map((d, i) => {
            const prev = filtered[i - 1];
            const showHeader = q.trim() === '' && (!prev || prev.group !== d.group);
            return (
              <div key={d.key}>
                {showHeader && (
                  <div style={{ fontFamily: 'var(--mono)', fontSize: 9.5, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--text-3)', padding: '10px 12px 5px' }}>{t(d.group)}</div>
                )}
                <button onMouseEnter={() => setSel(i)} onClick={() => choose(d)}
                  style={{ display: 'flex', alignItems: 'center', gap: 12, width: '100%', textAlign: 'left', padding: '10px 12px', borderRadius: 9, cursor: 'pointer', border: '1px solid transparent', background: i === sel ? 'color-mix(in oklab, var(--accent), transparent 86%)' : 'transparent', transition: 'background .12s' }}>
                  <div style={{ width: 30, height: 30, borderRadius: 8, display: 'grid', placeItems: 'center', background: i === sel ? 'color-mix(in oklab, var(--accent), transparent 78%)' : 'var(--surface-2)', color: i === sel ? 'var(--accent)' : 'var(--text-2)', flexShrink: 0 }}><Icon name={d.icon} size={16} /></div>
                  <span style={{ flex: 1, fontSize: 13.5, fontWeight: 600, color: i === sel ? 'var(--text)' : 'var(--text-2)' }}>{t(d.label)}</span>
                  <span style={{ fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--text-3)' }}>{t(d.hint)}</span>
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function DetailPanel({ node, engine, locked, onClose, narrow }: {
  node: GraphNode | null;
  engine: MindGraph | null;
  locked: boolean;
  onClose: () => void;
  narrow: boolean;
}) {
  const { t } = useLang();
  if (!node) return null;
  const cat = CATS[node.type];
  const meta = META[node.label] || {};
  const neighbors = engine ? engine.adj[node.id].map((j) => engine.nodes[j]).filter(Boolean) : [];
  const pos = narrow
    ? { left: 10, right: 10, bottom: 132, maxHeight: '46vh', animation: 'sheetup .3s cubic-bezier(0.16,1,0.3,1) both' }
    : { top: 64, right: 18, width: 322, maxHeight: 'calc(100% - 150px)', animation: 'slidein .3s cubic-bezier(0.16,1,0.3,1) both' };
  return (
    <div className="mind-panel" style={{ position: 'absolute', display: 'flex', flexDirection: 'column', zIndex: 11, ...pos }}>
      <div style={{ padding: '16px 18px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 10 }}>
          <Dot color={node.type === 'self' ? 'var(--accent)' : cat.color} glow />
          <span style={{ fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'var(--text-3)' }}>{t(cat.label)}</span>
          <div style={{ flex: 1 }} />
          {(locked || narrow) && <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-3)', cursor: 'pointer', fontSize: 17, lineHeight: 1, padding: 2 }}>×</button>}
        </div>
        <div style={{ fontSize: 18, fontWeight: 600, letterSpacing: '-0.01em', color: 'var(--text)', lineHeight: 1.25, fontFamily: node.type === 'skill' ? 'var(--mono)' : 'var(--ui)' }}>{t(node.label)}</div>
        {meta.detail && <div style={{ fontSize: 13, color: 'var(--text-2)', lineHeight: 1.55, marginTop: 9 }}>{t(meta.detail)}</div>}
      </div>
      <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)', display: 'flex', gap: 18, flexWrap: 'wrap' }}>
        {meta.uses != null && <Meta k={t('recalled')} v={meta.uses + '×'} />}
        {meta.learned && <Meta k={t('learned')} v={t(meta.learned)} />}
        {meta.src && <Meta k={t('origin')} v={t(meta.src)} />}
        {meta.uses == null && !meta.learned && <Meta k={t('links')} v={neighbors.length} />}
      </div>
      <div style={{ padding: '14px 18px', overflow: 'auto' }}>
        <div style={{ fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--text-3)', marginBottom: 11 }}>{t('Connected')} · {neighbors.length}</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          {neighbors.map((nb) => (
            <button key={nb.id} onClick={() => engine?.select(nb.id)} className="mind-link"
              style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 9px', borderRadius: 8, background: 'none', border: '1px solid transparent', cursor: 'pointer', textAlign: 'left', width: '100%', color: 'var(--text-2)' }}>
              <Dot color={nb.type === 'self' ? 'var(--accent)' : CATS[nb.type].color} size={7} />
              <span style={{ fontSize: 12.5, flex: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', fontFamily: nb.type === 'skill' ? 'var(--mono)' : 'var(--ui)' }}>{t(nb.label)}</span>
              <span style={{ fontFamily: 'var(--mono)', fontSize: 9.5, color: 'var(--text-3)', textTransform: 'uppercase' }}>{nb.type}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export function App() {
  const { lang, t } = useLang();
  const [tw, setTweak] = useTweaks({ accent: 'amber', motion: true });
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const engineRef = useRef<MindGraph | null>(null);
  const [hoverN, setHoverN] = useState<GraphNode | null>(null);
  const [selN, setSelN] = useState<GraphNode | null>(null);
  const [thought, setThought] = useState<string | null>(null);
  const [toasts, setToasts] = useState<{ id: number; label: string; type: NodeType }[]>([]);
  const [q, setQ] = useState('');
  const [cmd, setCmd] = useState('');
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [panel, setPanel] = useState<string | null>(null); // null | 'runs' | feature key
  const [goal, setGoal] = useState('');
  const [agentGoal, setAgentGoal] = useState('');
  const [runKey, setRunKey] = useState(0);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [connected, setConnected] = useState(false);
  const [hasMemory, setHasMemory] = useState(false);
  const refreshMemoryRef = useRef<(() => void) | null>(null);
  const thoughtTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const vw = useViewportWidth();
  const narrow = vw < 720;
  const [showHint, setShowHint] = useState(() => {
    try { return !localStorage.getItem('argos-onboarded'); } catch { return true; }
  });
  const dismissHint = () => {
    try { localStorage.setItem('argos-onboarded', '1'); } catch { /* ignore */ }
    setShowHint(false);
  };

  // respect prefers-reduced-motion on first load
  useEffect(() => {
    const rm = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (rm) {
      try {
        if (!localStorage.getItem('argos-rm')) {
          localStorage.setItem('argos-rm', '1');
          setTweak('motion', false);
        }
      } catch { /* ignore */ }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 连接指示灯:轮询真实 agent 服务 /health。LIVE = sidecar 已起且 key 已配。
  // 不读构建时 env(那是打包时刻的 stale 快照,会撒谎)。灯反映的是此刻的真实状态。
  useEffect(() => {
    let alive = true;
    const probe = async () => {
      const h = await agentHealth();
      if (alive) setConnected(h.ok && h.keyConfigured !== false);
    };
    probe();
    const id = setInterval(probe, 5000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  // ⌘K / Ctrl+K toggles the command palette
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, []);

  useEffect(() => {
    let eng: MindGraph | null = null;
    let disposed = false;

    const wire = (e: MindGraph) => {
      e.on.hover = (n) => setHoverN(n);
      e.on.select = (n) => setSelN(n);
      e.on.thought = (n) => {
        setThought(n ? (n.query ? '“' + n.label + '”' : n.label) : null);
        if (thoughtTimer.current) clearTimeout(thoughtTimer.current);
        thoughtTimer.current = setTimeout(() => setThought(null), 2800);
      };
      e.on.grow = (n) => {
        const id = Math.random();
        setToasts((ts) => [...ts, { id, label: n.label, type: n.type }]);
        setTimeout(() => setToasts((ts) => ts.filter((x) => x.id !== id)), 4200);
        setCounts((c) => ({ ...c, [n.type]: (c[n.type] || 0) + 1 }));
      };
      const c: Record<string, number> = {};
      e.nodes.forEach((n) => { c[n.type] = (c[n.type] || 0) + 1; });
      setCounts(c);
      e.setAccent((MIND_ACCENTS.find((a) => a.id === tw.accent) || MIND_ACCENTS[0]).hex);
    };

    // Argos 自有记忆大脑:真实、随任务生长。
    // 起步用空图(诚实空态 —— 独立 agent 还没积累记忆,不编造 seed);
    // 异步拉 /memory,有真实任务记忆就重建成记忆知识图谱。
    const build = (graph: ReturnType<typeof buildEmptyMind>) => {
      if (disposed) return;
      eng?.destroy();
      eng = new MindGraph(canvasRef.current!, graph);
      engineRef.current = eng;
      wire(eng);
    };
    build(buildEmptyMind());

    // 拉真实记忆 → 有则长出记忆图谱;无则保持诚实空态。
    const refreshMemory = async () => {
      const records = await agentMemory();
      if (disposed) return;
      const graph = memoryToMind(records);
      setHasMemory(!!graph);
      if (graph) build(graph);
    };
    refreshMemory();
    refreshMemoryRef.current = refreshMemory;

    return () => { disposed = true; refreshMemoryRef.current = null; eng?.destroy(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const eng = engineRef.current;
    if (!eng) return;
    const hex = (MIND_ACCENTS.find((a) => a.id === tw.accent) || MIND_ACCENTS[0]).hex;
    document.documentElement.style.setProperty('--accent', hex);
    document.documentElement.style.setProperty('--accent-text', hex);
    eng.setAccent(hex);
    eng.setMotion(tw.motion);
  }, [tw]);

  // dock 时大脑该锚到的横向比例 = 左侧可见区(0..面板左边界)的中心 / 视口宽。
  // 面板 CSS 是 right:16 + width:min(600,56vw),据此复现面板左边界,无论视口多宽都真居中。
  const dockAnchorFrac = (): number => {
    const vw = typeof window !== 'undefined' ? window.innerWidth : 1440;
    const panelW = Math.min(600, vw * 0.56);
    const panelLeft = vw - 16 - panelW;
    return (panelLeft / 2) / vw; // 左可见区中心 / 视口宽
  };
  const closePanel = () => {
    setPanel(null);
    engineRef.current?.dock(false, narrow);
  };
  const openPanel = (key: string, goalText?: string) => {
    const eng = engineRef.current;
    if (!eng) return;
    setQ('');
    eng.search('');
    if (key === 'memory') { closePanel(); return; }
    if (key === 'runs') {
      setGoal(goalText || DEMO_GOAL);
      setRunKey((k) => k + 1);
    }
    if (key === 'agent') {
      // 带 goal(来自首页输入框)= 自动开跑;从 ⌘K 菜单点开(无 goal)= 空面板等输入。
      setAgentGoal(goalText || '');
      setRunKey((k) => k + 1);
    }
    setPanel(key);
    eng.dock(true, narrow, dockAnchorFrac());
  };
  // 面板开着时改窗口大小 → 用新的视口宽重算 dock 锚点,让脑图重新居中到左侧空白区
  // (MindGraph.resize 已能用存储的旧 frac 重锚,但 frac 是按旧视口宽算的;这里喂新 frac)。
  useEffect(() => {
    const eng = engineRef.current;
    if (!eng || !panel || panel === 'memory') return;
    eng.dock(true, narrow, dockAnchorFrac());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vw, narrow, panel]);

  // 首页大输入框/建议/run 按钮 → 直连真 Python agent(LangGraph+verify),不再走假演示。
  const enterWork = (g: string) => openPanel('agent', g);
  const runSearch = (val: string) => { setQ(val); engineRef.current?.search(val); };

  const home = !panel;
  const detail = home ? selN || hoverN : null;
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  // swarm 单独处理:它要驱动中央知识图的临时叠加层,故直接渲染并注入 engine(见下方)。
  const OverlayComp = panel && panel !== 'runs' && panel !== 'swarm' ? OVERLAYS[panel as Exclude<OverlayKey, 'swarm'>] : null;
  const panelLabel = panel ? (DOCK.find((d) => d.key === panel) || {}).label : null;

  const pillBase: CSSProperties = {
    display: 'inline-flex', alignItems: 'center', gap: 5,
    fontFamily: 'var(--mono)', fontSize: 9.5, borderRadius: 4, padding: '1px 6px',
  };

  return (
    <div style={{ position: 'fixed', inset: 0, overflow: 'hidden' }}>
      <canvas ref={canvasRef} style={{ position: 'absolute', inset: 0, display: 'block' }} />

      {/* 顶部可拖动条:无边框窗口靠它拖动整个窗口(macOS Overlay 标题栏)。
          覆盖顶部一条,但避开右侧的搜索/功能区(它们 zIndex 更高可点)。 */}
      <div data-tauri-drag-region style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 52, zIndex: 1 }} />

      {/* identity —— 桌面端在红绿灯下方(top:44 清 36px 红绿灯区),移动端无红绿灯保持 top:16 */}
      <div style={{ position: 'absolute', top: narrow ? 16 : 44, left: 18, display: 'flex', alignItems: 'center', gap: 13, zIndex: 6, maxWidth: narrow ? '64vw' : 'none' }}>
        <HermesMark size={32} />
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
            <span style={{ fontSize: 16, fontWeight: 700, letterSpacing: '-0.01em' }}>Argos</span>
            {!narrow && <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--text-3)', letterSpacing: lang === 'zh' ? '0' : '0.12em', textTransform: 'uppercase', whiteSpace: 'nowrap', opacity: 0.8 }}>/ {t(panel === 'runs' ? 'working' : panelLabel || 'memory')}</span>}
            <span style={{ ...pillBase, color: 'var(--live)', border: '1px solid color-mix(in oklab,var(--live),transparent 65%)' }}><Dot color="var(--live)" size={5} glow /> {t(panel === 'runs' ? 'EXECUTING' : 'THINKING')}</span>
            {!narrow && (
              <span title={connected ? 'MiniMax 已配置' : '未配置模型(演示数据)'} style={{ ...pillBase, color: connected ? 'var(--accent)' : 'var(--text-3)', border: `1px solid ${connected ? 'color-mix(in oklab,var(--accent),transparent 65%)' : 'var(--border)'}` }}>
                <Dot color={connected ? 'var(--accent)' : 'var(--text-3)'} size={5} glow={connected} /> {t(connected ? 'LIVE' : 'DEMO')}
              </span>
            )}
          </div>
          <div style={{ height: 15, marginTop: 3, overflow: 'hidden' }}>
            {thought
              ? <div key={thought} className="thought-line" style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--accent)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{t('recalling')} · {t(thought)}</div>
              : <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--text-3)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{hasMemory ? <>{total} {t('memories')} · {panel === 'runs' ? t('lighting recalls ◂') : t('drag to explore')}</> : t('no memories yet — give it a goal, tasks settle here')}</div>}
          </div>
        </div>
      </div>

      {/* search + features launcher (home only) */}
      {home && (
        <div style={{ position: 'absolute', top: 18, right: 18, display: 'flex', alignItems: 'center', gap: 9, zIndex: 6 }}>
          <div className="mind-panel" style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 13px', width: narrow ? 150 : 220, maxWidth: '40vw' }}>
            <Icon name="search" size={15} style={{ color: 'var(--text-3)' }} />
            <input value={q} onChange={(e) => runSearch(e.target.value)} placeholder={narrow ? t('Search…') : t('Search the memory…')} style={{ flex: 1, minWidth: 0, background: 'none', border: 'none', outline: 'none', color: 'var(--text)', fontFamily: 'var(--mono)', fontSize: 12 }} />
          </div>
          <button onClick={() => setPaletteOpen(true)} className="mind-panel" title={t('Features')} style={{ display: 'flex', alignItems: 'center', gap: 7, padding: '9px 12px', cursor: 'pointer', color: 'var(--text-2)' }}
            onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text)'; }} onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-2)'; }}>
            <Icon name="layers" size={16} />
            {!narrow && <span style={{ fontFamily: 'var(--mono)', fontSize: 10.5, letterSpacing: '0.04em' }}>⌘K</span>}
          </button>
        </div>
      )}

      {/* detail */}
      <DetailPanel node={detail} engine={engineRef.current} locked={!!selN} narrow={narrow} onClose={() => engineRef.current?.select(null)} />

      {/* growth toasts */}
      <div style={{ position: 'absolute', right: 18, bottom: narrow ? 96 : 100, display: 'flex', flexDirection: 'column', gap: 8, zIndex: 6, alignItems: 'flex-end', maxWidth: narrow ? 'calc(100vw - 36px)' : 'none' }}>
        {toasts.map((ts) => (
          <div key={ts.id} className="mind-panel toast" style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px' }}>
            <Dot color={CATS[ts.type].color} glow />
            <div>
              <div style={{ fontFamily: 'var(--mono)', fontSize: 9.5, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--live)' }}>{t('learned')} · {t(CATS[ts.type].label)}</div>
              <div style={{ fontSize: 13, color: 'var(--text)', marginTop: 2, fontWeight: 500 }}>{t(ts.label)}</div>
            </div>
          </div>
        ))}
      </div>

      {/* docked panel — Runs */}
      {panel === 'runs' && (
        <div className="mind-panel" style={narrow
          ? { position: 'absolute', top: 8, left: 8, right: 8, bottom: 62, zIndex: 11, overflow: 'hidden', animation: 'slidein .35s cubic-bezier(0.16,1,0.3,1) both' }
          : { position: 'absolute', top: 16, right: 16, bottom: 16, width: 'min(600px, 56vw)', zIndex: 9, overflow: 'hidden', animation: 'slidein .35s cubic-bezier(0.16,1,0.3,1) both' }}>
          <RunView key={runKey} goal={goal} onExit={closePanel} onRecall={(labels) => engineRef.current?.lightLabels(labels, 1)} onLearn={(spec: LearnSpec) => engineRef.current?.learn(spec)} />
        </div>
      )}

      {/* Swarm — 图为主、面板变窄:蜂群过程实时长在中央知识图上,面板只放输入+阶段摘要 */}
      {panel === 'swarm' && (
        <div className="mind-panel" style={narrow
          ? { position: 'absolute', top: 8, left: 8, right: 8, bottom: 62, zIndex: 11, overflow: 'hidden', animation: 'slidein .35s cubic-bezier(0.16,1,0.3,1) both' }
          : { position: 'absolute', top: 16, right: 16, bottom: 16, width: 'min(380px, 34vw)', zIndex: 9, overflow: 'hidden', animation: 'slidein .35s cubic-bezier(0.16,1,0.3,1) both' }}>
          <SwarmPanel onClose={closePanel} engine={engineRef.current} />
        </div>
      )}

      {/* Agent — 独立通用智能体。AgentPanel 自带两栏 shell(左聊天列 + 右侧露出背景脑图),
          不要再套外层定位容器。 */}
      {panel === 'agent' && (
        <AgentPanel key={runKey} onClose={closePanel} initialGoal={agentGoal || undefined} onComplete={() => refreshMemoryRef.current?.()} />
      )}

      {/* feature panels (docked side panel, same as Runs) */}
      {OverlayComp && <OverlayComp onClose={closePanel} />}

      {/* first-run onboarding hint */}
      {home && showHint && (
        <div className="mind-panel" style={{ position: 'absolute', bottom: narrow ? 92 : 132, left: '50%', transform: 'translateX(-50%)', width: narrow ? 'calc(100vw - 24px)' : 'min(440px, 86vw)', maxWidth: 'calc(100vw - 24px)', padding: '13px 15px', zIndex: 7, animation: 'hintin .4s both', boxSizing: 'border-box' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 9 }}>
            <Icon name="sparkle" size={15} style={{ color: 'var(--accent)' }} />
            <span style={{ fontSize: 13, fontWeight: 700, whiteSpace: 'nowrap' }}>{t('Meet Argos')}</span>
            <div style={{ flex: 1 }} />
            <button onClick={dismissHint} style={{ fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--accent)', background: 'none', border: 'none', cursor: 'pointer', fontWeight: 700 }}>{t('Got it')}</button>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {([['memory', t('Drag & scroll the brain to explore its memory')], ['layers', t(narrow ? 'Tap the ✦ menu for tools, skills, connections & more' : 'Press ⌘K for tools, skills, connections & more')], ['sparkle', t('Give it a goal below — watch it work, beside its memory')]] as [IconName, string][]).map(([ic, txt], i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 9, fontSize: 12, color: 'var(--text-2)', lineHeight: 1.4 }}>
                <Icon name={ic} size={13} style={{ color: 'var(--text-3)', flexShrink: 0 }} />{txt}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* suggestion chips (home only, hidden on narrow) */}
      {home && !narrow && (
        <div style={{ position: 'absolute', bottom: 84, left: '50%', transform: 'translateX(-50%)', display: 'flex', gap: 7, zIndex: 6, flexWrap: 'wrap', justifyContent: 'center', width: 'min(560px, 70vw)' }}>
          {SUGGESTIONS.map((s) => (
            <button key={s} onClick={() => enterWork(s)} style={{ fontSize: 11.5, color: 'var(--text-2)', background: 'color-mix(in oklab, var(--surface), transparent 30%)', border: '1px solid var(--border)', borderRadius: 999, padding: '6px 12px', cursor: 'pointer', backdropFilter: 'blur(12px)', WebkitBackdropFilter: 'blur(12px)', transition: 'all .15s' }}
              onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--accent)'; e.currentTarget.style.color = 'var(--text)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.color = 'var(--text-2)'; }}>{t(s)}</button>
          ))}
        </div>
      )}

      {/* command bar (home only) */}
      {home && (
        <div className="mind-panel" style={{ position: 'absolute', bottom: narrow ? 22 : 26, left: '50%', transform: 'translateX(-50%)', width: narrow ? 'calc(100vw - 20px)' : 'min(560px, 64vw)', display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px 10px 14px', zIndex: 6 }}>
          <Icon name="sparkle" size={17} style={{ color: 'var(--accent)', flexShrink: 0 }} />
          <input value={cmd} onChange={(e) => setCmd(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && cmd.trim()) { enterWork(cmd.trim()); setCmd(''); } }} placeholder={narrow ? t('Give Argos a goal…') : t('Give Argos a goal — watch it work, beside its memory…')} style={{ flex: 1, minWidth: 0, background: 'none', border: 'none', outline: 'none', color: 'var(--text)', fontSize: 14 }} />
          <button onClick={() => openPanel('voice')} title={t('Voice')} style={{ width: 34, height: 34, flexShrink: 0, display: 'grid', placeItems: 'center', borderRadius: 9, cursor: 'pointer', border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-2)', transition: 'all .15s' }}
            onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--accent)'; e.currentTarget.style.borderColor = 'color-mix(in oklab,var(--accent),transparent 60%)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-2)'; e.currentTarget.style.borderColor = 'var(--border)'; }}>
            <Icon name="mic" size={16} />
          </button>
          <button onClick={() => { if (cmd.trim()) { enterWork(cmd.trim()); setCmd(''); } }} style={{ flexShrink: 0, display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: 'var(--mono)', fontSize: 11, color: '#1a1305', background: 'var(--accent)', border: 'none', borderRadius: 8, padding: '8px 12px', cursor: 'pointer', fontWeight: 700 }}>{t('run')} <span style={{ opacity: 0.7 }}>⏎</span></button>
        </div>
      )}

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} onPick={(key) => openPanel(key)} />

      <TweaksPanel>
        <TweakSection label={t('Core hue')} />
        <div style={{ display: 'flex', gap: 8, padding: '2px 2px 6px' }}>
          {MIND_ACCENTS.map((a) => (
            <button key={a.id} onClick={() => setTweak('accent', a.id)} style={{ width: 30, height: 30, borderRadius: 8, cursor: 'pointer', background: a.hex, border: tw.accent === a.id ? '2px solid #fff' : '2px solid transparent', boxShadow: `0 0 10px ${a.hex}66` }} />
          ))}
        </div>
        <TweakSection label={t('Behaviour')} />
        <TweakToggle label={t('Living motion')} value={tw.motion} onChange={(v) => setTweak('motion', v)} />
        <TweakButton label={t('Re-center memory')} onClick={() => closePanel()} />
      </TweaksPanel>
    </div>
  );
}
