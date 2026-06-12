/**
 * DaemonClient — minimal ACP HTTP/1.1 client over Unix domain socket.
 *
 * Mirrors daemon/server.py endpoint surface exactly.  Zero runtime deps
 * (uses Node built-in `net` module only).
 *
 * Connection model:
 *   - Each HTTP call opens a new Unix socket connection and closes it on
 *     response end (HTTP/1.1 Connection: close — matching server.py).
 *   - subscribeEvents opens a persistent connection for SSE streaming and
 *     emits ParsedEvent objects via callback until the connection closes.
 *
 * Session management:
 *   - Call createSession() once to obtain a session_id.
 *   - Pass the session_id to every subsequent call; the client stores it
 *     and sends it as the "X-Argos-Session" header automatically.
 */

import * as net from "net";
import type {
  Envelope,
  ParsedEvent,
  CreateRunRequest,
  CreateRunResponse,
  CreateSessionResponse,
  ApprovalBody,
  PlanDecisionBody,
  IntentConfirmBody,
} from "./types.js";
import { parseEnvelope, parseEvent } from "./parse.js";

export const SESSION_HEADER = "X-Argos-Session";

// ── Low-level HTTP/1.1 over Unix socket ──────────────────────────────────────

interface RawResponse {
  status: number;
  headers: Record<string, string>;
  body: string;
}

function buildRequest(
  method: string,
  path: string,
  sessionId: string | undefined,
  body?: string,
): string {
  const lines: string[] = [];
  lines.push(`${method} ${path} HTTP/1.1`);
  lines.push("Host: localhost");
  lines.push("Accept: application/json");
  if (sessionId) lines.push(`${SESSION_HEADER}: ${sessionId}`);
  if (body !== undefined) {
    const buf = Buffer.from(body, "utf-8");
    lines.push("Content-Type: application/json");
    lines.push(`Content-Length: ${buf.length}`);
  } else {
    lines.push("Content-Length: 0");
  }
  lines.push("Connection: close");
  lines.push("");
  lines.push(body ?? "");
  return lines.join("\r\n");
}

function doRequest(
  socketPath: string,
  method: string,
  path: string,
  sessionId: string | undefined,
  bodyObj?: unknown,
): Promise<RawResponse> {
  return new Promise((resolve, reject) => {
    const bodyStr = bodyObj !== undefined ? JSON.stringify(bodyObj) : undefined;
    const raw = buildRequest(method, path, sessionId, bodyStr);

    const socket = net.createConnection({ path: socketPath });
    let data = "";
    let timedOut = false;

    const timer = setTimeout(() => {
      timedOut = true;
      socket.destroy(new Error("request timeout"));
    }, 30_000);

    socket.on("connect", () => {
      socket.write(raw, "utf-8");
    });

    socket.on("data", (chunk) => {
      data += chunk.toString("utf-8");
    });

    socket.on("end", () => {
      clearTimeout(timer);
      if (timedOut) return;
      // Parse HTTP/1.1 response
      const sep = data.indexOf("\r\n\r\n");
      if (sep === -1) {
        return reject(new Error("malformed HTTP response: no header/body separator"));
      }
      const headerSection = data.slice(0, sep);
      const bodyPart = data.slice(sep + 4);
      const headerLines = headerSection.split("\r\n");
      const statusLine = headerLines[0] ?? "";
      const match = statusLine.match(/HTTP\/1\.1 (\d+)/);
      if (!match) {
        return reject(new Error(`unparseable status line: ${statusLine}`));
      }
      const status = parseInt(match[1]!, 10);
      const headers: Record<string, string> = {};
      for (const hl of headerLines.slice(1)) {
        const ci = hl.indexOf(":");
        if (ci === -1) continue;
        const k = hl.slice(0, ci).trim().toLowerCase();
        const v = hl.slice(ci + 1).trim();
        headers[k] = v;
      }
      resolve({ status, headers, body: bodyPart });
    });

    socket.on("error", (err) => {
      clearTimeout(timer);
      reject(err);
    });
  });
}

async function jsonRequest<T>(
  socketPath: string,
  method: string,
  path: string,
  sessionId: string | undefined,
  bodyObj?: unknown,
): Promise<T> {
  const resp = await doRequest(socketPath, method, path, sessionId, bodyObj);
  let parsed: unknown;
  try {
    parsed = JSON.parse(resp.body);
  } catch {
    throw new Error(`non-JSON response (status ${resp.status}): ${resp.body.slice(0, 200)}`);
  }
  if (resp.status >= 400) {
    const err = parsed as Record<string, unknown>;
    throw Object.assign(
      new Error(String(err["error"] ?? resp.body)),
      { status: resp.status, code: err["code"] },
    );
  }
  return parsed as T;
}

// ── SSE streaming ─────────────────────────────────────────────────────────────

export interface SSESubscription {
  /** Tear down the SSE connection. */
  close(): void;
}

/**
 * Subscribe to the SSE event stream for a run.
 *
 * @param socketPath   Unix socket path (e.g. /tmp/argosd.sock)
 * @param runId        Run to subscribe to
 * @param sessionId    Active session_id (required — daemon enforces it)
 * @param since        Resume from this seq (default 0 = full replay)
 * @param onEvent      Called for each parsed event
 * @param onError      Called on connection error or parse failure
 * @param onEnd        Called when the server closes the stream
 */
function subscribeSSE(
  socketPath: string,
  runId: string,
  sessionId: string,
  since: number,
  onEvent: (ev: ParsedEvent, envelope: Envelope) => void,
  onError: (err: Error) => void,
  onEnd: () => void,
): SSESubscription {
  const path = `/runs/${runId}/events?since=${since}`;
  const raw = buildRequest("GET", path, sessionId, undefined);

  const socket = net.createConnection({ path: socketPath });
  let headersDone = false;
  let buf = "";
  let closed = false;

  function close() {
    if (closed) return;
    closed = true;
    try { socket.destroy(); } catch { /* ignore */ }
  }

  socket.on("connect", () => {
    socket.write(raw, "utf-8");
  });

  socket.on("data", (chunk: Buffer) => {
    buf += chunk.toString("utf-8");
    // Skip HTTP response headers first time
    if (!headersDone) {
      const sep = buf.indexOf("\r\n\r\n");
      if (sep === -1) return;
      headersDone = true;
      buf = buf.slice(sep + 4);
    }
    // Parse SSE lines
    let nl: number;
    while ((nl = buf.indexOf("\n")) !== -1) {
      const line = buf.slice(0, nl).replace(/\r$/, "");
      buf = buf.slice(nl + 1);
      if (line.startsWith("data: ")) {
        const jsonStr = line.slice(6);
        const envelope = parseEnvelope(jsonStr);
        if (envelope === null) continue; // keepalive or malformed
        const event = parseEvent(envelope.kind, envelope.data);
        try {
          onEvent(event, envelope);
        } catch (handlerErr) {
          onError(handlerErr instanceof Error ? handlerErr : new Error(String(handlerErr)));
        }
      }
      // Ignore "event:", "id:", ": keepalive" lines
    }
  });

  socket.on("end", () => {
    closed = true;
    onEnd();
  });

  socket.on("error", (err) => {
    if (!closed) {
      closed = true;
      onError(err);
    }
  });

  return { close };
}

// ── DaemonClient ─────────────────────────────────────────────────────────────

export interface DaemonClientOptions {
  /** Path to the Unix domain socket. Defaults to /tmp/argosd.sock */
  socketPath?: string;
}

export class DaemonClient {
  private readonly socketPath: string;
  private sessionId: string | undefined;

  constructor(options: DaemonClientOptions = {}) {
    this.socketPath = options.socketPath ?? "/tmp/argosd.sock";
  }

  /** Current active session id (undefined until createSession is called). */
  get currentSessionId(): string | undefined {
    return this.sessionId;
  }

  // ── Session ───────────────────────────────────────────────────────

  /**
   * POST /sessions — create a new session.
   * Stores the returned session_id for subsequent calls.
   *
   * Mirrors server.py _handle_create_session line ~317.
   */
  async createSession(): Promise<string> {
    const resp = await jsonRequest<CreateSessionResponse>(
      this.socketPath, "POST", "/sessions", undefined,
    );
    this.sessionId = resp.session_id;
    return resp.session_id;
  }

  /**
   * POST /sessions/{id}/heartbeat — keep the session alive.
   * Mirrors server.py _handle_heartbeat line ~321.
   */
  async heartbeat(sessionId?: string): Promise<{ active_tuis: number }> {
    const sid = sessionId ?? this.sessionId;
    if (!sid) throw new Error("no active session — call createSession() first");
    return jsonRequest(this.socketPath, "POST", `/sessions/${sid}/heartbeat`, sid);
  }

  /**
   * DELETE /sessions/{id} — close the session.
   * Mirrors server.py _handle_delete_session line ~329.
   */
  async deleteSession(sessionId?: string): Promise<{ ok: boolean; promoted_to: string | null }> {
    const sid = sessionId ?? this.sessionId;
    if (!sid) throw new Error("no active session");
    if (sid === this.sessionId) this.sessionId = undefined;
    return jsonRequest(this.socketPath, "DELETE", `/sessions/${sid}`, sid);
  }

  // ── Health ────────────────────────────────────────────────────────

  /**
   * GET /health
   * Mirrors server.py _handle_health line ~305.
   */
  async health(): Promise<{ status: string; uptime_s: number; other_tuis: number }> {
    return jsonRequest(this.socketPath, "GET", "/health", this.sessionId);
  }

  // ── Runs ──────────────────────────────────────────────────────────

  /**
   * GET /runs — list runs (optionally filtered by state).
   * Mirrors server.py _handle_list_runs line ~336.
   */
  async listRuns(state?: string): Promise<unknown[]> {
    const qs = state ? `?state=${encodeURIComponent(state)}` : "";
    return jsonRequest(this.socketPath, "GET", `/runs${qs}`, this.sessionId);
  }

  /**
   * POST /runs — create and start a new run.
   * Mirrors server.py _handle_create_run line ~354.
   *
   * Requires an owner session (createSession must have been called).
   */
  async createRun(req: CreateRunRequest): Promise<CreateRunResponse> {
    if (!this.sessionId) throw new Error("no active session — call createSession() first");
    return jsonRequest(this.socketPath, "POST", "/runs", this.sessionId, req);
  }

  /**
   * GET /runs/{id} — get run metadata.
   * Mirrors server.py _handle_get_run line ~547.
   */
  async getRun(runId: string): Promise<unknown> {
    return jsonRequest(this.socketPath, "GET", `/runs/${runId}`, this.sessionId);
  }

  /**
   * GET /runs/{id}/events — SSE event stream with since-based resumption.
   * Mirrors server.py _handle_sse line ~1292.
   *
   * @param runId    Run id to subscribe to
   * @param since    Resume from this seq number (default 0)
   * @param onEvent  Called for each parsed event
   * @param onError  Called on error
   * @param onEnd    Called when stream ends
   */
  subscribeEvents(
    runId: string,
    since: number,
    onEvent: (ev: ParsedEvent, envelope: Envelope) => void,
    onError: (err: Error) => void,
    onEnd: () => void,
  ): SSESubscription {
    if (!this.sessionId) throw new Error("no active session — call createSession() first");
    return subscribeSSE(
      this.socketPath, runId, this.sessionId, since, onEvent, onError, onEnd,
    );
  }

  // ── Run control ───────────────────────────────────────────────────

  /**
   * POST /runs/{id}/pause
   * Mirrors server.py _handle_pause line ~571.
   */
  async pause(runId: string): Promise<{ state: string }> {
    return jsonRequest(this.socketPath, "POST", `/runs/${runId}/pause`, this.sessionId);
  }

  /**
   * POST /runs/{id}/resume
   * Mirrors server.py _handle_resume line ~579.
   */
  async resume(runId: string): Promise<{ state: string }> {
    return jsonRequest(this.socketPath, "POST", `/runs/${runId}/resume`, this.sessionId);
  }

  /**
   * POST /runs/{id}/cancel
   * Mirrors server.py _handle_cancel line ~587.
   */
  async cancel(runId: string): Promise<{ state: string }> {
    return jsonRequest(this.socketPath, "POST", `/runs/${runId}/cancel`, this.sessionId);
  }

  // ── Approval ──────────────────────────────────────────────────────

  /**
   * POST /runs/{id}/approval/{call_id} — respond to an ApprovalRequest.
   * Mirrors server.py _handle_approval line ~612.
   *
   * INVARIANT: Only valid decisions are "deny" | "once" | "session" | "always".
   * The SDK does not accept any other string.
   */
  async approve(
    runId: string,
    callId: string,
    body: ApprovalBody,
  ): Promise<{ call_id: string; decision: string; state: string }> {
    return jsonRequest(
      this.socketPath, "POST", `/runs/${runId}/approval/${callId}`,
      this.sessionId, body,
    );
  }

  // ── Plan decision ─────────────────────────────────────────────────

  /**
   * POST /runs/{id}/plan_decision — respond to a PlanDecisionRequest.
   * Mirrors server.py _handle_plan_decision line ~698.
   */
  async planDecision(
    runId: string,
    body: PlanDecisionBody,
  ): Promise<{ call_id: string; action: string; state: string }> {
    return jsonRequest(
      this.socketPath, "POST", `/runs/${runId}/plan_decision`,
      this.sessionId, body,
    );
  }

  // ── Intent confirm ────────────────────────────────────────────────

  /**
   * POST /runs/{id}/intent_confirm — respond to an IntentConfirmRequest (P4 §7).
   * Mirrors server.py _handle_intent_confirm line ~798.
   */
  async intentConfirm(
    runId: string,
    body: IntentConfirmBody,
  ): Promise<{ call_id: string; confirmed: boolean; state: string }> {
    return jsonRequest(
      this.socketPath, "POST", `/runs/${runId}/intent_confirm`,
      this.sessionId, body,
    );
  }

  // ── Ledger ────────────────────────────────────────────────────────

  /**
   * GET /runs/{id}/ledger — fetch the human-readable ledger for a run.
   * Mirrors server.py _handle_get_ledger line ~882.
   */
  async getLedger(runId: string): Promise<{ run_id: string; entries: unknown[] }> {
    return jsonRequest(this.socketPath, "GET", `/runs/${runId}/ledger`, this.sessionId);
  }
}
