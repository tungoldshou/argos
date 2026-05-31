// llm.ts — model-agnostic 的 LLM 调用层。
//
// 蜂群引擎(engine/swarm.ts)只依赖这个 ChatFn 抽象,不关心背后是哪家模型。
// Tauri 下走 hermes_post → /v1/chat/completions;浏览器下直连 8642。
// 两者都打真实模型(Hermes 已接 OpenRouter/Gemini/GLM/Kimi/MiniMax),不再有 mock 假数据。
//
// 这是「站在 Hermes 之上、复用其模型层」的接缝:Argos 不自己接模型,
// 借 Hermes 已有的 provider 路由。

export interface ChatOpts {
  system?: string;
  maxTokens?: number;
  temperature?: number;
}

/** 注入给蜂群引擎的统一 LLM 调用签名。 */
export type ChatFn = (prompt: string, opts?: ChatOpts) => Promise<string>;

function isTauri(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

interface ChatChoice {
  message?: { content?: string };
}
interface ChatResponse {
  choices?: ChatChoice[];
}

/** 真实实现:经 hermes 桥打到本地 Hermes 的 OpenAI 兼容端点。 */
async function tauriChat(prompt: string, opts: ChatOpts = {}): Promise<string> {
  const core = await import('@tauri-apps/api/core');
  const messages = [
    ...(opts.system ? [{ role: 'system', content: opts.system }] : []),
    { role: 'user', content: prompt },
  ];
  const res = await core.invoke<ChatResponse>('hermes_post', {
    path: '/v1/chat/completions',
    body: {
      messages,
      max_tokens: opts.maxTokens ?? 900,
      temperature: opts.temperature ?? 0.3,
    },
  });
  return res.choices?.[0]?.message?.content ?? '';
}

// 浏览器(非 Tauri)实现:直连本地 Hermes 的 OpenAI 兼容端点。
// 不再用 mock 假数据 —— 蜂群一律走真实模型(Hermes 已接 OpenRouter/Gemini/GLM/Kimi/MiniMax)。
// dev 下 key/url 经 Vite 环境变量注入(.env.local 的 VITE_HERMES_KEY / VITE_HERMES_URL)。
// dev 下走 vite 同源 proxy(/hermes → 8642)绕过 CORS;见 vite.config.ts。
const HERMES_BASE = '/hermes';
const HERMES_KEY = import.meta.env.VITE_HERMES_KEY as string | undefined;

async function browserChat(prompt: string, opts: ChatOpts = {}): Promise<string> {
  if (!HERMES_KEY) {
    // 不静默回退假数据:缺 key 就明确报错,逼出真实配置(这是「不用 mock」的本质)。
    throw new Error(
      '未配置 Hermes API key。请在 .env.local 写入 VITE_HERMES_KEY(从 ~/.hermes/.argos_api_key 取),' +
        '或在 Tauri 桌面端运行(走 hermes_post 桥)。',
    );
  }
  const messages = [
    ...(opts.system ? [{ role: 'system', content: opts.system }] : []),
    { role: 'user', content: prompt },
  ];
  const res = await fetch(`${HERMES_BASE}/v1/chat/completions`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${HERMES_KEY}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, max_tokens: opts.maxTokens ?? 900, temperature: opts.temperature ?? 0.3 }),
  });
  if (!res.ok) throw new Error(`Hermes ${res.status}: ${await res.text().catch(() => '')}`);
  const j: ChatResponse = await res.json();
  return j.choices?.[0]?.message?.content ?? '';
}

let _chat: ChatFn | null = null;
/** 取当前环境的 LLM 调用函数:Tauri 走 hermes_post 桥,浏览器直连 8642。两者都打真实模型。 */
export function chat(): ChatFn {
  if (!_chat) _chat = isTauri() ? tauriChat : browserChat;
  return _chat;
}
