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
// 零打包器约束:webview 的 ESM 解析不了裸说明符 "@tauri-apps/api/core",
// 走 tauri.conf withGlobalTauri=true 注入的 window.__TAURI__ 全局(实测 bug 修复:
// 此前 index.html 引用从未构建的 ../dist/main.js,前端 JS 从未执行过)。
const invoke = window.__TAURI__.core.invoke;
// Use vendored copies of SDK types/parse (no Node.js deps; safe in WebView).
// These are copied from desktop/sdk/src/{parse,types}.ts — re-copy on SDK breaking changes.
import { parseSSELine } from "./acp-parse.js";
// ── DOM refs ─────────────────────────────────────────────────────────────────
const statusDot = document.getElementById("status-dot");
const statusText = document.getElementById("status-text");
const socketPathEl = document.getElementById("socket-path");
const sessionIdEl = document.getElementById("session-id");
const taskInput = document.getElementById("task-input");
const submitBtn = document.getElementById("submit-btn");
const eventList = document.getElementById("event-list");
const clearBtn = document.getElementById("clear-btn");
// ── State ─────────────────────────────────────────────────────────────────────
let currentRunId = null;
let nextSince = 0;
let pollIntervalId = null;
// Track seq for gap detection (monotonically increasing per §4 design invariant).
let lastSeq = -1;
function setConnState(state, detail) {
    const labels = {
        disconnected: "Disconnected",
        probing: "Probing…",
        spawning: "Starting daemon…",
        connected: "Connected",
        failed: "Daemon failed",
        error: "Error",
    };
    const colors = {
        disconnected: "#6b7280", // grey
        probing: "#f59e0b", // amber
        spawning: "#f59e0b", // amber — honest intermediate state, not green
        connected: "#22c55e", // green
        failed: "#ef4444", // red — never show connected if spawn failed
        error: "#ef4444", // red
    };
    statusDot.style.background = colors[state];
    statusText.textContent = detail ? `${labels[state]}: ${detail}` : labels[state];
}
// ── Event row rendering ──────────────────────────────────────────────────────
/**
 * Map VerdictStatus to colour. INVARIANT: unverifiable → yellow, never green.
 * This is the UI enforcement of the SDK + protocol invariant.
 */
function verdictColor(status) {
    if (status === "passed")
        return "#22c55e"; // green
    if (status === "failed")
        return "#ef4444"; // red
    if (status === "unverifiable")
        return "#f59e0b"; // amber — NEVER green
    return "#6b7280";
}
function buildEventRow(envelope, _event, rawJson) {
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
    if (seqGap)
        seqEl.title = "WARNING: seq gap detected — frames may have been dropped";
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
        const ev = _event;
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
    }
    catch {
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
function buildSummary(envelope, event) {
    const data = envelope.data;
    switch (envelope.kind) {
        case "token_delta": {
            const text = data["text"];
            return text ? text.slice(0, 80) + (text.length > 80 ? "…" : "") : "";
        }
        case "phase_change":
            return `phase=${data["phase"] ?? "?"}`;
        case "verify_verdict": {
            const v = data["verdict"];
            return v ? `status=${v["status"]} detail=${String(v["detail"] ?? "").slice(0, 60)}` : "";
        }
        case "cost_update": {
            const total = data["cost_usd"];
            return total !== undefined && total !== null ? `$${total.toFixed(4)}` : "$(N/A)";
        }
        case "approval_request":
            return `call_id=${data["call_id"] ?? "?"} action=${data["action"] ?? "?"}`;
        case "error": {
            const msg = data["message"];
            return msg ? msg.slice(0, 100) : "";
        }
        case "plan_update": {
            const todos = data["todos"];
            return todos ? `${todos.length} todo(s)` : "";
        }
        case "ledger_entry":
            return `${data["action"] ?? "?"} reversible=${data["reversible"] ?? "?"}`;
        case "proactive_suggestion": {
            const goal = data["goal"];
            const reason = data["reason_human"];
            return goal ? goal.slice(0, 60) : (reason ? reason.slice(0, 60) : "");
        }
        default:
            return "";
    }
    // unreachable — TypeScript doesn't know this is exhaustive for ParsedEvent
    return "";
}
function appendEvent(envelope, event, rawJson) {
    const li = buildEventRow(envelope, event, rawJson);
    eventList.appendChild(li);
    // Auto-scroll to bottom
    eventList.scrollTop = eventList.scrollHeight;
}
function appendSystemMessage(text, cls = "info") {
    const li = document.createElement("li");
    li.className = `system-msg ${cls}`;
    li.textContent = text;
    eventList.appendChild(li);
    eventList.scrollTop = eventList.scrollHeight;
}
// ── Startup: probe → (spawn) → Hello/Welcome ─────────────────────────────────
async function initConnection() {
    // Show socket path first (purely informational)
    const socketPath = await invoke("acp_socket_path").catch(() => "unknown");
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
            const cs = await invoke("acp_conn_state");
            setConnState(cs.state, cs.detail || undefined);
        }
        catch {
            // ignore poll errors
        }
    }, 400);
    const spawnResult = await invoke("acp_spawn_daemon").catch((e) => {
        const msg = e instanceof Error ? e.message : JSON.stringify(e);
        return { state: "failed", detail: msg };
    });
    clearInterval(pollId);
    setConnState(spawnResult.state, spawnResult.detail || undefined);
    if (spawnResult.state !== "connected") {
        appendSystemMessage(`[error] Daemon not reachable. ${spawnResult.detail || ""}. ` +
            "Manual start: uv run argos --with-daemon", "err");
        return;
    }
    appendSystemMessage(`[ok] Daemon reachable at ${socketPath}`, "info");
    // Create session (Hello → Welcome)
    const session = await invoke("acp_create_session").catch((e) => {
        const msg = e instanceof Error ? e.message : String(e);
        setConnState("error", "session creation failed — " + msg.slice(0, 80));
        return null;
    });
    if (!session?.session_id) {
        setConnState("error", "no session_id in response");
        return;
    }
    sessionIdEl.textContent = session.session_id.slice(0, 12) + "…";
    startHeartbeat();
    setConnState("connected");
    appendSystemMessage(`[ok] Connected. Session: ${session.session_id.slice(0, 8)}… — daemon at ${socketPath}`, "info");
    submitBtn.disabled = false;
}
// ── Run creation & SSE poll ───────────────────────────────────────────────────
async function startRun(task) {
    submitBtn.disabled = true;
    taskInput.disabled = true;
    stopPoll();
    nextSince = 0;
    lastSeq = -1;
    appendSystemMessage(`[run] Creating run: "${task.slice(0, 80)}"…`, "info");
    const run = await invoke("acp_create_run", { task }).catch((e) => {
        const msg = e instanceof Error ? e.message : String(e);
        appendSystemMessage(`[error] create_run failed: ${msg}`, "err");
        submitBtn.disabled = false;
        taskInput.disabled = false;
        return null;
    });
    if (!run?.run_id) {
        submitBtn.disabled = false;
        taskInput.disabled = false;
        return;
    }
    currentRunId = run.run_id;
    appendSystemMessage(`[run] run_id=${currentRunId} — polling events…`, "info");
    startPoll(currentRunId);
}
function startPoll(runId) {
    if (pollIntervalId !== null)
        clearInterval(pollIntervalId);
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
async function pollEvents(runId) {
    const rawLines = await invoke("acp_events_poll", {
        runId,
        since: nextSince,
        maxEvents: 50,
    }).catch((e) => {
        console.warn("poll error", e);
        return [];
    });
    for (const rawLine of rawLines) {
        const parsed = parseSSELine(rawLine);
        if (!parsed)
            continue;
        const { envelope, event } = parsed;
        appendEvent(envelope, event, rawLine);
        // Advance cursor
        if (envelope.seq >= nextSince) {
            nextSince = envelope.seq + 1;
        }
        // Stop polling on terminal events
        if (envelope.kind === "verify_verdict" ||
            envelope.kind === "error" ||
            (envelope.kind === "phase_change" &&
                envelope.data["phase"] === "report")) {
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
    if (!task)
        return;
    startRun(task);
});
taskInput.addEventListener("keydown", (e) => {
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
// 心跳:10s 周期续命 session(实测 bug 修复:无心跳 30s 过期变僵尸客户端)。
// 心跳失败 = session 已被 daemon 回收 → 自动重建并如实更新状态条。
function startHeartbeat() {
    setInterval(async () => {
        try {
            await invoke("acp_heartbeat");
        }
        catch {
            try {
                const s = await invoke("acp_create_session");
                if (s?.session_id) {
                    sessionIdEl.textContent = s.session_id.slice(0, 12) + "…";
                    setConnState("connected", "session renewed");
                }
            }
            catch (e) {
                setConnState("error", "session lost — " + String(e).slice(0, 60));
            }
        }
    }, 10_000);
}
