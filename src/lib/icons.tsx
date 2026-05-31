// icons.tsx — minimal stroke line-icon set, brand mark, platform glyphs, favicon.
import type { CSSProperties, ReactElement } from 'react';
import type { PlatformKind } from '../data/types';

export type IconName =
  | 'overview' | 'activity' | 'skills' | 'memory' | 'automations' | 'connections'
  | 'sandbox' | 'settings' | 'send' | 'bolt' | 'branch' | 'terminal' | 'clock'
  | 'check' | 'plus' | 'search' | 'chevron' | 'chevronDown' | 'arrowUp' | 'dot'
  | 'pause' | 'play' | 'globe' | 'cpu' | 'file' | 'eye' | 'image' | 'mic'
  | 'sparkle' | 'refresh' | 'link' | 'pin' | 'plug' | 'wrench' | 'mask'
  | 'layers' | 'voice';

interface IconProps {
  name: IconName;
  size?: number;
  stroke?: number;
  style?: CSSProperties;
  className?: string;
}

export function Icon({ name, size = 16, stroke = 1.6, style = {}, className = '' }: IconProps) {
  const paths: Record<IconName, ReactElement> = {
    overview: <><rect x="3" y="3" width="7" height="9" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" /><rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="16" width="7" height="5" rx="1.5" /></>,
    activity: <path d="M3 12h3l2.5 7 5-16L18 12h3" />,
    skills: <path d="M12 3l2.3 4.7 5.2.8-3.75 3.65.9 5.15L12 14.9l-4.65 2.45.9-5.15L4.5 8.5l5.2-.8z" />,
    memory: <><rect x="4" y="4" width="16" height="16" rx="2" /><path d="M9 2v2M15 2v2M9 20v2M15 20v2M2 9h2M2 15h2M20 9h2M20 15h2" /><rect x="9" y="9" width="6" height="6" rx="1" /></>,
    automations: <><circle cx="12" cy="12" r="8" /><path d="M12 8v4l2.5 2.5" /></>,
    connections: <><circle cx="6" cy="12" r="2.4" /><circle cx="18" cy="6" r="2.4" /><circle cx="18" cy="18" r="2.4" /><path d="M8.1 11l7.8-3.8M8.1 13l7.8 3.8" /></>,
    sandbox: <><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z" /><path d="M4 7.5l8 4.5 8-4.5M12 12v9" /></>,
    settings: <><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" /></>,
    send: <path d="M4 12l16-8-6 16-3-6-7-2z" />,
    bolt: <path d="M13 2L4 14h6l-1 8 9-12h-6z" />,
    branch: <><circle cx="6" cy="6" r="2.2" /><circle cx="6" cy="18" r="2.2" /><circle cx="18" cy="9" r="2.2" /><path d="M6 8.2v7.6M8.2 6h4c2 0 3.6 1.3 3.6 3" /></>,
    terminal: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M7 9l3 3-3 3M13 15h4" /></>,
    clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3.5 2" /></>,
    check: <path d="M4 12.5l5 5L20 6" />,
    plus: <path d="M12 5v14M5 12h14" />,
    search: <><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></>,
    chevron: <path d="M9 6l6 6-6 6" />,
    chevronDown: <path d="M6 9l6 6 6-6" />,
    arrowUp: <path d="M12 19V5M6 11l6-6 6 6" />,
    dot: <circle cx="12" cy="12" r="4" />,
    pause: <><rect x="6" y="5" width="4" height="14" rx="1" /><rect x="14" y="5" width="4" height="14" rx="1" /></>,
    play: <path d="M7 5l12 7-12 7z" />,
    globe: <><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c2.5 2.5 2.5 15 0 18M12 3c-2.5 2.5-2.5 15 0 18" /></>,
    cpu: <><rect x="6" y="6" width="12" height="12" rx="2" /><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3" /></>,
    file: <><path d="M6 2h8l4 4v16H6z" /><path d="M14 2v4h4" /></>,
    eye: <><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" /><circle cx="12" cy="12" r="2.5" /></>,
    image: <><rect x="3" y="4" width="18" height="16" rx="2" /><circle cx="9" cy="10" r="2" /><path d="M3 17l5-4 4 3 3-2 6 5" /></>,
    mic: <><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0014 0M12 18v3" /></>,
    sparkle: <path d="M12 3v6M12 15v6M3 12h6M15 12h6M6.5 6.5l3 3M14.5 14.5l3 3M17.5 6.5l-3 3M9.5 14.5l-3 3" />,
    refresh: <path d="M21 12a9 9 0 11-3-6.7M21 4v4h-4" />,
    link: <path d="M9 15l6-6M10 6l1-1a4 4 0 016 6l-1 1M14 18l-1 1a4 4 0 01-6-6l1-1" />,
    pin: <><path d="M12 21s7-6.3 7-11a7 7 0 10-14 0c0 4.7 7 11 7 11z" /><circle cx="12" cy="10" r="2.5" /></>,
    plug: <><path d="M9 2v6M15 2v6M7 8h10v3a5 5 0 01-10 0z" /><path d="M12 16v6" /></>,
    wrench: <path d="M14.5 5.5a3.5 3.5 0 00-4.6 4.2L4 15.6 8.4 20l5.9-5.9a3.5 3.5 0 004.2-4.6l-2.3 2.3-2.1-.6-.6-2.1z" />,
    mask: <><path d="M4 5c5-1 11-1 16 0 0 7-2 12-8 14C6 17 4 12 4 5z" /><path d="M9 10c1 1 2 1 3 0M12 10c1 1 2 1 3 0" /></>,
    layers: <><path d="M12 3l9 5-9 5-9-5z" /><path d="M3 13l9 5 9-5M3 17l9 5 9-5" /></>,
    voice: <><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0014 0M12 18v3" /><path d="M2 12v0M22 12v0" /></>,
  };
  return (
    <svg
      width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={stroke}
      strokeLinecap="round" strokeLinejoin="round"
      style={style} className={className}
    >
      {paths[name] ?? paths.dot}
    </svg>
  );
}

// Brand mark — pixel-art dog head, front-facing, symmetric. 16×16.
const DOG_MAP = [
  ' KK         KK  ',
  ' KMK        KMK ',
  ' KMMK      KMMK ',
  ' KMMMMMMMMMMMMK ',
  ' KMMMMMMMMMMMMK ',
  ' KMMEGMMMMGEMMK ',
  ' KMMEEMMMMEEMMK ',
  ' KMMMMMMMMMMMMK ',
  ' KMMMWWWWWWMMMK ',
  ' KMMMWWNNWWMMMK ',
  ' KMMMMWWWWMMMMK ',
  '  KMMMMMMMMMMK  ',
  '  KKMMMMMMMMKK  ',
  '    KKKKKKKK    ',
  '                ',
  '                ',
];
const DOG_COLORS: Record<string, string> = {
  K: '#1b1109', M: '#f2a43e', L: '#ffe1a0', W: '#fff3e0', E: '#1b1109', N: '#241204', G: '#ffffff',
};

export function PixelDog({ size = 32, tile = true }: { size?: number; tile?: boolean }) {
  const cells: ReactElement[] = [];
  for (let y = 0; y < DOG_MAP.length; y++) {
    const row = DOG_MAP[y];
    for (let x = 0; x < row.length; x++) {
      const c = row[x];
      if (c === ' ') continue;
      cells.push(<rect key={x + '-' + y} x={x} y={y} width="1.02" height="1.02" fill={DOG_COLORS[c]} />);
    }
  }
  return (
    <svg width={size} height={size} viewBox="-2 -2 20 20" shapeRendering="crispEdges" style={{ display: 'block' }}>
      {tile && (
        <>
          <defs>
            <linearGradient id="dogtile" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#1c1812" />
              <stop offset="100%" stopColor="#0d0a06" />
            </linearGradient>
          </defs>
          <rect x="-2" y="-2" width="20" height="20" rx="4.6" fill="url(#dogtile)" stroke="rgba(255,180,90,0.28)" strokeWidth="0.6" />
        </>
      )}
      {cells}
    </svg>
  );
}

export const HermesMark = PixelDog;

// Platform glyphs — simplified, generic geometric marks (not brand logos)
export function PlatformGlyph({ kind, size = 18 }: { kind: PlatformKind | string; size?: number }) {
  const wrap = (children: ReactElement) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{children}</svg>
  );
  switch (kind) {
    case 'telegram': return wrap(<><path d="M21 4L3 11l5 2 2 6 3-4 5 4z" /><path d="M8 13l9-6" /></>);
    case 'discord': return wrap(<><path d="M7 7c3-1.3 7-1.3 10 0M5 18c2 1.5 4 2 7 2s5-.5 7-2" /><path d="M5 18c-1-3-1-7 1-11M19 18c1-3 1-7-1-11" /><circle cx="9.5" cy="13" r="1.2" /><circle cx="14.5" cy="13" r="1.2" /></>);
    case 'slack': return wrap(<><rect x="10" y="3" width="4" height="11" rx="2" /><rect x="3" y="10" width="11" height="4" rx="2" /><rect x="10" y="10" width="11" height="4" rx="2" /><rect x="10" y="10" width="4" height="11" rx="2" /></>);
    case 'whatsapp': return wrap(<><path d="M4 20l1.4-4A8 8 0 1112 20a8 8 0 01-4-1l-4 1z" /><path d="M9 9c0 4 2 6 6 6" /></>);
    case 'signal': return wrap(<><circle cx="12" cy="12" r="8" /><path d="M12 4v3M12 17v3M4 12h3M17 12h3" /></>);
    case 'email': return wrap(<><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M3 7l9 6 9-6" /></>);
    case 'cli': return wrap(<><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M7 9l3 3-3 3M13 15h4" /></>);
    case 'matrix': return wrap(<><path d="M5 4v16M19 4v16M5 5h2M5 19h2M17 5h2M17 19h2" /><path d="M9 8v8M9 8c2 0 2 2 2 2M15 16v-6M11 10c0-2 2-2 2 0v6" /></>);
    case 'teams': return wrap(<><circle cx="16" cy="7" r="2.2" /><rect x="3" y="8" width="9" height="9" rx="1.6" /><path d="M5.5 11h4M7.5 11v4M13 9h6v5a3 3 0 01-3 3" /></>);
    case 'sms': return wrap(<><path d="M4 5h16v11H9l-4 3v-3H4z" /><path d="M8 10h.01M12 10h.01M16 10h.01" /></>);
    case 'feishu': return wrap(<><path d="M4 18c5 1 11-1 15-7-3 1-5 0-7-2" /><path d="M4 18c0-4 3-9 8-11l3 3" /></>);
    case 'dingtalk': return wrap(<path d="M12 3a9 9 0 109 9c0-3-2-5-4-5M14 9l-4 6h4l-1 4 5-7h-4z" />);
    case 'wecom': return wrap(<><circle cx="9" cy="10" r="5" /><circle cx="16" cy="15" r="4" /><path d="M7 10h.01M11 10h.01M15 15h.01M17 15h.01" /></>);
    case 'gchat': return wrap(<><path d="M4 6h16v10H10l-4 3v-3H4z" /><circle cx="12" cy="11" r="2.4" /></>);
    case 'homeassistant': return wrap(<><path d="M12 3l9 8h-2v9H5v-9H3z" /><path d="M12 11v5M9.5 13.5h5" /></>);
    default: return wrap(<circle cx="12" cy="12" r="6" />);
  }
}

// Favicon — built from the same pixel map (single source of truth)
export function setFavicon(): void {
  let r = '';
  for (let y = 0; y < DOG_MAP.length; y++) {
    for (let x = 0; x < DOG_MAP[y].length; x++) {
      const c = DOG_MAP[y][x];
      if (c === ' ') continue;
      r += `<rect x="${x}" y="${y}" width="1.05" height="1.05" fill="${DOG_COLORS[c]}"/>`;
    }
  }
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="-2 -2 20 20"><rect x="-2" y="-2" width="20" height="20" rx="4.5" fill="#0d0a06"/>${r}</svg>`;
  const href = 'data:image/svg+xml,' + encodeURIComponent(svg);
  let link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
  if (!link) {
    link = document.createElement('link');
    link.rel = 'icon';
    document.head.appendChild(link);
  }
  link.type = 'image/svg+xml';
  link.href = href;
}
