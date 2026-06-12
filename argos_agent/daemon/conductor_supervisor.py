"""conductor_supervisor — daemon 内 conductor 后台协程（P5b §9 自治面通电）。

职责：
  - 宿主在 daemon 进程内以独立 asyncio.Task 运行 ConductorEngine.tick() 循环。
  - tick 产出的 ProactiveSuggestion：
      1. 登记到 pending_suggestions（内存 dict, suggestion_id → ProactiveSuggestion）
      2. 广播 ProactiveSuggestionEvent 到「全局通道」（run_id 保留为 "_conductor"）

全局通道诚实说明：
  daemon 当前的 SSE 端点是 per-run（/runs/{id}/events），没有跨所有 run 的全局 SSE 流。
  conductor suggestion 事件使用虚拟 run_id "_conductor" 落盘（RunStore.append）并通过
  manager.fanout("_conductor", ev_dict) 广播到订阅了 "_conductor" 流的消费者。
  TUI 客户端可通过 GET /runs/_conductor/events 订阅，或直接 GET /suggestions 轮询。
  未来可扩展为真正的全局 SSE 端点；当前路径诚实文档化，不假装有全局通道。

取消：daemon 关闭时对 asyncio.Task 调 cancel()，协程通过 CancelledError 干净退出。
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from argos_agent.conductor import ConductorEngine, OrderStore
from argos_agent.conductor.proposals import ProactiveSuggestion

log = logging.getLogger("argos.daemon.conductor")

# conductor 事件流的虚拟 run_id（诚实标注：非真实 run，仅用于 SSE 广播通道）
CONDUCTOR_RUN_ID = "_conductor"


class ConductorSupervisor:
    """daemon 内的 conductor 后台任务管理器。

    装配：daemon __main__.py 启动时调 start()，关闭时调 stop()。
    产出的 suggestion 存入 pending_suggestions dict，
    并通过注入的 _broadcast_fn 广播事件（解耦：不直接引用 manager）。
    """

    def __init__(
        self,
        *,
        orders_dir: Path,
        tick_interval: float = 30.0,
        broadcast_fn,  # Callable[[dict], Coroutine]：接收事件 dict，广播到全局通道
    ) -> None:
        self._orders_dir = orders_dir
        self._tick_interval = tick_interval
        self._broadcast_fn = broadcast_fn
        self._task: asyncio.Task | None = None
        # suggestion_id → ProactiveSuggestion（内存）
        self._pending: dict[str, ProactiveSuggestion] = {}

    @property
    def pending_suggestions(self) -> dict[str, ProactiveSuggestion]:
        """只读视图：当前待确认的建议（suggestion_id → ProactiveSuggestion）。"""
        return self._pending

    def start(self) -> None:
        """启动 conductor tick 后台协程（daemon 启动时调用）。"""
        if self._task is not None and not self._task.done():
            log.warning("conductor_supervisor: task 已在运行,跳过重复启动")
            return
        self._task = asyncio.create_task(
            self._run_loop(), name="conductor-tick"
        )
        log.info(
            "conductor_supervisor: 启动 tick loop(interval=%.0fs, orders_dir=%s)",
            self._tick_interval, self._orders_dir,
        )

    async def stop(self) -> None:
        """取消 tick 协程并等待干净退出（daemon 关闭时调用）。"""
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass  # 正常取消，干净退出
        log.info("conductor_supervisor: tick loop 已停止")

    def pop_suggestion(self, suggestion_id: str) -> ProactiveSuggestion | None:
        """取出并移除 pending suggestion（confirm/dismiss 调用）。"""
        return self._pending.pop(suggestion_id, None)

    def get_suggestion(self, suggestion_id: str) -> ProactiveSuggestion | None:
        """只读查询 pending suggestion（不移除）。"""
        return self._pending.get(suggestion_id)

    def dismiss_suggestion(self, suggestion_id: str) -> bool:
        """标记 suggestion 为已忽略（移出 pending）。返回 True = 成功；False = 未找到。"""
        if suggestion_id in self._pending:
            del self._pending[suggestion_id]
            return True
        return False

    # ── 内部 ──────────────────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        """tick 主循环。CancelledError 自然退出。"""
        store = OrderStore(self._orders_dir)
        engine = ConductorEngine(store, clock=time.time)

        while True:
            try:
                now = time.time()
                suggestions = engine.tick(now)
                for s in suggestions:
                    self._pending[s.id] = s
                    await self._emit_suggestion(s)
            except asyncio.CancelledError:
                raise  # 干净退出
            except Exception as exc:  # noqa: BLE001
                log.warning("conductor_supervisor: tick 异常(将在下次 tick 重试): %s", exc)
            await asyncio.sleep(self._tick_interval)

    async def _emit_suggestion(self, s: ProactiveSuggestion) -> None:
        """将 ProactiveSuggestion 广播为 ProactiveSuggestionEvent 事件 dict。"""
        from argos_agent.protocol.events import ProactiveSuggestionEvent, serialize_event
        ev = ProactiveSuggestionEvent(
            suggestion_id=s.id,
            order_id=s.order_id,
            goal=s.goal,
            reason_human=s.reason_human,
            suggested_at=s.suggested_at,
            requires_confirmation=True,
        )
        # 序列化为 dict（与 manager.fanout 期望的 dict 格式一致）
        import json
        ev_dict = json.loads(serialize_event(ev))
        # 展开 data 到顶层，加 run_id 字段（SSE 消费端期望的格式）
        payload = {**ev_dict["data"], "kind": ev_dict["kind"], "run_id": CONDUCTOR_RUN_ID}
        try:
            await self._broadcast_fn(payload)
        except Exception as exc:  # noqa: BLE001
            log.warning("conductor_supervisor: 广播建议失败(suggestion_id=%s): %s", s.id, exc)
