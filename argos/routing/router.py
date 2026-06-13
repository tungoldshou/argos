"""ModelRouter(契约 §11;spec §7):多个 ModelClient + RoutingConfig + history。

懒构造:首次 select() 某 tier 时才造 ModelClient(避免无 key 的 tier 启动即抛)。
history:deque(maxlen=10),本 run 内 /routing 读,run 终止即失(不持久化 spec §14.2)。
线程安全:select() 加锁,避免多 loop 并发构造同 tier 重复工厂调用。
"""
from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from dataclasses import replace

from argos.config import ConfigError
from argos.core.models import ModelClient
from argos.routing.categorizer import TaskCategory
from argos.routing.config import RoutingConfig
from argos.routing.resolver import RouteDecision, resolve

# ModelClient 抽象(spec D8):所有 client 必须有 .stream/.complete/.last_usage/.tier。
ClientFactory = Callable[[str], ModelClient]


class ModelRouter:
    def __init__(self, *, routing: RoutingConfig,
                 client_factory: ClientFactory) -> None:
        self._routing = routing
        self._client_factory = client_factory
        self._clients: dict[str, ModelClient] = {}
        self._history: deque[RouteDecision] = deque(maxlen=10)
        self._lock = threading.Lock()

    def select(self, *, category: TaskCategory, tool: str | None,
               step: int = 0) -> tuple[ModelClient, RouteDecision]:
        """按 (category, tool) 选 tier,懒构造 + 缓存 client,记到 history。"""
        with self._lock:
            decision = resolve(self._routing, category=category, tool=tool)
            client = self._clients.get(decision.tier)
            if client is None:
                client = self._client_factory(decision.tier)
                if client is None:
                    raise ConfigError(
                        f"profile '{decision.tier}' 工厂返 None,无法构造 ModelClient")
                self._clients[decision.tier] = client
            decision = replace(decision, step=step)
            self._history.append(decision)
            return client, decision

    def history(self) -> list[RouteDecision]:
        """snapshot 副本(spec §7 不暴露 deque)。"""
        return list(self._history)

    @property
    def routing(self) -> RoutingConfig:
        return self._routing
