# Argos — Hermes agent

A focused, cinematic hero interface for the [Hermes agent](https://hermes-agent.nousresearch.com)
(Nous Research's open, self-hosted autonomous agent).

The screen is a **living memory brain** — a force-directed knowledge graph of what the
agent knows, remembers, and connects. It breathes, glows, thinks (lighting up associative
paths every few seconds), and grows (new skills/memories bloom in over time). Everything
else is **on demand**: features dock in from the right (never a page nav), goals open a
workflow that runs *beside* the memory and lights the recalls it uses, and on completion
the new knowledge is wired back into the brain.

Recreated as a production React + TypeScript app from a Claude Design handoff prototype.

## Run

```bash
pnpm install
pnpm dev        # browser, demo data → http://localhost:5173
pnpm build      # type-check + production bundle into dist/

# Desktop app, wired to a local Hermes agent:
pnpm app:dev    # Tauri dev (native window + live Hermes)
pnpm app:build  # package a .app / .dmg
```

## Connecting to a local Hermes agent

The browser build runs on **demo data**. The **Tauri desktop app** connects to a
Hermes instance running on the same machine — the identity bar shows a `LIVE`
pill when connected, `DEMO` otherwise.

**Requirements on the Hermes side** (one-time):
1. Enable the OpenAI-compatible API server in `~/.hermes/.env`:
   ```
   API_SERVER_ENABLED=true
   API_SERVER_KEY=<a random token>
   ```
2. Restart the gateway: `hermes gateway restart` (messaging platforms reconnect).
   The API server then listens on `127.0.0.1:8642`.

Argos reads the bearer key from `~/.hermes/.argos_api_key` (falling back to
`API_SERVER_KEY` in `~/.hermes/.env`). The key never leaves the Rust backend.

**What's wired to real Hermes** (verified against Hermes v0.15.1):

| Argos surface | Hermes endpoint |
|---|---|
| Skills overlay | `GET /v1/skills` (live skill catalog) |
| Automations overlay + toggles | `GET /api/jobs`, `POST /api/jobs/{id}/pause\|resume` |
| Command bar → run + live event feed | `POST /v1/runs`, SSE `GET /v1/runs/{id}/events`, `POST .../stop` |
| Memory brain source | `~/.hermes/memories/{MEMORY,USER}.md` (read off disk) |
| LIVE/DEMO pill | `GET /health` |

The data layer is swappable: `src/lib/hermes.ts` defines a `HermesSource`
interface with a `TauriSource` (real, via Rust commands) and a `MockSource`
(seed data). It auto-selects `TauriSource` inside the desktop app and
`MockSource` in a plain browser, so both run from one codebase.

The Rust bridge lives in `src-tauri/src/lib.rs` — `hermes_get` / `hermes_post`
forward REST with the bearer token, `read_memory` reads the markdown, and
`stream_run_events` relays the SSE feed into Tauri events (`hermes://run-event`).

## The interface

- **Memory brain (canvas)** — drag to pan, scroll/pinch to zoom, click a node to focus
  (camera flies in, neighbours light, the rest dims, a detail panel slides in with the
  node's origin and its clickable connections). Hover to preview.
- **Command bar** (bottom) — give Hermes a goal. The brain shrinks and docks left while a
  **workflow run** slides in on the right: search memory → load skill → spawn parallel
  subagents (with streaming terminals) → reason → post to a channel. Each step lights the
  memory nodes it recalls. On completion the result blooms into the brain as a new memory.
- **⌘K command palette / Features launcher** — jump to any feature. Each opens as a
  right-docked panel (same motion as a run): **Skills, Tools, MCP, Voice, Connections,
  Automations, Personality, Sandboxes, Settings**.
- **Voice** — the mic button in the command bar opens Voice Mode.
- **EN / 中** — full bilingual UI, including the live canvas labels. Code-like identifiers
  (skill names, repo names, terminal text) stay in English by design.
- **Search** — matches English and translated node labels; the brain dims to the matches.
- **Tweaks** (gear, bottom-right) — switch the core hue (5 accents), toggle living motion,
  re-center the memory.
- **Onboarding** — a one-time "Meet Argos" hint (remembered in `localStorage`).
- **Responsive** — collapses gracefully below 720px (near-fullscreen panels, bottom-sheet
  detail, hidden suggestion chips).
- **Accessibility** — respects `prefers-reduced-motion` (auto-disables living motion on
  first load); the canvas supports touch (pan / drag node / pinch-zoom).

## Structure

```
index.html              fonts + mount point
src/
  main.tsx              entry; sets the pixel-dog favicon
  styles.css            design tokens (oklch palette), keyframes, panel/scrollbar styles
  App.tsx               shell: identity, search, ⌘K palette, detail panel, dock state,
                        command bar, onboarding, tweaks, responsive layout
  engine/MindGraph.ts   canvas force-directed graph: physics, glow render, hover/drag/
                        zoom/touch, thought pulses, grow()/learn(), dock(), search()
  components/
    RunView.tsx         agentic workflow timeline (typewriter + terminal stream)
    overlays.tsx        Overlay shell + 9 feature panels + OVERLAYS map
    Tweaks.tsx          floating tweaks panel + useTweaks hook
    atoms.tsx           Dot, Meta
  data/
    types.ts            domain types
    seed.ts             agent / platforms / skills / automations / sandboxes / MCP /
                        toolsets / models / voice / personality
    mind.ts             knowledge-graph clusters, cross-links, node metadata, growth,
                        buildMind()
    runs.ts             intent library — each goal routes to a different memory path
  lib/
    i18n.ts             EN/ZH dictionary, tr(), useLang() (live language switching)
    icons.tsx           line-icon set, pixel-dog brand mark, platform glyphs, favicon
    platforms.ts        platform hue metadata + oklch color helper
```

## Design system

- **Palette** — deep-space near-black backgrounds (low-chroma oklch), a single amber accent
  (`#ffb152`, Hermes = messenger/speed/warmth), bioluminescent node hues per category
  (teal memory · violet skill · green person · blue source · coral domain), amber white-hot
  core. Switchable accent via Tweaks.
- **Type** — IBM Plex Sans (UI) + IBM Plex Mono (technical/identifiers).
- **Data** is plausible seed content modelled on Hermes' documented capabilities
  (self-authored skills, 20+ messaging connectors, 6 sandbox backends, MCP, voice mode,
  SOUL.md personality, multi-model routing) — swap in real data at the `data/` layer.
