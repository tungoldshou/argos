// SkillsView.tsx — 列表 + 来源徽章 + 启/禁 + Import 按钮。从后端 /skills 拉真数据。
import { useEffect, useState } from 'react';
import { fetchSkills, toggleSkill, type Skill } from '../lib/skills';
import { SkillImportDialog } from './SkillImportDialog';

export function SkillsView() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = async () => setSkills(await fetchSkills());
  useEffect(() => { reload(); }, []);

  const onToggle = async (s: Skill) => {
    setError(null);
    const r = await toggleSkill(s.name, !s.enabled);
    if (!r.ok) setError(r.reason || 'toggle denied');
    await reload();
  };

  return (
    <div style={{ padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
        <h3>Skills</h3>
        <button onClick={() => setImporting(true)}>+ Import skill</button>
      </div>
      {error && <div style={{ color: 'var(--danger, #e44)' }}>{error}</div>}
      {skills.length === 0
        ? <div style={{ color: 'var(--text-3)' }}>No skills loaded — check sidecar logs.</div>
        : skills.map(s => (
            <div key={s.name} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 10, marginBottom: 8 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span><b>{s.name}</b> <span style={{ color: 'var(--text-3)' }}>[{s.trust}]</span></span>
                <button onClick={() => onToggle(s)}>{s.enabled ? '禁用' : '启用'}</button>
              </div>
              <div style={{ color: 'var(--text-3)', fontSize: 12 }}>{s.description}</div>
              {s.source && <div style={{ color: 'var(--text-3)', fontSize: 11, marginTop: 4 }}>来源: {s.source}</div>}
            </div>
          ))}
      {importing && <SkillImportDialog
        onClose={() => setImporting(false)}
        onDone={async () => { setImporting(false); await reload(); }}
      />}
    </div>
  );
}
