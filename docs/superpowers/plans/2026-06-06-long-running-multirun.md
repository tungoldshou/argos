# Long-running 多 run tabs — 实施计划

> Road-map #5b / spec `2026-06-06-long-running-multirun-design.md` 的 TDD 实施计划。
> 9 任务,1 任务 = 1 commit,合计 +50 测试,**0 新外部依赖**(stdlib + asyncio only)。

## 0. 总览

| 任务 | 标题 | 估测 | 关键文件 | 测试文件 |
|---|---|---|---|---|
| T1 | RunRegistry 注册表 + semaphore + max_history | 35 min | `daemon/registry.py`(新) | `test_daemon_registry.py` |
| T2 | 多 run 并发 dispatch + 503 拒 + focus 端点 | 30 min | `daemon/server.py` + `daemon/manager.py` | `test_daemon_multirun.py` + `test_daemon_focus.py` |
| T3 | owner/observer 角色 + promote 机制 | 30 min | `daemon/sessions.py` + `daemon/server.py` | `test_daemon_sessions_owner.py` |
| T4 | WorktreeManager + git worktree + temp fallback | 30 min | `daemon/worktree.py`(新) | `test_daemon_worktree.py` |
| T5 | RunWorker cost 累加 + worktree cleanup + focus 更新 | 25 min | `daemon/worker.py` + `daemon/manager.py` | `test_daemon_cost_tracking.py` |
| T6 | GET /runs /runs/{id} 返 cost/worktree/focus 字段 | 15 min | `daemon/server.py` + `daemon/manager.py` | 集成到 T2 测试 |
| T7 | TUI TabStrip widget + focus POST + SSE 切换 | 40 min | `tui/widgets/tab_strip.py`(新) + `tui/app.py` | `test_tui_tab_strip.py` + `test_tui_multirun_focus.py` |
| T8 | /runs 命令扩展(cost + worktree + observer 标识) | 20 min | `tui/commands.py` + `tui/app.py` | 集成到 T7 测试 |
| T9 | 文档 + CHANGELOG + 验收铁证 | 20 min | `CHANGELOG.md` + `docs/` + `README.md` | `test_daemon_multirun_e2e.py` |

## 1. 任务 T1:RunRegistry 注册表

### 1.1 目标
- 新文件 `argos/daemon/registry.py`
- `RunEntry` dataclass(运行中状态 + 累计 cost + focus + worktree_path)
- `RunRegistry`:register / get / list / mark / add_cost / set_focus / acquire_slot / release_slot / cleanup
- max_concurrent = 5 semaphore,max_history = 100
- 0 新依赖

### 1.2 实现
```python
# argos/daemon/registry.py
from __future__ import annotations
import asyncio, time
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class RunEntry:
    run_id: str
    state: str
    goal: str
    workspace: str
    worktree_path: str | None = None
    created_at: float = 0.0
    updated_at: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float | None = None
    focus_session_id: str | None = None
    task: asyncio.Task | None = field(default=None, repr=False)
    pause_event: asyncio.Event = field(default=None, repr=False)

    def __post_init__(self):
        if self.pause_event is None:
            self.pause_event = asyncio.Event()
            self.pause_event.set()   # 默认不阻塞

class RunRegistry:
    def __init__(self, *, max_concurrent: int = 5, max_history: int = 100):
        self._entries: dict[str, RunEntry] = {}
        self._max_concurrent = max_concurrent
        self._max_history = max_history
        self._lock = asyncio.Lock()
        self._sem = asyncio.Semaphore(max_concurrent)

    @property
    def max_concurrent(self) -> int: return self._max_concurrent

    @property
    def active_count(self) -> int:
        """当前 running 数(非终态)。"""
        return sum(1 for e in self._entries.values() if e.state not in TERMINAL_STATES)

    async def register(self, *, run_id, goal, workspace, worktree_path=None) -> RunEntry: ...
    def get(self, run_id) -> RunEntry | None: ...
    def list(self, *, state=None) -> list[RunEntry]: ...
    def mark(self, run_id, *, state) -> None: ...
    def add_cost(self, run_id, *, tokens_in_delta: int, tokens_out_delta: int,
                 cost_usd_delta: float | None) -> None: ...
    def set_focus(self, run_id, *, session_id: str | None) -> None: ...
    async def acquire_slot(self) -> None: ...
    def release_slot(self) -> None: ...
    async def cleanup(self, run_id) -> None: ...   # 终态时:扣 worktree + 缩 cap
```

### 1.3 RED 测试(`tests/test_daemon_registry.py`)
```python
def test_register_creates_entry(tmp_path)
def test_register_persists_worktree_path(tmp_path)
def test_list_filters_by_state(tmp_path)
def test_mark_updates_state_and_updated_at(tmp_path)
def test_add_cost_accumulates_tokens(tmp_path)
def test_add_cost_with_none_keeps_none(tmp_path)
def test_set_focus_roundtrip(tmp_path)
def test_acquire_and_release_slot_increments_active_count(tmp_path)
def test_max_history_trims_oldest_terminal_runs(tmp_path)
```

### 1.4 GREEN + 验证
```bash
rtk pytest tests/test_daemon_registry.py -v
```

### 1.5 Commit
```
feat(daemon): #5b T1 RunRegistry 注册表 + semaphore + max_history
```

## 2. 任务 T2:多 run 并发 dispatch + focus 端点

### 2.1 目标
- `daemon/server.py` `POST /runs` 集成 `RunRegistry.acquire_slot`
- 并发满 → 503 `busy`
- `POST /runs/{id}/focus` 新端点(本期不验 owner — T3 补)
- `RunManager.create_run` 末尾 `RunRegistry.register` 自动联动

### 2.2 实现
```python
# daemon/server.py _handle_create_run
async def _handle_create_run(self, writer, headers, body):
    if (sid := await self._require_session(writer, headers)) is None:
        return
    # ... parse body ...
    # 新增:并发满 → 503
    if not self._registry._sem.locked() and self._registry.active_count >= self._registry.max_concurrent:
        return await self._send_error(writer, 503, "busy", ...)
    # acquire slot(非阻塞,内部 try acquire)
    if not await self._try_acquire_slot():
        return await self._send_error(writer, 503, "busy", ...)
    try:
        run_id = await self._manager.create_run(goal=goal, ...)
        worktree_path = self._worktree.create(run_id=run_id, workspace=workspace) if isolation == "worktree" else None
        await self._registry.register(run_id=run_id, goal=goal, workspace=workspace, worktree_path=worktree_path)
        # spawn worker(if loop_factory injected)
        ...
    except Exception:
        self._registry._sem.release()  # 失败时还 slot
        raise

async def _handle_focus(self, writer, headers, run_id):
    if (sid := await self._require_session(writer, headers)) is None:
        return
    if not self._registry.get(run_id):
        return await self._send_error(writer, 404, ...)
    self._registry.set_focus(run_id, session_id=sid)
    await self._send_json(writer, 200, {"run_id": run_id, "focus_session_id": sid})
```

### 2.3 RED 测试(`tests/test_daemon_multirun.py` + `test_daemon_focus.py`)
```python
# test_daemon_multirun.py
def test_create_run_returns_id(server)
def test_concurrent_create_runs_all_register(server, tmp_path)
def test_post_runs_returns_503_when_max_reached(server)
def test_post_runs_after_cancel_frees_slot(server)
def test_post_runs_with_isolation_creates_worktree(server, tmp_path)
def test_post_runs_workspace_not_found_returns_400(server, tmp_path)
def test_active_count_decrements_on_terminal(server)

# test_daemon_focus.py
def test_focus_endpoint_sets_session(server)
def test_focus_unknown_run_returns_404(server)
def test_focus_omits_owner_check_for_now(server)   # placeholder for T3
def test_focus_round_trip(server)
def test_multiple_focus_calls_last_wins(server)
```

### 2.4 GREEN + Commit
```
feat(daemon): #5b T2 多 run 并发 dispatch + 503 拒 + /runs/{id}/focus 端点
```

## 3. 任务 T3:owner/observer 角色 + promote

### 3.1 目标
- `SessionRecord` 加 `role` + `last_active_run_id` 字段
- 第 1 个 session = owner;之后 = observer
- `DELETE /sessions/{id}` 时若删的是 owner → promote 最旧 observer
- `SessionRegistry.promote_oldest_observer() -> str | None`(返新 owner session_id)
- `_require_owner` helper
- 所有写端点(POST /runs, /focus, /pause, /resume, /cancel, /approval)改用 `_require_owner`

### 3.2 实现
```python
# daemon/sessions.py
from typing import Literal

@dataclass
class SessionRecord:
    session_id: str
    last_heartbeat: float
    created_at: float
    role: Literal["owner", "observer"] = "observer"
    last_active_run_id: str | None = None

class SessionRegistry:
    async def create(self) -> SessionRecord:
        async with self._lock:
            role = "owner" if not self._sessions else "observer"
            rec = SessionRecord(session_id=str(uuid.uuid4()),
                                last_heartbeat=time.time(),
                                created_at=time.time(),
                                role=role)
            self._sessions[rec.session_id] = rec
            return rec

    async def promote_oldest_observer(self) -> str | None:
        async with self._lock:
            observers = [r for r in self._sessions.values() if r.role == "observer"]
            if not observers:
                return None
            oldest = min(observers, key=lambda r: r.created_at)
            oldest.role = "owner"
            return oldest.session_id

    async def remove(self, session_id) -> str | None:
        """返被删 session 的 role(若 owner 则上层需 promote)。"""
        async with self._lock:
            rec = self._sessions.pop(session_id, None)
            return rec.role if rec else None

# daemon/server.py
async def _require_owner(self, writer, headers) -> str | None:
    sid = await self._require_session(writer, headers)
    if sid is None:
        return None
    rec = self._sessions.get(sid)
    if rec is None or rec.role != "owner":
        await self._send_error(writer, 403, CODE_SESSION_READONLY, "...")
        return None
    return sid
```

### 3.3 RED 测试(`tests/test_daemon_sessions_owner.py`)
```python
def test_first_session_is_owner()
def test_second_session_is_observer()
def test_remove_owner_promotes_oldest_observer()
def test_remove_owner_no_observer_leaves_empty()
def test_remove_observer_does_not_promote()
def test_require_owner_blocks_observer()
def test_focus_endpoint_blocks_observer_with_403()
def test_pause_endpoint_blocks_observer_with_403()
def test_cancel_endpoint_blocks_observer_with_403()
def test_create_run_blocks_observer_with_403()
```

### 3.4 GREEN + Commit
```
feat(daemon): #5b T3 owner/observer 角色 + promote 机制 + _require_owner
```

## 4. 任务 T4:WorktreeManager

### 4.1 目标
- 新文件 `argos/daemon/worktree.py`
- `create(run_id, workspace) -> str | None`:git worktree add 或 temp 目录
- `cleanup(run_id) -> None`:git worktree remove + 删目录,失败静默
- `is_git_repo(workspace) -> bool`

### 4.2 实现
```python
# daemon/worktree.py
from __future__ import annotations
import logging, shutil, subprocess, tempfile
from pathlib import Path

log = logging.getLogger(__name__)

class WorktreeError(Exception): ...

class WorktreeManager:
    def __init__(self, base_dir: Path | None = None):
        self._base = base_dir or (Path.home() / ".argos" / "worktrees")
        self._base.mkdir(parents=True, exist_ok=True)

    def is_git_repo(self, workspace: str) -> bool:
        return (Path(workspace) / ".git").exists()

    def create(self, *, run_id: str, workspace: str) -> str:
        path = self._base / run_id
        if self.is_git_repo(workspace):
            # git worktree add -b argos/<run_id> <path> HEAD
            try:
                subprocess.run(
                    ["git", "worktree", "add", "-b", f"argos/{run_id}", str(path), "HEAD"],
                    cwd=workspace, check=True, capture_output=True, text=True, timeout=10,
                )
            except subprocess.CalledProcessError as e:
                raise WorktreeError(f"git worktree add failed: {e.stderr}") from e
            except FileNotFoundError:
                raise WorktreeError("git not in PATH")
            return str(path)
        # 非 git repo → temp dir
        temp = Path(tempfile.mkdtemp(prefix=f"argos-{run_id}-", dir=self._base))
        return str(temp)

    def cleanup(self, run_id: str) -> None:
        path = self._base / run_id
        if not path.exists():
            return
        try:
            if (path / ".git").is_file() or (path / ".git").is_dir():
                # 找到 git repo root(workspace 的 .git)
                ws_git = path / ".git"
                if ws_git.exists():
                    # 用 worktree 自身 .git 里的 gitdir 找原 repo
                    try:
                        subprocess.run(
                            ["git", "worktree", "remove", "--force", str(path)],
                            check=False, capture_output=True, text=True, timeout=10,
                        )
                    except Exception:
                        pass
            shutil.rmtree(path, ignore_errors=True)
        except Exception as e:  # noqa: BLE001
            log.warning("worktree cleanup failed for %s: %s", run_id, e)
```

### 4.3 RED 测试(`tests/test_daemon_worktree.py`)
```python
def test_is_git_repo_true(tmp_path)
def test_is_git_repo_false(tmp_path)
def test_create_git_worktree(tmp_path)        # 真 git init + worktree add
def test_create_non_git_uses_temp(tmp_path)
def test_create_fails_when_git_missing(monkeypatch, tmp_path)
def test_cleanup_removes_directory(tmp_path)
def test_cleanup_nonexistent_is_noop(tmp_path)
def test_cleanup_force_removes_locked_worktree(tmp_path)
```

### 4.4 GREEN + Commit
```
feat(daemon): #5b T4 WorktreeManager + git worktree + temp fallback + cleanup
```

## 5. 任务 T5:RunWorker cost 累加 + cleanup + focus

### 5.1 目标
- `RunWorker.run` 累加 `tokens_in` / `tokens_out` / `cost_usd` 到 `RunRegistry.add_cost`
- 终态时(`completed` / `failed` / `cancelled` / `suspended`)调 `WorktreeManager.cleanup`
- `RunRegistry.release_slot` 在终态收尾
- `mark_suspended` 时同样调 cleanup(daemon 优雅退出时)

### 5.2 实现
```python
# daemon/worker.py
class RunWorker:
    def __init__(self, *, run_id, manager, loop_factory, registry, worktree):
        self._registry = registry
        self._worktree = worktree
        ...

    async def run(self) -> None:
        # mark_running
        ...
        try:
            async for ev in self._loop.run(...):
                if ev.get("kind") == "cost_update":
                    self._registry.add_cost(
                        self.run_id,
                        tokens_in_delta=ev.get("tokens_in", 0),
                        tokens_out_delta=ev.get("tokens_out", 0),
                        cost_usd_delta=ev.get("cost_usd"),
                    )
                # ... serialize + fanout ...
            # 终态
            if self._manager.index.get(self.run_id).state not in TERMINAL_STATES:
                ...
        finally:
            # 收尾:release slot + cleanup worktree
            cur = self._manager.index.get(self.run_id)
            if cur and cur.state in TERMINAL_STATES:
                self._registry.release_slot()
                self._worktree.cleanup(self.run_id)
                await self._registry.cleanup(self.run_id)   # 缩 cap
```

### 5.3 RED 测试(`tests/test_daemon_cost_tracking.py`)
```python
def test_cost_event_accumulates_to_registry(server, tmp_path)
def test_cost_event_with_none_keeps_none(server, tmp_path)
def test_multiple_cost_events_sum(server, tmp_path)
def test_terminal_state_triggers_worktree_cleanup(server, tmp_path)
def test_terminal_state_releases_semaphore_slot(server, tmp_path)
def test_get_run_includes_cost_and_worktree_fields(server, tmp_path)
def test_list_runs_includes_cost_and_worktree(server, tmp_path)
```

### 5.4 GREEN + Commit
```
feat(daemon): #5b T5 RunWorker cost 累加 + worktree cleanup + slot release
```

## 6. 任务 T6:GET /runs /runs/{id} 返 cost/worktree/focus 字段

### 6.1 目标
- `_handle_list_runs` + `_handle_get_run` 从 `RunRegistry` 读 cost + worktree + focus_session_id,合并到响应

### 6.2 实现
```python
# daemon/server.py
async def _handle_list_runs(self, writer, headers, query):
    ...
    runs = self._manager.list_runs(state=state_filter)
    # merge registry
    enriched = []
    for r in runs:
        entry = self._registry.get(r["run_id"])
        if entry:
            r["tokens_in"] = entry.tokens_in
            r["tokens_out"] = entry.tokens_out
            r["cost_usd"] = entry.cost_usd
            r["worktree_path"] = entry.worktree_path
            r["focus_session_id"] = entry.focus_session_id
        enriched.append(r)
    await self._send_json(writer, 200, enriched)

async def _handle_get_run(self, writer, headers, run_id):
    ...
    entry = self._registry.get(run_id)
    if entry is None:
        return await self._send_error(writer, 404, ...)
    await self._send_json(writer, 200, {
        "run_id": run_id,
        "state": entry.state,
        "tokens_in": entry.tokens_in,
        "tokens_out": entry.tokens_out,
        "cost_usd": entry.cost_usd,
        "worktree_path": entry.worktree_path,
        "focus_session_id": entry.focus_session_id,
        "events_count": self._manager.events_count(run_id),
        "last_event_seq": entry.last_event_seq,
        "goal": entry.goal,
        "workspace": entry.workspace,
    })
```

### 6.3 RED 测试(在 T2 + T5 测试中加,新文件)
```python
# tests/test_daemon_cost_tracking.py 加
def test_list_runs_response_shape_includes_new_fields(server, tmp_path)
def test_get_run_response_shape_includes_new_fields(server, tmp_path)
```

### 6.4 GREEN + Commit
```
feat(daemon): #5b T6 GET /runs + /runs/{id} 返 cost/worktree/focus 字段
```

## 7. 任务 T7:TUI TabStrip widget + focus POST + SSE 切换

### 7.1 目标
- 新文件 `argos/tui/widgets/tab_strip.py`
- `TabStrip(Widget)`:`Static` 或 `Horizontal` 包 `Button` 列表,每个 button 显示 icon + title + cost
- 鼠标 click → `post_message(TabActivated(run_id))`
- 键盘 `Ctrl+1`..`Ctrl+5` 跳第 1..5 tab
- TUI `app.py` 集成:
  - `on_mount` 后 mount TabStrip
  - `_on_tab_activated(run_id)` → POST /focus + 切 SSE 订阅 + 清 transcript + replay
  - `BINDINGS` 加 `ctrl+1`..`ctrl+5`

### 7.2 实现
```python
# tui/widgets/tab_strip.py
from textual.message import Message
from textual.widgets import Static
from textual.containers import Horizontal

class TabActivated(Message):
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        super().__init__()

class TabStrip(Static):
    DEFAULT_CSS = """
    TabStrip { height: 1; background: $surface; }
    TabStrip .active { background: $accent; color: $background; }
    """
    BINDINGS = [
        ("ctrl+1", "select_tab(0)"),
        ("ctrl+2", "select_tab(1)"),
        ("ctrl+3", "select_tab(2)"),
        ("ctrl+4", "select_tab(3)"),
        ("ctrl+5", "select_tab(4)"),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._tabs: list[dict] = []   # [{run_id, title, icon, cost, state, active}]
        self._active: str | None = None

    def update_tabs(self, tabs: list[dict], active: str | None) -> None: ...
    def action_select_tab(self, idx: int) -> None: ...
    def on_click(self, event) -> None: ...
    def render(self) -> str: ...   # 拼一行文本 tab strip
```

### 7.3 RED 测试(`tests/test_tui_tab_strip.py` + `test_tui_multirun_focus.py`)
```python
# test_tui_tab_strip.py
def test_tab_strip_renders_5_tabs()
def test_tab_strip_renders_with_active_highlight()
def test_tab_strip_icon_for_each_state()
def test_tab_strip_truncates_long_goal()
def test_tab_strip_includes_cost()
def test_tab_strip_post_activated_message_on_click()
def test_tab_strip_action_select_tab_0_to_4()
def test_tab_strip_ctrl_5_noop_when_fewer_tabs()

# test_tui_multirun_focus.py
def test_app_calls_focus_on_tab_change(tmp_path)
def test_app_cancels_old_sse_subscribes_new(tmp_path)
def test_app_replays_run_events_on_focus(tmp_path)
def test_app_updates_cost_on_focus_change(tmp_path)
```

### 7.4 GREEN + Commit
```
feat(tui): #5b T7 TabStrip widget + focus POST + SSE 切换 + Ctrl+1..5
```

## 8. 任务 T8:/runs 命令扩展

### 8.1 目标
- `app.py` `_runs_cmd` 扩展:列所有 run 时显示 icon + state + cost + worktree_path
- owner TUI 走原路径;observer TUI 显 `READ-ONLY` 标识(无 focus 权限)
- `/runs {id} focus` 新增 action:observer 调 403 + 显 "只读 TUI"

### 8.2 实现
```python
# tui/app.py
async def _runs_cmd(self, log, arg):
    ...
    # 检测 observer 身份
    if self._daemon_session_id and self._daemon_sessions:
        role = self._daemon_sessions.get(self._daemon_session_id, {}).get("role")
        if role == "observer":
            await log.append_line("🔒 READ-ONLY 观察者:不能 focus / pause / cancel。", kind="system")
    ...
    # 列 run
    for r in runs:
        icon = {"running": "🟢", "paused": "🟡", ...}.get(r["state"], "⚪")
        cost = _format_cost(r.get("cost_usd"))
        wt = r.get("worktree_path") or ""
        wt_short = wt.split("/")[-1] if wt else "(none)"
        lines.append(f" · {icon} {r['run_id']}  {r['state']:<10}  {r['goal'][:32]}  {cost}  [{wt_short}]")
```

### 8.3 RED 测试(集成到 T7 + T8 测试)
```python
# tests/test_tui_multirun_focus.py 加
def test_runs_command_shows_all_5_runs_with_cost_and_worktree(tmp_path)
def test_runs_command_observer_shows_readonly_banner(tmp_path)
def test_runs_command_owner_can_focus(tmp_path)
def test_runs_command_observer_focus_returns_403(tmp_path)
```

### 8.4 GREEN + Commit
```
feat(tui): #5b T8 /runs 扩展(cost + worktree + owner/observer 标识 + focus action)
```

## 9. 任务 T9:文档 + CHANGELOG + 验收铁证

### 9.1 目标
- `CHANGELOG.md` `[Unreleased]` 增 1 段
- `docs/multirun.md` 用户文档(简明,例子为主)
- README 段:多 run tabs 截图占位(本期不真截图,文字描述)
- 端到端铁证:`tests/test_daemon_multirun_e2e.py`
- 跑全 pytest 确认 +50 测试绿

### 9.2 实现
- 文档照 `docs/auto-memory.md` 风格
- 端到端铁证:5 个 FakeLoop 并发跑 → GET /runs 看 5 条 → /focus 切换 → /pause 限权测试

### 9.3 验收
- [ ] `rtk pytest tests/ -q` 全绿,测试数 1237 → ~1287(+50,含 1 e2e)
- [ ] `rtk pytest tests/test_daemon_registry.py tests/test_daemon_multirun.py tests/test_daemon_sessions_owner.py tests/test_daemon_worktree.py tests/test_daemon_cost_tracking.py tests/test_tui_tab_strip.py tests/test_tui_multirun_focus.py -v` 全绿
- [ ] 端到端:server up,3 个 FakeLoop 并发 5s,SSE 收 3 套事件,GET /runs 看到 cost + worktree + state
- [ ] CHANGELOG 段已加
- [ ] git log 含 9 个新 commit

### 9.4 Commit
```
docs: #5b T9 多 run tabs 文档 + CHANGELOG + 验收铁证
```

## 10. 风险与回退

- 任何任务失败(测试不绿、server 集成炸)→ **该任务 commit revert**,不进 T+1
- 护栏:`RunRegistry` 改动若让现有 daemon 集成测试回归 → 立即 revert T1
- T3 `_require_owner` 替换 `_require_session` 时,**所有现有写端点都需改**,漏改会让 observer
  能写。回归测试覆盖:observer 调 POST /pause 必须 403(现有 test_daemon_server.py 中
  `test_pause_request_returns_202` 等需改用 owner 身份或确保测试 sid 是 owner)。
- 不在 spec/plan 允许范围外的文件(除 `daemon/registry.py` / `worktree.py` /
  `tui/widgets/tab_strip.py` 新文件 + `tui/commands.py` 改 + 既有 daemon/tui 文件扩展)
  不做任何改动

## 11. 时间线与并行

- 9 任务串行(每任务内部全 TDD 闭环)
- T1 → T2 → T3 串行(registry 才有 server 集成;owner/observer 才让 server 限权完整)
- T4 独立,可在 T1 后并行(测试 git,慢一点)
- T5 等 T2 + T4 都完
- T6 紧跟 T5
- T7 / T8 紧跟 T5 + T6

## 12. 完成判据

- [ ] 9 commit 全推本地(不 push remote)
- [ ] 测试数 1237 → 1287+(+50,含 1 e2e)
- [ ] CHANGELOG Unreleased 含 #5b 段
- [ ] `docs/multirun.md` 用户文档存在
- [ ] 端到端铁证 1 份(test 输出)
- [ ] 5 并发 FakeLoop + 3 TUI 互斥 端到端断言在 e2e 测试中绿
