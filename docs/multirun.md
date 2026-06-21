# 多 run tabs (Long-running Multi-run Tabs) — 用户文档

> #5b 实施。从 v0.1.0 起,Argos 1 个 daemon 进程可同时跑 **最多 5 个 run**,TUI 顶部 tab 条切换 active,
> 多 TUI 互斥(1 owner 写 + N observer 读),worktree 自动隔离,每 run 累计 cost 实时显示。

## 1. 用法

### 1.1 启动 TUI（daemon 自动探测）

```bash
argos
```

TUI 启动时自动探测本地 daemon socket（`probe_or_spawn`）：已在运行则复用；
未运行则尝试拉起 `argosd` 子进程并等待就绪（最多 3s）；拉起失败则退回 inline
单进程模式（状态栏显 `inline`）。**不需要也不存在 `--with-daemon` 标志。**

起手时,顶部出现一行 tab 条(只有当前 run,1 个 tab):

```
┌─TabStrip──────────────────────────────────────────────────────────────────────┐
│ ⏳ refactor auth  $N/A                                                          │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 开第 2 个 run

直接在 prompt 输入新 goal(无需 Ctrl+B 后台化当前 run):

```
› refactor logging module
```

daemon 接 POST /runs,新建第 2 个 run,tab 条变 2 个:

```
🟢 refactor auth  $0.013  |  🟢 refactor logging  $N/A
```

### 1.3 切换 active run

- **键盘**:`Ctrl+1` 跳第 1 个 tab,`Ctrl+2` 跳第 2 个,`Ctrl+3..5` 跳 3-5;`Ctrl+Tab` 下一个,`Ctrl+Shift+Tab` 上一个
- **鼠标**:点击 tab 区域
- **命令**:`/runs` 看所有 run,`/runs {id} focus` 切到指定 run

切换后:
- transcript 落 `━━━ 切到 run xxxxxxx… ━━━`
- 活动栏 / 状态栏 / 输入框全部切到新 run 的上下文
- cost 显示切到新 run 的累计值

### 1.4 控制 run

- `/runs {id} resume` — 恢复 paused run
- `/runs {id} cancel` — 取消 run(终态 cancelled)
- `Esc` — 当前 run pause(step 边界)
- `Ctrl+B` — 当前 run 后台化(suspended)

### 1.5 状态图标

| 图标 | 状态 | 含义 |
|---|---|---|
| 🟢 | running | 正在跑 |
| 🟡 | paused | 用户按 Esc(step 边界暂停) |
| ⚪ | suspended | 后台化 / daemon 退出 / TUI 失联 |
| ⏳ | pending | 已建还没 worker 起 |
| ✓ | completed | 跑完 |
| 🔴 | failed | 异常 |
| ❌ | cancelled | 用户取消 |

## 2. 多 TUI 互斥(1 daemon ↔ N TUI)

你可以在多个 ssh 会话 / tmux pane / tab 各开一个 `argos` 连同一 daemon:

- **第 1 个连上的** = `owner`(全写权限,跟单 TUI 一样)
- **第 2..N 个** = `observer`(只读,GET /runs /runs/{id} /events 都可,POST 全 403)

observer TUI 的 `/runs` 命令会显 `🔒 READ-ONLY 观察者`;focus / pause / cancel 全 403。

owner 退出(TUI 关 / 网络断)→ **最旧 observer 自动 promote** 为新 owner,继续可用。

> **前向兼容说明**:daemon 的 ACP session/owner-observer 协议是客户端无关的；任何协议客户端接入时 owner/observer/promote 语义不变。

## 3. Worktree 隔离

开 run 时显式要 worktree:

```json
POST /runs
{
  "goal": "refactor auth",
  "workspace": "/Users/zc/projects/myrepo",
  "isolation": "worktree"
}
```

daemon 行为:
- workspace 是 git repo → `git worktree add -b argos/<run_id> ~/.argos/worktrees/<run_id> HEAD`
- workspace 不是 git repo → `tempfile.mkdtemp(prefix=argos-<run_id>-, dir=~/.argos/worktrees)` 兜底
- run 终态 → 自动 cleanup(失败静默)

**每 run 持有独立的沙箱上下文**:daemon 通过 `build_run_stack()` 为每个 run 分配各自的 `SeatbeltExecutor`、`ApprovalGate`、`CapabilityBroker`——并发 run 之间不共享任何可变沙箱状态。

`/runs {id} info` 显示 worktree_path 短名。

## 4. Cost tracking

每 run 累计 `tokens_in` / `tokens_out` / `cost_usd`:
- `cost_update` 事件自动累加
- `cost_usd = None` 时不累加(API 没返,UI 显 `$N/A`)
- tab 条 + 活动栏实时显示
- 终态保留 100 条,超 cap 按 created_at 删最旧

`cost_usd` 简写规则:
- `< $0.01` → `$<0.01`
- `0.01 - 0.999` → `$0.050` / `$0.123` (3 位小数)
- `>= $1` → `$1.50` / `$10.12` (2 位小数)
- `None` → `$N/A`

## 5. 限制

- **最多 5 个并发 run**:超过 → 503 `busy: max_concurrent_runs_reached (max=5, active=5)`(直接拒,**不排队**)
- **1 owner + N observer**:observer 写端点全 403
- **worktree 路径**:`~/.argos/worktrees/<run_id>`(中央,不污染 workspace)
- **保留 100 条历史**:超 cap 按 created_at 升序删最旧
- **多 TUI 角色**:owner 退出 promote 最旧 observer;心跳 30s 过期视同退出

## 6. 故障排查

| 现象 | 原因 | 解决 |
|---|---|---|
| `503 busy` | 5 个 run 全在跑 | 取消 / 后台化 / 等待 |
| `403 session_readonly` | observer 调了写端点 | 找 owner TUI 调,或等 owner 退出自动 promote |
| `404 not_found` (focus) | run_id 不存在 | `/runs` 查正确 id |
| tab 切走时 transcript 残留旧 run 文本 | 重放走 SSE 订阅,延迟到订阅建立 | 等下个 tick 自动重放 |
| worktree 终态没清 | git worktree 锁 | `git worktree prune` 手动 |

## 7. 内部接口(给开发者)

| 端点 | 方法 | owner | observer |
|---|---|---|---|
| `/health` | GET | ✅ | ✅ |
| `/runs` | GET | ✅ | ✅ |
| `/runs/{id}` | GET | ✅ | ✅ |
| `/runs/{id}/events` | GET (SSE) | ✅ | ✅ |
| `/runs` | POST | ✅ | ❌ 403 |
| `/runs/{id}/focus` | POST | ✅ | ❌ 403 |
| `/runs/{id}/pause|resume|cancel` | POST | ✅ | ❌ 403 |
| `/runs/{id}/approval/{call_id}` | POST | ✅ | ❌ 403 |
| `/sessions` | POST | ✅ | ✅ |
| `/sessions/{id}` | DELETE | (anyone) | (anyone) |

## 8. 不做(当前未计划)

- ❌ FIFO 排队(超 5 → 排队) — 本期直接拒
- ❌ Tab 拖拽重排 — 顺序 = created_at
- ❌ Cost budget 自动 kill — 用户自己 cancel
- ❌ N>5 SSE 聚合 — 1 tab 1 连接
- ❌ 跨 daemon 联邦
- ❌ 持久化 SQLite 元数据库(沿用 JSONL)

## 9. 实现位置

- `argos/daemon/registry.py` — RunRegistry
- `argos/daemon/worktree.py` — WorktreeManager
- `argos/git_worktree.py` — 底层 git worktree 原语(WorktreeManager 调用)
- `argos/daemon/sessions.py` — owner/observer + promote
- `argos/daemon/server.py` — 5 端点扩 + 503 拒
- `argos/daemon/worker.py` — cost 累加 + 终态 cleanup
- `argos/tui/widgets/tab_strip.py` — TabStrip widget
- `argos/tui/app.py` — `_on_tab_activated` + `/runs` 扩展
- spec: `docs/superpowers/specs/2026-06-06-long-running-multirun-design.md`
- plan: `docs/superpowers/plans/2026-06-06-long-running-multirun.md`
