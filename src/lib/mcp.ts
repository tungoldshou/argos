// mcp.ts — 拉后端真实 MCP 连接状态。失败返回空数组(诚实空态,绝不抛、不编假数据)。
import { agentBaseUrl } from './agent';

export interface McpServerLive {
  name: string;
  status: 'connected' | 'disconnected' | 'disabled';
  tools: number;
  transport: string;
  trust: string;
  desc: string;
  error?: string;
}

export async function fetchMcpServers(): Promise<McpServerLive[]> {
  try {
    const base = await agentBaseUrl();
    const res = await fetch(`${base}/mcp/servers`);
    if (!res.ok) return [];
    const body = await res.json();
    return Array.isArray(body.servers) ? body.servers : [];
  } catch {
    return [];
  }
}
