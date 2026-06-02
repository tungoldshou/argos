// ApprovalDialog.tsx — 当有 pending 审批请求时渲染模态(队列展示,每次只显示第一个)。
// 复用现有 CSS 变量(--surface-1/2, --border, --accent, --text-1/2/3, --mono)保持视觉一致。
// 注意:busy 状态必须在所有 hooks 调用后、条件 return 之前声明(hooks 规则)。
import { useEffect, useState } from 'react';
import type { CSSProperties } from 'react';
import { approvalStore, type ApprovalRequest } from '../lib/approval';
import { Icon } from '../lib/icons';

interface Props {
  sessionId: string | undefined;
}

/** description 里的 {arg_name} 占位符替换为 args 中对应的值。 */
function renderDescription(req: ApprovalRequest): string {
  return req.description.replace(/\{(\w+)\}/g, (_m, key) => {
    const v = req.args[key];
    if (v === undefined) return `{${key}}`;
    if (typeof v === 'string') return v;
    try { return JSON.stringify(v); } catch { return String(v); }
  });
}

const RISK_COLORS: Record<ApprovalRequest['risk'], string> = {
  low: 'var(--accent)',
  medium: 'var(--warn, #f59e0b)',
  high: 'var(--danger, #e44)',
};

export function ApprovalDialog({ sessionId }: Props) {
  const [pending, setPending] = useState<ApprovalRequest[]>(() => approvalStore.pending());
  // busy 在条件 return 之前声明,遵守 hooks 规则
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // 订阅 store 变更,同步到本地 state
    return approvalStore.subscribe(() => setPending([...approvalStore.pending()]));
  }, []);

  if (pending.length === 0) return null;

  const req = pending[0]; // 队列里第一个优先展示
  const description = renderDescription(req);
  const riskColor = RISK_COLORS[req.risk] ?? RISK_COLORS.medium;

  const decide = async (decision: 'approve' | 'deny', scope: 'once' | 'session' = 'once') => {
    if (busy) return;
    // 无 sessionId 时 UI 不应出现此弹窗,但防御性兜底
    if (!sessionId) {
      approvalStore.dismiss(req.call_id);
      return;
    }
    setBusy(true);
    await approvalStore.sendDecision(sessionId, req.call_id, decision, scope);
    setBusy(false);
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'rgba(0,0,0,0.55)',
        display: 'grid', placeItems: 'center',
      }}
    >
      <div style={{
        width: 460, maxWidth: '92vw',
        background: 'var(--surface-1)',
        border: '1px solid var(--border)',
        borderRadius: 14, padding: 22,
        boxShadow: '0 24px 60px rgba(0,0,0,0.4)',
      }}>
        {/* 标题行 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
          <span style={{
            width: 32, height: 32, borderRadius: 8,
            display: 'grid', placeItems: 'center', flexShrink: 0,
            background: `color-mix(in oklab, ${riskColor}, transparent 80%)`,
            color: riskColor,
          }}>
            {/* shield 不在图标集里;wrench 语义最近(有副作用的操作) */}
            <Icon name="wrench" size={17} />
          </span>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-1)' }}>
              Argos 想执行一个有副作用的操作
            </div>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>
              工具:{req.tool} · 风险:{req.risk}
            </div>
          </div>
        </div>

        {/* 描述 */}
        <div style={{
          background: 'var(--surface-2)',
          border: '1px solid var(--border)',
          borderRadius: 10, padding: 12, marginBottom: 14,
          fontSize: 13, lineHeight: 1.5, color: 'var(--text-1)',
        }}>
          {description || `工具 ${req.tool} 请求执行`}
        </div>

        {/* 可折叠参数详情 */}
        <details style={{ marginBottom: 14 }}>
          <summary style={{ cursor: 'pointer', fontSize: 12, color: 'var(--text-3)', userSelect: 'none' }}>
            查看参数
          </summary>
          <pre style={{
            marginTop: 8, padding: 10,
            background: 'var(--surface-3, rgba(255,255,255,0.03))',
            border: '1px solid var(--border)',
            borderRadius: 8,
            fontFamily: 'var(--mono)', fontSize: 11,
            overflow: 'auto', maxHeight: 160,
            color: 'var(--text-2)',
          }}>
            {JSON.stringify(req.args, null, 2)}
          </pre>
        </details>

        {/* 队列提示 */}
        {pending.length > 1 && (
          <div style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 10 }}>
            还有 {pending.length - 1} 个待审批
          </div>
        )}

        {/* 操作按钮 */}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
          <button
            disabled={busy}
            onClick={() => decide('deny')}
            style={btnStyle('ghost', busy)}
          >
            拒绝
          </button>
          <button
            disabled={busy}
            onClick={() => decide('approve', 'once')}
            style={btnStyle('secondary', busy)}
          >
            允许一次
          </button>
          {/* 高风险操作不提供"会话总是允许"按钮 */}
          {req.risk !== 'high' && (
            <button
              disabled={busy}
              onClick={() => decide('approve', 'session')}
              style={btnStyle('primary', busy)}
            >
              本次会话总是允许
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function btnStyle(variant: 'primary' | 'secondary' | 'ghost', disabled: boolean): CSSProperties {
  const base: CSSProperties = {
    padding: '8px 14px', borderRadius: 8, fontSize: 13, fontWeight: 500,
    cursor: disabled ? 'not-allowed' : 'pointer',
    border: '1px solid transparent',
    opacity: disabled ? 0.6 : 1,
    transition: 'opacity 0.15s',
  };
  if (variant === 'primary') {
    return { ...base, background: 'var(--accent)', color: 'white' };
  }
  if (variant === 'secondary') {
    return { ...base, background: 'var(--surface-2)', color: 'var(--text-1)', borderColor: 'var(--border)' };
  }
  // ghost
  return { ...base, background: 'transparent', color: 'var(--text-2)', borderColor: 'var(--border)' };
}
