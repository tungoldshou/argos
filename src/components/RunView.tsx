// RunView.tsx — glass agentic workflow timeline; lights recalled memories each step,
// and wires the new knowledge into the brain on completion (run → memory loop).
import { useState, useEffect, useMemo, useRef } from 'react';
import { Icon } from '../lib/icons';
import { PlatformGlyph } from '../lib/icons';
import { pColor } from '../lib/platforms';
import { tr } from '../lib/i18n';
import { pickRun, SK_ICON, SK_COL, type RunStep } from '../data/runs';
import type { LearnSpec } from '../data/types';
import { hermes, type RunEvent, type RunHandle } from '../lib/hermes';

type StepState = 'wait' | 'run' | 'done';

function RTypewriter({ text, speed = 15, onDone }: { text: string; speed?: number; onDone?: () => void }) {
  const [n, setN] = useState(0);
  useEffect(() => {
    setN(0);
    let i = 0;
    const id = setInterval(() => {
      i++;
      setN(i);
      if (i >= text.length) {
        clearInterval(id);
        onDone?.();
      }
    }, speed);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);
  return (
    <>
      {text.slice(0, n)}
      <span style={{ animation: 'blink-caret 1s step-end infinite', color: 'var(--accent)' }}>▏</span>
    </>
  );
}

function RTerminal({ lines }: { lines: string[] }) {
  const [shown, setShown] = useState(0);
  useEffect(() => {
    setShown(0);
    let i = 0;
    const id = setInterval(() => {
      i++;
      setShown(i);
      if (i >= lines.length) clearInterval(id);
    }, 300);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <div style={{ marginTop: 9, background: 'rgba(0,0,0,0.32)', border: '1px solid var(--border)', borderRadius: 9, padding: '10px 12px', fontFamily: 'var(--mono)', fontSize: 11, lineHeight: 1.7 }}>
      {lines.slice(0, shown).map((l, i) => (
        <div key={i} style={{ whiteSpace: 'pre-wrap', color: l.startsWith('$') ? 'var(--accent)' : '#8fd9c4', animation: 'thoughtin .25s both' }}>{l}</div>
      ))}
      {shown < lines.length && <span style={{ animation: 'blink-caret 1s step-end infinite', color: 'var(--accent)' }}>▋</span>}
    </div>
  );
}

function RStep({ step, state, isLast }: { step: RunStep; state: StepState; isLast: boolean }) {
  const col = SK_COL[step.kind];
  const [composed, setComposed] = useState(false);
  return (
    <div style={{ display: 'flex', gap: 13, animation: 'thoughtin .35s both' }}>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flexShrink: 0 }}>
        <div style={{
          width: 32, height: 32, borderRadius: 9, display: 'grid', placeItems: 'center',
          background: state === 'wait' ? 'rgba(255,255,255,0.04)' : `color-mix(in oklab, ${col}, transparent 80%)`,
          color: state === 'wait' ? 'var(--text-3)' : col, border: `1px solid ${state === 'run' ? col : 'var(--border)'}`,
          boxShadow: state === 'run' ? `0 0 0 4px color-mix(in oklab, ${col}, transparent 86%)` : 'none',
        }}>
          {state === 'done' ? <Icon name="check" size={16} /> : state === 'run' ? <Icon name="refresh" size={15} style={{ animation: 'spin 1.4s linear infinite' }} /> : <Icon name={SK_ICON[step.kind] as never} size={15} />}
        </div>
        {!isLast && <div style={{ width: 2, flex: 1, minHeight: 14, background: state === 'wait' ? 'var(--border)' : `color-mix(in oklab, ${col}, transparent 60%)`, marginTop: 2 }} />}
      </div>
      <div style={{ flex: 1, paddingBottom: 16, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 13.5, fontWeight: 600, color: state === 'wait' ? 'var(--text-3)' : 'var(--text)', whiteSpace: 'nowrap' }}>{tr(step.label)}</span>
          {step.dur && state === 'done' && <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--text-3)' }}>{step.dur}</span>}
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 2, fontFamily: step.kind === 'skill' ? 'var(--mono)' : 'var(--ui)' }}>{tr(step.detail)}</div>
        {step.terminal && state !== 'wait' && <RTerminal lines={step.terminal} />}
        {step.stream && state === 'run' && (
          <div style={{ marginTop: 9, padding: '10px 12px', background: 'var(--surface-2)', borderRadius: 9, border: '1px solid var(--border)', fontSize: 12, lineHeight: 1.6, color: 'var(--text-2)', fontStyle: 'italic' }}>
            <RTypewriter text={tr(step.stream)} />
          </div>
        )}
        {step.kind === 'post' && state === 'run' && step.post && (
          <div style={{ marginTop: 9, padding: 13, background: 'var(--surface-2)', borderRadius: 9, border: '1px solid var(--border)' }}>
            {!composed ? (
              <div style={{ fontSize: 12, color: 'var(--text-2)' }}>
                <RTypewriter text={tr(step.composing || '')} onDone={() => setTimeout(() => setComposed(true), 350)} />
              </div>
            ) : (
              <div style={{ animation: 'thoughtin .3s both' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 7, fontFamily: 'var(--mono)', fontSize: 11, color: pColor(step.post.platform, 0.78) }}>
                  <PlatformGlyph kind={step.post.platform} size={13} /> {tr('posted to')} {step.post.channel}
                </div>
                <div style={{ fontSize: 12, lineHeight: 1.7, color: 'var(--text)' }}>
                  <strong>{step.post.title}</strong>
                  <br />
                  {step.post.bullets.map((b, i) => <span key={i}>• {b}<br /></span>)}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function RunTimer({ running }: { running: boolean }) {
  const [t, setT] = useState(0);
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setT((x) => x + 0.1), 100);
    return () => clearInterval(id);
  }, [running]);
  return <span style={{ fontVariantNumeric: 'tabular-nums' }}>{t.toFixed(1)}s</span>;
}

interface RunViewProps {
  goal: string;
  onExit: () => void;
  onRecall: (labels: string[]) => void;
  onLearn: (spec: LearnSpec) => void;
}

export function RunView({ goal, onExit, onRecall, onLearn }: RunViewProps) {
  const run = useMemo(() => pickRun(goal), [goal]);
  const steps = run.steps;
  const total = steps.length;
  const [active, setActive] = useState(-1);
  const [learned, setLearned] = useState(false);
  const firedRef = useRef(false);

  // Live run: when connected to a real Hermes (Tauri), kick off an actual run
  // and stream its events alongside the cinematic scripted timeline.
  const src = hermes();
  const live = src.kind === 'tauri' && !!src.startRun;
  const [liveEvents, setLiveEvents] = useState<RunEvent[]>([]);
  const [liveDone, setLiveDone] = useState(false);
  useEffect(() => {
    if (!live || !src.startRun) return;
    let handle: RunHandle | null = null;
    let alive = true;
    src
      .startRun(
        goal,
        (e) => alive && setLiveEvents((prev) => (prev.length > 200 ? [...prev.slice(-180), e] : [...prev, e])),
        () => alive && setLiveDone(true),
      )
      .then((h) => { if (alive) handle = h; else h.cancel(); })
      .catch(() => alive && setLiveDone(true));
    return () => { alive = false; handle?.cancel(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { setActive(0); }, []);
  useEffect(() => {
    if (active < 0 || active >= total) return;
    const s = steps[active];
    onRecall?.(s.recall);
    const ms = s.terminal ? 2600 : s.kind === 'reason' ? 3400 : s.kind === 'post' ? 3800 : 1400;
    const id = setTimeout(() => setActive((a) => a + 1), ms);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  const done = active >= total;
  useEffect(() => {
    if (done && !firedRef.current) {
      firedRef.current = true;
      const id = setTimeout(() => {
        onLearn?.(run.learn);
        setLearned(true);
      }, 950);
      return () => clearTimeout(id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [done]);

  const stateOf = (i: number): StepState => (i < active ? 'done' : i === active ? 'run' : 'wait');
  const metaCells: [string, string][] = [
    ['subagents', run.meta.subagents], ['tokens', run.meta.tokens], ['cost', run.meta.cost], ['sandbox', 'docker'],
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ padding: '18px 22px', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          <button onClick={onExit} className="mind-link" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, background: 'none', border: '1px solid var(--border)', borderRadius: 8, padding: '5px 10px', cursor: 'pointer', color: 'var(--text-2)', fontSize: 12 }}>
            <Icon name="chevron" size={13} style={{ transform: 'rotate(180deg)' }} /> {tr('back to memory')}
          </button>
          <div style={{ flex: 1 }} />
          {done ? (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--live)' }}>
              <Icon name="check" size={13} /> {tr('completed')} · {run.meta.tokens}
            </span>
          ) : (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--accent)' }}>
              <Icon name="refresh" size={13} style={{ animation: 'spin 1.4s linear infinite' }} /> {tr('working')} · <RunTimer running={!done} />
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <span style={{ color: pColor(run.trigger.platform, 0.78), display: 'flex' }}><PlatformGlyph kind={run.trigger.platform} size={16} /></span>
          <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--text-3)' }}>{tr(run.trigger.who)} · {run.trigger.channel}</span>
        </div>
        <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--text)', marginTop: 7, lineHeight: 1.4 }}>“{goal}”</div>
      </div>
      <div style={{ flex: 1, overflow: 'auto', padding: '18px 22px' }}>
        {steps.map((s, i) => (stateOf(i) !== 'wait' || i === active) && (
          <RStep key={i} step={s} state={stateOf(i)} isLast={i === total - 1} />
        ))}
        {!done && <div style={{ paddingLeft: 45, fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--text-3)' }}>{tr('… lighting recalled memories ◂')}</div>}
        {learned && (
          <div style={{ marginLeft: 45, marginTop: 2, padding: '12px 14px', borderRadius: 11, background: 'color-mix(in oklab, var(--accent), transparent 88%)', border: '1px solid color-mix(in oklab, var(--accent), transparent 68%)', display: 'flex', alignItems: 'center', gap: 11, animation: 'pop .45s cubic-bezier(0.16,1,0.3,1) both' }}>
            <Icon name="memory" size={17} style={{ color: 'var(--accent)' }} />
            <div>
              <div style={{ fontFamily: 'var(--mono)', fontSize: 9.5, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--accent)' }}>{tr('learned · wired into memory')}</div>
              <div style={{ fontSize: 13, color: 'var(--text)', marginTop: 2, fontWeight: 600 }}>{tr(run.learn.label)}</div>
            </div>
            <div style={{ flex: 1 }} />
            <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--text-3)' }}>{tr('← in your brain')}</span>
          </div>
        )}
        {live && liveEvents.length > 0 && (
          <div style={{ marginTop: 14, paddingTop: 14, borderTop: '1px dashed var(--border)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 7, fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--live)', marginBottom: 9 }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--live)', boxShadow: '0 0 8px var(--live)' }} />
              {tr('live · Hermes')} {liveDone ? `· ${tr('completed')}` : ''}
            </div>
            <div style={{ background: 'rgba(0,0,0,0.32)', border: '1px solid var(--border)', borderRadius: 9, padding: '10px 12px', fontFamily: 'var(--mono)', fontSize: 11, lineHeight: 1.7, maxHeight: 240, overflow: 'auto' }}>
              {liveEvents.map((e, i) => (
                <div key={i} style={{ whiteSpace: 'pre-wrap', color: e.type.includes('tool') ? 'var(--accent)' : e.type.includes('error') ? '#ff8a7a' : '#8fd9c4', animation: 'thoughtin .2s both' }}>
                  <span style={{ color: 'var(--text-3)' }}>{e.type}</span>{e.text ? '  ' + e.text : ''}
                </div>
              ))}
              {!liveDone && <span style={{ animation: 'blink-caret 1s step-end infinite', color: 'var(--accent)' }}>▋</span>}
            </div>
          </div>
        )}
      </div>
      <div style={{ flexShrink: 0, borderTop: '1px solid var(--border)', padding: '12px 22px', display: 'flex', gap: 22, alignItems: 'center', flexWrap: 'wrap' }}>
        {metaCells.map(([k, v]) => (
          <div key={k}>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 9, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-3)' }}>{tr(k)}</div>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 12.5, color: k === 'tokens' ? 'var(--accent)' : 'var(--text)', marginTop: 2 }}>{v}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
