# Long-running 多 run tabs — 设计规格(spec)

> Road-map entry **#5b** "多 run tabs / 多 TUI 互斥 / worktree-per-run / cost tracking"
> 的设计规格。Road-map 估时 1 周,中等。Builds on **#5a** 长跑 daemon
> (`RunManager` + 7 状态机 + `RunStore` + `SessionRegistry` + HTTP/SSE),在已有
> 1 active run + history 之上,加 **多 run 并发 + TUI tab 切换 + worktree 隔离 + 成本追踪**。
> 灵魂对齐"让便宜模型可靠":并发不是炫技,是同时跑多 agent 时不让单 run 的小成本事件
> 抹掉大 run 的真成本 / 暂停信号。

## 1. 背景与现状

- **v0.1.0 已发** + 7 个未推送 commit(2026-06-06 节点)。1237 测试绿。
- **#5a 长跑 daemon 已落地**:`RunManager` 单例 + `RunStore`(JSONL 持久化)+ `StateIndex`(in-memory +
  落盘)+ 7 状态机 + `RunWorker`(单 run 协程,包 AgentLoop + pause/resume)+ `SessionRegistry`
  (UUID + 30s heartbeat)+ HTTP/SSE server(Unix socket 13 端点)+ `DaemonClient`(TUI 侧 stdlib HTTP)。
- **当前能力**:1 TUI ↔ 1 daemon,daemon 任意时刻**至多 1 active run**。新 run 必须等当前 run
  完成 / 暂停 / 取消。用户视角:`arg start` → 一来一回。
- **缺**:
  1. **多 run 并发**:开 run A 时想开 run B 排错/打补丁 → 只能 Ctrl+B 后台化 A 才能开 B。体验糟糕。
  2. **多 TUI 互斥**:第 2 个 TUI 想 observe 进度 → 当前实现拿 active write 锁(单 TUI 限定),
     必然冲突。需求真实存在:用户在两个 ssh 会话/两个 tab 看同一 daemon。
  3. **worktree 隔离**:多 run 写同一 workspace 互相覆盖 → 不可逆崩溃。`isolation: worktree`
     模式已在 `workflow/` 落地,但 daemon 路径没接。
  4. **成本追踪**:CostUpdate 事件已投,但**没有"按 run 累计"**。多 run 时无法回答"哪个 run 烧钱最多"。

## 2. 目标与非目标

### 2.1 目标(本期)

1. **RunRegistry**:daemon 维护 `run_id → RunEntry` 内存注册表(含 running + suspended + recent
   completed/failed/cancelled,默认保留最近 100 条);每条带 `worktree_path` / `cost_usd` /
   `tokens_in` / `tokens_out` / `tui_focus_session_id`(哪个 TUI 把它当 active 焦点)
2. **多 run 并发 dispatch**:`POST /runs` 在任何时刻可接受(包括已有 5 个 running);
   daemon 维护一个 size-N(默认 5)semaphore,`create_run` 超过容量返 503。
3. **TUI tabs**:顶部 tab strip,1 tab 1 run,4 状态图标(🟢 running / 🟡 paused / ⚪ suspended /
   🔴 failed/cancelled,completed 用 ✓);点击 + Ctrl+1..5 切换焦点;只有 1 个 tab 是 active(收输入)。
4. **多 TUI 互斥**:1 TUI = 1 session。1st TUI 是 owner(全 write 权);2nd TUI 连上变 read-only
   observer(GET /runs / /runs/{id} /events 可读,POST pause/resume/cancel/focus 拿 403);
   owner 退出 → 自动 promote 下一个最旧 observer 为 owner(权限不掉)。
5. **Worktree-per-run**:`POST /runs` body 加可选 `isolation: "worktree"`,daemon 在
   `~/.argos/worktrees/<run_id>/` 起 git worktree(若 workspace 是 git repo)或 temp 目录
   (若不是);run cancelled / completed → 自动 cleanup worktree。RunMeta 持久化 `worktree_path`。
6. **Cost tracking per-run**:`RunMeta` 新增 `tokens_in` / `tokens_out` / `cost_usd` 字段;
   `RunWorker` 监听 `CostUpdate` 事件累加,落盘;SSE 投 `cost_update` 事件已带累计值。
7. **Run control semantics 显式化**:7 端点清单
   ```
   POST   /runs                       # 新建(可选 isolation: worktree)
   GET    /runs?state=running|...     # 列表 + filter
   GET    /runs/{id}                  # 元信息(状态/事件数/成本/worktree)
   GET    /runs/{id}/events?since=N   # SSE(已有)
   POST   /runs/{id}/pause|resume|cancel    # 控制(已有,语义不变)
   POST   /runs/{id}/focus                  # TUI 告诉 daemon "这是我的 active"
   POST   /runs/{id}/approval/{call_id}     # 审批(已有)
   ```
8. **错误处理 / 测试 / 护城河对齐**:沿用已有 spec 风格

### 2.2 非目标(本期不做)

- ❌ **Run 优先级队列 / 抢占**:并发满 → 排队,不做 preempt(语义会变复杂)
- ❌ **跨 daemon 联邦**:1 daemon 1 用户 1 机器,不做 P2P 协作
- ❌ **SQLite 元数据库**:RunStore + StateIndex 已够,不引新 dep
- ❌ **Worktree 持久化跨 daemon 重启**:`worktree_path` 持久化到 JSONL,但 daemon 重启时不
  自动 reattach,recover 只把 run 标 suspended(worktree 由用户手动 /resume 时 reuse)
- ❌ **Cost ceiling 自动 kill**:本期只追踪,超 budget 不自动 cancel(用户自己 /cancel)
- ❌ **Tab 拖拽重排**:本期只 append 顺序 = 创建时间,不做手动拖

## 3. 架构总览

```
                       ┌────────────────────────────────────────┐
                       │              TUI (Textual)             │
                       │  ┌─TabStrip──────────────────────────┐ │
                       │  │ 🟢 run-A  🟡 run-B  ⚪ run-C   │ │
                       │  │  └─active: run-B (Ctrl+1..5/click) │ │
                       │  └──────────────────────────────────┘ │
                       │  ┌Transcript┐  ┌ActivityPanel┐         │
                       │  │(run-B 内容)│ │(cost/worktree)│        │
                       │  └───────────┘  └──────────────┘         │
                       │  [PromptArea → 输入只送 active tab]    │
                       └────────────────┬───────────────────────┘
                                        │ Unix socket
                                        │ X-Argos-Session: <sid>
                                        ▼
              ┌──────────────────────────────────────────────┐
              │            Daemon (asyncio)                  │
              │  ┌─RunRegistry(内存注册表,cap 100)───────┐  │
              │  │ run_id → RunEntry(atomic upsert)      │  │
              │  └────────────────────────────────────────┘  │
              │  ┌─SessionRegistry(UUID,owner/observer)─┐    │
              │  │ 1st session = owner, 2nd..N = observer│   │
              │  │ owner 退出 → promote 最旧 observer    │    │
              │  └────────────────────────────────────────┘   │
              │  ┌─RunWorker pool(N=5 semaphore)────────┐    │
              │  │ worker(run_id) → drive AgentLoop      │   │
              │  │   - 累加 tokens_in/out + cost_usd     │   │
              │  │   - 监听 pause_event + cancel_request │   │
              │  │   - 写 RunCheckpoint + state_change   │   │
              │  │   - 落 RunMeta(worktree_path, cost)   │   │
              │  └────────────────────────────────────────┘   │
              │  ┌─WorktreeManager──────────────────────┐    │
              │  │ create/cleanup ~/.argos/worktrees/<rid> │  │
              │  └────────────────────────────────────────┘   │
              └────────────────┬─────────────────────────────┘
                               ▼
                  ┌─RunStore(JSONL, append-only)─┐
                  │ runs/<run_id>.jsonl          │
                  │ line 0: run_meta             │
                  │ line 1+: events/state_change │
                  └──────────────────────────────┘
```

**关键不变量**:
- **Run 状态真相源 = JSONL tail**,StateIndex 是缓存(沿用 #5a)
- **1 run 1 worker**,不并发驱动同一 run(避免 step 串台/pause 信号二义)
- **多 TUI = 1 owner + N observer**,所有 observer SSE 订阅全 run 流(只读),**不**能调
  focus/pause/resume/cancel(403)
- **Worktree 与 run 寿命绑定**:`completed`/`failed`/`cancelled` 终态 → worker 协程收尾时
  调 `WorktreeManager.cleanup`(失败静默 log,不留垃圾)
- **Cost 累加走 `CostUpdate` 事件**(`tokens_in` / `tokens_out` 是累计值,worker 累加差额;
  `cost_usd` 同样累加;每条 SSE cost_update 事件已带累计,前端展示无需额外请求)

## 4. Run 注册表(daemon 内存)

### 4.1 数据结构

```python
# argos_agent/daemon/registry.py
@dataclass
class RunEntry:
    run_id: str
    state: str
    goal: str
    workspace: str
    worktree_path: str | None     # ← 新
    created_at: float
    updated_at: float
    tokens_in: int                # ← 新,累计
    tokens_out: int               # ← 新,累计
    cost_usd: float | None        # ← 新,累计;API 返 None 时也置 None(不编造)
    focus_session_id: str | None  # ← 新,哪个 TUI session 把它当 active
    task: asyncio.Task | None     # 内部用,worker 句柄
    pause_event: asyncio.Event    # 内部用

class RunRegistry:
    _entries: dict[str, RunEntry]
    _max_concurrent: int = 5      # size-N semaphore
    _max_history: int = 100       # 终态保留 N 条(超过按 created_at 删)
    _sem: asyncio.Semaphore
    _lock: asyncio.Lock
```

### 4.2 API

```python
# 注册(在 create_run 末尾调)
async def register(self, run_id, goal, workspace, worktree_path=None) -> RunEntry: ...

# 取条目(同步读)
def get(self, run_id) -> RunEntry | None: ...
def list(self, state=None) -> list[RunEntry]: ...

# 状态机标记(沿用 RunManager.mark_running/... 但同时维护 registry 副本)
def mark(self, run_id, state: str) -> None: ...

# 累计 cost(worker 调)
def add_cost(self, run_id, *, tokens_in_delta: int, tokens_out_delta: int,
             cost_usd_delta: float) -> None: ...

# focus(POST /runs/{id}/focus)
def set_focus(self, run_id, session_id: str | None) -> None: ...

# semaphore(worker 入口抢)
async def acquire_slot(self) -> None: ...
def release_slot(self) -> None: ...

# 终态清理(worktree + 缩 cap)
async def cleanup(self, run_id) -> None: ...
```

### 4.3 并发不变量

- **asyncio.Lock** 保护 `_entries` dict(read 可不持锁;write 必持)
- **Semaphore size=5**:`create_run` 前 `await self._sem.acquire()`,worker 终态时 `release`
- **max_history=100**:`cleanup` 末尾扫一遍,按 `created_at` 升序,`len > 100` 删最旧(仅删
  `IndexEntry`,不动 JSONL —— JSONL 是真相源,query 仍能 replay)

## 5. 多 run 并发 dispatch

### 5.1 `POST /runs` 流程

```
TUI ─POST /runs {goal, workspace, isolation?}─→ Server
                                              │
                                              ▼
                                RunRegistry.acquire_slot()  ← semaphore.wait()
                                              │ 满 → 503
                                              ▼
                                RunManager.create_run()      ← index + jsonl
                                              │
                                              ▼
                                WorktreeManager.create(workspace)  ← git worktree add
                                              │
                                              ▼
                                RunRegistry.register(worktree_path=...)
                                              │
                                              ▼
                                RunWorker.spawn()           ← asyncio.create_task
                                              │
                                              ▼
                                _sem.release()              ← 不阻塞 return 201
                                              │
                                              ▼
TUI ← {run_id} (201)
```

### 5.2 超载响应

- **503 Service Unavailable** + `{error: "max_concurrent_runs_reached", code: "busy", max: 5, active: 5}`
- TUI 客户端:接 503 → transcript 落一行 `⏸ 已有 5 个 run 在跑,等空闲后再开。`
- **不排队**:本期不实现 FIFO 队列(语义复杂 + 用户更想直接拒绝)

### 5.3 取消与重入

- `POST /runs/{id}/cancel` → worker 协程接 `cancel_requested` → 自然收尾 → `mark_cancelled`
  → `_sem.release()` → 槽位回池
- 终态保留 100 条:超 cap 删最旧 index entry(JSONL 保留供 inspect)

## 6. TUI tabs

### 6.1 视觉规范

```
┌─TabStrip (height 1, 顶贴边)────────────────────────────────────┐
│ 🟢 refactor auth  🟡 refactor logging  ⚪ update deps  ✓ tests  │
│  ^active (bg 高亮)                                              │
└──────────────────────────────────────────────────────────────────┘
```

- **图标语义**:
  - `🟢` running
  - `🟡` paused(用户手动 Esc / Ctrl+B)
  - `⚪` suspended(daemon 优雅退出 / 上次 TUI 失联)
  - `🔴` failed
  - `❌` cancelled
  - `✓` completed
  - `⏳` pending(已 create 还没 worker 起)
- **文本截断**:tab title = `goal[:24]`,超出 `goal[:23] + "…"`
- **顺序**:`created_at` 升序(老 tab 在左,新 tab 在右)
- **滚动**:`> 8` 个 tab 时左右滚动,当前 active 居中(本期:`> N` 仍全显示,超长省略
  右侧 tab,用 `+N more` 提示 —— v1.1 滚动)
- **关闭 tab**:本期不实现(用户用 `/runs {id} cancel` 控制 run 终止即等同"关闭 tab",
  daemon 终态保留 100 条 tab 还在但灰色)

### 6.2 交互

- **鼠标点击 tab**:`TabStrip` 发 `TabActivated(run_id)` 事件 → TUI 调
  `daemon.focus(run_id, session_id)` → 切换 EventBus / SSE 订阅
- **键盘**:`Ctrl+1`..`Ctrl+5` 直接跳第 1..5 tab,`Ctrl+Tab` / `Ctrl+Shift+Tab` 下一/上一
- **active tab 视觉**:背景色用 `theme.accent`(暖橙,与其他 active 指示一致)
- **非 active tab**:暗灰,鼠标 hover 时亮一下
- **cost 在 tab 上**:`🟢 refactor auth  $0.13` —— 简写,精度 2 位小数(> $1 才显示整数位,
  < $0.01 显示 `$<0.01`)

### 6.3 切换 tab 时数据流

```
user 按 Ctrl+2
  ↓
TabStrip.on_key  → post_message(TabActivated(run_id=run_B))
  ↓
ArgosApp._on_tab_activated(run_id):
  1. daemon.focus(run_B, self._daemon_session_id)  ← POST /runs/{id}/focus
  2. 取消旧 run 的 SSE 订阅(self._sse_tasks[run_A].cancel())
  3. 起新 run 的 SSE 订阅(由 manager.subscribe_events 走)
  4. Transcript 清空(本次会话的本地 widget)→ 拉 replay:GET /runs/{id}/events?since=0
     → 重新渲染该 run 的事件(整条 transcript)
  5. Cost / ActivityPanel 同步切到新 run 的累计值
  6. _interrupted / _last_esc_time 全部 reset(避免切 tab 误触发双 Esc cancel)
```

## 7. 多 TUI 互斥

### 7.1 角色模型

```python
class SessionRecord:
    session_id: str
    role: Literal["owner", "observer"]
    created_at: float
    last_heartbeat: float
    last_active_run_id: str | None   # 哪个 run 是它的 active 焦点
```

- **owner** = 第 1 个 session 进来时,自动设为 owner;**observer** = 之后所有连上的 session
- **数量**:`1 owner + N observer`(N 无上限,但 owner 只有一个)
- **owner 退出**:`DELETE /sessions/{id}` → `SessionRegistry.remove(id)` → 自动挑 `list_active()`
  里 `created_at` 最早的 observer promote 为 owner

### 7.2 权限矩阵

| 端点 | owner | observer | 未认证 |
|---|---|---|---|
| `GET /health` / `GET /version` | ✅ | ✅ | ✅ |
| `GET /runs` / `GET /runs/{id}` | ✅ | ✅ | ✅(读公开) |
| `GET /runs/{id}/events`(SSE) | ✅ | ✅ | ❌ 401 |
| `POST /runs` | ✅ | ❌ 403 | ❌ 401 |
| `POST /runs/{id}/focus` | ✅(自己) | ❌ 403 | ❌ 401 |
| `POST /runs/{id}/pause|resume|cancel` | ✅ | ❌ 403 | ❌ 401 |
| `POST /runs/{id}/approval/{call_id}` | ✅ | ❌ 403 | ❌ 401 |

**关键不变量**:
- 1 owner 是**单点**;若 owner 心跳超时(>30s 未 heartbeat)→ 视同退出,promote 最旧 observer
- observer 不该尝试 focus(若它真 focus,daemon 返 403 `code: session_readonly` —— 沿用 #5a D3)
- 端点级别的 403 在 `_require_session` 后加 `_require_owner` helper 检查

### 7.3 端点签名

```python
# 现有 _require_session 之后:
async def _require_owner(self, writer, headers) -> str | None:
    """owner 才放行;observer / unknown → 403"""
    sid = await self._require_session(writer, headers)
    if sid is None:
        return None
    rec = self._sessions.get(sid)
    if rec is None or rec.role != "owner":
        await self._send_error(writer, 403, CODE_SESSION_READONLY,
                               "session is read-only observer (not owner)")
        return None
    return sid
```

## 8. Worktree-per-run

### 8.1 触发条件

`POST /runs` body 字段:

```json
{
  "goal": "refactor auth",
  "workspace": "/path/to/repo",
  "isolation": "worktree"        // ← 新字段,可选;默认 "none"
}
```

- `isolation == "worktree"` + `workspace` 是 git repo → `git worktree add -b argos/<run_id> ~/.argos/worktrees/<run_id> <commit>`
- `isolation == "worktree"` + `workspace` 不是 git repo → fallback:temp 目录(诚实标注 "temp")
- `isolation == "none"`(默认)→ run 直接在 `workspace` 跑(沿用 #5a 行为)

### 8.2 WorktreeManager

```python
# argos_agent/daemon/worktree.py
class WorktreeManager:
    def __init__(self, base_dir: Path = Path.home() / ".argos" / "worktrees"):
        self._base = base_dir
        self._base.mkdir(parents=True, exist_ok=True)

    def create(self, *, run_id: str, workspace: str) -> str:
        """返回 worktree_path。失败抛 WorktreeError(daemon 5xx,run 不创建)。"""
        ...

    def cleanup(self, run_id: str) -> None:
        """git worktree remove + 删除目录。失败静默 log。"""
        ...

    def is_git_repo(self, path: str) -> bool: ...
```

### 8.3 失败模式

- `git` 不在 PATH → WorktreeError
- workspace 没 `.git` 且 `isolation == "worktree"` → 用 `tempfile.mkdtemp(prefix=f"argos-{run_id}-")`,
  RunMeta 标 `worktree_path` + `isolation_fallback: "temp"`
- 创建 worktree 时 git 报错(分支已存在 / 锁文件) → WorktreeError → 503

## 9. Cost tracking per run

### 9.1 数据流

```
AgentLoop.run()
  ↓ 调 LLM API 返 token usage + cost
emit(CostUpdate(tokens_in=N, tokens_out=M, cost_usd=X, elapsed_s=...))
  ↓
RunWorker._on_cost(ev):
  - RunRegistry.add_cost(run_id, tokens_in_delta=N, tokens_out_delta=M, cost_usd_delta=X)
  - RunStore.append(run_id, {...ev, _registry_snapshot: {tokens_in, tokens_out, cost_usd}})  ← 累加值落 JSONL
  - SSE fanout(ev) ← TUI / CostUpdate 已带累计,无需再发
```

### 9.2 字段语义

- `CostUpdate.tokens_in` / `tokens_out` / `cost_usd` 是**本轮 run 累计值**(per-run),不是
  session 累计(沿用 spec 2026-06-06 §1)
- worker 累加:`tokens_in = previous + ev.tokens_in`,`cost_usd = previous + ev.cost_usd`
  (LLM 每次返的 CostUpdate 是**增量**,由 loop 端从 `usage` 字段算)
- `cost_usd is None` 时不累加(`previous + None` = 仍为 None,UI 显示 `$N/A` 沿用 #5a)
- 落 `RunMeta` 时只存初始 0 / 0 / None(由 worker 累加更新到 StateIndex 的 `last_event_seq`
  旁字段 → 本期**不**新增字段到 IndexEntry,改存 JSONL 第一行后面跟一个 `cost_update` 事件)

### 9.3 暴露

- `GET /runs/{id}` body 新增:
  ```json
  {
    "run_id": "abc123",
    "state": "running",
    "tokens_in": 12400,
    "tokens_out": 3100,
    "cost_usd": 0.013,
    "worktree_path": "/Users/zc/.argos/worktrees/abc123",
    "events_count": 12,
    "last_event_seq": 12,
    "goal": "...",
    "workspace": "..."
  }
  ```
- `GET /runs` list 同样带这 4 字段(TUI /runs 命令直接渲染)

## 10. 错误处理

| 失败 | 行为 |
|---|---|
| `POST /runs` workspace 不存在 | 400 `bad_request: workspace not found` |
| `POST /runs isolation=worktree` git 失败 | 503 `worktree_failed: <git stderr>` |
| `POST /runs` 并发满 | 503 `busy: max_concurrent_runs_reached` |
| `POST /runs/{id}/focus` observer 调 | 403 `session_readonly` |
| `POST /runs/{id}/cancel` 已终态 | 409 `invalid_transition`(沿用) |
| Worktree cleanup 失败(分支 lock / 路径占用) | log warning,**不**回滚 run 状态(数据已写,worktree 留待用户手动 `git worktree prune`) |
| Cost 累加时 KeyError / TypeError(loop 投错 event) | worker except 兜底 + log error,**不** crash worker(run 继续) |
| SessionRegistry owner 退出 promote 失败(无 observer) | 不 promote,session 表清空;新 TUI 进来时直接 owner |
| 多 owner 心跳都过期(>30s) | reap_expired 清光;新 TUI 进来变 owner |
| Tab 切换时拉 SSE 失败(daemon 死了) | transcript 落 `⏸ 失去 daemon 连接` + 顶部边框转 ERROR 色 + 终止该 run 渲染 |

## 11. 测试

### 11.1 6 测试文件(总 +50 测试)

| 文件 | 覆盖 | 估测数 |
|---|---|---|
| `tests/test_daemon_registry.py` | RunRegistry 注册/查询/cleanup/max_history/semaphore | 8 |
| `tests/test_daemon_multirun.py` | 多 run 并发 dispatch,POST /runs 满 N → 503,worker pool | 7 |
| `tests/test_daemon_focus.py` | POST /runs/{id}/focus 权限矩阵(owner ✅ / observer ❌) | 5 |
| `tests/test_daemon_sessions_owner.py` | owner 退出 promote observer,observer 限权 | 6 |
| `tests/test_daemon_worktree.py` | WorktreeManager create/cleanup/fallback/non-git | 6 |
| `tests/test_tui_tab_strip.py` | TabStrip widget 渲染 + 键盘 + click 事件 | 8 |
| `tests/test_daemon_cost_tracking.py` | cost 累加 + SSE deltas + GET /runs/{id} 字段 | 6 |
| `tests/test_tui_multirun_focus.py` | tab 切换 → 切 SSE 订阅 + cost 同步 + transcript 切换 | 4 |

### 11.2 端到端铁证

`tests/test_daemon_multirun_e2e.py`:起真 server,3 个 FakeLoop 并发跑 5s,SSE 收到 3 套事件,
GET /runs 看 cost + worktree + state 全部正确。RunRegistry 跑完 cleanup → index 缩到 100 内。

## 12. 决策记录(D1-D20)

| # | 决策 | 选项 | 拍板 | 理由 |
|---|---|---|---|---|
| D1 | 最大并发 run 数 | 5 / 10 / 无上限 | **5** | 内存 + LLM 速率 + 用户认知(> 5 tab 视觉拥挤);可 ARGOS_MAX_CONCURRENT 覆盖 |
| D2 | 超过并发上限 | 503 拒 / FIFO 排队 | **503 直接拒** | 排队语义复杂,用户更想"现在不行"的清晰反馈 |
| D3 | Tab 切换交互 | 鼠标 / 键盘 / 二者 | **二者(默认键盘 Ctrl+1..5,鼠标 click 可选)** | 键盘为 power user,鼠标降低门槛 |
| D4 | Tab 切走时 transcript | 清空重拉 / 缓存 | **清空重拉(replay JSONL)** | 一致性 > 内存,JSONL 是真相源,简单 |
| D5 | Worktree 创建时机 | create_run 时 / 第一次写文件时 | **create_run 时(同步)** | 失败早暴露;daemon 责任清晰 |
| D6 | Worktree 路径格式 | `~/.argos/worktrees/<run_id>` / `<workspace>/.argos-worktrees/<run_id>` | **`~/.argos/worktrees/<run_id>`(中央)** | 多 run 时不会污染 workspace;cleanup 一个 `rm -rf` 完事 |
| D7 | 非 git repo 走 worktree | 拒绝 / temp dir | **temp dir(`tempfile.mkdtemp`)标 `isolation_fallback: temp`** | 不假装支持,诚实标注 fallback |
| D8 | Worktree 终态清理 | 立即 / 24h 后 | **终态立即 cleanup** | 避免磁盘堆积;用户需保留可 `git worktree add` 回来 |
| D9 | Cost 字段精度 | int / float | **float(USD 8 位有效数字)** | 几百美元的 run 也要 $0.000123 精度;沿用 spec 2026-06-06 |
| D10 | Cost 累加失败兜底 | 重试 / 静默 | **静默 + log error + run 继续** | cost 是 nice-to-have,run 主线不依赖 |
| D11 | observer 数上限 | 1 / 5 / 无 | **无(实用:开个 tmux 多 pane 看)** | 内存成本低;竞争也无(只读) |
| D12 | owner 心跳超时 = 退 | 是 / 否 | **是(>30s 未 heartbeat 视同退)** | 沿用 #5a session_timeout_s;无新概念 |
| D13 | owner 退出 promote 策略 | 最早 observer / 最近 observer / 不 promote | **最早 observer(`created_at` 升序,挑最旧)** | 最早 observer 通常最"老"角色,语义自然 |
| D14 | observer focus 403 | 静默 200 / 403 | **403 `code: session_readonly`** | 显式信号,TUI 据此切换 UI 到 "READ-ONLY" 角标 |
| D15 | Tab 切走 SSE 订阅 | 保持订阅 / 取消 | **取消旧 + 订阅新** | 内存节省;切回来时再 subscribe 一次(代价毫秒级) |
| D16 | Tab 切回时 replay 起点 | `since=0` / `since=last_seen_seq` | **`since=0` 重放全**(本期);`since=N` 走增量(v1.1) | 简单;replay 单 run 事件量级小,无 IO 负担 |
| D17 | 多 TUI 同 session_id | 允许 / 拒 | **拒(heartbeat 时校验 session_id 与 record 匹配 → owner 心跳拿自己的 sid,observer 心跳拿自己的 sid,不允许伪造)** | 显式安全;防 observer 抢 owner 角色 |
| D18 | TabStrip 与 status_bar 关系 | 同行 / 单独一行 | **单独一行(Header 之下,Transcript 之上)** | Header 已有 title;sub_title 已有 plan/yolo 标识;tab 是"内容"维度独立 |
| D19 | max_history 缩 cap 时机 | 终态立即 / 定期 1h | **终态立即(cleanup 时扫一遍)** | 简单,100 条上限下不会频繁 |
| D20 | 客户端 fetch 多 run SSE | 1 连接多 run / N 连接 | **1 tab 1 SSE 连接(本期 N=1~5)** | N=5 不算多,Unix socket 单机能扛;N>1 时聚合(v1.1) |

## 13. 风险与未来

- **风险 1**:多 run 共享同一 model client(API key 限速) → 5 个 run 同时打 LLM 可能触发 429。
  缓解:CostUpdate 已记录;本期不重试,429 由 loop 端沿用现有 backoff(若实现);v1.1 加 daemon 端
  集中调度 + 队列。
- **风险 2**:Worktree 路径 collision(用户同 workspace 起 2 个 run,branch 名冲突)→ 我们用
  `argos/<run_id>`(run_id 是 hex 12 位,collision 概率 ~0)。
- **风险 3**:observer 收 SSE 慢(网络差)→ 沿用 #5a fanout 丢策略(`QueueFull` 警告 + replay 补)。
- **未来 v1.1**:Tab 拖拽重排 / cost budget 自动 kill / 多 run 优先级 / N>5 SSE 聚合 / cost
  持久化到独立 `costs.jsonl` 便于分析。

## 14. 实施任务(对应 plan)

8 任务,1 任务 = 1 commit,TDD 闭环:
1. `daemon/registry.py` + RunRegistry(max_history + semaphore + cost/focus 字段)
2. `daemon/server.py` 多 run dispatch + 503 拒 + `POST /runs/{id}/focus` 端点
3. `daemon/sessions.py` owner/observer 角色 + promote 机制 + `CODE_SESSION_READONLY` 复用
4. `daemon/worktree.py` WorktreeManager + git worktree + temp fallback
5. `daemon/worker.py` cost 累加 + worktree cleanup on terminal + focus 更新
6. `daemon/server.py` GET /runs /runs/{id} 返 cost/worktree/focus 字段
7. `tui/widgets/tab_strip.py` + `tui/app.py` 集成(键盘 + 鼠标 + focus POST + SSE 切换)
8. `tui/commands.py` /runs 渲染扩展(cost + worktree + 多 TUI owner/observer 标识)
9. 文档 + CHANGELOG + 验收
