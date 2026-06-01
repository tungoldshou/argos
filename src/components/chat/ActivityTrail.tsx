// ActivityTrail.tsx — agent 普通过程(工具调用/结果)的"安静"折叠流。
// 默认收起成一行摘要,点击展开看细节。诚实信号不走这里(走 HonestyCard)。
import { useState } from 'react';
import { Icon } from '../../lib/icons';

export interface Activity {
  call: string;
  result?: string;
}

// CJK/emoji 安全:按 code-point(不是 UTF-16 单元)切,避免把代理对切成半边。
function truncateSafe(s: string, max: number): string {
  const cps = Array.from(s);
  return cps.length > max ? cps.slice(0, max).join('') + '…' : s;
}

// 工具结果里夹带 API 错误字符串时(被 LLM 当文本回流),给点危险色提示,
// 避免和普通结果混在一起被忽略。
function resultLooksLikeError(s: string): boolean {
  return /^Error code:\s*\d{3}\b/.test(s) && /api_error/.test(s);
}

export function ActivityTrail({ activities }: { activities: Activity[] }) {
  const [open, setOpen] = useState(false);
  if (activities.length === 0) return null;
  return (
    <div style={{ margin: '4px 0' }}>
      <button
        onClick={() => setOpen((v) => !v)}
        style={{ display: 'inline-flex', alignItems: 'center', gap: 6, background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-3)', fontFamily: 'var(--mono)', fontSize: 11.5, padding: '2px 0' }}
      >
        <Icon name="activity" size={12} style={{ color: 'var(--text-3)' }} />
        用了 {activities.length} 个工具
        <Icon name="chevron" size={11} style={{ transform: open ? 'rotate(90deg)' : 'none', transition: 'transform .15s' }} />
      </button>
      {open && (
        <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 8, paddingLeft: 4, borderLeft: '1px solid var(--border)' }}>
          {activities.map((a, i) => {
            const isErr = a.result !== undefined && resultLooksLikeError(a.result);
            return (
              <div key={i} style={{ paddingLeft: 10, display: 'flex', flexDirection: 'column', gap: 3 }}>
                <div style={{ fontFamily: 'var(--mono)', fontSize: 11.5, color: 'var(--accent)', wordBreak: 'break-all' }}>{a.call}</div>
                {a.result !== undefined && (
                  <div style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
                    <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: isErr ? 'var(--danger)' : 'var(--text-3)', flexShrink: 0, lineHeight: 1.5 }}>↳</span>
                    <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: isErr ? 'var(--danger)' : 'var(--text-3)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.5 }}>
                      {truncateSafe(a.result, 600)}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
