// HonestyCard.tsx — argos 的"灵魂时刻":verify 拦截假完成 / 诚实求助 / 篡改警告。
// 比普通气泡响亮,但用柔背景+左色条+图标,显得高级而非刺眼的 alert box。
import { Icon, type IconName } from '../../lib/icons';

type HonestyType = 'verify_failed' | 'escalation' | 'tampering';

const SPEC: Record<HonestyType, { color: string; icon: IconName; title: string }> = {
  verify_failed: { color: '#ffb152', icon: 'activity', title: 'Argos 拦下了一次假完成' },
  escalation: { color: '#ff7a4d', icon: 'memory', title: 'Argos 卡住了，诚实求助' },
  tampering: { color: '#ff5c5c', icon: 'activity', title: '⚠ 改动了被保护的测试文件' },
};

export function HonestyCard({ type, detail }: { type: HonestyType; detail: string }) {
  const s = SPEC[type];
  const extra = type === 'tampering' ? '：请人工核对它是否为了"通过"而改测试。' : '';
  return (
    <div style={{ display: 'flex', gap: 11, margin: '6px 0', padding: '11px 13px', borderRadius: 11, borderLeft: `3px solid ${s.color}`, background: `color-mix(in oklab, ${s.color}, transparent 90%)` }}>
      <Icon name={s.icon} size={16} style={{ color: s.color, flexShrink: 0, marginTop: 1 }} />
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: s.color, marginBottom: 3 }}>{s.title}</div>
        <div style={{ fontSize: 12.5, color: 'var(--text-2)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.5 }}>
          {detail}{extra}
        </div>
      </div>
    </div>
  );
}
