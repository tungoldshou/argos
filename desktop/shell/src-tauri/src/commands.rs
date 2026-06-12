/// Tauri IPC command handlers — all `#[tauri::command]` fns live here.
///
/// Keeping them in a child module prevents `E0255` duplicate macro-namespace
/// errors that arise when `#[tauri::command]` proc-macros fire at the crate
/// root for both the `lib` and `bin` compilation units.
/// See: https://github.com/tauri-apps/tauri/issues/7534

use std::time::Duration;
use tauri::State;
use tokio::time::sleep;

use crate::bridge::{uds_get, uds_post, uds_sse_batch, BridgeError, BridgeResult};
use crate::state::{AppState, ConnState, resolve_daemon_cmd};

// ── Diagnostic ───────────────────────────────────────────────────────────────

/// Return the resolved socket path (for status bar display).
#[tauri::command]
pub async fn acp_socket_path(state: State<'_, AppState>) -> BridgeResult<String> {
    Ok(state.socket_path.to_string_lossy().to_string())
}

/// Return the current connection state and detail string.
/// Shape: { "state": "connected" | "disconnected" | "probing" | "spawning" | "failed",
///          "detail": "..." }
#[tauri::command]
pub async fn acp_conn_state(state: State<'_, AppState>) -> BridgeResult<serde_json::Value> {
    let cs = state.conn_state.lock().await.clone();
    let detail = state.conn_detail.lock().await.clone();
    Ok(serde_json::json!({ "state": cs, "detail": detail }))
}

// ── Health ────────────────────────────────────────────────────────────────────

/// GET /health — probe whether argosd is reachable.
/// Returns the raw JSON response body on success.
#[tauri::command]
pub async fn acp_health(state: State<'_, AppState>) -> BridgeResult<serde_json::Value> {
    let body = uds_get(&state.socket_path, "/health", None).await?;
    serde_json::from_str(&body).map_err(|e| BridgeError::bad_response(e))
}

// ── Sidecar spawn ─────────────────────────────────────────────────────────────

/// Probe the daemon socket, spawn argosd if unreachable, poll until connected.
///
/// State machine:
///   probing → (reachable) → connected
///   probing → (unreachable) → spawning → (poll ≤5s) → connected
///                                                      → failed (+ stderr excerpt)
///
/// Idempotent: if already connected, returns immediately.
/// Window close does NOT kill the daemon — argosd is a persistent kernel process.
/// The spawned process is detached (no child handle retained after spawn).
///
/// # Packaged / PyInstaller sidecar
/// TODO: detect bundled `argosd` binary next to the app bundle and exec it
/// instead.  For dev mode, `ARGOS_DAEMON_CMD` / the uv default is used.
#[tauri::command]
pub async fn acp_spawn_daemon(state: State<'_, AppState>) -> BridgeResult<serde_json::Value> {
    // Already connected → fast path.
    {
        let cs = state.conn_state.lock().await;
        if matches!(*cs, ConnState::Connected) {
            let detail = state.conn_detail.lock().await.clone();
            return Ok(serde_json::json!({ "state": "connected", "detail": detail }));
        }
    }

    // Phase 1: probe
    *state.conn_state.lock().await = ConnState::Probing;
    *state.conn_detail.lock().await = String::new();

    if uds_get(&state.socket_path, "/health", None).await.is_ok() {
        *state.conn_state.lock().await = ConnState::Connected;
        return Ok(serde_json::json!({ "state": "connected", "detail": "" }));
    }

    // Phase 2: spawn
    *state.conn_state.lock().await = ConnState::Spawning;

    let argv = resolve_daemon_cmd();
    if argv.is_empty() {
        let msg = "daemon cmd resolved to empty argv".to_string();
        *state.conn_state.lock().await = ConnState::Failed;
        *state.conn_detail.lock().await = msg.clone();
        return Err(BridgeError::daemon_unavailable(msg));
    }

    // Resolve working directory: one level above the desktop/ dir.
    // In dev mode the shell is at desktop/shell/src-tauri/; the repo root is
    // three levels up.  We use the current exe's dir as an anchor only as a
    // fallback; the real cwd at launch (inherited by the Tauri process) is the
    // repo root when launched via `cargo tauri dev` from there.
    // The safest approach: just inherit cwd (which is the repo root in dev mode).
    let spawn_result = tokio::process::Command::new(&argv[0])
        .args(&argv[1..])
        // Detach from Tauri's stdio so the daemon keeps running after window close.
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::piped())
        // kill_on_drop(false) is the default for tokio::process::Command,
        // so the daemon outlives the Tauri process (persistent kernel).
        .spawn();

    let mut child = match spawn_result {
        Ok(c) => c,
        Err(e) => {
            let msg = format!("spawn failed: {e}");
            *state.conn_state.lock().await = ConnState::Failed;
            *state.conn_detail.lock().await = msg.clone();
            return Err(BridgeError::daemon_unavailable(msg));
        }
    };

    // Phase 3: poll socket ≤5 s (10 × 500 ms)
    let deadline = std::time::Instant::now() + Duration::from_secs(5);
    loop {
        sleep(Duration::from_millis(500)).await;
        if uds_get(&state.socket_path, "/health", None).await.is_ok() {
            *state.conn_state.lock().await = ConnState::Connected;
            return Ok(serde_json::json!({ "state": "connected", "detail": "" }));
        }
        if std::time::Instant::now() >= deadline {
            break;
        }
        // If child exited early, capture stderr for diagnostics.
        if let Ok(Some(exit)) = child.try_wait() {
            let stderr_bytes = if let Some(mut se) = child.stderr.take() {
                use tokio::io::AsyncReadExt;
                let mut buf = Vec::new();
                let _ = se.read_to_end(&mut buf).await;
                buf
            } else {
                vec![]
            };
            let stderr_str = String::from_utf8_lossy(&stderr_bytes);
            let detail = format!(
                "daemon exited early ({}): {}",
                exit,
                stderr_str.chars().take(300).collect::<String>()
            );
            *state.conn_state.lock().await = ConnState::Failed;
            *state.conn_detail.lock().await = detail.clone();
            return Err(BridgeError::daemon_unavailable(detail));
        }
    }

    // Timed out — collect stderr excerpt
    let stderr_bytes = if let Some(mut se) = child.stderr.take() {
        use tokio::io::AsyncReadExt;
        let mut buf = Vec::new();
        // Non-blocking read: give it 200 ms
        let _ = tokio::time::timeout(Duration::from_millis(200), se.read_to_end(&mut buf)).await;
        buf
    } else {
        vec![]
    };
    let stderr_str = String::from_utf8_lossy(&stderr_bytes);
    let detail = format!(
        "daemon 拉起失败: socket 5 s 内不可达. stderr: {}",
        stderr_str.chars().take(300).collect::<String>()
    );
    *state.conn_state.lock().await = ConnState::Failed;
    *state.conn_detail.lock().await = detail.clone();
    Err(BridgeError::daemon_unavailable(detail))
}

// ── Session ───────────────────────────────────────────────────────────────────

/// POST /sessions — create a new ACP session (Hello → Welcome handshake).
/// Stores the session_id in AppState for subsequent requests.
/// Returns `CreateSessionResponse` JSON.
#[tauri::command]
pub async fn acp_create_session(state: State<'_, AppState>) -> BridgeResult<serde_json::Value> {
    let body = uds_post(&state.socket_path, "/sessions", None, "{}").await?;
    let value: serde_json::Value =
        serde_json::from_str(&body).map_err(|e| BridgeError::bad_response(e))?;
    if let Some(sid) = value.get("session_id").and_then(|v| v.as_str()) {
        let mut guard = state.session_id.lock().await;
        *guard = Some(sid.to_string());
    }
    Ok(value)
}

/// Return the current active session_id (null if no session created yet).
#[tauri::command]
pub async fn acp_session_id(state: State<'_, AppState>) -> BridgeResult<Option<String>> {
    let guard = state.session_id.lock().await;
    Ok(guard.clone())
}

/// POST /sessions/{id}/heartbeat — 续命当前 session(实测 bug 修复:壳无心跳,
/// 30s 后 session 过期变僵尸客户端,一切写操作 401)。前端 10s 周期调用。
#[tauri::command]
pub async fn acp_heartbeat(state: State<'_, AppState>) -> BridgeResult<serde_json::Value> {
    let sid = {
        let guard = state.session_id.lock().await;
        guard.clone()
    };
    let Some(sid) = sid else {
        return Err(BridgeError::bad_response("no active session"));
    };
    let path = format!("/sessions/{}/heartbeat", sid);
    let body = uds_post(&state.socket_path, &path, Some(&sid), "{}").await?;
    serde_json::from_str(&body).map_err(|e| BridgeError::bad_response(e))
}

/// DELETE /sessions/{id} — close the active session (best-effort).
#[tauri::command]
pub async fn acp_delete_session(state: State<'_, AppState>) -> BridgeResult<serde_json::Value> {
    let sid = {
        let guard = state.session_id.lock().await;
        guard.clone()
    };

    if let Some(ref sid) = sid {
        let path = format!("/sessions/{}", sid);
        // Best-effort DELETE — re-use POST with empty body and ignore error
        let _ = uds_post(&state.socket_path, &path, Some(sid), "{}").await;
    }

    {
        let mut guard = state.session_id.lock().await;
        *guard = None;
    }
    Ok(serde_json::json!({ "ok": true }))
}

// ── Runs ──────────────────────────────────────────────────────────────────────

/// GET /runs — list all known runs.
#[tauri::command]
pub async fn acp_list_runs(state: State<'_, AppState>) -> BridgeResult<serde_json::Value> {
    let sid = { state.session_id.lock().await.clone() };
    let body = uds_get(&state.socket_path, "/runs", sid.as_deref()).await?;
    serde_json::from_str(&body).map_err(|e| BridgeError::bad_response(e))
}

/// POST /runs — create a new run with the given task string.
/// Returns `CreateRunResponse` JSON (contains `run_id`).
#[tauri::command]
pub async fn acp_create_run(
    state: State<'_, AppState>,
    task: String,
) -> BridgeResult<serde_json::Value> {
    let sid = { state.session_id.lock().await.clone() };
    let body_json =
        serde_json::to_string(&serde_json::json!({ "goal": task }))
        .map_err(|e| BridgeError::bad_response(e))?;
    let body = uds_post(&state.socket_path, "/runs", sid.as_deref(), &body_json).await?;
    serde_json::from_str(&body).map_err(|e| BridgeError::bad_response(e))
}

// ── SSE event polling ─────────────────────────────────────────────────────────

/// GET /runs/{run_id}/events (SSE) — batch-poll up to `max_events` frames.
///
/// Returns a `Vec<String>` where each element is a raw ACP Envelope JSON
/// string (from a `data: <json>` SSE line).  The frontend's TypeScript
/// `parseSSELine()` from @argos/sdk handles deserialization.
///
/// `since` is the seq cursor (default 0); advance it by setting it to
/// the last received seq + 1 to avoid re-delivering events.
///
/// DESIGN: long-poll batch, not a real stream.  Sufficient for walking
/// skeleton.  Replace with Tauri-event streaming bridge later if needed.
#[tauri::command]
pub async fn acp_events_poll(
    state: State<'_, AppState>,
    run_id: String,
    since: Option<u64>,
    max_events: Option<usize>,
) -> BridgeResult<Vec<String>> {
    let sid = { state.session_id.lock().await.clone() };
    let since_val = since.unwrap_or(0);
    let cap = max_events.unwrap_or(50).min(200);
    let path = format!("/runs/{}/events?since={}", run_id, since_val);
    uds_sse_batch(&state.socket_path, &path, sid.as_deref(), cap).await
}
