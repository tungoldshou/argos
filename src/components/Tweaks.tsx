// Tweaks.tsx — floating "Tweaks" panel + form-control helpers + useTweaks hook.
// Standalone port: opened via a floating gear button (no external design host).
import {
  useState, useCallback, useRef, useEffect,
  type ReactNode,
} from 'react';
import { useNarrow } from '../lib/responsive';

const STYLE = `
  .twk-fab{position:fixed;right:16px;bottom:16px;z-index:2147483645;width:42px;height:42px;
    display:grid;place-items:center;border:none;border-radius:12px;cursor:pointer;
    background:var(--surface-2);color:var(--text-2);
    -webkit-backdrop-filter:blur(18px);backdrop-filter:blur(18px);
    border:1px solid var(--border);box-shadow:0 8px 24px rgba(0,0,0,.4);transition:color .15s,transform .15s}
  .twk-fab:hover{color:var(--accent);transform:translateY(-1px)}

  .twk-panel{position:fixed;right:16px;bottom:16px;z-index:2147483646;width:268px;
    max-height:calc(100vh - 32px);display:flex;flex-direction:column;
    background:var(--surface);color:var(--text);
    -webkit-backdrop-filter:blur(24px) saturate(150%);backdrop-filter:blur(24px) saturate(150%);
    border:1px solid var(--border);border-radius:14px;
    box-shadow:0 1px 0 rgba(255,255,255,.05) inset,0 18px 50px -16px rgba(0,0,0,.7);
    font:11.5px/1.4 var(--ui);overflow:hidden}
  .twk-hd{display:flex;align-items:center;justify-content:space-between;
    padding:11px 8px 11px 15px;user-select:none}
  .twk-hd b{font-size:12.5px;font-weight:600;letter-spacing:.01em}
  .twk-x{appearance:none;border:0;background:transparent;color:var(--text-3);
    width:24px;height:24px;border-radius:6px;cursor:pointer;font-size:14px;line-height:1}
  .twk-x:hover{background:var(--surface-2);color:var(--text)}
  .twk-body{padding:2px 15px 15px;display:flex;flex-direction:column;gap:11px;
    overflow-y:auto;overflow-x:hidden;min-height:0}
  .twk-sect{font-size:10px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;
    color:var(--text-3);padding:8px 0 0}
  .twk-sect:first-child{padding-top:0}
  .twk-row{display:flex;flex-direction:column;gap:5px}
  .twk-row-h{flex-direction:row;align-items:center;justify-content:space-between;gap:10px}
  .twk-lbl{display:flex;justify-content:space-between;align-items:baseline;color:var(--text-2)}
  .twk-lbl>span:first-child{font-weight:500}
  .twk-toggle{position:relative;width:34px;height:19px;border:0;border-radius:999px;
    background:var(--surface-3);transition:background .15s;cursor:pointer;padding:0}
  .twk-toggle[data-on="1"]{background:var(--accent)}
  .twk-toggle i{position:absolute;top:2px;left:2px;width:15px;height:15px;border-radius:50%;
    background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.25);transition:transform .15s}
  .twk-toggle[data-on="1"] i{transform:translateX(15px)}
  .twk-btn{appearance:none;height:30px;padding:0 12px;border:1px solid var(--border);border-radius:8px;
    background:var(--surface-2);color:var(--text);font:inherit;font-weight:600;cursor:pointer;
    text-align:left;transition:border-color .15s}
  .twk-btn:hover{border-color:var(--border-strong)}
  @media (max-width: 719px){
    .twk-fab{bottom:84px}
  }
`;

// ── useTweaks ──────────────────────────────────────────────────────────────
export function useTweaks<T extends Record<string, unknown>>(
  defaults: T,
): [T, (key: keyof T, val: T[keyof T]) => void] {
  const [values, setValues] = useState<T>(defaults);
  const setTweak = useCallback((key: keyof T, val: T[keyof T]) => {
    setValues((prev) => ({ ...prev, [key]: val }));
  }, []);
  return [values, setTweak];
}

// ── TweaksPanel ────────────────────────────────────────────────────────────
export function TweaksPanel({ title = 'Tweaks', children }: { title?: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const narrow = useNarrow();
  const dragRef = useRef<HTMLDivElement>(null);
  const offsetRef = useRef({ x: 16, y: narrow ? 84 : 16 });
  const PAD = 16;

  const clampToViewport = useCallback(() => {
    const panel = dragRef.current;
    if (!panel) return;
    const w = panel.offsetWidth, h = panel.offsetHeight;
    const maxRight = Math.max(PAD, window.innerWidth - w - PAD);
    const maxBottom = Math.max(PAD, window.innerHeight - h - PAD);
    offsetRef.current = {
      x: Math.min(maxRight, Math.max(PAD, offsetRef.current.x)),
      y: Math.min(maxBottom, Math.max(PAD, offsetRef.current.y)),
    };
    panel.style.right = offsetRef.current.x + 'px';
    panel.style.bottom = offsetRef.current.y + 'px';
  }, []);

  useEffect(() => {
    if (!open) return;
    clampToViewport();
    const ro = new ResizeObserver(clampToViewport);
    ro.observe(document.documentElement);
    return () => ro.disconnect();
  }, [open, clampToViewport]);

  const onDragStart = (e: React.MouseEvent) => {
    const panel = dragRef.current;
    if (!panel) return;
    const r = panel.getBoundingClientRect();
    const sx = e.clientX, sy = e.clientY;
    const startRight = window.innerWidth - r.right;
    const startBottom = window.innerHeight - r.bottom;
    const move = (ev: MouseEvent) => {
      offsetRef.current = { x: startRight - (ev.clientX - sx), y: startBottom - (ev.clientY - sy) };
      clampToViewport();
    };
    const up = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  };

  return (
    <>
      <style>{STYLE}</style>
      {!open && (
        <button className="twk-fab" aria-label="Open tweaks" onClick={() => setOpen(true)}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" />
          </svg>
        </button>
      )}
      {open && (
        <div ref={dragRef} className="twk-panel" style={{ right: offsetRef.current.x, bottom: offsetRef.current.y }}>
          <div className="twk-hd" style={{ cursor: 'move' }} onMouseDown={onDragStart}>
            <b>{title}</b>
            <button className="twk-x" aria-label="Close tweaks" onMouseDown={(e) => e.stopPropagation()} onClick={() => setOpen(false)}>✕</button>
          </div>
          <div className="twk-body">{children}</div>
        </div>
      )}
    </>
  );
}

export function TweakSection({ label }: { label: string }) {
  return <div className="twk-sect">{label}</div>;
}

export function TweakToggle({ label, value, onChange }: { label: string; value: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="twk-row twk-row-h">
      <div className="twk-lbl"><span>{label}</span></div>
      <button type="button" className="twk-toggle" data-on={value ? '1' : '0'} role="switch" aria-checked={value} onClick={() => onChange(!value)}><i /></button>
    </div>
  );
}

export function TweakButton({ label, onClick }: { label: string; onClick: () => void }) {
  return <button type="button" className="twk-btn" onClick={onClick}>{label}</button>;
}
