// seed.ts — realistic seed data for the Hermes desktop app.
import type {
  Agent, Platform, Skill, Automation, Sandbox, McpServer, Models, Voice, Personality,
} from './types';

export const AGENT: Agent = {
  name: 'Argos',
  host: 'argos@local',
  version: 'v0.1.0',
  uptimeDays: 41,
  model: 'MiniMax-M3',
  fallback: 'GLM / Kimi / DeepSeek (multi-model)',
  memories: 2847,
  skills: 38,
  tokensToday: '1.84M',
  costMonth: '$22.40',
};

export const PLATFORMS: Platform[] = [
  { kind: 'telegram', name: 'Telegram', handle: '@hermes_atlas_bot', status: 'connected', primary: true, msgs: 1240, last: '2m ago' },
  { kind: 'discord', name: 'Discord', handle: 'atlas-guild · 4 channels', status: 'connected', msgs: 860, last: '11m ago' },
  { kind: 'slack', name: 'Slack', handle: 'nous-eng · #ops #eng', status: 'connected', msgs: 512, last: 'just now' },
  { kind: 'whatsapp', name: 'WhatsApp', handle: '+1 ••• ••• 4471', status: 'connected', msgs: 96, last: '1h ago' },
  { kind: 'email', name: 'Email', handle: 'hermes@atlas.dev', status: 'connected', msgs: 318, last: '24m ago' },
  { kind: 'signal', name: 'Signal', handle: 'linked device', status: 'reauth', msgs: 40, last: '3d ago' },
  { kind: 'cli', name: 'CLI / SSH', handle: 'tty · 2 sessions', status: 'active', msgs: 0, last: 'now' },
  { kind: 'matrix', name: 'Matrix', handle: '#atlas:matrix.org', status: 'connected', msgs: 74, last: '40m ago' },
  { kind: 'teams', name: 'Microsoft Teams', handle: 'atlas-corp · 2 teams', status: 'connected', msgs: 130, last: '2h ago' },
  { kind: 'feishu', name: 'Feishu', handle: 'atlas · 飞书机器人', status: 'connected', msgs: 58, last: '5h ago' },
  { kind: 'sms', name: 'SMS', handle: '+1 ••• ••• 2210', status: 'available', msgs: 0, last: '—' },
];

// Hermes ships 20+ messaging connectors from one gateway
export const PLATFORMS_MORE = ['Mattermost', 'DingTalk', 'WeCom', 'Weixin', 'QQ Bot', 'Yuanbao', 'BlueBubbles', 'Home Assistant', 'Google Chat'];

export const SKILLS: Skill[] = [
  { name: 'summarize-pull-requests', uses: 214, lastUsed: '2m ago', source: 'Slack · #eng', tags: ['git', 'github', 'report'], hot: true, age: '38d' },
  { name: 'morning-briefing', uses: 41, lastUsed: '8h ago', source: 'scheduled', tags: ['digest', 'calendar', 'news'], hot: true, age: '38d' },
  { name: 'backup-postgres', uses: 12, lastUsed: '2d ago', source: 'Telegram · @you', tags: ['db', 'cron', 'ssh'], age: '31d' },
  { name: 'scrape-arxiv-cs-ai', uses: 188, lastUsed: '4h ago', source: 'self-initiated', tags: ['research', 'browser'], hot: true, age: '36d' },
  { name: 'deploy-staging', uses: 27, lastUsed: '1d ago', source: 'Discord · #ops', tags: ['ci', 'docker', 'ssh'], age: '29d' },
  { name: 'finance-monthly-report', uses: 5, lastUsed: '12d ago', source: 'Email', tags: ['sheets', 'pdf'], age: '24d' },
  { name: 'triage-inbox', uses: 96, lastUsed: '24m ago', source: 'Email', tags: ['email', 'classify'], age: '22d' },
  { name: 'transcribe-voice-note', uses: 63, lastUsed: '3h ago', source: 'WhatsApp', tags: ['audio', 'tts'], age: '18d' },
  { name: 'watch-rss-feeds', uses: 140, lastUsed: '1h ago', source: 'self-initiated', tags: ['rss', 'browser'], age: '14d' },
  { name: 'generate-release-notes', uses: 9, lastUsed: '5d ago', source: 'Slack · #eng', tags: ['git', 'writing'], age: '9d' },
];

export const AUTOMATIONS: Automation[] = [
  { title: 'Morning briefing', cron: 'Every weekday at 8:00 AM', nl: 'send me a digest of overnight messages, calendar, and arXiv', dest: 'telegram', next: 'Tomorrow 8:00', on: true },
  { title: 'Summarize new PRs', cron: 'Every 6 hours', nl: 'check open PRs across repos and post a summary', dest: 'slack', next: 'in 2h 14m', on: true },
  { title: 'Postgres backup', cron: 'Sundays at 10:00 PM', nl: 'dump prod db, push to b2, email me the report', dest: 'email', next: 'Sun 22:00', on: true },
  { title: 'arXiv cs.AI watch', cron: 'Every 6 hours', nl: 'scrape new cs.AI papers, rank by relevance to my projects', dest: 'discord', next: 'in 2h 14m', on: true },
  { title: 'Monthly finance report', cron: '1st of month, 9:00 AM', nl: 'pull Stripe + bank, build the P&L sheet and PDF', dest: 'email', next: 'Jun 1, 9:00', on: false },
];

// 诚实:工具调用实际是在本机以子进程运行的(裸 subprocess on host),目前没有任何
// OS 级沙箱。曾经这里假装在跑 Docker/SSH/Daytona/Modal/Singularity —— 全是假的,
// 后端 sidecar 不存在,违反"UI 数字必须匹配真实能力"。等真接了 OS 沙箱再加回来。
export const SANDBOXES: Sandbox[] = [
  { backend: 'local', label: 'Local process', status: 'running', detail: 'runs on this machine · no OS sandbox yet', icon: 'cpu' },
];

// ── MCP servers (Model Context Protocol) ──
export const MCP_SERVERS: McpServer[] = [
  { name: 'filesystem', tools: 8, status: 'connected', via: 'stdio', desc: 'read/write project files in the sandbox' },
  { name: 'github', tools: 14, status: 'connected', via: 'stdio', desc: 'issues, pull requests, repos, actions' },
  { name: 'postgres', tools: 6, status: 'connected', via: 'stdio', desc: 'query the prod replica (read-only)' },
  { name: 'puppeteer', tools: 7, status: 'connected', via: 'stdio', desc: 'headless browser control & scraping' },
  { name: 'linear', tools: 9, status: 'available', via: 'sse', desc: 'tasks, projects, cycles' },
  { name: 'sentry', tools: 5, status: 'available', via: 'sse', desc: 'error monitoring & traces' },
];

// ── Model providers & routing ──
export const MODELS: Models = {
  primary: { name: 'MiniMax-M3', via: 'Anthropic 兼容端', note: '便宜 · 逼近 Opus' },
  routes: [
    { role: 'Reasoning / default', model: 'MiniMax-M3', via: 'MiniMax' },
    { role: 'Fallback', model: 'GLM / Kimi / DeepSeek', via: 'multi-provider' },
  ],
  providers: ['Nous Portal', 'OpenRouter', 'OpenAI', 'Anthropic', 'any OpenAI-compatible endpoint'],
};

// ── Voice mode ──
export const VOICE: Voice = {
  state: 'ready',
  stt: 'Whisper (local)', tts: 'Nous Portal TTS',
  channels: [
    { kind: 'cli', name: 'CLI', mode: 'push-to-talk', on: true },
    { kind: 'telegram', name: 'Telegram', mode: 'voice notes ↔ replies', on: true },
    { kind: 'discord', name: 'Discord', mode: 'voice notes', on: true },
    { kind: 'discord', name: 'Discord VC', mode: 'real-time, full-duplex', on: true },
  ],
};

// ── Personality / SOUL.md / context ──
export const PERSONALITY: Personality = {
  soul: 'You are Hermes — terse, dry wit, allergic to preamble. Lead with the answer. Never flatter. When unsure, say so and show your reasoning. Treat the operator as a peer engineer.',
  traits: ['terse', 'dry wit', 'no preamble', 'peer, not assistant'],
  context: [
    { path: '~/.hermes/SOUL.md', scope: 'global voice', desc: 'default tone across every conversation' },
    { path: 'atlas-core/CONTEXT.md', scope: 'project', desc: 'repos, deploy targets, conventions' },
    { path: 'long-horizon-paper/CONTEXT.md', scope: 'project', desc: 'thesis, citations to track' },
  ],
  honcho: { model: 'dialectic user model', conf: 0.86, facts: 214 },
};
