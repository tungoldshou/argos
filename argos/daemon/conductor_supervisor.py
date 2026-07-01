"""conductor_supervisor — daemon 内 conductor 后台协程（P5b §9 自治面通电）。

职责：
  - 宿主在 daemon 进程内以独立 asyncio.Task 运行 ConductorEngine.tick() 循环。
  - tick 产出的 ProactiveSuggestion：
      - action="dream"（builtin 夜间整合）且材料门放行：若注入了 dream_starter，
        直接调 dream_starter(s)（自主模式，无需用户确认）；否则走旧路：登记到
        pending_suggestions + 广播 ProactiveSuggestionEvent（等用户 confirm）。
      - 其他 action：登记 pending + 广播（永远要用户确认）。

全局通道诚实说明：
  daemon 当前的 SSE 端点是 per-run（/runs/{id}/events），没有跨所有 run 的全局 SSE 流。
  conductor suggestion 事件通过虚拟 run_id "_conductor" 走 manager.fanout("_conductor", ev_dict)
  纯实时广播到订阅者 —— 绝不落盘（RunStore.append 拒绝 `_` 前缀），避免无 run_meta 头的事件
  污染 run store 让 replay/recover 崩溃。历史建议的持久化由内存 pending_suggestions +
  GET /suggestions 负责，不靠事件流回放。
  TUI 客户端可通过 GET /runs/_conductor/events 订阅（只推实时，不回放），或直接 GET /suggestions 轮询。
  未来可扩展为真正的全局 SSE 端点；当前路径诚实文档化，不假装有全局通道。

取消：daemon 关闭时对 asyncio.Task 调 cancel()，协程通过 CancelledError 干净退出。
"""
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

# conductor 事件流的虚拟 run_id（诚实标注：非真实 run，仅用于 SSE 广播通道）
CONDUCTOR_RUN_ID = "_conductor"

# builtin 夜间整合 order 的固定 ID（幂等注册靠它去重）
BUILTIN_DREAM_ORDER_ID = "builtin-dream-nightly"


def ensure_builtin_dream_order(store: OrderStore) -> None:
    """幂等注册 builtin 夜间整合 StandingOrder（Dream 的自治触发源）。

    幂等只看**存在性**（store.get(BUILTIN_DREAM_ORDER_ID) 非 None 即返），不看 enabled：
    用户主动 disable 后绝不复活（尊重用户意志）。删了才会在下次 ensure 时重建。
    """
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
    """daemon 内的 conductor 后台任务管理器。

    装配：daemon __main__.py 启动时调 start()，关闭时调 stop()。
    产出的 suggestion 存入 pending_suggestions dict，
    并通过注入的 _broadcast_fn 广播事件（解耦：不直接引用 manager）。

    dream_starter（可选）：若注入，action=dream 的建议在材料门放行后直接调 dream_starter(s)
    启动 Dream，不再进 pending、不广播 suggestion 事件（自主模式）。
    未注入则退回旧路：进 pending + 广播，等用户 confirm（兼容无 daemon 场景）。
    """

    def __init__(
        self,
        *,
        orders_dir: Path,
        tick_interval: float = 30.0,
        broadcast_fn,  # Callable[[dict], Coroutine]：接收事件 dict，广播到全局通道
        dream_starter: Callable[[ProactiveSuggestion], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        self._orders_dir = orders_dir
        self._tick_interval = tick_interval
        self._broadcast_fn = broadcast_fn
        self._dream_starter = dream_starter
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
        # builtin 夜间整合 order 幂等注册：注册失败不挂 tick loop（包 try/except）。
        try:
            ensure_builtin_dream_order(store)
        except Exception as exc:  # noqa: BLE001 — 注册失败降级,tick loop 照常跑
            log.warning("conductor_supervisor: builtin dream order 注册失败(忽略): %s", exc)
        engine = ConductorEngine(store, clock=time.time)

        while True:
            try:
                now = time.time()
                suggestions = engine.tick(now)
                for s in suggestions:
                    # 材料门：action=dream 但候选区无未消费材料 → 空料静默(不进 pending、不广播)。
                    if not self._should_emit_dream(s):
                        continue
                    # 自主模式：builtin dream 直接启动，无需用户确认。
                    # ponytail: dream_starter 注入时才走自主路径；未注入则退回旧路（向后兼容）。
                    if s.action == "dream" and self._dream_starter is not None:
                        await self._start_dream_autonomous(s)
                        continue
                    self._pending[s.id] = s
                    await self._emit_suggestion(s)
            except asyncio.CancelledError:
                raise  # 干净退出
            except Exception as exc:  # noqa: BLE001
                log.warning("conductor_supervisor: tick 异常(将在下次 tick 重试): %s", exc)
            await asyncio.sleep(self._tick_interval)

    async def _start_dream_autonomous(self, s: ProactiveSuggestion) -> None:
        """自主启动 Dream — 材料门已通过，guards 由 dream_starter 内部检查。

        dream_starter 返回 True = 已启动；False = 守卫拦截（busy / no key）→ 静默跳过。
        异常 → log.warning + 不抛（不挂 tick loop）。
        """
        assert self._dream_starter is not None  # 调用方已检查
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
        """材料门：action=dream 的建议仅在候选区有未消费材料时才放行。

        - action != "dream"：永远放行（材料门只管 dream 建议）。
        - action == "dream"：has_material(DEFAULT_ROOT) 为 True 才放行，否则空料静默。
        - 学习模块 import 失败（has_material/DEFAULT_ROOT 不可用）：视为无材料 → 静默，
          绝不让学习子系统的故障挂掉 conductor tick（局部 import + try/except）。
        """
        if getattr(s, "action", "run") != "dream":
            return True
        try:
            from argos.learning.candidates import DEFAULT_ROOT
            from argos.learning.dream import has_material
            return has_material(DEFAULT_ROOT)
        except Exception as exc:  # noqa: BLE001 — 学习模块故障视为无材料
            log.warning("conductor_supervisor: 材料门检查失败(视为无材料,静默): %s", exc)
            return False

    async def _emit_suggestion(self, s: ProactiveSuggestion) -> None:
        """将 ProactiveSuggestion 广播为 ProactiveSuggestionEvent 事件 dict。"""
        from argos.protocol.events import ProactiveSuggestionEvent, serialize_event
        ev = ProactiveSuggestionEvent(
            suggestion_id=s.id,
            order_id=s.order_id,
            goal=s.goal,
            reason_human=s.reason_human,
            suggested_at=s.suggested_at,
            requires_confirmation=True,
            action=s.action,   # 透传 suggestion.action（"run" 或 "dream"，构造时已校验）
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
