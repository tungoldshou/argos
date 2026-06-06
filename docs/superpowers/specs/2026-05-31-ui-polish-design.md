# Argos UI Polish — Design Spec

**Date:** 2026-05-31
**Scope:** Comprehensive polish pass (全面打磨) across four dimensions — mobile bugs, visual refinement, information architecture, motion/performance. **Not a redesign.** The cinematic dark aesthetic, accent system, memory-brain canvas, dock-from-right pattern, and run timeline are kept; we improve through consistency, spacing, detail, and bug fixes.

## Goal

Take an already-strong cinematic agent UI from "impressive prototype" to "shipped product" by removing the rough edges that read as unfinished — especially on mobile, where there are genuine layout bugs.

## Evidence

All findings below were observed in the live app (`localhost:5173`) at 1440×900 (desktop) and 390×844 (mobile), captured during this session. Root causes were confirmed in source.

---

## Findings & Fixes

### A. Mobile bugs (priority — real, reproducible)

**A1. Onboarding hint overflows the right edge on mobile.**
At 390px the "Meet Argos" hint clips its text ("explore its me…", "connections &", "watch it work, bes…").
- *Root cause:* `App.tsx` `useViewport()` returns `window.innerWidth` initialized correctly, but the hint and several elements branch on `narrow = vw < 720`. The hint card uses `width: narrow ? 'calc(100vw - 28px)' : ...` with `left:50%; transform:translateX(-50%)`. The observed overflow indicates the card is rendering with content wider than its box (the inner rows use `whiteSpace` defaults but the row text does not wrap because the flex row has no `min-width:0` / wrap). Fix: allow the hint body rows to wrap (`flexWrap`/`min-width:0`) and constrain the card to `max-width: calc(100vw - 24px)` regardless of branch.
- *Fix:* make the hint robust to width — wrap long lines, cap width, verify at 360px and 390px.

**A2. Tweaks gear ⚙ (FAB) overlaps the command bar's `run` button on mobile.**
The FAB is hard-pinned `position:fixed; right:16px; bottom:16px` (`Tweaks.tsx`). The command bar on narrow is `bottom:22px`, full-width (`calc(100vw - 20px)`), so its `run` button sits directly under the gear. "ru" was visibly clipped.
- *Fix:* On narrow viewports, move the FAB out of the command-bar zone. Options: lift it to `bottom: 84px` (above the command bar) on narrow, OR relocate to top-area. Chosen: **lift FAB above the command bar on narrow** (`bottom` computed from whether the home command bar is present). Keep desktop position unchanged.

**A3. Keyboard-only affordances shown on touch devices.**
- The `⌘K` chip in the header launcher button and the "Press ⌘K for tools…" onboarding line are meaningless on a phone.
- *Fix:* On narrow, replace the `⌘K` chip with the layers icon only (already icon + chip; drop the chip on narrow), and reword the onboarding line to "Tap ✦ for tools, skills, connections & more" on narrow (the launcher is the layers button top-right).

### B. Visual refinement (去AI味 — designer's judgment, base tone preserved)

**B1. Graph node labels overlap when dense.**
"retrieval-augmented memory" / "streaming gateway" / "atlas-core" collide near the bottom of the brain (desktop and mobile). This is the single biggest "unfinished" tell.
- *Fix:* In `MindGraph` label rendering, add lightweight label-collision avoidance: skip or fade labels that would overlap a higher-priority (more-connected / selected / hovered) node's label. Priority order: self > hovered/selected > by degree. Non-drawn labels still appear on hover. This is a canvas-render change, motion-budget-neutral.

**B2. Header pill noise.**
THINKING / DEMO / (LIVE) plus the `/ MEMORY` breadcrumb and recall line stack up as competing mono text.
- *Fix:* Unify the pills into one consistent visual weight; reduce the breadcrumb prominence (it duplicates the status). Keep all information, lower the contrast of secondary items. Tighten vertical rhythm of the identity block.

**B3. Spacing/rhythm consistency pass.**
Padding values are slightly ad hoc across panels (`14px 18px`, `16px 20px`, `16px 18px`, `13px 15px`). 
- *Fix:* Introduce a small spacing scale (e.g. `--sp-1..5`) in `styles.css` and align panel paddings to it where it doesn't disrupt a deliberate composition. Low-risk, applied conservatively.

### C. Information architecture

**C1. ⌘K palette is a flat list of 12.**
The features are really 4 groups: **Work** (Swarm, Runs), **Capabilities** (Skills, Tools, MCP), **Reach** (Voice, Connections, Automations), **Identity/Config** (Personality, Sandboxes, Settings). Memory is home (excluded).
- *Fix:* Add lightweight section headers in the palette list (grouped, but still flat-filterable when a query is typed — groups collapse to a flat filtered list during search). Keyboard nav still walks all items in order.

**C2. First-run hint is the only onboarding and it's the buggy one (A1).**
Fixing A1 covers this; no separate change.

### D. Motion / performance

**D1. Verify reduced-motion + low-end path.**
The app already respects `prefers-reduced-motion` and has a `motion` tweak. No new always-on animation will be added. The label-collision change (B1) must not add per-frame cost beyond a cheap bounding-box check.
- *Fix:* Confirm B1's collision check is O(n) per frame with early-out, gated by the same motion budget. No regression to the breathing/thinking loop.

### E. Code consistency (incidental, serves the above)

**E1. Two duplicate viewport hooks.** `useViewport` (App.tsx) and `useNarrow` (overlays.tsx) implement the same logic with the same 720 breakpoint.
- *Fix:* Extract one `useNarrow` / `BREAKPOINT` into a shared module (e.g. `src/lib/responsive.ts`) and use it in both. Single source of truth for the breakpoint.

---

## Non-goals (explicitly preserved)

- Color system / accent palette — unchanged (base tone kept per direction "你来判断" → preserve & refine).
- Dark space background, starfield, pulse/breathe loop — unchanged.
- Runs view (desktop & mobile) — already excellent, untouched except shared-hook refactor.
- Docked Skills/feature panels structure — untouched except shared-hook refactor + spacing scale.
- Bilingual EN/中 — all new copy must go through `t()`/`tr()`.

## Architecture / approach

All changes are localized to the existing files; no new dependencies, no router, no state-management change.

| Area | File(s) |
|---|---|
| Mobile bug fixes A1–A3 | `src/App.tsx`, `src/components/Tweaks.tsx` |
| Shared breakpoint E1 | new `src/lib/responsive.ts`; `src/App.tsx`, `src/components/overlays.tsx` |
| Label collision B1 | `src/engine/MindGraph.ts` |
| Header refinement B2 | `src/App.tsx` |
| Spacing scale B3 | `src/styles.css` + conservative consumer edits |
| Palette grouping C1 | `src/App.tsx` (`CommandPalette`, `DOCK` → grouped) |

## Testing / verification

- **Visual verification via Chrome DevTools MCP** at 1440×900, 768×1024, 390×844, 360×640.
  - Home, ⌘K palette (empty + filtered), one docked overlay, Runs view, onboarding hint.
  - Confirm: no clipped text, no FAB/run overlap, labels don't overlap at rest, palette groups render and filtering still works.
- **`pnpm build`** (tsc -b + vite) passes — type-check is the gate.
- **Bilingual:** toggle 中 and re-check the same screens for overflow (Chinese strings differ in width).
- **Reduced motion:** verify `motion` off path still renders the brain statically without errors.

## Rollout

Single branch, incremental commits per finding group (A, B, C, D/E). Each group independently verifiable. Lowest-risk first (A mobile bugs), highest-judgment last (B2 header, C1 grouping) so they can be reviewed/backed out individually.
