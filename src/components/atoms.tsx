// atoms.tsx — small shared presentational atoms.
import type { CSSProperties } from 'react';

export function Dot({ color, size = 9, glow }: { color: string; size?: number; glow?: boolean }) {
  return (
    <span
      style={{
        width: size, height: size, borderRadius: '50%', background: color,
        boxShadow: glow ? `0 0 8px ${color}` : 'none', display: 'inline-block', flexShrink: 0,
      }}
    />
  );
}

export function Meta({ k, v }: { k: string; v: string | number }) {
  return (
    <div style={{ minWidth: 70 }}>
      <div style={{ fontFamily: 'var(--mono)', fontSize: 9.5, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-3)' }}>{k}</div>
      <div style={{ fontSize: 12.5, color: 'var(--text)', marginTop: 3, fontWeight: 500 }}>{v}</div>
    </div>
  );
}

export const panelBase: CSSProperties = {
  position: 'absolute', zIndex: 11, display: 'flex', flexDirection: 'column', overflow: 'hidden',
};
