"""ConductorEngine — 自治调度引擎（设计 §9 自治面）。

职责：
  - tick(now) 驱动：扫描所有 enabled 的 StandingOrder，
    判断是否到期/触发 → 产出 ProactiveSuggestion 列表。
  - 不执行任何副作用（不创建 run、不写文件）。
  - 幂等：同一 now 点不重复产出同一 order 的 suggestion。
  - 标记 last_fired_at：产出 suggestion 后通过 OrderStore.update() 落盘。

文件触发：
  - FileTriggerWatcher 按 order_id 懒创建（每个 file_trigger order 一个 watcher）。
  - tick 中轮询所有 watcher，收集 FileTriggerFact → 产 suggestion。

定时触发：
  - 用 cronlite.next_due 计算 next_due；若 next_due ≤ now 且与上次触发不同 → 产 suggestion。
  - last_fired_at 对齐到分钟（60s），避免 tick 过频时重复产出。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from argos.conductor.orders import OrderStore, StandingOrder
from argos.conductor.cronlite import next_due as cron_next_due
from argos.conductor.proposals import ProactiveSuggestion, propose
from argos.conductor.triggers import FileTriggerWatcher

log = logging.getLogger("argos.conductor.engine")

# 定时任务的幂等窗口（秒）：同一 order 在此窗口内不重复触发
_SCHEDULE_IDEMPOTENCY_WINDOW = 55.0


class ConductorEngine:
    """自治调度引擎。

    参数：
        store           OrderStore 实例（可注入 tmp 目录供测试）
        clock           注入时钟函数（禁止引擎内部调用 time.time()）
        watcher_factory 可注入 FileTriggerWatcher 工厂（默认构造真实 watcher）
        base_dir        文件触发 watcher 的 glob 搜索根目录（默认 Path.cwd()）
    """

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

        # order_id → FileTriggerWatcher（懒创建）
        self._watchers: dict[str, FileTriggerWatcher] = {}

        # 定时幂等记录：order_id → 上次触发的「到期时间点」（对齐分钟）
        # 用于区分"此到期点已产出"与"下一轮新到期点"
        self._last_schedule_fired: dict[str, float] = {}

    # ------------------------------------------------------------------
    # 主接口
    # ------------------------------------------------------------------

    def tick(self, now: float) -> list[ProactiveSuggestion]:
        """驱动一次引擎 tick，返回本轮产出的 ProactiveSuggestion 列表。

        不修改外部状态（除 OrderStore.update last_fired_at），不执行任何 run。

        幂等保证：
          - 定时：同一 order 的同一到期分钟点不重复产出。
          - 文件触发：FileTriggerWatcher 内部 debounce + mtime 缓存保证幂等。
        """
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
    # 内部：定时触发
    # ------------------------------------------------------------------

    def _tick_schedule(
        self, order: StandingOrder, now: float
    ) -> ProactiveSuggestion | None:
        """检查一条 schedule 类 order 是否到期，返回 suggestion 或 None。"""
        if not order.schedule:
            return None

        # 求上次到期点之后的下一个到期点
        # 若 last_fired_at 存在，以它为参考基准；否则以 now-60s 为基准（确保当分钟可触发）
        ref = order.last_fired_at if order.last_fired_at else now - 60.0
        try:
            due = cron_next_due(order.schedule, ref, clock=self._clock)
        except ValueError as exc:
            log.warning("conductor: order %r cron 解析失败: %s", order.id, exc)
            return None

        # 未到期
        if due > now:
            return None

        # 幂等：同一到期点（对齐分钟）不重复触发
        due_minute = int(due) // 60 * 60
        last_due_minute = self._last_schedule_fired.get(order.id, -1)
        if last_due_minute == due_minute:
            return None

        # 产出 suggestion
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(now, tz=timezone.utc)
        context = {
            "date": dt.strftime("%Y-%m-%d"),
            "time": dt.strftime("%H:%M"),
            "datetime": dt.strftime("%Y-%m-%d %H:%M"),
        }
        suggestion = propose(order, context, clock=self._clock)

        # 更新幂等记录
        self._last_schedule_fired[order.id] = due_minute

        # 持久化 last_fired_at
        updated_order = order.with_last_fired(now)
        self._store.update(updated_order)

        return suggestion

    # ------------------------------------------------------------------
    # 内部：文件触发
    # ------------------------------------------------------------------

    def _tick_file_trigger(
        self, order: StandingOrder, now: float
    ) -> list[ProactiveSuggestion]:
        """轮询 file_trigger 类 order 的 watcher，返回 suggestion 列表。"""
        if not order.trigger_glob:
            return []

        # 懒创建 watcher
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

            # 持久化 last_fired_at（每次触发都更新）
            updated_order = order.with_last_fired(now)
            self._store.update(updated_order)
            # 更新 order 引用（下一次 fact 用更新后的 order）
            order = updated_order

        return suggestions


def _ts_to_date(ts: float) -> str:
    """Unix 时间戳 → "YYYY-MM-DD" 字符串（UTC）。"""
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
