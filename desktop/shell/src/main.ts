/**
 * Argos desktop shell — minimal walking skeleton frontend.
 *
 * This module proves the channel end-to-end:
 *   window open → connect to argosd → Hello/Welcome → subscribe to a run's
 *   SSE → render event rows honestly.
 *
 * Architecture notes (§11 + bridge rationale in lib.rs):
 *   - NO Node.js available in the WebView.  DaemonClient from @argos/sdk
 *     cannot be used directly.  Instead we use Tauri's `invoke()` IPC to
 *     call the Rust bridge commands (acp_health, acp_create_session, etc.).
 *   - Types and parse logic from @argos/sdk are REUSED here (they have zero
 *     Node imports and compile fine for the browser target).
 *   - VerdictStatus three-state: unverifiable MUST render as yellow, not green.
 *     This invariant is enforced here and is tested visually in the skeleton.
 */

import { invoke } from "@tauri-apps/api/core";
// Use vendored copies of SDK types/parse (no Node.js deps; safe in WebView).
// These are copied from desktop/sdk/src/{parse,types}.ts — re-copy on SDK breaking changes.
import { parseSSELine } from "./acp-parse.js";
import type { Envelope, ParsedEvent, VerdictStatus } from "./acp-types.js";

// ── DOM refs ─────────────────────────────────────────────────────────────────

const statusDot = document.getElementById("status-dot") as HTMLSpanElement;
const statusText = document.getElementById("status-text") as HTMLSpanElement;
const socketPathEl = document.getElementById("socket-path") as HTMLSpanElement;
const sessionIdEl = document.getElementById("session-id") as HTMLSpanElement;
const taskInput = document.getElementById("task-input") as HTMLInputElement;
const submitBtn = document.getElementById("submit-btn") as HTMLButtonElement;
const eventList = document.getElementById("event-list") as HTMLOListElement;
const clearBtn = document.getElementById("clear-btn") as HTMLButtonElement;

// ── State ─────────────────────────────────────────────────────────────────────

let currentRunId: string | null = null;
let nextSince: number = 0;
let pollIntervalId: ReturnType<typeof setInterval> | null = null;
// Track seq for gap detection (monotonically increasing per §4 design invariant).
let lastSeq: number = -1;

// ── Connection state display ──────────────────────────────────────────────────

/** Mirrors ConnState enum in state.rs — must stay in sync. */
type ConnState = "disconnected" | "probing" | "spawning" | "connected" | "failed" | "error";

function setConnState(state: ConnState, detail?: string) {
    const labels: Record<ConnState, string> = {
        disconnected: "Disconnected",
        probing: "Probing…",
        spawning: "Starting daemon…",
        connected: "Connected",
        failed: "Daemon failed",
        error: "Error",
    };
    const colors: Record<ConnState, string> = {
        disconnected: "#6b7280", // grey
        probing: "#f59e0b",      // amber
        spawning: "#f59e0b",     // amber — honest intermediate state, not green
        connected: "#22c55e",    // green
        failed: "#ef4444",       // red — never show connected if spawn failed
        error: "#ef4444",        // red
    };
    statusDot.style.background = colors[state];
    statusText.textContent = detail ? `${labels[state]}: ${detail}` : labels[state];
}

// ── Event row rendering ──────────────────────────────────────────────────────

/**
 * Map VerdictStatus to colour. INVARIANT: unverifiable → yellow, never green.
 * This is the UI enforcement of the SDK + protocol invariant.
 */
function verdictColor(status: VerdictStatus): string {
    if (status === "passed") return "#22c55e";        // green
    if (status === "failed") return "#ef4444";        // red
    if (status === "unverifiable") return "#f59e0b";  // amber — NEVER green
    return "#6b7280";
}

function buildEventRow(
    envelope: Envelope,
    _event: ParsedEvent,
    rawJson: string,
): HTMLLIElement {
    const li = document.createElement("li");
    li.className = "event-row";

    // Seq gap warning
    const seqGap = envelope.seq > lastSeq + 1 && lastSeq >= 0;
    if (seqGap) {
        li.classList.add("seq-gap");
    }
    lastSeq = envelope.seq;

    // Kind badge
    const kindEl = document.createElement("span");
    kindEl.className = "event-kind";
    kindEl.textContent = envelope.kind;

    // Seq number
    const seqEl = document.createElement("span");
    seqEl.className = "event-seq";
    seqEl.textContent = `#${envelope.seq}`;
    if (seqGap) seqEl.title = "WARNING: seq gap detected — frames may have been dropped";

    // Run id (short)
    const runEl = document.createElement("span");
    runEl.className = "event-run";
    runEl.textContent = envelope.run ? envelope.run.slice(0, 8) : "(session)";

    // Key-field summary
    const summaryEl = document.createElement("span");
    summaryEl.className = "event-summary";
    summaryEl.textContent = buildSummary(envelope, _event);

    // Verdict colouring for verify_verdict rows
    if (envelope.kind === "verify_verdict") {
        const ev = _event as { kind: "verify_verdict"; verdict?: { status?: VerdictStatus } };
        const status = ev.verdict?.status;
        if (status) {
            li.style.borderLeftColor = verdictColor(status);
            li.style.borderLeftWidth = "3px";
            li.style.borderLeftStyle = "solid";
            kindEl.style.color = verdictColor(status);
        }
    }

    // Detail toggle
    const toggle = document.createElement("button");
    toggle.className = "detail-toggle";
    toggle.textContent = "▶";
    const detailEl = document.createElement("pre");
    detailEl.className = "event-detail hidden";
    try {
        detailEl.textContent = JSON.stringify(JSON.parse(rawJson), null, 2);
    } catch {
        detailEl.textContent = rawJson;
    }
    toggle.onclick = () => {
        const hidden = detailEl.classList.toggle("hidden");
        toggle.textContent = hidden ? "▶" : "▼";
    };

    li.append(seqEl, kindEl, runEl, summaryEl, toggle, detailEl);
    return li;
}

/**
 * Build a one-line human summary for the most important fields of an event.
 * This is a best-effort display — the raw JSON is always available via toggle.
 */
function buildSummary(envelope: Envelope, event: ParsedEvent): string {
    const data = envelope.data as Record<string, unknown>;
    switch (envelope.kind) {
        case "token_delta": {
            const text = data["text"] as string | undefined;
            return text ? text.slice(0, 80) + (text.length > 80 ? "…" : "") : "";
        }
        case "phase_change":
            return `phase=${data["phase"] ?? "?"}`;
        case "verify_verdict": {
            const v = data["verdict"] as Record<string, unknown> | undefined;
            return v ? `status=${v["status"]} detail=${String(v["detail"] ?? "").slice(0, 60)}` : "";
        }
        case "cost_update": {
            const total = data["cost_usd"] as number | undefined | null;
            return total !== undefined && total !== null ? `$${total.toFixed(4)}` : "$(N/A)";
        }
        case "approval_request":
            return `call_id=${data["call_id"] ?? "?"} action=${data["action"] ?? "?"}`;
        case "error": {
            const msg = data["message"] as string | undefined;
            return msg ? msg.slice(0, 100) : "";
        }
        case "plan_update": {
            const todos = data["todos"] as Array<Record<string, unknown>> | undefined;
            return todos ? `${todos.length} todo(s)` : "";
        }
        case "ledger_entry":
            return `${data["action"] ?? "?"} reversible=${data["reversible"] ?? "?"}`;
        case "proactive_suggestion": {
            const goal = data["goal"] as string | undefined;
            const reason = data["reason_human"] as string | undefined;
            return goal ? goal.slice(0, 60) : (reason ? reason.slice(0, 60) : "");
        }
        default:
            return "";
    }
    // unreachable — TypeScript doesn't know this is exhaustive for ParsedEvent
    return "";
}

function appendEvent(envelope: Envelope, event: ParsedEvent, rawJson: string) {
    const li = buildEventRow(envelope, event, rawJson);
    eventList.appendChild(li);
    // Auto-scroll to bottom
    eventList.scrollTop = eventList.scrollHeight;
}

function appendSystemMessage(text: string, cls: "info" | "warn" | "err" = "info") {
    const li = document.createElement("li");
    li.className = `system-msg ${cls}`;
    li.textContent = text;
    eventList.appendChild(li);
    eventList.scrollTop = eventList.scrollHeight;
}

// ── Startup: probe → (spawn) → Hello/Welcome ─────────────────────────────────

async function initConnection() {
    // Show socket path first (purely informational)
    const socketPath = await invoke<string>("acp_socket_path").catch(() => "unknown");
    socketPathEl.textContent = socketPath;

    setConnState("probing");
    appendSystemMessage(`[boot] Probing daemon at ${socketPath}…`, "info");

    // acp_spawn_daemon drives the full state machine:
    //   probing → connected (daemon already up)
    //   probing → spawning → connected (daemon spawned successfully)
    //   probing → spawning → failed (spawn or socket-poll timed out)
    //
    // We poll conn_state while waiting so the status bar updates honestly.
    const pollId = setInterval(async () => {
        try {
            const cs = await invoke<{ state: string; detail: string }>("acp_conn_state");
            setConnState(cs.state as ConnState, cs.detail || undefined);
        } catch {
            // ignore poll errors
        }
    }, 400);

    const spawnResult = await invoke<{ state: string; detail: string }>(
        "acp_spawn_daemon"
    ).catch((e: unknown) => {
        const msg = e instanceof Error ? e.message : JSON.stringify(e);
        return { state: "failed", detail: msg };
    });

    clearInterval(pollId);
    setConnState(spawnResult.state as ConnState, spawnResult.detail || undefined);

    if (spawnResult.state !== "connected") {
        appendSystemMessage(
            `[error] Daemon not reachable. ${spawnResult.detail || ""}. ` +
            "Manual start: uv run argos --with-daemon",
            "err",
        );
        return;
    }

    appendSystemMessage(`[ok] Daemon reachable at ${socketPath}`, "info");

    // Create session (Hello → Welcome)
    const session = await invoke<{ session_id?: string }>("acp_create_session").catch(
        (e: unknown) => {
            const msg = e instanceof Error ? e.message : String(e);
            setConnState("error", "session creation failed — " + msg.slice(0, 80));
            return null;
        },
    );
    if (!session?.session_id) {
        setConnState("error", "no session_id in response");
        return;
    }

    sessionIdEl.textContent = session.session_id.slice(0, 12) + "…";
    setConnState("connected");
    appendSystemMessage(`[ok] Connected. Session: ${session.session_id.slice(0, 8)}… — daemon at ${socketPath}`, "info");
    submitBtn.disabled = false;
}

// ── Run creation & SSE poll ───────────────────────────────────────────────────

async function startRun(task: string) {
    submitBtn.disabled = true;
    taskInput.disabled = true;
    stopPoll();
    nextSince = 0;
    lastSeq = -1;

    appendSystemMessage(`[run] Creating run: "${task.slice(0, 80)}"…`, "info");

    const run = await invoke<{ run_id?: string }>("acp_create_run", { task }).catch(
        (e: unknown) => {
            const msg = e instanceof Error ? e.message : String(e);
            appendSystemMessage(`[error] create_run failed: ${msg}`, "err");
            submitBtn.disabled = false;
            taskInput.disabled = false;
            return null;
        },
    );
    if (!run?.run_id) {
        submitBtn.disabled = false;
        taskInput.disabled = false;
        return;
    }

    currentRunId = run.run_id;
    appendSystemMessage(`[run] run_id=${currentRunId} — polling events…`, "info");
    startPoll(currentRunId);
}

function startPoll(runId: string) {
    if (pollIntervalId !== null) clearInterval(pollIntervalId);
    pollIntervalId = setInterval(() => pollEvents(runId), 2000);
    // Immediate first poll
    pollEvents(runId);
}

function stopPoll() {
    if (pollIntervalId !== null) {
        clearInterval(pollIntervalId);
        pollIntervalId = null;
    }
}

async function pollEvents(runId: string) {
    const rawLines = await invoke<string[]>("acp_events_poll", {
        runId,
        since: nextSince,
        maxEvents: 50,
    }).catch((e: unknown) => {
        console.warn("poll error", e);
        return [] as string[];
    });

    for (const rawLine of rawLines) {
        const parsed = parseSSELine(rawLine);
        if (!parsed) continue;
        const { envelope, event } = parsed;
        appendEvent(envelope, event, rawLine);

        // Advance cursor
        if (envelope.seq >= nextSince) {
            nextSince = envelope.seq + 1;
        }

        // Stop polling on terminal events
        if (
            envelope.kind === "verify_verdict" ||
            envelope.kind === "error" ||
            (envelope.kind === "phase_change" &&
                (envelope.data as Record<string, unknown>)["phase"] === "report")
        ) {
            stopPoll();
            submitBtn.disabled = false;
            taskInput.disabled = false;
            appendSystemMessage("[done] Run completed. Ready for next task.", "info");
        }
    }
}

// ── UI event handlers ─────────────────────────────────────────────────────────

submitBtn.addEventListener("click", () => {
    const task = taskInput.value.trim();
    if (!task) return;
    startRun(task);
});

taskInput.addEventListener("keydown", (e: KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey && !submitBtn.disabled) {
        e.preventDefault();
        submitBtn.click();
    }
});

clearBtn.addEventListener("click", () => {
    eventList.innerHTML = "";
    lastSeq = -1;
    nextSince = 0;
});

// ── Boot ──────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
    submitBtn.disabled = true;
    initConnection();
});
