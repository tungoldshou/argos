/// Argos desktop shell — Tauri 2 Rust bridge.
///
/// # Architecture
///
/// The WebView has no Node.js runtime, so the TypeScript SDK's DaemonClient
/// (which uses Node's `net` module for Unix socket I/O) cannot run in the
/// frontend.  Instead the Rust layer acts as an HTTP proxy:
///
///   Frontend invoke("acp_health") → Rust opens UDS → HTTP GET /health → JSON response
///
/// SSE event streaming uses a long-poll batch command (`acp_events_poll`):
/// the frontend calls it on an interval, receiving up to 50 events per call.
/// This avoids per-event Tauri IPC overhead in the walking skeleton.
/// A Tauri-event streaming bridge (emit() per SSE line) can replace it later
/// without changing the ACP wire format.
///
/// # Module layout
///
/// - `bridge` — shared UDS HTTP helpers (no Tauri deps)
/// - `state`  — AppState (socket path + session_id mutex)
/// - `commands` — all `#[tauri::command]` functions
///   NOTE: kept in a child module to avoid `E0255` duplicate macro names
///   when the rlib target is compiled alongside the cdylib. See:
///   https://github.com/tauri-apps/tauri/issues/7534

pub mod bridge;
pub mod commands;
pub mod state;

/// Tauri app entry point.  Called from main.rs.
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(state::AppState::new())
        .invoke_handler(tauri::generate_handler![
            commands::acp_health,
            commands::acp_create_session,
            commands::acp_session_id,
            commands::acp_create_run,
            commands::acp_events_poll,
            commands::acp_list_runs,
            commands::acp_delete_session,
            commands::acp_socket_path,
            commands::acp_conn_state,
            commands::acp_spawn_daemon,
        ])
        .run(tauri::generate_context!())
        .expect("error running Argos shell");
}
