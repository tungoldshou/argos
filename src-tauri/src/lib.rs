// Argos Tauri backend — bridges the UI to a locally-running Hermes agent.
//
// It does three things the browser cannot:
//   1. Forward REST calls to the Hermes API server (127.0.0.1:8642) with the
//      Bearer key read from ~/.hermes/.argos_api_key (no CORS, key never leaves Rust).
//   2. Read the agent's memory markdown (~/.hermes/memories/*.md) off disk.
//   3. Stream a run's SSE event feed, re-emitting each event as a Tauri event.
use std::path::PathBuf;
use std::sync::RwLock;
use std::time::Duration;
use std::collections::HashMap;

use futures_util::StreamExt;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::{Emitter, State};

const DEFAULT_BASE: &str = "http://127.0.0.1:8642";

#[derive(Debug, thiserror::Error)]
enum BridgeError {
    #[error("hermes api key not found — is the API server enabled? ({0})")]
    NoKey(String),
    #[error("http error: {0}")]
    Http(#[from] reqwest::Error),
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("hermes returned {status}: {body}")]
    Status { status: u16, body: String },
}

// Tauri commands must return a String/JSON-serializable error.
impl Serialize for BridgeError {
    fn serialize<S: serde::Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        s.serialize_str(&self.to_string())
    }
}

struct Bridge {
    client: reqwest::Client,
    base: String,
}

fn hermes_home() -> PathBuf {
    if let Ok(h) = std::env::var("HERMES_HOME") {
        return PathBuf::from(h);
    }
    dirs::home_dir().unwrap_or_default().join(".hermes")
}

fn read_api_key() -> Result<String, BridgeError> {
    // Preferred: the dedicated key file Argos wrote when enabling the API server.
    let key_file = hermes_home().join(".argos_api_key");
    if let Ok(k) = std::fs::read_to_string(&key_file) {
        let k = k.trim().to_string();
        if !k.is_empty() {
            return Ok(k);
        }
    }
    // Fallback: parse API_SERVER_KEY out of ~/.hermes/.env
    let env_file = hermes_home().join(".env");
    if let Ok(contents) = std::fs::read_to_string(&env_file) {
        for line in contents.lines() {
            let line = line.trim();
            if line.starts_with('#') {
                continue;
            }
            if let Some(rest) = line.strip_prefix("API_SERVER_KEY=") {
                let v = rest.trim().trim_matches('"').trim_matches('\'').to_string();
                if !v.is_empty() {
                    return Ok(v);
                }
            }
        }
    }
    Err(BridgeError::NoKey(key_file.display().to_string()))
}

fn base_url() -> String {
    std::env::var("HERMES_API_URL").unwrap_or_else(|_| DEFAULT_BASE.to_string())
}

/// GET a path on the Hermes API server, returning parsed JSON.
#[tauri::command]
async fn hermes_get(bridge: State<'_, Bridge>, path: String) -> Result<serde_json::Value, BridgeError> {
    let key = read_api_key()?;
    let url = format!("{}{}", bridge.base, path);
    let resp = bridge
        .client
        .get(&url)
        .bearer_auth(&key)
        .send()
        .await?;
    let status = resp.status();
    if !status.is_success() {
        let body = resp.text().await.unwrap_or_default();
        return Err(BridgeError::Status { status: status.as_u16(), body });
    }
    Ok(resp.json::<serde_json::Value>().await?)
}

/// POST a JSON body to a path on the Hermes API server.
#[tauri::command]
async fn hermes_post(
    bridge: State<'_, Bridge>,
    path: String,
    body: serde_json::Value,
) -> Result<serde_json::Value, BridgeError> {
    let key = read_api_key()?;
    let url = format!("{}{}", bridge.base, path);
    let resp = bridge
        .client
        .post(&url)
        .bearer_auth(&key)
        .json(&body)
        .send()
        .await?;
    let status = resp.status();
    if !status.is_success() {
        let text = resp.text().await.unwrap_or_default();
        return Err(BridgeError::Status { status: status.as_u16(), body: text });
    }
    // Some endpoints (pause/resume) may return empty body.
    let text = resp.text().await.unwrap_or_default();
    if text.trim().is_empty() {
        return Ok(serde_json::json!({ "ok": true }));
    }
    Ok(serde_json::from_str(&text).unwrap_or(serde_json::json!({ "raw": text })))
}

#[derive(Serialize)]
struct MemoryFiles {
    memory: String,
    user: String,
}

/// Read the agent's persistent memory markdown off disk.
#[tauri::command]
fn read_memory() -> Result<MemoryFiles, BridgeError> {
    let mem_dir = hermes_home().join("memories");
    let memory = std::fs::read_to_string(mem_dir.join("MEMORY.md")).unwrap_or_default();
    let user = std::fs::read_to_string(mem_dir.join("USER.md")).unwrap_or_default();
    Ok(MemoryFiles { memory, user })
}

// ── Context Lens: read Claude Code session transcripts (~/.claude/projects) ──
// Zero-install, local-only: Claude Code persists complete JSONL transcripts per
// session, so we reconstruct "what the agent touched" without any hooks.
#[derive(Serialize, Default)]
struct ToolHit {
    tool: String,
    file: Option<String>,
}
#[derive(Serialize, Default)]
struct SessionTrace {
    source: String, // "claude-code"
    project: String,
    session: String,
    mtime: u64,
    user_turns: u32,
    assistant_turns: u32,
    hits: Vec<ToolHit>,
}

fn claude_home() -> PathBuf {
    if let Ok(h) = std::env::var("CLAUDE_HOME") {
        return PathBuf::from(h);
    }
    dirs::home_dir().unwrap_or_default().join(".claude")
}

fn parse_transcript(path: &std::path::Path) -> Option<SessionTrace> {
    let content = std::fs::read_to_string(path).ok()?;
    let meta = std::fs::metadata(path).ok();
    let mtime = meta
        .and_then(|m| m.modified().ok())
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let project = path
        .parent()
        .and_then(|p| p.file_name())
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_default();
    let session = path.file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_default();

    let mut trace = SessionTrace {
        source: "claude-code".into(),
        project,
        session,
        mtime,
        ..Default::default()
    };

    for line in content.lines() {
        let v: serde_json::Value = match serde_json::from_str(line) {
            Ok(v) => v,
            Err(_) => continue,
        };
        let msg = &v["message"];
        if let Some(role) = msg["role"].as_str() {
            match role {
                "user" => trace.user_turns += 1,
                "assistant" => trace.assistant_turns += 1,
                _ => {}
            }
        }
        if let Some(content) = msg["content"].as_array() {
            for c in content {
                if c["type"] == "tool_use" {
                    let tool = c["name"].as_str().unwrap_or("?").to_string();
                    let inp = &c["input"];
                    let file = inp["file_path"]
                        .as_str()
                        .or_else(|| inp["path"].as_str())
                        .or_else(|| inp["notebook_path"].as_str())
                        .map(|s| s.rsplit('/').next().unwrap_or(s).to_string());
                    trace.hits.push(ToolHit { tool, file });
                }
            }
        }
    }
    Some(trace)
}

/// Scan recent Claude Code session transcripts and return per-session traces.
/// `limit` caps how many most-recent sessions to parse (keeps it fast).
#[tauri::command]
fn read_claude_transcripts(limit: Option<usize>) -> Result<Vec<SessionTrace>, BridgeError> {
    let limit = limit.unwrap_or(40);
    let projects = claude_home().join("projects");
    let mut files: Vec<(PathBuf, u64)> = Vec::new();
    if let Ok(dirs) = std::fs::read_dir(&projects) {
        for d in dirs.flatten() {
            let p = d.path();
            if !p.is_dir() {
                continue;
            }
            if let Ok(entries) = std::fs::read_dir(&p) {
                for e in entries.flatten() {
                    let fp = e.path();
                    if fp.extension().and_then(|s| s.to_str()) == Some("jsonl") {
                        let m = e
                            .metadata()
                            .ok()
                            .and_then(|m| m.modified().ok())
                            .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
                            .map(|d| d.as_secs())
                            .unwrap_or(0);
                        files.push((fp, m));
                    }
                }
            }
        }
    }
    files.sort_by(|a, b| b.1.cmp(&a.1)); // newest first
    files.truncate(limit);
    Ok(files.iter().filter_map(|(p, _)| parse_transcript(p)).collect())
}

/// Is the Hermes API server reachable right now?
#[tauri::command]
async fn hermes_health(bridge: State<'_, Bridge>) -> Result<bool, BridgeError> {
    let url = format!("{}/health", bridge.base);
    match bridge.client.get(&url).timeout(Duration::from_secs(3)).send().await {
        Ok(r) => Ok(r.status().is_success()),
        Err(_) => Ok(false),
    }
}

#[derive(Serialize, Clone)]
struct RunEvent {
    run_id: String,
    data: serde_json::Value,
}

#[derive(Serialize, Clone)]
struct RunDone {
    run_id: String,
    error: Option<String>,
}

/// Subscribe to a run's SSE event stream and re-emit each event to the UI as
/// `hermes://run-event` (+ a final `hermes://run-done`). Returns once started.
#[tauri::command]
async fn stream_run_events(
    app: tauri::AppHandle,
    bridge: State<'_, Bridge>,
    run_id: String,
) -> Result<(), BridgeError> {
    let key = read_api_key()?;
    let url = format!("{}/v1/runs/{}/events", bridge.base, run_id);
    let client = bridge.client.clone();
    // Spawn so the command returns immediately; events arrive asynchronously.
    tauri::async_runtime::spawn(async move {
        let resp = match client.get(&url).bearer_auth(&key).send().await {
            Ok(r) => r,
            Err(e) => {
                let _ = app.emit("hermes://run-done", RunDone { run_id, error: Some(e.to_string()) });
                return;
            }
        };
        let mut stream = resp.bytes_stream();
        let mut buf = String::new();
        while let Some(chunk) = stream.next().await {
            let bytes = match chunk {
                Ok(b) => b,
                Err(e) => {
                    let _ = app.emit("hermes://run-done", RunDone { run_id: run_id.clone(), error: Some(e.to_string()) });
                    return;
                }
            };
            buf.push_str(&String::from_utf8_lossy(&bytes));
            // SSE frames are separated by a blank line.
            while let Some(idx) = buf.find("\n\n") {
                let frame = buf[..idx].to_string();
                buf.drain(..idx + 2);
                for line in frame.lines() {
                    let line = line.trim_start();
                    if let Some(payload) = line.strip_prefix("data:") {
                        let payload = payload.trim();
                        if payload.is_empty() {
                            continue;
                        }
                        match serde_json::from_str::<serde_json::Value>(payload) {
                            Ok(json) => {
                                let _ = app.emit(
                                    "hermes://run-event",
                                    RunEvent { run_id: run_id.clone(), data: json },
                                );
                            }
                            Err(_) => { /* keepalive / non-JSON line, ignore */ }
                        }
                    }
                    // lines beginning with ':' are SSE comments (keepalive) — ignore.
                }
            }
        }
        let _ = app.emit("hermes://run-done", RunDone { run_id, error: None });
    });
    Ok(())
}

// ══════════════════════════════════════════════════════════════════════════════
// TODO REST API — 3 core endpoints (create / query / delete)
// Follows the shared contract: UUIDv4, snake_case, ISO8601 UTC, enum status,
// version optimistic lock, unified error wrapper, length limits.
// ══════════════════════════════════════════════════════════════════════════════

const VALID_STATUSES: [&str; 4] = ["pending", "in_progress", "completed", "cancelled"];

fn now_iso() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let d = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default();
    let secs = d.as_secs();
    // Decompose into UTC date-time parts (naive, Z suffix added manually).
    // 86400 s/day; ignore leap seconds.
    let days = secs / 86400;
    let rem = secs % 86400;
    let hours = rem / 3600;
    let minutes = (rem % 3600) / 60;
    let seconds = rem % 60;
    let millis = d.subsec_millis();
    // Convert days-since-1970 to Y-M-D (Zeller-like, no external crate).
    let (year, month, day) = civil_from_days(days as i64);
    format!("{:04}-{:02}-{:02}T{:02}:{:02}:{:02}.{:03}Z",
            year, month, day, hours, minutes, seconds, millis)
}

// Gregorian calendar from days since 1970-01-01 (proleptic).
fn civil_from_days(z: i64) -> (i64, u64, u64) {
    // Simplified algorithm from Howard Hinnant's date library.
    let z = z + 719468;
    let era = (if z >= 0 { z } else { z - 146096 }) / 146097;
    let doe = z - era * 146097;
    let yoe = (doe - doe/1460 + doe/36524 - doe/146096) / 365;
    let y = yoe as i64 + era * 400;
    let doy = doe - (365*yoe + yoe/4 - yoe/100);
    let mp = (5*doy + 2)/153;
    let d = doy - (153*mp+2)/5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = y + (if m <= 2 { 1 } else { 0 });
    (year, m as u64, d as u64)
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Todo {
    pub id: String,               // UUIDv4
    pub title: String,            // ≤200 chars
    pub description: Option<String>, // ≤2000 chars, nullable
    pub tags: Vec<String>,        // each ≤50 chars, total ≤10
    pub status: String,           // enum: pending|in_progress|completed|cancelled
    pub version: i32,             // optimistic lock, starts at 1
    pub created_at: String,       // ISO8601 UTC Z
    pub updated_at: String,       // ISO8601 UTC Z
}

#[derive(Default)]
struct TodoStore {
    items: RwLock<HashMap<String, Todo>>,
}

fn validate_todo_input(title: &str, description: &Option<String>, tags: &[String]) -> Result<(), (u16, &'static str)> {
    if title.is_empty() {
        return Err((40001, "title is required"));
    }
    if title.chars().count() > 200 {
        return Err((422, "title exceeds 200 characters"));
    }
    if let Some(ref d) = *description {
        if d.chars().count() > 2000 {
            return Err((422, "description exceeds 2000 characters"));
        }
    }
    if tags.len() > 10 {
        return Err((422, "tags exceeds 10 items"));
    }
    for tag in tags {
        if tag.chars().count() > 50 {
            return Err((422, "tag exceeds 50 characters"));
        }
    }
    Ok(())
}

fn build_error(code: u16, message: &'static str) -> Value {
    serde_json::json!({ "error": { "code": code, "message": message } })
}

/// POST /todos — create a new todo.
/// Request body: { title: string (required), description?: string, tags?: string[] }
#[tauri::command]
fn todos_create(
    store: State<'_, TodoStore>,
    title: String,
    description: Option<String>,
    tags: Option<Vec<String>>,
    status: Option<String>,
) -> Result<Value, Value> {
    let tags = tags.unwrap_or_default();
    validate_todo_input(&title, &description, &tags)
        .map_err(|(code, msg)| build_error(code, msg))?;

    let status = status.unwrap_or_else(|| "pending".to_string());
    if !VALID_STATUSES.contains(&status.as_str()) {
        return Err(build_error(40001, "invalid status value"));
    }

    let id = uuid::Uuid::new_v4().to_string();
    let ts = now_iso();
    let todo = Todo {
        id: id.clone(),
        title,
        description,
        tags,
        status,
        version: 1,
        created_at: ts.clone(),
        updated_at: ts,
    };

    store.items.write()
        .map_err(|_| build_error(50001, "internal error"))?
        .insert(id.clone(), todo.clone());

    Ok(serde_json::json!({ "data": todo }))
}

/// GET /todos — list todos with optional filters, sort, pagination.
/// Query params: page (default 1), page_size (default 20, max 100),
///               tags (repeatable, AND logic), status (comma-separated),
///               search (fuzzy title+description), sort (field:dir, default created_at:desc)
#[tauri::command]
fn todos_list(
    store: State<'_, TodoStore>,
    page: Option<usize>,
    page_size: Option<usize>,
    tags: Option<Vec<String>>,
    status: Option<String>,
    search: Option<String>,
    sort: Option<String>,
) -> Result<Value, Value> {
    let page = page.unwrap_or(1).max(1);
    let page_size = page_size.unwrap_or(20).min(100).max(1);

    let guard = store.items.read()
        .map_err(|_| build_error(50001, "internal error"))?;

    // Collect all todos into a mutable vec we can filter and sort in-place.
    let mut todos: Vec<Todo> = guard.values().map(|t| (*t).clone()).collect();

    // Filter by tags (AND — every tag filter must be present).
    if let Some(ref tag_filter) = tags {
        todos.retain(|t| tag_filter.iter().all(|f| t.tags.contains(f)));
    }

    // Filter by status (comma-separated list).
    if let Some(ref s) = status {
        let statuses: Vec<&str> = s.split(',').map(|x| x.trim()).collect();
        todos.retain(|t| statuses.contains(&t.status.as_str()));
    }

    // Filter by search (case-insensitive title + description).
    if let Some(ref q) = search {
        let q_lower = q.to_lowercase();
        todos.retain(|t| {
            t.title.to_lowercase().contains(&q_lower) ||
            t.description.as_ref()
                .map(|d| d.to_lowercase().contains(&q_lower))
                .unwrap_or(false)
        });
    }

    // Sort.
    let sort_str = sort.unwrap_or_else(|| "created_at:desc".to_string());
    let (field, dir) = sort_str.split_once(':').unwrap_or(("created_at", "desc"));
    let ascending = dir == "asc";
    todos.sort_by(|a, b| {
        let ord = match field {
            "title" => a.title.cmp(&b.title),
            "status" => a.status.cmp(&b.status),
            "updated_at" => a.updated_at.cmp(&b.updated_at),
            _ => a.created_at.cmp(&b.created_at),
        };
        if ascending { ord } else { ord.reverse() }
    });

    let total = todos.len();
    let start = (page - 1) * page_size;
    let page_items: Vec<Todo> = todos.into_iter().skip(start).take(page_size).collect();

    drop(guard); // release read lock early

    Ok(serde_json::json!({
        "data": page_items,
        "meta": { "total": total, "page": page, "page_size": page_size }
    }))
}

/// GET /todos/:id — get a single todo by id.
#[tauri::command]
fn todos_get(store: State<'_, TodoStore>, id: String) -> Result<Value, Value> {
    let items = store.items.read()
        .map_err(|_| build_error(50001, "internal error"))?;

    match items.get(&id) {
        Some(todo) => Ok(serde_json::json!({ "data": todo.clone() })),
        None => Err(build_error(40401, "todo not found")),
    }
}

/// DELETE /todos/:id — permanently delete a todo.
#[tauri::command]
fn todos_delete(store: State<'_, TodoStore>, id: String) -> Result<(), Value> {
    let mut items = store.items.write()
        .map_err(|_| build_error(50001, "internal error"))?;

    if items.remove(&id).is_none() {
        return Err(build_error(40401, "todo not found"));
    }
    Ok(())
}

/// PATCH /todos/:id — update a todo (partial).
/// Request body: { title?, description?, tags?, status?, version (required) }
#[tauri::command]
fn todos_update(
    store: State<'_, TodoStore>,
    id: String,
    title: Option<String>,
    description: Option<String>,
    tags: Option<Vec<String>>,
    status: Option<String>,
    version: i32,
) -> Result<Value, Value> {
    let tags = tags.unwrap_or_default();
    if !title.as_ref().map(|t| t.chars().count()).unwrap_or(0).le(&200) {
        return Err(build_error(422, "title exceeds 200 characters"));
    }
    if let Some(ref d) = description {
        if d.chars().count() > 2000 {
            return Err(build_error(422, "description exceeds 2000 characters"));
        }
    }
    if tags.len() > 10 {
        return Err(build_error(422, "tags exceeds 10 items"));
    }
    for tag in &tags {
        if tag.chars().count() > 50 {
            return Err(build_error(422, "tag exceeds 50 characters"));
        }
    }
    if let Some(ref s) = status {
        if !VALID_STATUSES.contains(&s.as_str()) {
            return Err(build_error(40001, "invalid status value"));
        }
    }

    let mut items = store.items.write()
        .map_err(|_| build_error(50001, "internal error"))?;

    let todo = items.get_mut(&id)
        .ok_or_else(|| build_error(40401, "todo not found"))?;

    if todo.version != version {
        return Err(build_error(409, "version conflict"));
    }

    if let Some(t) = title {
        todo.title = t;
    }
    if description.is_some() {
        todo.description = description;
    }
    if !tags.is_empty() {
        todo.tags = tags;
    }
    if let Some(s) = status {
        todo.status = s;
    }
    todo.version += 1;
    todo.updated_at = now_iso();

    Ok(serde_json::json!({ "data": todo.clone() }))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let client = reqwest::Client::builder()
        .build()
        .expect("failed to build http client");

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(Bridge { client, base: base_url() })
        .manage(TodoStore::default())
        .invoke_handler(tauri::generate_handler![
            hermes_get,
            hermes_post,
            read_memory,
            read_claude_transcripts,
            hermes_health,
            stream_run_events,
            todos_create,
            todos_list,
            todos_get,
            todos_delete,
            todos_update
        ])
        .run(tauri::generate_context!())
        .expect("error while running argos");
}
