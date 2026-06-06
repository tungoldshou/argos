// responsive.ts — single source of truth for the narrow/mobile breakpoint.
import { useState, useEffect } from 'react';

export const NARROW_BREAKPOINT = 720;

/** Current viewport width, updated on resize. */
export function useViewportWidth(): number {
  const [w, setW] = useState(typeof window !== 'undefined' ? window.innerWidth : 1440);
  useEffect(() => {
    const f = () => setW(window.innerWidth);
    window.addEventListener('resize', f);
    return () => window.removeEventListener('resize', f);
  }, []);
  return w;
}

/** True when the viewport is below the narrow breakpoint. */
export function useNarrow(): boolean {
  return useViewportWidth() < NARROW_BREAKPOINT;
}
