// llm.ts — model-agnostic 的 LLM 调用层。
//
// Argos 是独立通用智能体,直连模型 provider,不依赖任何外部 agent。
// 当前 provider:MiniMax(Anthropic 兼容端 /v1/messages,模型 MiniMax-M2)。
// 蜂群/agent loop 只依赖 ChatFn 抽象,不关心背后是哪家模型 —— 换 provider 只动这一层。
//
// dev 下走 vite 同源 proxy(/minimax → api.minimaxi.com/anthropic)绕过 CORS;见 vite.config.ts。
// key 经 Vite 环境变量注入(.env.local 的 VITE_MINIMAX_KEY)。

export interface ChatOpts {
  system?: string;
  maxTokens?: number;
  temperature?: number;
}

/** 注入给蜂群/agent 引擎的统一 LLM 调用签名。 */
export type ChatFn = (prompt: string, opts?: ChatOpts) => Promise<string>;

// ── MiniMax Anthropic 兼容端 ────────────────────────────────────────────────
// 完整端点 = <base>/v1/messages。dev 下 base=/minimax(vite proxy 转发到
// https://api.minimaxi.com/anthropic 并注入 CORS);Tauri/生产可改直连。
// Swarm LLM 层只说 Anthropic Messages 格式(/v1/messages)。优先读通用 VITE_LLM_*
// (与 Python agent 共用一套配置),回退旧 VITE_MINIMAX_*。注意:OpenAI 格式的 provider
// 目前蜂群层不支持(只 agent 面板支持);此处仅让 Anthropic 兼容端点的配置生效。
const LLM_BASE = (import.meta.env.VITE_LLM_BASE as string | undefined)
  ?? (import.meta.env.VITE_MINIMAX_BASE as string | undefined) ?? '/minimax';
const LLM_KEY = (import.meta.env.VITE_LLM_KEY as string | undefined)
  ?? (import.meta.env.VITE_MINIMAX_KEY as string | undefined);
const LLM_MODEL = (import.meta.env.VITE_LLM_MODEL as string | undefined)
  ?? (import.meta.env.VITE_MINIMAX_MODEL as string | undefined) ?? 'MiniMax-M2';
const ANTHROPIC_VERSION = '2023-06-01';

// Anthropic Messages API 的响应形状:content 是 block 数组,文本在 type:'text' 的 block 里。
interface AnthropicBlock {
  type: string;
  text?: string;
}
interface AnthropicResponse {
  content?: AnthropicBlock[];
}

/** 从 Anthropic content 数组里拼出纯文本。 */
function textOf(res: AnthropicResponse): string {
  return (res.content ?? [])
    .filter((b) => b.type === 'text' && typeof b.text === 'string')
    .map((b) => b.text)
    .join('');
}

/**
 * 真实实现:打到 MiniMax 的 Anthropic 兼容端。
 * Anthropic Messages 格式:system 顶层单独传,messages 只放对话轮,max_tokens 必填。
 */
async function minimaxChat(prompt: string, opts: ChatOpts = {}): Promise<string> {
  if (!LLM_KEY) {
    // 不静默回退假数据:缺 key 就明确报错,逼出真实配置。
    throw new Error(
      '未配置 LLM API key。请在设置里填写,或在 .env.local 写入 VITE_LLM_KEY。',
    );
  }
  const res = await fetch(`${LLM_BASE}/v1/messages`, {
    method: 'POST',
    headers: {
      'x-api-key': LLM_KEY,
      'anthropic-version': ANTHROPIC_VERSION,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: LLM_MODEL,
      ...(opts.system ? { system: opts.system } : {}),
      messages: [{ role: 'user', content: prompt }],
      max_tokens: opts.maxTokens ?? 900,
      temperature: opts.temperature ?? 0.3,
    }),
  });
  if (!res.ok) throw new Error(`MiniMax ${res.status}: ${await res.text().catch(() => '')}`);
  const j: AnthropicResponse = await res.json();
  return textOf(j);
}

let _chat: ChatFn | null = null;
/** 取当前环境的 LLM 调用函数。当前固定 MiniMax;将来多 provider 在此路由。 */
export function chat(): ChatFn {
  if (!_chat) _chat = minimaxChat;
  return _chat;
}
