/// Low-level Unix domain socket HTTP helpers.
///
/// Zero Tauri deps — pure hyper + hyperlocal.
///
/// # Dependency choice rationale (for packager)
///
/// `reqwest` does not support Unix domain sockets.
/// `hyperlocal 0.9` provides a `UnixConnector` that adapts tokio's
/// `UnixStream` into hyper's HTTP stack locally, with no TLS/openssl.
/// Crate versions pinned in Cargo.toml:
///   - hyperlocal 0.9  (requires hyper 1.x)
///   - hyper 1.x + hyper-util 0.1 (client-legacy feature for Client<C,B>)
///   - http-body-util 0.1 (BodyExt collector)
///   - tokio 1 (full features — async runtime)
/// No network is ever used: all I/O is local UDS.

use std::path::PathBuf;
use std::time::Duration;

use bytes::Bytes;
use http_body_util::{BodyExt, Empty, Full};
use hyper::body::Incoming;
use hyper::{Method, Request, Response};
use hyper_util::client::legacy::Client;
use hyperlocal::{UnixClientExt, Uri as UnixUri};
use serde::Serialize;
use tokio::time::timeout;

// ── Error type ─────────────────────────────────────────────────────────────

/// Error returned from every bridge command.  Tauri serialises this to JSON
/// and delivers it as the `Err` side of `invoke()` in the frontend.
#[derive(Debug, Serialize)]
pub struct BridgeError {
    pub code: String,
    pub message: String,
}

impl BridgeError {
    pub fn new(code: impl Into<String>, msg: impl std::fmt::Display) -> Self {
        Self { code: code.into(), message: msg.to_string() }
    }
    pub fn daemon_unavailable(msg: impl std::fmt::Display) -> Self {
        Self::new("daemon_unavailable", msg)
    }
    pub fn bad_response(msg: impl std::fmt::Display) -> Self {
        Self::new("bad_response", msg)
    }
}

pub type BridgeResult<T> = Result<T, BridgeError>;

// ── Helpers ─────────────────────────────────────────────────────────────────

fn unix_uri(socket_path: &PathBuf, path: &str) -> hyper::Uri {
    UnixUri::new(socket_path, path).into()
}

async fn collect_body(body: Incoming) -> BridgeResult<String> {
    let collected = body.collect().await.map_err(|e| BridgeError::bad_response(e))?;
    String::from_utf8(collected.to_bytes().to_vec())
        .map_err(|e| BridgeError::bad_response(e))
}

/// Send a GET request over UDS, return response body as `String`.
pub async fn uds_get(
    socket_path: &PathBuf,
    path: &str,
    session_id: Option<&str>,
) -> BridgeResult<String> {
    let client: Client<hyperlocal::UnixConnector, Empty<Bytes>> = Client::unix();
    let uri = unix_uri(socket_path, path);

    let mut req_builder = Request::builder()
        .method(Method::GET)
        .uri(uri)
        .header("Host", "localhost")
        .header("Accept", "application/json");

    if let Some(sid) = session_id {
        req_builder = req_builder.header("X-Argos-Session", sid);
    }

    let req = req_builder
        .body(Empty::new())
        .map_err(|e| BridgeError::bad_response(e))?;

    let resp: Response<Incoming> = timeout(Duration::from_secs(15), client.request(req))
        .await
        .map_err(|_| BridgeError::daemon_unavailable("GET timed out after 15 s"))?
        .map_err(|e| BridgeError::daemon_unavailable(e))?;

    let status = resp.status();
    let body = collect_body(resp.into_body()).await?;

    if !status.is_success() {
        return Err(BridgeError::bad_response(format!(
            "HTTP {} — {}",
            status.as_u16(),
            body.chars().take(200).collect::<String>()
        )));
    }
    Ok(body)
}

/// Send a POST request over UDS with a JSON body, return response body as `String`.
pub async fn uds_post(
    socket_path: &PathBuf,
    path: &str,
    session_id: Option<&str>,
    body_json: &str,
) -> BridgeResult<String> {
    let client: Client<hyperlocal::UnixConnector, Full<Bytes>> = Client::unix();
    let uri = unix_uri(socket_path, path);
    let body_bytes = Bytes::copy_from_slice(body_json.as_bytes());

    let mut req_builder = Request::builder()
        .method(Method::POST)
        .uri(uri)
        .header("Host", "localhost")
        .header("Accept", "application/json")
        .header("Content-Type", "application/json")
        .header("Content-Length", body_bytes.len().to_string());

    if let Some(sid) = session_id {
        req_builder = req_builder.header("X-Argos-Session", sid);
    }

    let req = req_builder
        .body(Full::new(body_bytes))
        .map_err(|e| BridgeError::bad_response(e))?;

    let resp: Response<Incoming> = timeout(Duration::from_secs(15), client.request(req))
        .await
        .map_err(|_| BridgeError::daemon_unavailable("POST timed out after 15 s"))?
        .map_err(|e| BridgeError::daemon_unavailable(e))?;

    let status = resp.status();
    let body = collect_body(resp.into_body()).await?;

    if !status.is_success() {
        return Err(BridgeError::bad_response(format!(
            "HTTP {} — {}",
            status.as_u16(),
            body.chars().take(200).collect::<String>()
        )));
    }
    Ok(body)
}

/// Read up to `max_events` data-lines from an SSE stream over UDS.
///
/// Returns a `Vec<String>` where each element is the raw JSON string from a
/// `data: <json>` SSE line.  The frontend's `parse.ts` handles deserialization.
///
/// Uses raw `tokio::net::UnixStream` (not hyper) because hyper's HTTP/1.1
/// client buffers the full response before returning it — it does not expose
/// a streaming interface suitable for SSE.  The raw approach here:
///   1. Opens a `UnixStream`
///   2. Writes a raw HTTP/1.1 GET request with `Accept: text/event-stream`
///   3. Reads bytes in a loop, extracting `data:` lines
///   4. Returns after `max_events` events or when the server closes the conn
///
/// Timeout: 10 s to connect, 30 s per read chunk.
pub async fn uds_sse_batch(
    socket_path: &PathBuf,
    path: &str,
    session_id: Option<&str>,
    max_events: usize,
) -> BridgeResult<Vec<String>> {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::UnixStream;

    let socket_path_str = socket_path
        .to_str()
        .ok_or_else(|| BridgeError::daemon_unavailable("socket path is not valid UTF-8"))?;

    let mut stream = timeout(Duration::from_secs(10), UnixStream::connect(socket_path_str))
        .await
        .map_err(|_| BridgeError::daemon_unavailable("connect timed out after 10 s"))?
        .map_err(|e| BridgeError::daemon_unavailable(e))?;

    // Write raw HTTP/1.1 GET
    let mut req_lines = vec![
        format!("GET {} HTTP/1.1\r\n", path),
        "Host: localhost\r\n".to_string(),
        "Accept: text/event-stream\r\n".to_string(),
        "Cache-Control: no-cache\r\n".to_string(),
    ];
    if let Some(sid) = session_id {
        req_lines.push(format!("X-Argos-Session: {}\r\n", sid));
    }
    req_lines.push("Connection: keep-alive\r\n".to_string());
    req_lines.push("\r\n".to_string());
    let req_raw: String = req_lines.concat();

    stream
        .write_all(req_raw.as_bytes())
        .await
        .map_err(|e| BridgeError::daemon_unavailable(e))?;

    // Read + parse SSE
    let mut buf: Vec<u8> = Vec::with_capacity(8192);
    let mut tmp = [0u8; 2048];
    let mut events: Vec<String> = Vec::new();
    let mut header_done = false;

    loop {
        if events.len() >= max_events {
            break;
        }
        let n = match timeout(Duration::from_secs(30), stream.read(&mut tmp)).await {
            Ok(Ok(0)) => break, // EOF
            Ok(Ok(n)) => n,
            Ok(Err(e)) => return Err(BridgeError::daemon_unavailable(e)),
            Err(_) => break, // per-read timeout → return what we have
        };
        buf.extend_from_slice(&tmp[..n]);

        // Drain complete lines from buf
        loop {
            if let Some(pos) = buf.windows(2).position(|w| w == b"\r\n") {
                let line = String::from_utf8_lossy(&buf[..pos]).to_string();
                buf.drain(..pos + 2);

                if !header_done {
                    if line.is_empty() {
                        header_done = true;
                    }
                    continue;
                }
                // SSE data line
                if let Some(data) = line.strip_prefix("data: ") {
                    events.push(data.to_string());
                    if events.len() >= max_events {
                        break;
                    }
                }
                // skip comment/retry/event-type lines
            } else {
                break; // need more data
            }
        }
    }

    Ok(events)
}
