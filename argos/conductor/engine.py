from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from argos.conductor.orders import OrderStore, StandingOrder
from argos.conductor.cronlite import next_due as cron_next_due
from argos.conductor.proposals import ProactiveSuggestion, propose
from argos.conductor.triggers import FileTriggerWatcher

log = logging.getLogger("argos.conductor.engine")

_SCHEDULE_IDEMPOTENCY_WINDOW = 55.0


class ConductorEngine:

    def __init__(
        self,
        store: OrderStore,
        clock: Callable[[], float],
        *,
        watcher_factory: Callable[..., FileTriggerWatcher] | None = None,
        base_dir: Path | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._watcher_factory = watcher_factory or FileTriggerWatcher
        self._base_dir = base_dir

        self._watchers: dict[str, FileTriggerWatcher] = {}

        self._last_schedule_fired: dict[str, float] = {}

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    def tick(self, now: float) -> list[ProactiveSuggestion]:
        suggestions: list[ProactiveSuggestion] = []
        orders = self._store.list()

        for order in orders:
            if not order.enabled:
                continue
            try:
                if order.kind == "schedule":
                    s = self._tick_schedule(order, now)
                    if s:
                        suggestions.append(s)
                elif order.kind == "file_trigger":
                    s_list = self._tick_file_trigger(order, now)
                    suggestions.extend(s_list)
            except Exception as exc:  # noqa: BLE001
                log.warning("conductor.tick: order %r 处理异常: %s", order.id, exc)

        return suggestions

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    def _tick_schedule(
        self, order: StandingOrder, now: float
    ) -> ProactiveSuggestion | None:
        if not order.schedule:
            return None

        ref = order.last_fired_at if order.last_fired_at else now - 60.0
        try:
            due = cron_next_due(order.schedule, ref, clock=self._clock)
        except ValueError as exc:
            log.warning("conductor: order %r cron 解析失败: %s", order.id, exc)
            return None

        if due > now:
            return None

        due_minute = int(due) // 60 * 60
        last_due_minute = self._last_schedule_fired.get(order.id, -1)
        if last_due_minute == due_minute:
            return None

        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(now, tz=timezone.utc)
        context = {
            "date": dt.strftime("%Y-%m-%d"),
            "time": dt.strftime("%H:%M"),
            "datetime": dt.strftime("%Y-%m-%d %H:%M"),
        }
        suggestion = propose(order, context, clock=self._clock)

        self._last_schedule_fired[order.id] = due_minute

        updated_order = order.with_last_fired(now)
        self._store.update(updated_order)

        return suggestion

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    def _tick_file_trigger(
        self, order: StandingOrder, now: float
    ) -> list[ProactiveSuggestion]:
        if not order.trigger_glob:
            return []

        if order.id not in self._watchers:
            kwargs: dict = {"clock": self._clock}
            if self._base_dir:
                kwargs["base_dir"] = self._base_dir
            self._watchers[order.id] = self._watcher_factory(
                order.trigger_glob, **kwargs
            )

        watcher = self._watchers[order.id]
        facts = watcher.poll()

        suggestions: list[ProactiveSuggestion] = []
        for fact in facts:
            context = {
                "path": fact.path,
                "mtime": str(fact.mtime),
                "date": _ts_to_date(fact.detected_at),
            }
            s = propose(order, context, clock=self._clock)
            suggestions.append(s)

            updated_order = order.with_last_fired(now)
            self._store.update(updated_order)
            order = updated_order

        return suggestions


def _ts_to_date(ts: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
