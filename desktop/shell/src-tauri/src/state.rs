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
///   1. `ARGOS_DAEMON_SOCK` environment variable (override for tests / custom installs)
///   2. `~/.argos/daemon.sock` (convention from argos_agent/daemon/__main__.py)
pub fn resolve_socket_path() -> PathBuf {
    if let Ok(v) = std::env::var("ARGOS_DAEMON_SOCK") {
        return PathBuf::from(v);
    }
    dirs_home().join(".argos").join("daemon.sock")
}

/// Application-level state managed by Tauri.
pub struct AppState {
    /// Path to the argosd Unix domain socket.
    /// Resolved once at startup; immutable thereafter.
    pub socket_path: PathBuf,

    /// Active ACP session_id (set after acp_create_session succeeds).
    pub session_id: Mutex<Option<String>>,
}

impl AppState {
    pub fn new() -> Self {
        Self {
            socket_path: resolve_socket_path(),
            session_id: Mutex::new(None),
        }
    }
}
