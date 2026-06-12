# P6 桌面端通道 — 接线备忘（2026-06-12）

## 阶段 1 交付物

### `desktop/sdk/` — TypeScript ACP 客户端 SDK

零运行时依赖（仅 Node 内置 `net` 模块）。devDeps：typescript + @types/node + tsx。

#### 文件布局

```
desktop/sdk/
  src/
    types.ts      — Envelope + 全部 Event kind 类型（手工对齐 protocol/events.py）
    parse.ts      — parseEnvelope / parseEvent（未知 kind → {kind:"unknown",raw} 前向兼容）
    client.ts     — DaemonClient（Unix socket HTTP/1.1，mirror server.py 端点）
    index.ts      — 桶式导出
  test/
    vectors.json  — Python 导出的黄金向量（入库，运行时不依赖 Python；
                    export_vectors.py 与 tests/protocol/test_event_golden.py
                    平行维护，并非同一信源——破坏性变更两处需同步更新）
    vectors.test.ts — node:test 向量测试（33 个，全绿）
  scripts/
    export_vectors.py — 只读导出脚本（uv run --no-sync python desktop/sdk/scripts/export_vectors.py）
  package.json    — devDeps + scripts.test
  tsconfig.json   — strict / NodeNext / ES2022
```

#### 协议不变量（SDK 层面执行）

- `VerdictStatus = "passed" | "failed" | "unverifiable"`：三态铁打，SDK 无任何 API 把 `unverifiable` 映射为绿色/成功。
- `ProactiveSuggestionEvent.requires_confirmation`：协议级恒 `true`，TypeScript 类型直接写死 `true` 而非 `boolean`，防止客户端渲染层误用。
- 未知 event kind：`parseEvent` 返回 `{ kind: "unknown", raw: data }` 而非抛错，保前向兼容。

#### DaemonClient 端点 mirror

| SDK 方法 | daemon HTTP 端点 | server.py 行 |
|---|---|---|
| `createSession()` | POST /sessions | ~317 |
| `heartbeat()` | POST /sessions/{id}/heartbeat | ~321 |
| `deleteSession()` | DELETE /sessions/{id} | ~329 |
| `health()` | GET /health | ~305 |
| `listRuns()` | GET /runs | ~336 |
| `createRun()` | POST /runs | ~354 |
| `getRun()` | GET /runs/{id} | ~547 |
| `subscribeEvents()` | GET /runs/{id}/events (SSE) | ~1292 |
| `pause()` | POST /runs/{id}/pause | ~571 |
| `resume()` | POST /runs/{id}/resume | ~579 |
| `cancel()` | POST /runs/{id}/cancel | ~587 |
| `approve()` | POST /runs/{id}/approval/{call_id} | ~612 |
| `planDecision()` | POST /runs/{id}/plan_decision | ~698 |
| `intentConfirm()` | POST /runs/{id}/intent_confirm | ~798 |
| `getLedger()` | GET /runs/{id}/ledger | ~882 |

缺失（未来桌面端阶段补）：/orders CRUD、/suggestions CRUD（P5b 自治面端点，桌面端 UI 建好后再接）。

#### 向量导出再生

当 `argos_agent/protocol/events.py` 或相关 events 文件有 breaking change 时：

```bash
cd <repo_root>
uv run --no-sync python desktop/sdk/scripts/export_vectors.py
# 然后把 desktop/sdk/test/vectors.json 加进 commit
```

---

## 阶段 2 交付物

### `desktop/shell/` — Tauri 2 行走骨架

#### 文件布局

```
desktop/shell/
  src/
    index.html      — 极简 UI（连接状态 + 输入栏 + 事件行列表）
    main.ts         — 前端逻辑（invoke + parseSSELine + 事件渲染）
    acp-types.ts    — vendored copy of sdk/src/types.ts（WebView 无 Node，不能直接 import SDK）
    acp-parse.ts    — vendored copy of sdk/src/parse.ts（同上）
  src-tauri/
    Cargo.toml      — Tauri 2 + hyperlocal 0.9 + hyper 1.x + tokio
    build.rs        — tauri-build
    tauri.conf.json — 窗口 900×650，bundle.active=false（开发骨架不打包）
    icons/icon.png  — 最小 RGBA PNG（Tauri generate_context! 必须存在）
    src/
      lib.rs        — pub mod bridge/commands/state + run() 入口
      main.rs       — #[cfg_attr(mobile,...)] main() 调 run()
      bridge.rs     — UDS HTTP 工具函数（uds_get/uds_post/uds_sse_batch）
      commands.rs   — 所有 #[tauri::command] 函数（子模块隔离，避免 E0255）
      state.rs      — AppState（socket_path + session_id Mutex）
  package.json      — devDeps: @tauri-apps/cli@2 + typescript
  tsconfig.json     — strict / ES2022 / bundler moduleResolution
```

#### 冒烟结果

```
cargo check   → Finished `dev` profile [unoptimized + debuginfo] ✓
tsc --noEmit  → (no output = clean) ✓
npm run check → (no output = clean) ✓
```

#### Tauri Rust 命令桥（为什么要有桥）

WebView 进程无 Node.js 运行时——`DaemonClient`（依赖 `net` 模块）不能在前端直接运行。
Rust 侧代理：

```
前端 invoke("acp_health")
  → Rust commands::acp_health
    → bridge::uds_get(~/.argos/daemon.sock, "/health")
      → hyperlocal UnixConnector + hyper HTTP/1.1
        → argosd 响应 JSON
  → Tauri IPC 返回 serde_json::Value
→ 前端拿到 JSON
```

SSE 流：`bridge::uds_sse_batch` 用裸 `tokio::net::UnixStream`（非 hyper）逐行读 `data:` 并攒批返回，前端每 2s `invoke("acp_events_poll")` 取一批。

#### 依赖选型注释（Cargo.toml 中已注释）

| 包 | 版本 | 选择理由 |
|---|---|---|
| `hyperlocal` | 0.9 | 唯一支持 Unix domain socket 的 hyper connector；reqwest 不支持 UDS |
| `hyper` | 1.x | hyperlocal 0.9 依赖 hyper 1.x API |
| `hyper-util` | 0.1 | `client-legacy` feature 提供 `Client<C, B>` |
| `http-body-util` | 0.1 | `BodyExt::collect()` + `Empty`/`Full` body types |
| `tokio` | 1 | Tauri 2 已有 tokio 运行时；full features 含 `UnixStream` |
| `bytes` | 1 | 传统；与 hyper 1.x 同版本系 |

不需要 openssl/rustls：全部流量本地 UDS，无 TLS。

#### SDK 复用：vendored copy 策略

`types.ts` 和 `parse.ts` 无任何 Node 依赖——复制进 `shell/src/` 即可在 WebView 里用。
命名为 `acp-types.ts` / `acp-parse.ts` 以区分来源。
**维护约定**：当 `desktop/sdk/src/{types,parse}.ts` 因协议 breaking change 更新时，手动同步这两个 vendored 文件。未来用 bundler（vite）可用 workspace symlink 取代 vendored copy。

#### 协议复用对照表（TUI ↔ 桌面端）

| 层 | TUI（Python/Textual） | 桌面端（Tauri/WebView） |
|---|---|---|
| 传输 | `argos_agent/tui/commands.py` → HTTP over `~/.argos/daemon.sock` | Rust `bridge.rs` → HTTP over 同一 socket |
| 序列化 | `protocol/events.py` serialize_event | `acp-parse.ts` parseSSELine（向量测试对齐） |
| 会话 | `X-Argos-Session` header | 同；AppState 存 session_id |
| SSE | Python SSE client 逐行 yield | Rust `uds_sse_batch` 裸 UnixStream 读 `data:` 行 |
| 内核 | argosd（完全不变） | argosd（完全不变） |
| 事件类型 | `tui/events.py`（protocol/events.py shim） | `acp-types.ts`（手工对齐同一 Python 源） |

内核零改动——这是 §11 设计目标的直接体现。

#### Verdict 渲染不变量（诚实红线）

```typescript
// verdictColor() in main.ts — protocol invariant:
// "unverifiable" MUST render amber, NEVER green
if (status === "passed")       return "#22c55e";  // green
if (status === "failed")       return "#ef4444";  // red
if (status === "unverifiable") return "#f59e0b";  // amber ← NOT green
```

SDK 的 `VerdictStatus` 类型无 `null` / `unknown` 逃逸路径。渲染层无法绕过。

---

## 阶段 3 预留（sidecar 打包方案，未实施）

### 问题

开发期：桌面壳连接「已存在的 argosd socket」——用户先手动跑 `uv run argos --with-daemon`。
生产期：需要 Tauri sidecar 自动拉起 argosd，否则用户体验断裂。

### sidecar 方案

**选项 A（推荐）：PyInstaller 单文件 + Tauri sidecar**

1. `argos_agent/__main__.py daemon` 模式已有 PyInstaller spec（`packaging/argos.spec`）。
2. Tauri `tauri.conf.json` 的 `bundle.externalBin` 字段声明 sidecar 二进制路径。
3. Rust 侧用 `tauri-plugin-shell`（`process::Command::new_sidecar("argosd")`) 拉起，
   传 `--socket-path ~/.argos/daemon.sock`；pid 写入 AppState，窗口关闭时 kill。
4. 复杂度：PyInstaller 打包 + 平台签名 + 首次启动慢（Python 解压）。
   → 这是打包新增 client-only 规格所指的主要工作量。

**选项 B（简单）：假设用户已装 `uv`，sidecar = `uv run argos --with-daemon`**

适合开发者用户（argos 的早期受众）。生产阶段再换 A。

**选项 C：Go/Rust 重写 daemon HTTP 层**

不现实——daemon 与 loop/broker/sandbox 深度耦合，重写等于重做整个内核。

### 实施前提

- `tauri-plugin-shell` 加入 Cargo.toml（`features = ["process"]`）。
- `tauri.conf.json` 增加 `bundle.active: true` + `externalBin: ["../argosd"]`。
- sidecar 拉起逻辑：`src-tauri/src/sidecar.rs`（新文件）。
- 需要先完成 `packaging/argos.spec` 验证（已有，见 docs/argos-v6-design.md §12）。

---

## 已知限制（诚实列出）

1. **无 bundler**：`main.ts` 编译成 `dist/main.js`，HTML 用 `<script type="module">` 直接引用。
   Tauri 开发模式下 `frontendDist` 指向 `src/`，需要先 `tsc` 编译；没有热重载。
   生产阶段加 vite。

2. **SSE 长轮询而非真实流**：`acp_events_poll` 每 2s 轮询一次，最多 50 条。
   延迟可接受（本地 socket 2s）但不是真正的推送。
   替换路径：Tauri 的 `app_handle.emit("acp_event", envelope)` 从 Rust SSE 读循环发出，
   前端用 `listen("acp_event", cb)`——wire format 不变。

3. **sidecar 未实施**：开发期需要用户先手动启动 argosd。

4. **DELETE /sessions 实现为 POST**：daemon server.py 对 DELETE 的处理实际上接受任何方法
   到该路径，但正确做法是发 `DELETE` 方法。hyper 桥已有正确 Method 支持，只需把
   `uds_post` 改为 `uds_delete`（1 行）。标记为 TODO。

5. **bundle.active = false**：骨架不生成 .app/.dmg。打包时改为 true 并补 icons 全套尺寸。

6. **icon.png 是占位符**：32×32 纯色 RGBA。生产阶段需要全套 Tauri icon 尺寸。
