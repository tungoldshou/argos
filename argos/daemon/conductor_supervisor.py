"""Internal documentation."""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Callable, Coroutine, Any

from argos.conductor import ConductorEngine, OrderStore
from argos.conductor.orders import StandingOrder
from argos.conductor.proposals import ProactiveSuggestion
from argos.i18n import t

log = logging.getLogger("argos.daemon.conductor")

CONDUCTOR_RUN_ID = "_conductor"

BUILTIN_DREAM_ORDER_ID = "builtin-dream-nightly"


def ensure_builtin_dream_order(store: OrderStore) -> None:
    """Internal documentation."""
    if store.get(BUILTIN_DREAM_ORDER_ID) is not None:
        return
    order = StandingOrder(
        id=BUILTIN_DREAM_ORDER_ID,
        utterance=t("daemon.srv.dream_order_utterance"),
        kind="schedule",
        schedule="03:00",
        trigger_glob=None,
        goal_template="__dream__",
        enabled=True,
        created_at=time.time(),
        last_fired_at=None,
        action="dream",
    )
    store.add(order)


class ConductorSupervisor:
    """Internal documentation."""

    def __init__(
        self,
        *,
        orders_dir: Path,
        tick_interval: float = 30.0,
        broadcast_fn,
        dream_starter: Callable[[ProactiveSuggestion], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        self._orders_dir = orders_dir
        self._tick_interval = tick_interval
        self._broadcast_fn = broadcast_fn
        self._dream_starter = dream_starter
        self._task: asyncio.Task | None = None
        self._pending: dict[str, ProactiveSuggestion] = {}

    @property
    def pending_suggestions(self) -> dict[str, ProactiveSuggestion]:
        """Internal documentation."""
        return self._pending

    def start(self) -> None:
        """Internal documentation."""
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
        """Internal documentation."""
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        log.info("conductor_supervisor: tick loop 已停止")

    def pop_suggestion(self, suggestion_id: str) -> ProactiveSuggestion | None:
        """Internal documentation."""
        return self._pending.pop(suggestion_id, None)

    def get_suggestion(self, suggestion_id: str) -> ProactiveSuggestion | None:
        """Internal documentation."""
        return self._pending.get(suggestion_id)

    def dismiss_suggestion(self, suggestion_id: str) -> bool:
        """Internal documentation."""
        if suggestion_id in self._pending:
            del self._pending[suggestion_id]
            return True
        return False


    async def _run_loop(self) -> None:
        """Internal documentation."""
        store = OrderStore(self._orders_dir)
        try:
            ensure_builtin_dream_order(store)
        except Exception as exc:  # noqa: BLE001
            log.warning("conductor_supervisor: builtin dream order 注册失败(忽略): %s", exc)
        engine = ConductorEngine(store, clock=time.time)

        while True:
            try:
                now = time.time()
                suggestions = engine.tick(now)
                for s in suggestions:
                    if not self._should_emit_dream(s):
                        continue
                    if s.action == "dream" and self._dream_starter is not None:
                        await self._start_dream_autonomous(s)
                        continue
                    self._pending[s.id] = s
                    await self._emit_suggestion(s)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("conductor_supervisor: tick 异常(将在下次 tick 重试): %s", exc)
            await asyncio.sleep(self._tick_interval)

    async def _start_dream_autonomous(self, s: ProactiveSuggestion) -> None:
        """Internal documentation."""
        assert self._dream_starter is not None
        try:
            started = await self._dream_starter(s)
            if started:
                log.info(
                    "conductor_supervisor: Dream 自主启动 (order_id=%s, suggestion_id=%s)",
                    s.order_id, s.id,
                )
            else:
                log.debug(
                    "conductor_supervisor: Dream 守卫拦截(busy/no-key),本次跳过 (order_id=%s)",
                    s.order_id,
                )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "conductor_supervisor: dream_starter 异常(静默跳过): %s", exc,
            )

    def _should_emit_dream(self, s: ProactiveSuggestion) -> bool:
        """Internal documentation."""
        if getattr(s, "action", "run") != "dream":
            return True
        try:
            from argos.learning.candidates import default_root
            from argos.learning.dream import has_material
            return has_material(default_root())
        except Exception as exc:  # noqa: BLE001
            log.warning("conductor_supervisor: 材料门检查失败(视为无材料,静默): %s", exc)
            return False

    async def _emit_suggestion(self, s: ProactiveSuggestion) -> None:
        """Internal documentation."""
        from argos.protocol.events import ProactiveSuggestionEvent, serialize_event
        ev = ProactiveSuggestionEvent(
            suggestion_id=s.id,
            order_id=s.order_id,
            goal=s.goal,
            reason_human=s.reason_human,
            suggested_at=s.suggested_at,
            requires_confirmation=True,
            action=s.action,
        )
        import json
        ev_dict = json.loads(serialize_event(ev))
        payload = {**ev_dict["data"], "kind": ev_dict["kind"], "run_id": CONDUCTOR_RUN_ID}
        try:
            await self._broadcast_fn(payload)
        except Exception as exc:  # noqa: BLE001
            log.warning("conductor_supervisor: 广播建议失败(suggestion_id=%s): %s", s.id, exc)
