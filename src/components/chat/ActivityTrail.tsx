// ActivityTrail.tsx — agent 普通过程(工具调用/结果)的"安静"折叠流。
// 默认收起成一行摘要,点击展开看细节。诚实信号不走这里(走 HonestyCard)。
import { useState } from 'react';
import { Icon } from '../../lib/icons';

export interface Activity {
  call: string;
  result?: string;
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
        <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 6, paddingLeft: 4, borderLeft: '1px solid var(--border)' }}>
          {activities.map((a, i) => (
            <div key={i} style={{ paddingLeft: 10 }}>
              <div style={{ fontFamily: 'var(--mono)', fontSize: 11.5, color: 'var(--accent)', wordBreak: 'break-all' }}>{a.call}</div>
              {a.result !== undefined && (
                <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--text-3)', marginTop: 2, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                  {a.result.length > 600 ? a.result.slice(0, 600) + '…' : a.result}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
