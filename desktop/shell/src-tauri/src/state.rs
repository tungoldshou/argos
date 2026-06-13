/// Shared Tauri application state.

use std::path::PathBuf;
use tokio::sync::Mutex;

fn dirs_home() -> PathBuf {
    std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("/tmp"))
}

/// Resolve the argosd Unix socket path.
///
/// Priority:
///   1. `ARGOS_DAEMON_SOCKET` environment variable — canonical Python-side name
///      (used by argos/tui/app.py and the pytest smoke-test suite for
///      per-test daemon isolation).  This is the **preferred** override for
///      integration tests and multi-daemon setups.
///   2. `ARGOS_DAEMON_SOCK` environment variable — legacy short alias kept for
///      backwards compatibility (older scripts / custom installs may still set it).
///   3. `~/.argos/daemon.sock` (convention from argos/daemon/__main__.py)
///
/// Having the Python side and the Rust side share the same env-var name means
/// a single `ARGOS_DAEMON_SOCKET=/tmp/test.sock cargo test` is enough to
/// redirect both halves of the channel — no per-side configuration needed.
pub fn resolve_socket_path() -> PathBuf {
    // Canonical name (matches argos/tui/app.py)
    if let Ok(v) = std::env::var("ARGOS_DAEMON_SOCKET") {
        if !v.is_empty() {
            return PathBuf::from(v);
        }
    }
    // Legacy alias
    if let Ok(v) = std::env::var("ARGOS_DAEMON_SOCK") {
        if !v.is_empty() {
            return PathBuf::from(v);
        }
    }
    dirs_home().join(".argos").join("daemon.sock")
}

/// Resolve the daemon spawn command.
///
/// Priority:
///   1. `ARGOS_DAEMON_CMD` environment variable — space-split into argv.
///      Example: `ARGOS_DAEMON_CMD="uv run python -m argos.daemon"`
///   2. Hardcoded dev default: `["uv", "run", "python", "-m", "argos.daemon"]`
///      Working directory for spawn: the repo root (one level above `desktop/`).
///
/// NOTE: packaged / PyInstaller sidecar mode is NOT handled here — the binary
/// would re-exec itself as the daemon child.  That path is left as a TODO:
/// detect a `ARGOS_PACKAGED_SIDECAR` env or a bundled `argosd` binary alongside
/// the app, then exec that instead.  For now, dev mode is the only supported path.
pub fn resolve_daemon_cmd() -> Vec<String> {
    if let Ok(v) = std::env::var("ARGOS_DAEMON_CMD") {
        let parts: Vec<String> = v.split_whitespace().map(String::from).collect();
        if !parts.is_empty() {
            return parts;
        }
    }
    vec![
        "uv".to_string(),
        "run".to_string(),
        "python".to_string(),
        "-m".to_string(),
        "argos.daemon".to_string(),
    ]
}

/// Connection state visible to the frontend via `acp_conn_state` command.
#[derive(Debug, Clone, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ConnState {
    /// No daemon reachable; spawn not yet attempted.
    Disconnected,
    /// Probing socket — trying GET /health.
    Probing,
    /// Daemon not reachable; spawn subprocess started, waiting for socket.
    Spawning,
    /// Socket reachable and /health returned OK.
    Connected,
    /// Spawn or connection permanently failed; detail carries reason.
    Failed,
}

/// Application-level state managed by Tauri.
pub struct AppState {
    /// Path to the argosd Unix domain socket.
    /// Resolved once at startup; immutable thereafter.
    pub socket_path: PathBuf,

    /// Active ACP session_id (set after acp_create_session succeeds).
    pub session_id: Mutex<Option<String>>,

    /// Current connection state (updated by sidecar spawn logic).
    pub conn_state: Mutex<ConnState>,

    /// Last failure detail (stderr excerpt or error string), if any.
    pub conn_detail: Mutex<String>,
}

impl AppState {
    pub fn new() -> Self {
        Self {
            socket_path: resolve_socket_path(),
            session_id: Mutex::new(None),
            conn_state: Mutex::new(ConnState::Disconnected),
            conn_detail: Mutex::new(String::new()),
        }
    }
}
