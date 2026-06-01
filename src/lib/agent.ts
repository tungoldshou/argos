// agent.ts — 前端与 Python agent 服务(FastAPI+LangGraph)的客户端。
//
// Argos 的智能在 Python 服务里(agent loop + verify + 护城河)。前端只负责:
// 发起 goal、消费 SSE 事件流、把每一步渲染到 UI。
//
// 地址来源:Tauri 下问后端 agent_base_url();纯浏览器 dev 直连约定端口。

const DEFAULT_BASE = 'http://127.0.0.1:8848';

export function isTauri(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

/** app 设置(key 只回是否已配置 + 后四位,不回明文)。仅 Tauri 下有效。 */
export interface AppSettings {
  key_configured: boolean;
  key_tail: string;
  provider: string; // anthropic | openai
  base: string;
  model: string;
}

/** 读 app 设置(MiniMax key 配置状态)。非 Tauri(纯浏览器)→ null。 */
export async function getSettings(): Promise<AppSettings | null> {
  if (!isTauri()) return null;
  try {
    const core = await import('@tauri-apps/api/core');
    return await core.invoke<AppSettings>('get_settings');
  } catch {
    return null;
  }
}

/** 写 LLM 配置(provider/base/model/key)。持久化到用户配置目录,配合 restartAgent 生效。 */
export async function setLlmConfig(cfg: { provider: string; base: string; model: string; key: string }): Promise<boolean> {
  if (!isTauri()) return false;
  try {
    const core = await import('@tauri-apps/api/core');
    await core.invoke('set_llm_config', { provider: cfg.provider, base: cfg.base, model: cfg.model, key: cfg.key });
    return true;
  } catch {
    return false;
  }
}

/** 重启 agent sidecar(杀旧+重拉,读最新 key)。填 key 后调它即可生效,无需退出整个 app。 */
export async function restartAgent(): Promise<boolean> {
  if (!isTauri()) return false;
  try {
    const core = await import('@tauri-apps/api/core');
    await core.invoke('restart_agent');
    return true;
  } catch {
    return false;
  }
}

/** agent 服务地址:Tauri 走后端命令(它拉起的服务),浏览器用默认端口。 */
export async function agentBaseUrl(): Promise<string> {
  if (isTauri()) {
    try {
      const core = await import('@tauri-apps/api/core');
      return await core.invoke<string>('agent_base_url');
    } catch {
      return DEFAULT_BASE;
    }
  }
  return DEFAULT_BASE;
}

/** 一个规范化的 agent 运行事件。 */
export interface AgentEvent {
  type:
    | 'session'
    | 'start'
    | 'token' // 增量文本流式事件:chatReducer 把它累成 streaming text block
    | 'tool_call'
    | 'tool_result'
    | 'message'
    | 'verify_failed' // verify 硬门禁拦截了一次"假完成",把真实失败 bounce 回去
    | 'escalation' // 反复修仍不过 → agent 诚实升级求助人类
    | 'tampering' // project 模式:agent 改动了被保护的测试文件(篡改可见,诚实警告)
    | 'done'
    | 'error';
  data: Record<string, unknown>;
}

/** agent 服务是否就绪(健康检查)。 */
export async function agentHealth(): Promise<{ ok: boolean; model?: string; keyConfigured?: boolean }> {
  try {
    const base = await agentBaseUrl();
    const r = await fetch(`${base}/health`);
    if (!r.ok) return { ok: false };
    const j = await r.json();
    return { ok: !!j.ok, model: j.model, keyConfigured: j.key_configured };
  } catch {
    return { ok: false };
  }
}

/** 一条任务记忆(来自 /memory)。 */
export interface MemoryRecord {
  id: string;
  goal: string;
  verdict?: string | null;
  model?: string | null;
  fact?: string | null;
  ts?: number | null;
}

/** 拉 Argos 自己跑过的任务记忆(真实、随任务生长)。失败/无记忆 → 空数组(诚实空态)。 */
export async function agentMemory(): Promise<MemoryRecord[]> {
  try {
    const base = await agentBaseUrl();
    const r = await fetch(`${base}/memory`);
    if (!r.ok) return [];
    const j = await r.json();
    return Array.isArray(j.records) ? j.records : [];
  } catch {
    return [];
  }
}

/**
 * 跑一个 goal,逐事件回调。返回一个 abort 函数可中断。
 * SSE 解析:按 `event:`/`data:` 帧切分,每帧一个 AgentEvent。
 */
export interface RunOptions {
  /** 可选:可机检的验证命令(白名单内,如 "python3 check.py")。给了就启用 verify 硬门禁。 */
  verifyCmd?: string;
  /** 可选:用户自己的项目目录。给了就让 agent 在该项目里干活、跑该项目自己的测试。 */
  projectDir?: string;
  /** 可选:要监控篡改的文件(通常是测试文件)。agent 改了 run 结束会警告。 */
  guardFiles?: string[];
  /** 多轮会话 id。首轮不传,从 'session' 事件取得后,后续轮带上以延续上下文。 */
  sessionId?: string;
}

export function runAgent(
  goal: string,
  onEvent: (e: AgentEvent) => void,
  onDone: (err?: string) => void,
  opts: RunOptions = {},
): () => void {
  const ctrl = new AbortController();

  (async () => {
    const base = await agentBaseUrl();
    let res: Response;
    try {
      res = await fetch(`${base}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          goal,
          session_id: opts.sessionId || null,
          verify_cmd: opts.verifyCmd || null,
          project_dir: opts.projectDir || null,
          guard_files: opts.guardFiles || null,
        }),
        signal: ctrl.signal,
      });
    } catch (e) {
      // 主动中止(组件卸载 / 用户点停止)不是错误,静默收尾,不打红字。
      if (ctrl.signal.aborted) { onDone(); return; }
      onDone(`无法连接 agent 服务(${String(e)})。确认 Python 服务已启动。`);
      return;
    }
    if (!res.ok || !res.body) {
      onDone(`agent 服务返回 ${res.status}`);
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        // SSE 帧以空行分隔
        let idx: number;
        while ((idx = buf.indexOf('\n\n')) !== -1) {
          const frame = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          const ev = parseFrame(frame);
          if (ev) {
            onEvent(ev);
            if (ev.type === 'done') { onDone(); return; }
            if (ev.type === 'error') { onDone(String(ev.data.message ?? 'agent error')); return; }
          }
        }
      }
      onDone();
    } catch (e) {
      if (!ctrl.signal.aborted) onDone(String(e));
    }
  })();

  return () => ctrl.abort();
}

function parseFrame(frame: string): AgentEvent | null {
  let type = '';
  let dataRaw = '';
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) type = line.slice(6).trim();
    else if (line.startsWith('data:')) dataRaw += line.slice(5).trim();
  }
  if (!type) return null;
  let data: Record<string, unknown> = {};
  try { data = dataRaw ? JSON.parse(dataRaw) : {}; } catch { data = { raw: dataRaw }; }
  return { type: type as AgentEvent['type'], data };
}
