// approval.ts — 前端审批 store:接 SSE approval_request 事件,弹模态,POST 决定回后端。
// 极简,无外部依赖(v1 够用,避免拉 zustand/jotai)。
import { agentBaseUrl } from './agent';

export interface ApprovalRequest {
  call_id: string;
  tool: string;
  args: Record<string, unknown>;
  description: string;
  risk: 'low' | 'medium' | 'high';
}

type Listener = () => void;

class ApprovalStore {
  private _pending: ApprovalRequest[] = [];
  private _listeners = new Set<Listener>();

  pending(): ApprovalRequest[] {
    return this._pending;
  }

  /** 入队一个审批请求;同 call_id 已存在则忽略(防 SSE 重发)。 */
  addRequest(req: ApprovalRequest): void {
    if (this._pending.some((r) => r.call_id === req.call_id)) return;
    this._pending = [...this._pending, req];
    this._emit();
  }

  /** 移除指定 call_id 的请求(决定已发出后调用)。 */
  dismiss(call_id: string): void {
    this._pending = this._pending.filter((r) => r.call_id !== call_id);
    this._emit();
  }

  /** 订阅 store 变更;返回取消订阅函数。 */
  subscribe(fn: Listener): () => void {
    this._listeners.add(fn);
    return () => this._listeners.delete(fn);
  }

  /**
   * 把用户的决定 POST 回后端,并始终 dismiss 本地记录(尽力而为,绝不抛出)。
   */
  async sendDecision(
    sessionId: string,
    call_id: string,
    decision: 'approve' | 'deny',
    scope: 'once' | 'session' = 'once',
    reason: string = '',
  ): Promise<boolean> {
    try {
      const base = await agentBaseUrl();
      const res = await fetch(`${base}/run/${sessionId}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ call_id, decision, scope, reason }),
      });
      this.dismiss(call_id);
      return res.ok;
    } catch {
      // 网络失败也要 dismiss,不让弹窗永久卡住
      this.dismiss(call_id);
      return false;
    }
  }

  private _emit(): void {
    for (const fn of this._listeners) fn();
  }
}

export const approvalStore = new ApprovalStore();
