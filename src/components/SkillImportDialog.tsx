// SkillImportDialog.tsx — 导入 skill 的前端表单。后端走 _SKILL_GATE 弹审批,这里只接表单。
import { useState } from 'react';
import { importSkill } from '../lib/skills';

export function SkillImportDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [tab, setTab] = useState<'url' | 'content'>('content');
  const [url, setUrl] = useState('');
  const [content, setContent] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true); setErr(null);
    const r = await importSkill(tab === 'url' ? { url } : { content, source: 'inline' });
    setBusy(false);
    if (!r.ok) { setErr(r.reason || 'failed'); return; }
    onDone();
  };

  return (
    <div role="dialog" aria-modal="true" style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', display: 'grid', placeItems: 'center', zIndex: 1000 }}>
      <div style={{ width: 520, maxWidth: '92vw', background: 'var(--surface-1)', border: '1px solid var(--border)', borderRadius: 14, padding: 22 }}>
        <h3>Import skill</h3>
        <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
          <button onClick={() => setTab('content')} disabled={tab === 'content'}>粘贴内容</button>
          <button onClick={() => setTab('url')} disabled={tab === 'url'}>URL</button>
        </div>
        {tab === 'content'
          ? <textarea rows={12} value={content} onChange={e => setContent(e.target.value)}
              style={{ width: '100%', fontFamily: 'var(--mono)', fontSize: 12 }} />
          : <input value={url} onChange={e => setUrl(e.target.value)} placeholder="https://..."
              style={{ width: '100%' }} />}
        {err && <div style={{ color: 'var(--danger, #e44)', marginTop: 8 }}>{err}</div>}
        <p style={{ color: 'var(--text-3)', fontSize: 11, marginTop: 8 }}>
          导入的技能视同 untrusted 文本。提交后会弹审批让你看清来源与正文。
        </p>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 12 }}>
          <button onClick={onClose} disabled={busy}>取消</button>
          <button onClick={submit} disabled={busy || (tab === 'content' ? !content.trim() : !url.trim())}>提交</button>
        </div>
      </div>
    </div>
  );
}
