// i18n.ts — lightweight EN/ZH layer. English strings are keys; tr() returns
// the Chinese form when lang is 'zh' and an entry exists, else the original.
// Code-like identifiers (skill names, repo names, platform names, terminal text)
// are intentionally left untranslated — natural for a developer tool.
import { useSyncExternalStore } from 'react';

export type Lang = 'en' | 'zh';

const STORAGE_KEY = 'hermes-lang';

const TR: Record<string, string> = {
  // chrome / status
  working: '执行中', memory: '记忆', EXECUTING: '执行中', THINKING: '思考中',
  recalling: '回忆', memories: '条记忆', 'lighting recalls ◂': '点亮回忆 ◂', 'drag to explore': '拖拽探索',
  'Search the memory…': '搜索记忆…', 'Search…': '搜索…',
  'Give Hermes a goal — watch it work, beside its memory…': '给 Hermes 一个目标 —— 看它在记忆旁工作…',
  'Give Hermes a goal…': '给 Hermes 一个目标…', run: '执行',
  // dock
  Memory: '记忆', Runs: '任务', Skills: '技能', Connections: '连接', Automations: '自动化', Sandboxes: '沙箱', Settings: '设置',
  // detail panel
  recalled: '已回忆', learned: '学习于', origin: '来源', links: '连接', Connected: '相连',
  Domain: '领域', Person: '人物', Source: '来源', Skill: '技能',
  // tweaks
  'Core hue': '核心色', Behaviour: '行为', 'Living motion': '活体动效', 'Re-center memory': '重新居中',
  // suggestions
  'Summarize this week’s merged PRs': '总结本周合并的 PR',
  'Scan today’s arXiv for my paper': '扫描今天 arXiv 上与我论文相关的内容',
  'Deploy atlas-core to staging': '把 atlas-core 部署到预发布',
  'Give me the morning briefing': '给我今天的晨间简报',
  // run view
  'back to memory': '返回记忆', 'goal · via command': '目标 · 来自指令',
  completed: '完成',
  'Searching memory': '检索记忆', 'Loaded skill': '加载技能',
  'Spawned subagent · fetch-prs': '派生子代理 · fetch-prs', 'Spawned subagent · read-ci': '派生子代理 · read-ci',
  Reasoning: '推理', 'Posting to Slack #eng': '发布到 Slack #eng',
  'pulled 4 facts: repos, summary style, #eng channel': '调取 4 条事实:仓库、摘要风格、#eng 频道',
  'isolated terminal · gh + jq': '隔离终端 · gh + jq', 'parallel · CI + changelogs': '并行 · CI + 变更日志',
  'clustering 14 PRs into 4 themes': '把 14 个 PR 聚成 4 个主题', 'composing digest': '正在撰写摘要',
  'Grouping: gateway streaming (3), memory subsystem (4), perf (2), housekeeping (5). Lead with the streaming gateway — you shipped it this week…': '分组:网关流式 (3)、记忆子系统 (4)、性能 (2)、杂项 (5)。以流式网关开头 —— 你本周刚上线了它…',
  'Composing: 4 themes · 14 PRs · leading with the streaming gateway…': '撰写中:4 个主题 · 14 个 PR · 以流式网关开头…',
  'posted to': '已发布到',
  '… lighting recalled memories ◂': '… 点亮回忆的记忆 ◂',
  'learned · wired into memory': '学到 · 已写入记忆', '← in your brain': '← 已进入大脑',
  'this week · gateway shipped': '本周 · 网关已上线',
  subagents: '子代理', cost: '成本', sandbox: '沙箱', '2 parallel': '2 并行', '1 task': '1 任务',
  // overlays — titles & subs
  'self-authored procedures · 995 runs / 30d': '自创流程 · 995 次运行 / 30 天',
  'One agent, every channel — start anywhere, continue anywhere': '一个智能体,全平台 —— 随处开始,随处继续',
  'Plain-language schedules, run unattended through the gateway': '自然语言定时,经网关无人值守运行',
  'Every tool call runs hardened & isolated': '每次工具调用都在加固隔离环境中运行',
  'runs entirely on your infra': '完全运行在你自己的基础设施上',
  // misc data labels (topics + memory texts + meta)
  'long-horizon agents': '长程智能体', 'deploy & ops': '部署与运维', 'comms & inbox': '通讯与收件箱',
  finance: '财务', 'knowledge ingest': '知识摄取',
  'streaming gateway': '流式网关', 'memory architectures': '记忆架构', 'tool use': '工具使用', 'daily digest': '每日摘要',
  // memory node texts
  'deploy → ssh atlas-box': '部署 → ssh atlas-box', 'fixed memory-eviction race': '修复了内存逐出竞态',
  'prefer terse PR summaries': '偏好简洁的 PR 摘要', 'writing a paper on this': '正在就此写一篇论文',
  'on fail → rollback + ping #ops': '失败时 → 回滚 + 通知 #ops', 'vault creds · never log': 'vault 凭据 · 永不记录日志',
  'standup 9:15 — brief before': '站会 9:15 — 之前发简报', 'you ship on Fridays': '你常在周五上线',
  'P&L on the 1st': '每月 1 号出损益表', 'detect flaky CI tests': '检测不稳定的 CI 测试',
  'cache arXiv embeddings': '缓存 arXiv 向量', 'retrieval-augmented memory': '检索增强记忆',
  'repo: atlas-core': '仓库:atlas-core', 'CI · github actions': 'CI · github actions',
  // META details
  'Reads merged PRs, clusters by theme, posts a terse digest.': '读取已合并的 PR,按主题聚类,发布简洁摘要。',
  'Overnight messages + calendar + arXiv, delivered before standup.': '隔夜消息 + 日历 + arXiv,在站会前送达。',
  'Pulls new cs.AI papers, ranks by relevance to your projects.': '抓取新的 cs.AI 论文,按与你项目的相关性排序。',
  'CI-gated deploy to atlas-box over SSH inside a hardened sandbox.': '经 SSH 在加固沙箱内、由 CI 把关部署到 atlas-box。',
  'Bullet points, no preamble, always link the diff.': '要点式,无开场白,始终附上 diff 链接。',
  'When a deploy fails, roll back automatically and alert #ops.': '部署失败时自动回滚并通知 #ops。',
  'Prod secrets live in vault://atlas/pg and must never be logged.': '生产密钥存于 vault://atlas/pg,绝不可写入日志。',
  'Daily standup is 9:15 AM PT; the briefing must land before it.': '每日站会为 PT 上午 9:15,简报须在此前送达。',
  'You are drafting a paper on long-horizon agents — flag relevant work.': '你在撰写一篇关于长程智能体的论文 —— 标记相关工作。',
  'Primary operator. Reachable on Telegram, Slack, WhatsApp, Email.': '主要操作者。可通过 Telegram、Slack、WhatsApp、Email 联系。',
  // detail origin/meta values
  'self-authored': '自创', 'taught by @you': '由 @you 教授', preference: '偏好', rule: '规则', project: '项目', person: '人物', owner: '所有者',
  'inferred from feedback': '由反馈推断', 'standing rule': '长期规则', 'project context': '项目上下文',
  'scheduled, 38d ago': '定时,38 天前', 'self-initiated, 36d ago': '自发,36 天前',
  'from Slack · #eng, 38d ago': '来自 Slack · #eng,38 天前', 'from Discord · #ops, 29d ago': '来自 Discord · #ops,29 天前',
  // dock additions
  Tools: '工具', MCP: 'MCP', Voice: '语音', Personality: '人格',
  Features: '功能', 'Jump to a feature…': '跳转到功能…', 'No feature matches': '没有匹配的功能',
  'Work': '工作', 'Capabilities': '能力', 'Reach': '触达', 'Identity': '身份',
  home: '主页', tasks: '任务', servers: '服务器', mic: '麦克风', cron: '定时', models: '模型',
  'Meet Argos': '认识 Argos', 'Got it': '知道了',
  'Drag & scroll the brain to explore its memory': '拖拽、滚轮缩放大脑,探索它的记忆',
  'Press ⌘K for tools, skills, connections & more': '按 ⌘K 打开工具、技能、连接等功能',
  'Tap the ✦ menu for tools, skills, connections & more': '点右上角 ✦ 打开工具、技能、连接等功能',
  'Give it a goal below — watch it work, beside its memory': '在下方给它一个目标 —— 看它在记忆旁工作',
  // connections extra
  '20+ connectors — one gateway': '20+ 连接器 —— 同一网关', more: '更多',
  // tools overlay
  'built-in tools, grouped into toolsets': '内置工具,按工具集分组', tools: '个工具',
  'Shell & Code': 'Shell 与代码', Web: '网络', Media: '媒体', Delegation: '委派', Messaging: '消息', 'MCP (dynamic)': 'MCP(动态)',
  'bash · execute_code · edit_file · read_file · grep …': 'bash · execute_code · edit_file · read_file · grep …',
  'tools exposed by connected MCP servers': '由已连接的 MCP 服务器暴露的工具',
  // mcp overlay
  'Model Context Protocol — plug in external tool servers': 'Model Context Protocol —— 接入外部工具服务器',
  connected: '已连接', available: '可用',
  'read/write project files in the sandbox': '在沙箱中读写项目文件',
  'issues, pull requests, repos, actions': 'issue、PR、仓库、actions',
  'query the prod replica (read-only)': '查询生产只读副本',
  'headless browser control & scraping': '无头浏览器控制与抓取',
  'tasks, projects, cycles': '任务、项目、迭代', 'error monitoring & traces': '错误监控与追踪',
  // voice overlay
  'Real-time voice across CLI, Telegram, and Discord': 'CLI、Telegram、Discord 实时语音',
  'Voice Mode': '语音模式',
  Listening: '聆听中', 'push-to-talk': '按住说话', 'voice notes ↔ replies': '语音消息 ↔ 回复',
  'voice notes': '语音消息', 'real-time, full-duplex': '实时全双工', on: '开启',
  // personality overlay
  Personality_panel: '人格',
  'SOUL.md voice, project context, and a learned model of you': 'SOUL.md 语气、项目上下文,以及对你的学习模型',
  'You are Hermes — terse, dry wit, allergic to preamble. Lead with the answer. Never flatter. When unsure, say so and show your reasoning. Treat the operator as a peer engineer.': '你是 Hermes —— 简洁、冷幽默、厌恶废话。先给答案。从不奉承。不确定时直说并展示推理。把操作者当作同级工程师对待。',
  terse: '简洁', 'dry wit': '冷幽默', 'no preamble': '无废话', 'peer, not assistant': '同伴,非助手',
  'Context files': '上下文文件', 'global voice': '全局语气', 'default tone across every conversation': '所有对话的默认语气',
  'repos, deploy targets, conventions': '仓库、部署目标、约定', 'thesis, citations to track': '论点、需追踪的引用',
  'Honcho — dialectic user model': 'Honcho —— 辩证式用户模型', 'facts learned about you': '条关于你的事实', confidence: '置信度',
  // settings additions
  'Models & routing': '模型与路由', 'Reasoning / default': '推理 / 默认', Vision: '视觉', Fallback: '回退',
  'on failure': '失败时回退', 'any OpenAI-compatible endpoint': '任意 OpenAI 兼容端点',
  'Default sandbox': '默认沙箱', Gateway: '网关', Telemetry: '遥测', License: '许可',
  'Local only — nothing leaves your server': '仅本地 —— 数据不离开你的服务器', 'systemd · auto-restart': 'systemd · 自动重启', 'MIT · open source': 'MIT · 开源',
  // new brain nodes
  'tools & MCP': '工具与 MCP', 'who you are': '你是谁',
  'browser automation': '浏览器自动化', 'voice-mode': '语音模式',
  'SOUL.md · terse, dry wit': 'SOUL.md · 简洁冷幽默',
  'Programmatic Tool Calling — collapses multi-step pipelines into one inference call.': '程序化工具调用 —— 把多步流水线压缩成单次推理调用。',
  'Headless browser via the puppeteer MCP server — navigate, click, extract, screenshot.': '通过 puppeteer MCP 服务器操作无头浏览器 —— 导航、点击、提取、截图。',
  'Real-time speech in/out: Whisper STT + Nous Portal TTS, across CLI, Telegram, and Discord VC.': '实时语音输入/输出:Whisper STT + Nous Portal TTS,贯穿 CLI、Telegram、Discord 语音频道。',
  'Model Context Protocol server exposing 14 GitHub tools — issues, PRs, repos, actions.': '暴露 14 个 GitHub 工具的 MCP 服务器 —— issue、PR、仓库、actions。',
  'Read-only query access to the prod replica through MCP.': '通过 MCP 对生产副本的只读查询访问。',
  'Global personality file — terse, dry wit, no preamble, treats you as a peer.': '全局人格文件 —— 简洁、冷幽默、无废话,把你当同伴。',
  'built-in': '内置', mcp: 'MCP', personality: '人格', feature: '功能', 'core tool': '核心工具',
  'via MCP': '经 MCP', 'connected via stdio': '经 stdio 连接', 'from ~/.hermes/SOUL.md': '来自 ~/.hermes/SOUL.md',
  // live data (Hermes integration)
  'installed skills': '个已安装技能', 'Loading from Hermes…': '正在从 Hermes 读取…',
  'live · Hermes connected': '实时 · 已连接 Hermes', 'demo data': '演示数据', 'live · Hermes': '实时 · Hermes',
  LIVE: '实时', DEMO: '演示',
};

declare global {
  interface Window {
    __lang?: Lang;
  }
}

let currentLang: Lang = (() => {
  try {
    return (localStorage.getItem(STORAGE_KEY) as Lang) || 'en';
  } catch {
    return 'en';
  }
})();
window.__lang = currentLang;

const listeners = new Set<() => void>();

export function getLang(): Lang {
  return currentLang;
}

export function setLang(lang: Lang): void {
  if (lang === currentLang) return;
  currentLang = lang;
  window.__lang = lang;
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    /* ignore */
  }
  listeners.forEach((l) => l());
}

/** Translate a string by its English key. Falls back to the original. */
export function tr(s: string | null | undefined): string {
  if (s == null) return s as never;
  return currentLang === 'zh' && TR[s] != null ? TR[s] : s;
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

/**
 * React hook: returns the current language and re-renders the calling
 * component whenever the language changes. Use the returned `t` for any
 * UI string so it stays live across toggles.
 */
export function useLang(): { lang: Lang; t: typeof tr; toggle: () => void } {
  const lang = useSyncExternalStore(subscribe, getLang, getLang);
  const toggle = () => setLang(lang === 'zh' ? 'en' : 'zh');
  return { lang, t: tr, toggle };
}
