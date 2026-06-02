import { describe, it, expect, beforeEach } from 'vitest';
import { approvalStore, type ApprovalRequest } from './approval';

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
