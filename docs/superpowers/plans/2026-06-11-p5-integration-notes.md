# P5 自治面集成注记

本文件记录 `conductor/` 纯逻辑包完成后、集成阶段统一接线时需要处理的接入点。
实现者：conductor/ 独立轨（P5 并行轨），不触碰禁区文件。

---

## 交付清单（P5 并行轨）

| 文件 | 职责 |
|---|---|
| `argos/conductor/__init__.py` | 公开 API |
| `argos/conductor/orders.py` | `StandingOrder` + `OrderStore` JSONL 持久化 |
| `argos/conductor/cronlite.py` | 零依赖 cron-lite（`next_due`）|
| `argos/conductor/triggers.py` | `FileTriggerWatcher` + `FileTriggerFact` |
| `argos/conductor/proposals.py` | `ProactiveSuggestion` + `propose()` |
| `argos/conductor/engine.py` | `ConductorEngine`（`tick()` 驱动）|
| `tests/conductor/*.py` | 119 测试全绿 |

---

## 1. Daemon 接线方案

### 1.1 conductor loop 宿主在 daemon

**接入文件**：`argos/daemon/worker.py`（或 daemon 主循环）

ConductorEngine 应在 daemon 进程内以独立后台协程（asyncio task）运行，与 RunWorker 共享同一进程但不共享线程（使用 `asyncio.create_task`）。

推荐接线骨架（概念伪代码，集成阶段在 daemon 侧实现）：

```python
# daemon/__init__.py 或 daemon/supervisor.py（集成阶段新建）
import asyncio
import time
from argos.conductor import ConductorEngine, OrderStore
from pathlib import Path

async def conductor_loop(
    store: OrderStore,
    *,
    tick_interval: float = 30.0,   # 每 30s tick 一次，减少空转
    suggestion_queue: asyncio.Queue,
):
    """后台 conductor loop，产出 suggestion → 推入 queue，由 HTTP SSE 路由消费。"""
    engine = ConductorEngine(store, clock=time.time)
    while True:
        now = time.time()
        suggestions = engine.tick(now)
        for s in suggestions:
            await suggestion_queue.put(s)
        await asyncio.sleep(tick_interval)
```

**装配位置**：daemon `startup()` 中，与 registry / server 同批启动：

```python
suggestion_queue: asyncio.Queue[ProactiveSuggestion] = asyncio.Queue()
conductor_store = OrderStore(daemon_home / "conductor")
asyncio.create_task(conductor_loop(conductor_store, suggestion_queue=suggestion_queue))
```

### 1.2 并发槽位与 Scheduler 优先级

- conductor 产出的 run 使用现有 daemon registry 的并发槽位（与普通 run 共享）。
- 建议 conductor-triggered run 优先级低于用户手动触发 run（可在 `create_run` 中传 `priority="low"`）。
- 当 daemon 槽位满时，ProactiveSuggestion 在 queue 中等待；用户确认时再 `create_run`，不预占槽位。

---

## 2. POST /orders CRUD 端点

**接入文件**：`argos/daemon/server.py`（ACP HTTP 路由）

新增 4 个端点（RESTful），集成阶段在 server.py 中注册：

```
POST   /orders           → OrderStore.add()     → 201 { "id": "..." }
GET    /orders           → OrderStore.list()    → 200 [ { StandingOrder } ]
DELETE /orders/{id}      → OrderStore.delete()  → 204 / 404
PATCH  /orders/{id}      → OrderStore.update()  → 200 / 404

# 快速 enable/disable（不需要全量 PATCH body）
POST   /orders/{id}/enable   → store.update(order.with_enabled(True))
POST   /orders/{id}/disable  → store.update(order.with_enabled(False))
```

请求/响应体直接使用 `StandingOrder.to_dict()` / `StandingOrder.from_dict()`，格式稳定。

---

## 3. suggestion → SSE 事件提案

### 3.1 新事件类型

集成时在 `protocol/events.py` 中新增两个事件（与 `PlanDecisionRequest` 同构）：

```python
@dataclass(frozen=True, slots=True)
class ProactiveSuggestionEvent:
    """Conductor 产出主动建议事件（daemon → client 方向，SSE 推送）。

    客户端收到后在 TUI 活动栏展示，等用户点击「运行」或「忽略」。
    requires_confirmation 恒 True（协议级，不可覆盖）。
    """
    kind = "proactive_suggestion"
    suggestion_id: str               # ProactiveSuggestion.id
    order_id: str
    goal: str
    reason_human: str                # 供 TUI 展示的人话原因
    suggested_at: float
    requires_confirmation: bool = True


@dataclass(frozen=True, slots=True)
class TrustSuggestionEvent:
    """Trust Dial 升档建议事件（基于 Ledger 行为历史分析产出）。

    与 ProactiveSuggestionEvent 不同：这是信任级别的调整建议，
    不触发 create_run，触发 TUI 展示升档警示对话框。
    """
    kind = "trust_suggestion"
    from_level: str     # e.g. "L0_EVERY_STEP"
    to_level: str       # e.g. "L1_DANGEROUS_ONLY"
    warning: str        # escalation_warning() 返回的警示文案（非空）
    rationale: str      # 人话原因（来自 suggest_escalation()）
```

### 3.2 SSE 路由中消费 suggestion_queue

```python
# daemon/server.py SSE 端点（集成阶段实现）
@app.get("/events")
async def stream_events(request: Request):
    async def generate():
        while True:
            if not suggestion_queue.empty():
                s = await suggestion_queue.get()
                event = ProactiveSuggestionEvent(
                    suggestion_id=s.id,
                    order_id=s.order_id,
                    goal=s.goal,
                    reason_human=s.reason_human,
                    suggested_at=s.suggested_at,
                    requires_confirmation=True,
                )
                yield f"data: {serialize_event(event)}\n\n"
            await asyncio.sleep(0.1)
    return EventSourceResponse(generate())
```

---

## 4. 用户确认 → create_run（worktree 隔离 + 低信任档）

**这是两条写死的安全要求（集成时必须遵守，禁止降级）：**

1. **自治 run 默认 worktree 隔离**：conductor 触发的 run 必须传 `isolation="worktree"`，不允许用 `isolation="none"`（即使 TrustDial 当前档位为 L4）。
2. **自治 run 最高信任档 ≤ L1**：conductor 触发的 run 信任级别固定为 `L1_DANGEROUS_ONLY`（仅危险操作问），不随 TrustDial 全局档位提升，不允许传 L2 及以上。

推荐接线伪代码（daemon 侧，用户点击「运行」后执行）：

```python
# daemon/server.py 或 daemon/approval_handler.py
async def confirm_suggestion(suggestion_id: str) -> dict:
    """用户确认 ProactiveSuggestion → 创建隔离 run。

    硬约束：
      - isolation 永远 "worktree"
      - trust_level 永远 "L1_DANGEROUS_ONLY"（不读全局 TrustDial）
    """
    s = get_suggestion(suggestion_id)  # 从 queue/cache 取
    if s is None:
        raise NotFound(suggestion_id)

    run_id = await create_run(
        goal=s.goal,
        isolation="worktree",             # 写死：自治 run 必须 worktree 隔离
        trust_level="L1_DANGEROUS_ONLY",  # 写死：自治 run 最高 L1
        source="conductor",
        order_id=s.order_id,
    )
    return {"run_id": run_id}
```

**反例（禁止）**：
```python
# ❌ 错误：自治 run 不得用 isolation="none"
create_run(goal=s.goal, isolation="none", trust_level=global_trust_level)
```

---

## 5. 与 Scheduler 优先级/并发槽位关系

| 维度 | conductor 触发 run | 用户手动 run |
|---|---|---|
| 并发槽位 | 共享 daemon registry 槽位 | 共享 daemon registry 槽位 |
| 排队优先级 | 低（建议 `priority="low"`）| 正常 |
| worktree 隔离 | **必须**（写死）| 默认开，用户可关 |
| 信任档位 | **最高 L1**（写死）| 跟随全局 TrustDial |
| 触发路径 | `ConductorEngine.tick()` → ProactiveSuggestion → 用户确认 → `create_run` | 用户直接输入 → `create_run` |

**并发竞争策略**：当 daemon 并发槽位满时，conductor 产出的 suggestion 保留在 queue 中等待；用户确认时若槽位仍满，返回「队列已满，建议稍后」的诚实提示（不静默丢弃，Ledger 留痕）。

---

## 6. 约束与已知限制（诚实标注）

1. **重启幂等已由盘上 `last_fired_at` 保证**（终审实测核正）：`_tick_schedule` 以落盘的 `last_fired_at` 为 ref，`next_due` 严格返回 >ref 的下一到期点，重启 N 次零补发。内存 `_last_schedule_fired` 只是冗余二道闸 —— 集成阶段**不要**为此加 engine_state.json。
2. **FileTriggerWatcher 无持久化 mtime 缓存**：daemon 重启后 `_known_mtimes` 清空，所有匹配文件在下次 poll 时视为"新出现"，各产出一条 suggestion。这是保守行为（宁可多问不少问），用户体验可在 TUI 侧用"这些文件已在上次会话触发过"标注改善。
3. **cron-lite 不支持 DST/时区**：`next_due` 使用 UTC 计算，不处理夏令时跳变。用户设置的定点时间（如 "09:00"）在 DST 切换日会偏移 1 小时。这是已知限制，集成注记中明确告知用户（不假装"每天准点"）。
4. **`every N` 间隔对齐到 Unix 纪元**：`every 30m` 的触发点是 Unix 时间戳被 1800 整除的点（00:00、00:30、01:00…），不是"从命令创建时起每 30 分钟"。对大多数用例无影响；需要相对间隔的场景可用 `last_fired_at + interval` 在 engine 层改写（留给集成阶段按需实现）。

---

*最后更新：2026-06-11，P5 自治面 conductor/ 并行轨初版完成。*
