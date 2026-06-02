import { describe, it, expect, afterEach, vi } from 'vitest';
import { fetchMcpServers } from './mcp';

vi.mock('./agent', () => ({ agentBaseUrl: async () => 'http://test' }));

afterEach(() => vi.unstubAllGlobals());

describe('fetchMcpServers', () => {
  it('GETs /mcp/servers and returns the servers array', async () => {
    const servers = [{ name: 'filesystem', status: 'connected', tools: 11, transport: 'stdio', trust: 'builtin', desc: 'fs' }];
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ servers }) }) as Response);
    vi.stubGlobal('fetch', fetchMock);

    const out = await fetchMcpServers();
    expect(out).toEqual(servers);
    const [url] = fetchMock.mock.calls[0] as unknown as [string];
    expect(url).toBe('http://test/mcp/servers');
  });

  it('returns [] on network error (honest empty, never throws)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('down'); }));
    expect(await fetchMcpServers()).toEqual([]);
  });

  it('returns [] when response not ok', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, json: async () => ({}) }) as Response));
    expect(await fetchMcpServers()).toEqual([]);
  });
});
