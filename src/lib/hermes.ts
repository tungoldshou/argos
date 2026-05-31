// hermes.ts — data-source adapter between the UI and the Hermes agent.
//
// Two implementations behind one interface:
//   • TauriSource — invokes the Rust backend (real REST + SSE + ~/.hermes files)
//   • MockSource  — the built-in seed data, for running in a plain browser
//
// The right one is picked at runtime: Tauri injects `window.__TAURI_INTERNALS__`,
// so when that's present we talk to the real local Hermes; otherwise we mock.
import type { Skill, Automation, PlatformKind } from '../data/types';
import { SKILLS as MOCK_SKILLS, AUTOMATIONS as MOCK_AUTOMATIONS } from '../data/seed';
import { parseTranscripts, type SessionTrace } from '../data/parseTranscripts';
import type { BuiltMind } from '../data/mind';

export interface RunHandle {
  runId: string;
  /** stop receiving events + ask Hermes to stop the run */
  cancel: () => void;
}

/** A normalized real-time run event surfaced to the run view. */
export interface RunEvent {
  /** raw event type from Hermes, e.g. "tool.start", "message.delta", "run.completed" */
  type: string;
  /** human-readable line, best-effort extracted from the payload */
  text?: string;
  /** the full raw event for views that want more */
  raw: unknown;
}

export interface HermesSource {
  readonly kind: 'tauri' | 'mock';
  /** is the live Hermes API reachable? (mock: always true) */
  health(): Promise<boolean>;
  getSkills(): Promise<Skill[]>;
  getAutomations(): Promise<Automation[]>;
  /** toggle a job on/off; no-op in mock */
  toggleAutomation(id: string, on: boolean): Promise<void>;
  /** the agent's persistent memory markdown (tauri only; mock returns '') */
  getMemory(): Promise<{ memory: string; user: string }>;
  /**
   * Context Lens: a cross-agent "mind" graph built from local session
   * transcripts (Claude Code today). Returns null when unavailable (mock /
   * no transcripts) so the caller can fall back to the memory or seed graph.
   */
  getClaudeGraph?(): Promise<BuiltMind | null>;
  /**
   * Start a run for a goal. Calls `onEvent` for each streamed event and
   * `onDone` when the stream closes. Returns a handle to cancel.
   * Mock: synthesizes nothing (the existing scripted RunView drives itself).
   */
  startRun?(
    goal: string,
    onEvent: (e: RunEvent) => void,
    onDone: (err?: string) => void,
  ): Promise<RunHandle>;
}

// ──────────────────────────────────────────────────────────────────────────
// Tauri detection + typed invoke
// ──────────────────────────────────────────────────────────────────────────
function isTauri(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

// ──────────────────────────────────────────────────────────────────────────
// Mappers: real Hermes shapes → UI shapes
// ──────────────────────────────────────────────────────────────────────────
interface RawSkill {
  name: string;
  description?: string | null;
  category?: string | null;
}

function mapSkill(r: RawSkill): Skill {
  const tags = r.category ? [r.category] : (r.description ? deriveTags(r.description) : []);
  return {
    name: r.name,
    uses: 0,
    lastUsed: r.description?.slice(0, 48) ?? '',
    source: r.category ?? 'installed',
    tags,
    age: '',
  };
}

// Cheap keyword tagging so the skill cards aren't tag-less when Hermes gives no category.
const TAG_WORDS = ['browser', 'finance', 'stock', 'image', 'video', 'research', 'github', 'email', 'design', 'memory', 'web', 'audio', 'data', 'agent', 'mcp'];
function deriveTags(desc: string): string[] {
  const d = desc.toLowerCase();
  return TAG_WORDS.filter((w) => d.includes(w)).slice(0, 3);
}

interface RawJob {
  id: string;
  name: string;
  prompt?: string;
  schedule?: { display?: string; expr?: string } | null;
  schedule_display?: string | null;
  enabled?: boolean;
  deliver?: { platform?: string } | string | null;
  next_run_at?: string | null;
}

const KNOWN_PLATFORMS = new Set<PlatformKind>([
  'telegram', 'discord', 'slack', 'whatsapp', 'signal', 'email', 'cli',
  'matrix', 'teams', 'sms', 'feishu', 'dingtalk', 'wecom', 'gchat', 'homeassistant',
]);

function jobDest(j: RawJob): PlatformKind {
  let raw = '';
  if (typeof j.deliver === 'string') raw = j.deliver;
  else if (j.deliver && typeof j.deliver === 'object') raw = j.deliver.platform ?? '';
  raw = raw.toLowerCase();
  return (KNOWN_PLATFORMS.has(raw as PlatformKind) ? raw : 'cli') as PlatformKind;
}

function mapJob(j: RawJob): Automation & { id: string } {
  const cron = j.schedule?.display ?? j.schedule_display ?? j.schedule?.expr ?? '';
  return {
    id: j.id,
    title: j.name,
    cron,
    nl: (j.prompt ?? '').split('\n')[0].slice(0, 120),
    dest: jobDest(j),
    next: j.next_run_at ? new Date(j.next_run_at).toLocaleString() : '',
    on: j.enabled !== false,
  };
}

// ──────────────────────────────────────────────────────────────────────────
// Tauri implementation
// ──────────────────────────────────────────────────────────────────────────
class TauriSource implements HermesSource {
  readonly kind = 'tauri' as const;

  // Lazily import the Tauri API so the module still loads in a plain browser.
  private async api() {
    const core = await import('@tauri-apps/api/core');
    const event = await import('@tauri-apps/api/event');
    return { invoke: core.invoke, listen: event.listen };
  }

  async health(): Promise<boolean> {
    try {
      const { invoke } = await this.api();
      return await invoke<boolean>('hermes_health');
    } catch {
      return false;
    }
  }

  async getSkills(): Promise<Skill[]> {
    const { invoke } = await this.api();
    const res = await invoke<{ data?: RawSkill[] } | RawSkill[]>('hermes_get', { path: '/v1/skills' });
    const list = Array.isArray(res) ? res : (res.data ?? []);
    return list.map(mapSkill);
  }

  async getAutomations(): Promise<Automation[]> {
    const { invoke } = await this.api();
    const res = await invoke<{ data?: RawJob[] } | RawJob[]>('hermes_get', { path: '/api/jobs' });
    const list = Array.isArray(res) ? res : (res.data ?? []);
    return list.map(mapJob);
  }

  async toggleAutomation(id: string, on: boolean): Promise<void> {
    const { invoke } = await this.api();
    await invoke('hermes_post', { path: `/api/jobs/${id}/${on ? 'resume' : 'pause'}`, body: {} });
  }

  async getMemory(): Promise<{ memory: string; user: string }> {
    const { invoke } = await this.api();
    return invoke<{ memory: string; user: string }>('read_memory');
  }

  async getClaudeGraph(): Promise<BuiltMind | null> {
    try {
      const { invoke } = await this.api();
      const traces = await invoke<SessionTrace[]>('read_claude_transcripts', { limit: 40 });
      return parseTranscripts(traces);
    } catch {
      return null;
    }
  }

  async startRun(
    goal: string,
    onEvent: (e: RunEvent) => void,
    onDone: (err?: string) => void,
  ): Promise<RunHandle> {
    const { invoke, listen } = await this.api();
    const created = await invoke<{ run_id?: string; id?: string }>('hermes_post', {
      path: '/v1/runs',
      body: { input: goal },
    });
    const runId = created.run_id ?? created.id ?? '';

    const unlistenEvent = await listen<{ run_id: string; data: unknown }>('hermes://run-event', (ev) => {
      if (ev.payload.run_id !== runId) return;
      onEvent(normalizeEvent(ev.payload.data));
    });
    const unlistenDone = await listen<{ run_id: string; error?: string }>('hermes://run-done', (ev) => {
      if (ev.payload.run_id !== runId) return;
      onDone(ev.payload.error);
    });

    // begin streaming on the Rust side
    await invoke('stream_run_events', { runId });

    let cancelled = false;
    const cancel = () => {
      if (cancelled) return;
      cancelled = true;
      unlistenEvent();
      unlistenDone();
      invoke('hermes_post', { path: `/v1/runs/${runId}/stop`, body: {} }).catch(() => {});
    };
    return { runId, cancel };
  }
}

function normalizeEvent(data: unknown): RunEvent {
  const d = (data ?? {}) as Record<string, unknown>;
  const type = String(d.type ?? d.event ?? 'event');
  // best-effort text extraction across the event shapes Hermes emits
  const text =
    (typeof d.text === 'string' && d.text) ||
    (typeof d.delta === 'string' && d.delta) ||
    (typeof d.message === 'string' && d.message) ||
    (typeof d.name === 'string' && d.name) ||
    (typeof d.tool === 'string' && d.tool) ||
    undefined;
  return { type, text, raw: data };
}

// ──────────────────────────────────────────────────────────────────────────
// Mock implementation (browser / no Hermes)
// ──────────────────────────────────────────────────────────────────────────
class MockSource implements HermesSource {
  readonly kind = 'mock' as const;
  async health() { return true; }
  async getSkills() { return MOCK_SKILLS; }
  async getAutomations() { return MOCK_AUTOMATIONS; }
  async toggleAutomation() { /* no-op */ }
  async getMemory() { return { memory: '', user: '' }; }
  // startRun intentionally omitted — the scripted RunView drives itself in mock.
}

// ──────────────────────────────────────────────────────────────────────────
let _source: HermesSource | null = null;
export function hermes(): HermesSource {
  if (!_source) _source = isTauri() ? new TauriSource() : new MockSource();
  return _source;
}
