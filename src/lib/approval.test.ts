import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { approvalStore, type ApprovalRequest } from './approval';

// 把 base-url 解析打桩成固定值,sendDecision 测试只关心 POST 的 URL/body 与 fail-closed。
vi.mock('./agent', () => ({ agentBaseUrl: async () => 'http://test' }));

function _clearPending(): void {
  while (approvalStore.pending().length > 0) {
    approvalStore.dismiss(approvalStore.pending()[0].call_id);
  }
}

describe('approvalStore', () => {
  beforeEach(() => {
    // 重置:清空所有 pending
    while (approvalStore.pending().length > 0) {
      approvalStore.dismiss(approvalStore.pending()[0].call_id);
    }
  });

  it('starts with no pending', () => {
    expect(approvalStore.pending()).toEqual([]);
  });

  it('addRequest enqueues a request', () => {
    const req: ApprovalRequest = {
      call_id: 'abc',
      tool: 'write_file',
      args: { path: 'x.py' },
      description: '写入文件 {path}',
      risk: 'low',
    };
    approvalStore.addRequest(req);
    expect(approvalStore.pending()).toHaveLength(1);
    expect(approvalStore.pending()[0].call_id).toBe('abc');
  });

  it('addRequest deduplicates same call_id', () => {
    const req: ApprovalRequest = {
      call_id: 'dup',
      tool: 'write_file',
      args: {},
      description: '',
      risk: 'low',
    };
    approvalStore.addRequest(req);
    approvalStore.addRequest(req);
    expect(approvalStore.pending()).toHaveLength(1);
  });

  it('dismiss removes a request', () => {
    approvalStore.addRequest({ call_id: 'a', tool: 't', args: {}, description: '', risk: 'low' });
    approvalStore.dismiss('a');
    expect(approvalStore.pending()).toHaveLength(0);
  });

  it('subscribe notifies on changes', () => {
    const calls: number[] = [];
    const unsub = approvalStore.subscribe(() => calls.push(approvalStore.pending().length));
    approvalStore.addRequest({ call_id: 'x', tool: 't', args: {}, description: '', risk: 'low' });
    approvalStore.dismiss('x');
    unsub();
    // After unsub, further changes should not fire
    approvalStore.addRequest({ call_id: 'y', tool: 't', args: {}, description: '', risk: 'low' });
    expect(calls).toEqual([1, 0]);
  });
});

describe('approvalStore.sendDecision', () => {
  beforeEach(_clearPending);
  afterEach(() => {
    vi.unstubAllGlobals();
    _clearPending();
  });

  it('POSTs the decision to the contract URL/body and dismisses locally', async () => {
    approvalStore.addRequest({ call_id: 'c1', tool: 'write_file', args: {}, description: '', risk: 'low' });
    const fetchMock = vi.fn(async () => ({ ok: true }) as Response);
    vi.stubGlobal('fetch', fetchMock);

    const ok = await approvalStore.sendDecision('sess9', 'c1', 'deny', 'once', '太危险');

    expect(ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('http://test/run/sess9/approve');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({
      call_id: 'c1', decision: 'deny', scope: 'once', reason: '太危险',
    });
    expect(approvalStore.pending()).toHaveLength(0);
  });

  it('defaults scope to "once" when omitted', async () => {
    approvalStore.addRequest({ call_id: 'c3', tool: 'write_file', args: {}, description: '', risk: 'low' });
    const fetchMock = vi.fn(async () => ({ ok: true }) as Response);
    vi.stubGlobal('fetch', fetchMock);

    await approvalStore.sendDecision('s', 'c3', 'approve');

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(init.body as string).scope).toBe('once');
  });

  it('fail-closed: network error still dismisses and returns false', async () => {
    approvalStore.addRequest({ call_id: 'c2', tool: 'write_file', args: {}, description: '', risk: 'low' });
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('network down'); }));

    const ok = await approvalStore.sendDecision('sess9', 'c2', 'approve');

    expect(ok).toBe(false);
    expect(approvalStore.pending()).toHaveLength(0);
  });
});
