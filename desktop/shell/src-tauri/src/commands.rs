/// Tauri IPC command handlers — all `#[tauri::command]` fns live here.
///
/// Keeping them in a child module prevents `E0255` duplicate macro-namespace
/// errors that arise when `#[tauri::command]` proc-macros fire at the crate
/// root for both the `lib` and `bin` compilation units.
/// See: https://github.com/tauri-apps/tauri/issues/7534

use tauri::State;

use crate::bridge::{uds_get, uds_post, uds_sse_batch, BridgeError, BridgeResult};
use crate::state::AppState;

// ── Diagnostic ───────────────────────────────────────────────────────────────

/// Return the resolved socket path (for status bar display).
#[tauri::command]
pub async fn acp_socket_path(state: State<'_, AppState>) -> BridgeResult<String> {
    Ok(state.socket_path.to_string_lossy().to_string())
}

// ── Health ────────────────────────────────────────────────────────────────────

/// GET /health — probe whether argosd is reachable.
/// Returns the raw JSON response body on success.
#[tauri::command]
pub async fn acp_health(state: State<'_, AppState>) -> BridgeResult<serde_json::Value> {
    let body = uds_get(&state.socket_path, "/health", None).await?;
    serde_json::from_str(&body).map_err(|e| BridgeError::bad_response(e))
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
