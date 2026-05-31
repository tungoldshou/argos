// runs.ts — intent-aware agentic workflows; each goal lights a different memory path.
import type { LearnSpec, PlatformKind } from './types';

export type StepKind = 'recall' | 'skill' | 'subagent' | 'reason' | 'post';

export interface PostBlock {
  platform: PlatformKind;
  channel: string;
  title: string;
  bullets: string[];
}

export interface RunStep {
  kind: StepKind;
  label: string;
  detail: string;
  dur?: string;
  recall: string[];
  terminal?: string[];
  stream?: string;
  composing?: string;
  post?: PostBlock;
}

export interface RunMeta {
  tokens: string;
  cost: string;
  subagents: string;
}

export interface RunDef {
  id: string;
  match?: string[];
  trigger: { platform: PlatformKind; who: string; channel: string };
  meta: RunMeta;
  learn: LearnSpec;
  steps: RunStep[];
}

export const SK_ICON: Record<StepKind, string> = {
  recall: 'memory', skill: 'skills', subagent: 'branch', reason: 'sparkle', post: 'send',
};
export const SK_COL: Record<StepKind, string> = {
  recall: 'var(--accent)', skill: '#c4a0ff', subagent: '#c4a0ff', reason: 'var(--accent)', post: 'var(--live)',
};

export const RUNS: RunDef[] = [
  {
    id: 'pr',
    match: ['pr', 'pull request', 'merge', 'merged', 'review', 'changelog', 'release note'],
    trigger: { platform: 'slack', who: '@you', channel: '#eng' },
    meta: { tokens: '31.0k', cost: '$0.04', subagents: '2 parallel' },
    learn: { label: 'this week · gateway shipped', type: 'memory', links: ['streaming gateway', 'repo: atlas-core', 'summarize-pull-requests'] },
    steps: [
      { kind: 'recall', label: 'Searching memory', detail: 'pulled 4 facts: repos, summary style, #eng channel', dur: '0.4s', recall: ['repo: atlas-core', 'prefer terse PR summaries', 'Slack', 'deploy → ssh atlas-box'] },
      { kind: 'skill', label: 'Loaded skill', detail: 'summarize-pull-requests', dur: '0.1s', recall: ['summarize-pull-requests'] },
      { kind: 'subagent', label: 'Spawned subagent · fetch-prs', detail: 'isolated terminal · gh + jq', dur: '6.2s', recall: ['repo: atlas-core', 'CI · github actions'],
        terminal: ['$ gh pr list --state merged --search "merged:>=2026-05-23"', 'atlas-core   #1841  feat: streaming gateway', 'atlas-core   #1838  fix: memory eviction race', 'hermes-gw    #402   perf: batch RPC calls', '… 14 PRs across 3 repos'] },
      { kind: 'subagent', label: 'Spawned subagent · read-ci', detail: 'parallel · CI + changelogs', dur: '4.8s', recall: ['CI · github actions'],
        terminal: ['$ gh run list --limit 14 --json conclusion', 'green: 13   flaky: 1 (re-run passed)', 'no failing checks on merged set'] },
      { kind: 'reason', label: 'Reasoning', detail: 'clustering 14 PRs into 4 themes', dur: '2.1s', recall: ['streaming gateway', 'fixed memory-eviction race', 'memory architectures'],
        stream: 'Grouping: gateway streaming (3), memory subsystem (4), perf (2), housekeeping (5). Lead with the streaming gateway — you shipped it this week…' },
      { kind: 'post', label: 'Posting to Slack #eng', detail: 'composing digest', recall: ['Slack'], composing: 'Composing: 4 themes · 14 PRs · leading with the streaming gateway…',
        post: { platform: 'slack', channel: '#eng', title: 'This week — 14 PRs / 3 repos', bullets: ['Streaming gateway shipped (3)', 'Memory subsystem (4) · perf (2)', 'CI all green'] } },
    ],
  },
  {
    id: 'research',
    match: ['arxiv', 'paper', 'research', 'read', 'study', 'literature', 'survey'],
    trigger: { platform: 'telegram', who: '@you', channel: 'DM' },
    meta: { tokens: '24.8k', cost: '$0.03', subagents: '2 parallel' },
    learn: { label: 'flagged · RAG vs long-context', type: 'memory', links: ['memory architectures', 'arXiv · cs.AI', 'writing a paper on this'] },
    steps: [
      { kind: 'recall', label: 'Searching memory', detail: 'research context · long-horizon agents', dur: '0.5s', recall: ['writing a paper on this', 'memory architectures', 'arXiv · cs.AI'] },
      { kind: 'skill', label: 'Loaded skill', detail: 'scrape-arxiv-cs-ai', dur: '0.1s', recall: ['scrape-arxiv-cs-ai'] },
      { kind: 'subagent', label: 'Spawned subagent · fetch-papers', detail: 'browser · arxiv', dur: '5.4s', recall: ['arXiv · cs.AI', 'Web search'],
        terminal: ['$ arxiv search cat:cs.AI --since 24h --rank relevance', '› 38 new · 6 relevant to your paper', '#1 Retrieval-augmented long-horizon agents', '#2 Memory-eviction policies for agents', '…'] },
      { kind: 'subagent', label: 'Spawned subagent · summarize', detail: 'parallel · summarize-paper', dur: '4.4s', recall: ['summarize-paper', 'memory architectures'],
        terminal: ['$ summarize --papers 6 --style terse', '6 abstracts → 6 bullet takeaways', 'flagged 2 as high-relevance'] },
      { kind: 'reason', label: 'Reasoning', detail: 'ranking against your open questions', dur: '2.4s', recall: ['writing a paper on this', 'tool use'],
        stream: 'Top signal: retrieval-augmented memory beats long-context on 3 of 4 benchmarks — directly relevant to section 4 of your draft…' },
      { kind: 'post', label: 'Posting to Discord #research', detail: 'composing digest', recall: ['Discord #research'], composing: 'Composing: 6 papers, leading with the RAG result…',
        post: { platform: 'discord', channel: '#research', title: 'Today · 6 relevant papers', bullets: ['RAG > long-context on 3/4 — must-read', 'Memory-eviction policies — skim', '+4 tangential'] } },
    ],
  },
  {
    id: 'deploy',
    match: ['deploy', 'ship', 'release', 'staging', 'rollback', 'build', 'rollout'],
    trigger: { platform: 'discord', who: '@ops', channel: '#ops' },
    meta: { tokens: '18.2k', cost: '$0.02', subagents: '2 parallel' },
    learn: { label: 'deployed atlas-core · #1841', type: 'memory', links: ['deploy-staging', 'repo: atlas-core', 'SSH · atlas-box'] },
    steps: [
      { kind: 'recall', label: 'Searching memory', detail: 'deploy rules + target', dur: '0.4s', recall: ['deploy → ssh atlas-box', 'on fail → rollback + ping #ops', 'vault creds · never log'] },
      { kind: 'skill', label: 'Loaded skill', detail: 'deploy-staging', dur: '0.1s', recall: ['deploy-staging'] },
      { kind: 'subagent', label: 'Spawned subagent · build', detail: 'docker · hardened', dur: '5.0s', recall: ['Docker', 'repo: atlas-core'],
        terminal: ['$ docker build -t atlas-core:1841 .', '✓ build 38s · image 412MB', '$ trivy image atlas-core:1841', 'no critical vulns'] },
      { kind: 'subagent', label: 'Spawned subagent · deploy', detail: 'ssh atlas-box', dur: '4.6s', recall: ['SSH · atlas-box', 'CI · github actions'],
        terminal: ['$ ssh atlas-box "deploy atlas-core:1841"', 'rolling 3/3 ✓   health: green', 'migration ok · 0 downtime'] },
      { kind: 'reason', label: 'Verifying', detail: 'smoke tests + health', dur: '2.0s', recall: ['on fail → rollback + ping #ops'],
        stream: 'All health checks green, p99 latency steady. No rollback needed — recording the deploy in memory…' },
      { kind: 'post', label: 'Posting to Slack #ops', detail: 'composing report', recall: ['Slack'], composing: 'Composing deploy report…',
        post: { platform: 'slack', channel: '#ops', title: 'Deployed atlas-core #1841', bullets: ['Streaming gateway live', '0 downtime · CI green', 'Rollback armed'] } },
    ],
  },
  {
    id: 'briefing',
    match: ['brief', 'digest', 'morning', 'standup', 'catch me up', 'summary of', 'overnight'],
    trigger: { platform: 'telegram', who: 'scheduled', channel: 'DM' },
    meta: { tokens: '12.4k', cost: '$0.01', subagents: '1 task' },
    learn: { label: 'briefing read · 08:02', type: 'memory', links: ['morning-briefing', 'standup 9:15 — brief before', 'Telegram'] },
    steps: [
      { kind: 'recall', label: 'Searching memory', detail: 'briefing prefs + schedule', dur: '0.4s', recall: ['morning-briefing', 'standup 9:15 — brief before', 'prefer terse PR summaries'] },
      { kind: 'skill', label: 'Loaded skill', detail: 'morning-briefing', dur: '0.1s', recall: ['morning-briefing'] },
      { kind: 'subagent', label: 'Spawned subagent · gather', detail: 'inbox + calendar + feeds', dur: '5.2s', recall: ['Email', 'RSS feeds', 'arXiv · cs.AI'],
        terminal: ['$ gather --overnight', 'email: 23 (4 need you)', 'calendar: standup 9:15 · 1:1 11:00', 'feeds: 6 arxiv · 3 rss'] },
      { kind: 'reason', label: 'Reasoning', detail: 'rank by what matters today', dur: '2.2s', recall: ['writing a paper on this', 'daily digest'],
        stream: 'Leading with the 4 emails that need a reply before standup, then the RAG paper you’ll care about, then overnight merges…' },
      { kind: 'post', label: 'Posting to Telegram', detail: 'composing briefing', recall: ['Telegram'], composing: 'Composing your briefing…',
        post: { platform: 'telegram', channel: 'DM', title: 'Morning briefing · 08:00', bullets: ['4 emails need you before 9:15', 'RAG paper — relevant to your draft', 'Gateway merged overnight'] } },
    ],
  },
];

const FALLBACK: RunDef = {
  id: 'generic',
  trigger: { platform: 'telegram', who: '@you', channel: 'DM' },
  meta: { tokens: '9.1k', cost: '$0.01', subagents: '1 task' },
  learn: { label: '', type: 'memory', links: ['@you'] },
  steps: [
    { kind: 'recall', label: 'Searching memory', detail: 'relevant context for your request', dur: '0.4s', recall: ['@you', 'prefer terse PR summaries'] },
    { kind: 'reason', label: 'Planning', detail: 'decomposing into steps + picking tools', dur: '2.3s', recall: ['tool use'],
      stream: 'Breaking this down, selecting the right tools and the channel to reply on…' },
    { kind: 'subagent', label: 'Spawned subagent · work', detail: 'isolated sandbox · tools', dur: '4.4s', recall: ['Web search'],
      terminal: ['$ run task --sandbox docker', '› web search · 12 sources', '› drafting result', 'done'] },
    { kind: 'post', label: 'Posting to Telegram', detail: 'composing reply', recall: ['Telegram'], composing: 'Composing your reply…',
      post: { platform: 'telegram', channel: 'DM', title: 'Done', bullets: ['Completed your request', 'Full details in thread'] } },
  ],
};

export function pickRun(goal: string): RunDef {
  const g = (goal || '').toLowerCase();
  const hit = RUNS.find((r) => r.match?.some((m) => g.includes(m)));
  if (hit) return hit;
  const short = goal.length > 30 ? goal.slice(0, 28).trim() + '…' : goal;
  return { ...FALLBACK, learn: { label: short, type: 'memory', links: ['@you'] } };
}
