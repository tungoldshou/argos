// overlays.tsx — feature panels that dock from the right over the memory brain
// (no page nav). Same docked behaviour as Runs.
import { useEffect, useState, type ReactNode, type ReactElement } from 'react';
import { useNarrow } from '../lib/responsive';
import { Icon, PlatformGlyph, type IconName } from '../lib/icons';
import { pColor } from '../lib/platforms';
import { tr, useLang } from '../lib/i18n';
import type { Skill, Automation, McpServer } from '../data/types';
import { isTauri, getSettings, setLlmConfig, restartAgent, type AppSettings } from '../lib/agent';
import { fetchMcpServers } from '../lib/mcp';
import {
  AGENT, SKILLS, PLATFORMS, PLATFORMS_MORE, AUTOMATIONS, SANDBOXES, MODELS,
  VOICE, PERSONALITY,
} from '../data/seed';

interface OverlayProps {
  title: string;
  icon: IconName;
  sub?: string;
  onClose: () => void;
  children: ReactNode;
}

export function Overlay({ title, icon, sub, onClose, children }: OverlayProps) {
  const narrow = useNarrow();
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [onClose]);
  return (
    <div className="mind-panel" style={narrow
      ? { position: 'absolute', top: 8, left: 8, right: 8, bottom: 62, zIndex: 11, display: 'flex', flexDirection: 'column', overflow: 'hidden', animation: 'slidein .35s cubic-bezier(0.16,1,0.3,1) both' }
      : { position: 'absolute', top: 16, right: 16, bottom: 16, width: 'min(600px, 56vw)', zIndex: 11, display: 'flex', flexDirection: 'column', overflow: 'hidden', animation: 'slidein .35s cubic-bezier(0.16,1,0.3,1) both' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '16px 20px', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
        <div style={{ width: 34, height: 34, borderRadius: 10, display: 'grid', placeItems: 'center', background: 'color-mix(in oklab, var(--accent), transparent 84%)', color: 'var(--accent)' }}><Icon name={icon} size={18} /></div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 16, fontWeight: 700, letterSpacing: '-0.01em' }}>{tr(title)}</div>
          {sub && <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{tr(sub)}</div>}
        </div>
        <button onClick={onClose} className="mind-link" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, height: 30, padding: '0 11px', borderRadius: 8, border: '1px solid var(--border)', background: 'none', color: 'var(--text-2)', cursor: 'pointer', fontFamily: 'var(--mono)', fontSize: 11 }}>
          <Icon name="chevron" size={13} style={{ transform: 'rotate(180deg)' }} /> {tr('back to memory')}
        </button>
      </div>
      <div style={{ overflow: 'auto', padding: 20, flex: 1 }}>{children}</div>
    </div>
  );
}

function SkillsOverlay({ onClose }: { onClose: () => void }) {
  // Argos 自有技能(当前用 seed 展示)。P1 接入 Argos 自己的技能注册表后替换。
  const skills: Skill[] = SKILLS;
  const sub = `${AGENT.skills} ` + tr('self-authored procedures · 995 runs / 30d');
  return (
    <Overlay title="Skills" sub={sub} icon="skills" onClose={onClose}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {skills.map((s, i) => (
          <div key={s.name + i} style={{ display: 'grid', gridTemplateColumns: '20px 1fr auto', gap: 13, alignItems: 'center', padding: '11px 10px', borderRadius: 9, borderBottom: i < skills.length - 1 ? '1px solid color-mix(in oklab,var(--border),transparent 40%)' : 'none' }}>
            <span style={{ color: s.hot ? 'var(--accent)' : 'var(--text-3)', display: 'flex' }}><Icon name={s.hot ? 'bolt' : 'skills'} size={15} /></span>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontFamily: 'var(--mono)', fontSize: 12.5, fontWeight: 600, color: 'var(--text)' }}>{s.name}</div>
              {s.lastUsed && <div style={{ fontSize: 11.5, color: 'var(--text-3)', marginTop: 3, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.lastUsed}</div>}
              {s.tags.length > 0 && <div style={{ display: 'flex', gap: 5, marginTop: 5 }}>{s.tags.map((t) => <span key={t} style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--text-3)', background: 'var(--surface-2)', border: '1px solid var(--border)', padding: '1px 6px', borderRadius: 5 }}>{t}</span>)}</div>}
            </div>
            <div style={{ textAlign: 'right' }}>
              {s.uses > 0 && <div style={{ fontFamily: 'var(--mono)', fontSize: 13, fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>{s.uses}</div>}
              <div style={{ fontSize: 10, color: 'var(--text-3)' }}>{s.source}</div>
            </div>
          </div>
        ))}
      </div>
    </Overlay>
  );
}

function ConnectionsOverlay({ onClose }: { onClose: () => void }) {
  const st: Record<string, string> = { connected: 'var(--live)', active: 'var(--live)', reauth: 'var(--accent)', available: 'var(--text-3)' };
  return (
    <Overlay title="Connections" sub="One agent, every channel — start anywhere, continue anywhere" icon="connections" onClose={onClose}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2,1fr)', gap: 11 }}>
        {PLATFORMS.map((p) => (
          <div key={p.kind} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: 13, borderRadius: 11, background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
            <div style={{ width: 38, height: 38, borderRadius: 10, display: 'grid', placeItems: 'center', background: `color-mix(in oklab, ${pColor(p.kind, 0.74)}, transparent 82%)`, color: pColor(p.kind, 0.74) }}><PlatformGlyph kind={p.kind} size={19} /></div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13.5, fontWeight: 600 }}>{p.name}</div>
              <div style={{ fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--text-3)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{p.handle}</div>
            </div>
            <span style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: st[p.status], fontWeight: 600, whiteSpace: 'nowrap' }}><span style={{ width: 6, height: 6, borderRadius: '50%', background: st[p.status] }} />{p.status === 'reauth' ? 're-auth' : 'on'}</span>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--border)' }}>
        <div style={{ fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-3)', marginBottom: 10 }}>{tr('20+ connectors — one gateway')}</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 7 }}>
          {PLATFORMS_MORE.map((n) => (
            <span key={n} style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--text-2)', background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 999, padding: '5px 11px' }}>{n}</span>
          ))}
          <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--text-3)', padding: '5px 4px' }}>+ {tr('more')}</span>
        </div>
      </div>
    </Overlay>
  );
}

function Toggle2({ on, onChange }: { on: boolean; onChange?: (v: boolean) => void }) {
  const [v, setV] = useState(on);
  useEffect(() => setV(on), [on]);
  const flip = () => { const next = !v; setV(next); onChange?.(next); };
  return (
    <button onClick={flip} style={{ width: 38, height: 22, borderRadius: 999, border: 'none', cursor: 'pointer', background: v ? 'var(--accent)' : 'var(--surface-2)', position: 'relative', flexShrink: 0 }}>
      <span style={{ position: 'absolute', top: 3, left: v ? 19 : 3, width: 16, height: 16, borderRadius: '50%', background: v ? '#1a1305' : 'var(--text-3)', transition: 'left .2s' }} />
    </button>
  );
}

// Automations carry an optional real job id when sourced live, so we can toggle them.
type LiveAutomation = Automation & { id?: string };

function AutomationsOverlay({ onClose }: { onClose: () => void }) {
  // Argos 自有自动化(当前用 seed 展示)。P1 接入 Argos 自己的调度器后替换。
  const jobs: LiveAutomation[] = AUTOMATIONS;
  const toggle = (_a: LiveAutomation, _on: boolean) => { /* P1: Argos 自有调度器 */ };
  return (
    <Overlay title="Automations" sub="Plain-language schedules, run unattended through the gateway" icon="automations" onClose={onClose}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
        {jobs.map((a, i) => (
          <div key={a.id ?? i} style={{ display: 'flex', alignItems: 'center', gap: 13, padding: 13, borderRadius: 11, background: 'var(--surface-2)', border: '1px solid var(--border)', opacity: a.on ? 1 : 0.55 }}>
            <div style={{ width: 34, height: 34, borderRadius: 9, display: 'grid', placeItems: 'center', background: 'rgba(255,255,255,0.05)', color: a.on ? 'var(--accent)' : 'var(--text-3)', flexShrink: 0 }}><Icon name="clock" size={17} /></div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}><span style={{ fontSize: 13.5, fontWeight: 600 }}>{a.title}</span><span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--text-3)' }}>{a.cron}</span></div>
              {a.nl && <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 3, fontStyle: 'italic', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>“{a.nl}”</div>}
            </div>
            <span style={{ color: pColor(a.dest, 0.78), display: 'flex' }}><PlatformGlyph kind={a.dest} size={15} /></span>
            <Toggle2 on={a.on} onChange={(v) => toggle(a, v)} />
          </div>
        ))}
      </div>
    </Overlay>
  );
}

function SandboxesOverlay({ onClose }: { onClose: () => void }) {
  const c: Record<string, string> = { running: 'var(--live)', idle: 'var(--text-3)' };
  return (
    <Overlay title="Sandboxes" sub="Tool calls run as a local subprocess on this machine — no OS-level isolation yet" icon="sandbox" onClose={onClose}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
        {SANDBOXES.map((s, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 13, padding: 13, borderRadius: 11, background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
            <div style={{ width: 38, height: 38, borderRadius: 10, display: 'grid', placeItems: 'center', background: s.status === 'running' ? 'color-mix(in oklab,var(--live),transparent 82%)' : 'rgba(255,255,255,0.05)', color: s.status === 'running' ? 'var(--live)' : 'var(--text-2)', flexShrink: 0 }}><Icon name={s.icon as IconName} size={19} /></div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 14, fontWeight: 600 }}>{s.label}</div>
              <div style={{ fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--text-3)', marginTop: 2 }}>{s.detail}</div>
            </div>
            <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 600, color: c[s.status], textTransform: 'capitalize' }}><span style={{ width: 6, height: 6, borderRadius: '50%', background: c[s.status] }} />{s.status}</span>
          </div>
        ))}
      </div>
    </Overlay>
  );
}

function SettingsOverlay({ onClose }: { onClose: () => void }) {
  const rows: [string, string][] = [
    ['Default sandbox', 'Local process — no OS sandbox yet'], ['Gateway', 'systemd · auto-restart'],
    ['Telemetry', 'Local only — nothing leaves your server'], ['License', 'MIT · open source'],
  ];
  // 通用 provider 配置:打包 .app 双击不继承 shell env,必须让用户在这里填 key,
  // 持久化到用户配置目录,Rust 启动 sidecar 时读出注入。这是"下载即用"的关键。
  const { lang, toggle: toggleLang } = useLang();
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [provider, setProvider] = useState('anthropic');
  const [base, setBase] = useState('');
  const [model, setModel] = useState('');
  const [keyInput, setKeyInput] = useState('');
  const [status, setStatus] = useState<'' | 'saving' | 'restarting' | 'done'>('');
  const inTauri = isTauri();
  const PROVIDER_DEFAULTS: Record<string, string> = {
    anthropic: 'https://api.minimaxi.com/anthropic',
    openai: 'https://api.openai.com/v1',
  };

  useEffect(() => {
    getSettings().then((s) => {
      setSettings(s);
      if (s) { setProvider(s.provider || 'anthropic'); setBase(s.base || PROVIDER_DEFAULTS[s.provider || 'anthropic']); setModel(s.model || ''); }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = async () => {
    setStatus('saving');
    const ok = await setLlmConfig({ provider, base: base.trim(), model: model.trim(), key: keyInput.trim() });
    if (!ok) { setStatus(''); return; }
    setKeyInput('');
    setStatus('restarting');
    await restartAgent();
    await new Promise((r) => setTimeout(r, 1500));
    getSettings().then(setSettings);
    setStatus('done');
  };
  const pickProvider = (p: string) => { setProvider(p); setBase(PROVIDER_DEFAULTS[p]); setStatus(''); };

  return (
    <Overlay title="Settings" sub={`Argos ${AGENT.version} · MIT · ` + tr('runs entirely on your infra')} icon="settings" onClose={onClose}>
      {/* 语言:从顶栏移来 */}
      <div style={{ fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-3)', marginBottom: 10 }}>{tr('Language')}</div>
      <div style={{ display: 'flex', gap: 1, background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 8, padding: 2, marginBottom: 16, width: 'fit-content' }}>
        {([['en', 'EN'], ['zh', '中']] as const).map(([code, lbl]) => (
          <button key={code} onClick={() => { if (lang !== code) toggleLang(); }} style={{ fontFamily: 'var(--mono)', fontSize: 12, fontWeight: 600, padding: '5px 14px', borderRadius: 6, cursor: 'pointer', border: 'none', background: lang === code ? 'var(--accent)' : 'transparent', color: lang === code ? '#1a1305' : 'var(--text-3)' }}>{lbl}</button>
        ))}
      </div>

      {/* 模型厂商:任意 OpenAI/Anthropic 兼容端点 */}
      <div style={{ fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-3)', marginBottom: 10 }}>{tr('Provider')}</div>
      <div style={{ padding: 14, borderRadius: 11, background: 'var(--surface-2)', border: '1px solid var(--border)', marginBottom: 16 }}>
        {!inTauri ? (
          <div style={{ fontSize: 12, color: 'var(--text-3)', lineHeight: 1.6 }}>{tr('key is set via .env.local in browser dev')}</div>
        ) : (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 11 }}>
              <span style={{ width: 7, height: 7, borderRadius: '50%', background: settings?.key_configured ? 'var(--live, #45e0a0)' : 'var(--text-3)', flexShrink: 0 }} />
              <span style={{ fontSize: 12.5, color: settings?.key_configured ? 'var(--live, #45e0a0)' : 'var(--text-3)' }}>
                {settings?.key_configured ? tr('key configured') + ` · ••••${settings.key_tail}` : tr('no key — agent runs in demo mode')}
              </span>
            </div>
            <div style={{ display: 'flex', gap: 1, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: 2, marginBottom: 9, width: 'fit-content' }}>
              {([['anthropic', tr('Anthropic-compatible')], ['openai', tr('OpenAI-compatible')]] as const).map(([p, lbl]) => (
                <button key={p} onClick={() => pickProvider(p)} style={{ fontSize: 11.5, fontWeight: 600, padding: '5px 12px', borderRadius: 6, cursor: 'pointer', border: 'none', background: provider === p ? 'var(--accent)' : 'transparent', color: provider === p ? '#1a1305' : 'var(--text-3)' }}>{lbl}</button>
              ))}
            </div>
            <input value={base} onChange={(e) => setBase(e.target.value)} placeholder={tr('Base URL')}
              style={{ width: '100%', boxSizing: 'border-box', height: 34, padding: '0 11px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text-1)', fontSize: 12, fontFamily: 'var(--mono)', marginBottom: 8 }} />
            <input value={model} onChange={(e) => setModel(e.target.value)} placeholder={tr('Model name')}
              style={{ width: '100%', boxSizing: 'border-box', height: 34, padding: '0 11px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text-1)', fontSize: 12, fontFamily: 'var(--mono)', marginBottom: 8 }} />
            <div style={{ display: 'flex', gap: 8 }}>
              <input type="password" value={keyInput} onChange={(e) => { setKeyInput(e.target.value); setStatus(''); }} onKeyDown={(e) => e.key === 'Enter' && save()}
                placeholder={settings?.key_configured ? tr('API key') + ' — ' + tr('keep existing key — leave blank') : tr('paste your API key')}
                disabled={status === 'saving' || status === 'restarting'}
                style={{ flex: 1, height: 36, padding: '0 11px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text-1)', fontSize: 12.5, fontFamily: 'var(--mono)' }} />
              <button onClick={save} disabled={status === 'saving' || status === 'restarting' || (!keyInput.trim() && !settings?.key_configured)}
                style={{ height: 36, padding: '0 15px', borderRadius: 8, border: 'none', background: 'var(--accent)', color: '#1a1205', fontWeight: 700, fontSize: 12.5, cursor: 'pointer', whiteSpace: 'nowrap' }}>
                {status === 'saving' ? tr('Saving…') : status === 'restarting' ? tr('Restarting…') : tr('Save & apply')}
              </button>
            </div>
            {status === 'done' && <div style={{ marginTop: 9, fontSize: 11.5, color: 'var(--accent)' }}>{tr('applied — agent restarted')}</div>}
          </>
        )}
      </div>
      <div style={{ fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-3)', marginBottom: 10 }}>{tr('Models & routing')}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 16 }}>
        {MODELS.routes.map((r, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: 12, borderRadius: 11, background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
            <div style={{ width: 32, height: 32, borderRadius: 9, display: 'grid', placeItems: 'center', background: 'color-mix(in oklab,var(--accent),transparent 84%)', color: 'var(--accent)', flexShrink: 0 }}><Icon name="cpu" size={16} /></div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 600 }}>{tr(r.role)}</div>
              <div style={{ fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--text-3)' }}>{r.via}</div>
            </div>
            <span style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--text-2)' }}>{r.model}</span>
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 7, marginBottom: 18 }}>
        {MODELS.providers.map((p) => (
          <span key={p} style={{ fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--text-2)', background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 999, padding: '4px 10px' }}>{tr(p)}</span>
        ))}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {rows.map(([k, v], i) => (
          <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '13px 4px', borderBottom: i < rows.length - 1 ? '1px solid color-mix(in oklab,var(--border),transparent 40%)' : 'none' }}>
            <span style={{ fontSize: 13.5, fontWeight: 600 }}>{tr(k)}</span>
            <span style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--text-2)', textAlign: 'right' }}>{tr(v)}</span>
          </div>
        ))}
      </div>
    </Overlay>
  );
}

function ToolsOverlay({ onClose }: { onClose: () => void }) {
  const groups: { group: string; tools: { name: string; desc: string }[] }[] = [
    { group: 'File', tools: [
      { name: 'read_file', desc: 'Read a file in the workspace' },
      { name: 'write_file', desc: 'Write/overwrite a file in the workspace' },
      { name: 'edit_file', desc: 'Edit a file (exact or whitespace-fuzzy match)' },
      { name: 'search_files', desc: 'Search file contents or names (ripgrep)' },
    ] },
    { group: 'Execution', tools: [
      { name: 'run_command', desc: 'Run a whitelisted command (tests/build/lint)' },
    ] },
    { group: 'Web', tools: [
      { name: 'web_search', desc: 'Search the web (DuckDuckGo free, Tavily with key)' },
      { name: 'web_extract', desc: 'Read a web page (cleaned + summarized)' },
    ] },
  ];
  const total = groups.reduce((n, g) => n + g.tools.length, 0);
  return (
    <Overlay title="Tools" sub={`${total} ` + tr('real built-in tools')} icon="layers" onClose={onClose}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {groups.map((g) => (
          <div key={g.group}>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--text-3)', marginBottom: 8 }}>{tr(g.group)}</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {g.tools.map((t) => (
                <div key={t.name} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: 12, borderRadius: 11, background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
                  <div style={{ width: 32, height: 32, borderRadius: 9, display: 'grid', placeItems: 'center', background: 'color-mix(in oklab,var(--accent),transparent 84%)', color: 'var(--accent)', flexShrink: 0 }}><Icon name="layers" size={16} /></div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontFamily: 'var(--mono)', fontSize: 13, fontWeight: 600 }}>{t.name}</div>
                    <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 2 }}>{tr(t.desc)}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </Overlay>
  );
}

function McpOverlay({ onClose }: { onClose: () => void }) {
  const st: Record<string, string> = { connected: 'var(--live)', disconnected: 'var(--accent)', disabled: 'var(--text-3)', available: 'var(--text-3)' };
  const [mcpServers, setMcpServers] = useState<McpServer[]>([]);
  useEffect(() => {
    let alive = true;
    fetchMcpServers().then((rows) => {
      if (!alive) return;
      setMcpServers(rows.map((r) => ({
        name: r.name,
        status: r.status as McpServer['status'],
        tools: r.tools,
        via: r.transport,
        desc: r.desc,
        error: r.error,
      })));
    });
    return () => { alive = false; };
  }, []);
  return (
    <Overlay title="MCP" sub={tr('Model Context Protocol — plug in external tool servers')} icon="plug" onClose={onClose}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
        {mcpServers.map((m, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: 13, borderRadius: 11, background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
            <div style={{ width: 36, height: 36, borderRadius: 10, display: 'grid', placeItems: 'center', background: m.status === 'connected' ? 'color-mix(in oklab,var(--live),transparent 82%)' : 'rgba(255,255,255,0.05)', color: m.status === 'connected' ? 'var(--live)' : 'var(--text-2)', flexShrink: 0 }}><Icon name="plug" size={18} /></div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontFamily: 'var(--mono)', fontSize: 13, fontWeight: 600 }}>{m.name}</span>
                <span style={{ fontFamily: 'var(--mono)', fontSize: 9.5, color: 'var(--text-3)', border: '1px solid var(--border)', borderRadius: 4, padding: '0 5px' }}>{m.via}</span>
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 3 }}>{tr(m.desc)}</div>
              {m.error && <div style={{ fontSize: 11, color: 'var(--accent)', marginTop: 3, fontFamily: 'var(--mono)' }}>{m.error}</div>}
            </div>
            <div style={{ textAlign: 'right', flexShrink: 0 }}>
              <div style={{ fontFamily: 'var(--mono)', fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>{m.tools}</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 10.5, color: st[m.status], fontWeight: 600, justifyContent: 'flex-end' }}><span style={{ width: 5, height: 5, borderRadius: '50%', background: st[m.status] }} />{tr(m.status)}</div>
            </div>
          </div>
        ))}
        {mcpServers.length === 0 && (
          <div style={{ fontSize: 12, color: 'var(--text-3)', padding: '8px 4px' }}>{tr('No MCP servers connected — check sidecar logs.')}</div>
        )}
      </div>
    </Overlay>
  );
}

function VoiceOverlay({ onClose }: { onClose: () => void }) {
  return (
    <Overlay title="Voice Mode" sub={tr('Real-time voice across CLI, Telegram, and Discord')} icon="voice" onClose={onClose}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '14px 16px', borderRadius: 12, background: 'color-mix(in oklab,var(--accent),transparent 90%)', border: '1px solid color-mix(in oklab,var(--accent),transparent 70%)', marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 3, alignItems: 'center', height: 30 }}>
          {[10, 20, 30, 18, 26, 12, 22].map((h, i) => (
            <span key={i} style={{ width: 3, height: h, borderRadius: 2, background: 'var(--accent)', animation: `vbar 1s ${i * 0.12}s ease-in-out infinite alternate` }} />
          ))}
        </div>
        <div>
          <div style={{ fontSize: 14, fontWeight: 600 }}>{tr('Listening')}</div>
          <div style={{ fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--text-3)', marginTop: 2 }}>{VOICE.stt} · {VOICE.tts}</div>
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
        {VOICE.channels.map((c, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: 12, borderRadius: 11, background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
            <div style={{ width: 32, height: 32, borderRadius: 9, display: 'grid', placeItems: 'center', background: `color-mix(in oklab, ${pColor(c.kind, 0.74)}, transparent 82%)`, color: pColor(c.kind, 0.74), flexShrink: 0 }}><PlatformGlyph kind={c.kind} size={16} /></div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13, fontWeight: 600 }}>{c.name}</div>
              <div style={{ fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--text-3)' }}>{tr(c.mode)}</div>
            </div>
            <span style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: 'var(--live)', fontWeight: 600 }}><span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--live)' }} />{tr('on')}</span>
          </div>
        ))}
      </div>
    </Overlay>
  );
}

function PersonalityOverlay({ onClose }: { onClose: () => void }) {
  return (
    <Overlay title="Personality" sub={tr('SOUL.md voice, project context, and a learned model of you')} icon="mask" onClose={onClose}>
      <div style={{ fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-3)', marginBottom: 9 }}>~/.hermes/SOUL.md</div>
      <div style={{ padding: '14px 16px', borderRadius: 11, background: 'rgba(0,0,0,0.28)', border: '1px solid var(--border)', fontFamily: 'var(--mono)', fontSize: 12, lineHeight: 1.7, color: 'var(--text-2)', marginBottom: 10 }}>{tr(PERSONALITY.soul)}</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 7, marginBottom: 18 }}>
        {PERSONALITY.traits.map((t) => (
          <span key={t} style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--accent)', background: 'color-mix(in oklab,var(--accent),transparent 86%)', border: '1px solid color-mix(in oklab,var(--accent),transparent 70%)', borderRadius: 999, padding: '4px 11px' }}>{tr(t)}</span>
        ))}
      </div>
      <div style={{ fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-3)', marginBottom: 9 }}>{tr('Context files')}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 18 }}>
        {PERSONALITY.context.map((c, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 11, padding: 12, borderRadius: 11, background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
            <Icon name="file" size={16} style={{ color: 'var(--text-3)', flexShrink: 0 }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--text)' }}>{c.path}</div>
              <div style={{ fontSize: 11.5, color: 'var(--text-3)', marginTop: 2 }}>{tr(c.desc)}</div>
            </div>
            <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--text-3)', border: '1px solid var(--border)', borderRadius: 4, padding: '1px 6px' }}>{tr(c.scope)}</span>
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 11, padding: 13, borderRadius: 11, background: 'color-mix(in oklab,var(--accent),transparent 90%)', border: '1px solid color-mix(in oklab,var(--accent),transparent 72%)' }}>
        <Icon name="sparkle" size={17} style={{ color: 'var(--accent)' }} />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 600 }}>{tr('Honcho — dialectic user model')}</div>
          <div style={{ fontSize: 11.5, color: 'var(--text-3)', marginTop: 2 }}>{PERSONALITY.honcho.facts} {tr('facts learned about you')} · {tr('confidence')} {Math.round(PERSONALITY.honcho.conf * 100)}%</div>
        </div>
      </div>
    </Overlay>
  );
}

export type OverlayKey =
  | 'swarm' | 'skills' | 'tools' | 'mcp' | 'voice' | 'connections' | 'automations'
  | 'personality' | 'sandboxes' | 'settings';

// swarm 不在此表:它需要 engine 引用驱动中央知识图,由 App 直接渲染(见 App.tsx)。
export const OVERLAYS: Record<Exclude<OverlayKey, 'swarm'>, (props: { onClose: () => void }) => ReactElement> = {
  skills: SkillsOverlay,
  tools: ToolsOverlay,
  mcp: McpOverlay,
  voice: VoiceOverlay,
  connections: ConnectionsOverlay,
  automations: AutomationsOverlay,
  personality: PersonalityOverlay,
  sandboxes: SandboxesOverlay,
  settings: SettingsOverlay,
};
