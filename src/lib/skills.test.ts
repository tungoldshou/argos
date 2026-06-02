import { describe, it, expect, afterEach, vi } from 'vitest';
import { fetchSkills, importSkill, toggleSkill } from './skills';

vi.mock('./agent', () => ({ agentBaseUrl: async () => 'http://test' }));

afterEach(() => vi.unstubAllGlobals());

const sample = [
  { name: 'py-test-runner', description: 'd', trust: 'builtin', enabled: true, source: '' },
];

function jsonResponse(body: unknown, ok = true): Response {
  return { ok, json: async () => body } as Response;
}

describe('skills API', () => {
  it('fetchSkills GETs /skills and returns the list', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ skills: sample }));
    vi.stubGlobal('fetch', fetchMock);
    const out = await fetchSkills();
    expect(out).toEqual(sample);
    const [url] = fetchMock.mock.calls[0] as unknown as [string];
    expect(url).toBe('http://test/skills');
  });

  it('fetchSkills returns [] on network error (honest empty)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('down'); }));
    expect(await fetchSkills()).toEqual([]);
  });

  it('importSkill POSTs body and returns ok', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ ok: true, skill: { name: 'x' } }));
    vi.stubGlobal('fetch', fetchMock);
    const out = await importSkill({ content: '...', source: 'inline' });
    expect(out.ok).toBe(true);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('http://test/skills/import');
    expect(JSON.parse(init.body as string)).toMatchObject({ content: '...', source: 'inline' });
  });

  it('toggleSkill POSTs to /skills/{name}/toggle', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ ok: true }));
    vi.stubGlobal('fetch', fetchMock);
    const out = await toggleSkill('a', false);
    expect(out.ok).toBe(true);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('http://test/skills/a/toggle');
    expect(JSON.parse(init.body as string)).toEqual({ enabled: false });
  });
});
