// Shared domain types for the Hermes agent data layer.

export type NodeType = 'self' | 'topic' | 'memory' | 'skill' | 'person' | 'source';

export type PlatformKind =
  | 'telegram' | 'discord' | 'slack' | 'whatsapp' | 'signal' | 'email' | 'cli'
  | 'matrix' | 'teams' | 'sms' | 'feishu' | 'dingtalk' | 'wecom' | 'gchat' | 'homeassistant';

export interface Agent {
  name: string;
  host: string;
  version: string;
  uptimeDays: number;
  model: string;
  fallback: string;
  memories: number;
  skills: number;
  tokensToday: string;
  costMonth: string;
}

export type PlatformStatus = 'connected' | 'active' | 'reauth' | 'available';

export interface Platform {
  kind: PlatformKind;
  name: string;
  handle: string;
  status: PlatformStatus;
  primary?: boolean;
  msgs: number;
  last: string;
}

export interface Skill {
  name: string;
  uses: number;
  lastUsed: string;
  source: string;
  tags: string[];
  hot?: boolean;
  age: string;
}

export interface Automation {
  title: string;
  cron: string;
  nl: string;
  dest: PlatformKind;
  next: string;
  on: boolean;
}

export interface Sandbox {
  backend: string;
  label: string;
  status: 'running' | 'idle';
  detail: string;
  icon: string;
  count?: number;
}

export interface McpServer {
  name: string;
  tools: number;
  status: 'connected' | 'available';
  via: string;
  desc: string;
}

export interface Toolset {
  group: string;
  n: number;
  icon: string;
  tools: string;
}

export interface ModelRoute {
  role: string;
  model: string;
  via: string;
}

export interface Models {
  primary: { name: string; via: string; note: string };
  routes: ModelRoute[];
  providers: string[];
}

export interface VoiceChannel {
  kind: PlatformKind;
  name: string;
  mode: string;
  on: boolean;
}

export interface Voice {
  state: string;
  stt: string;
  tts: string;
  channels: VoiceChannel[];
}

export interface ContextFile {
  path: string;
  scope: string;
  desc: string;
}

export interface Personality {
  soul: string;
  traits: string[];
  context: ContextFile[];
  honcho: { model: string; conf: number; facts: number };
}

// ── Knowledge graph (the mind) ──
export interface NodeMeta {
  kind?: string;
  detail?: string;
  uses?: number;
  learned?: string;
  src?: string;
}

export interface Cluster {
  topic: string;
  members: [label: string, type: NodeType][];
}

export interface GrowthSpec {
  label: string;
  type: NodeType;
  near: string;
}

export interface LearnSpec {
  label: string;
  type: NodeType;
  links: string[];
}

export interface CategoryStyle {
  color: string;
  glow: string;
  label: string;
}
