// skills.ts — 前端 skill 仓库 client。失败 → 返 []/null,绝不抛;审批闸的事由后端做。
import { agentBaseUrl } from './agent';

export type Trust = 'builtin' | 'imported' | 'user_created';

export interface Skill {
  name: string;
  description: string;
  trust: Trust;
  enabled: boolean;
  source: string;
}

export async function fetchSkills(): Promise<Skill[]> {
  try {
    const base = await agentBaseUrl();
    const res = await fetch(`${base}/skills`);
    if (!res.ok) return [];
    const body = await res.json();
    return Array.isArray(body.skills) ? body.skills : [];
  } catch {
    return [];
  }
}

export interface ImportResult {
  ok: boolean;
  reason?: string;
  skill?: Skill;
}

export async function importSkill(body: { url?: string; content?: string; source?: string }): Promise<ImportResult> {
  try {
    const base = await agentBaseUrl();
    const res = await fetch(`${base}/skills/import`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) return { ok: false, reason: `http ${res.status}` };
    return (await res.json()) as ImportResult;
  } catch (e) {
    return { ok: false, reason: String(e) };
  }
}

export async function toggleSkill(name: string, enabled: boolean): Promise<{ ok: boolean; reason?: string }> {
  try {
    const base = await agentBaseUrl();
    const res = await fetch(`${base}/skills/${encodeURIComponent(name)}/toggle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    });
    if (!res.ok) return { ok: false, reason: `http ${res.status}` };
    return (await res.json()) as { ok: boolean; reason?: string };
  } catch (e) {
    return { ok: false, reason: String(e) };
  }
}
