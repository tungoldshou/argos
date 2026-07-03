from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from dataclasses import replace

from argos.config import ConfigError
from argos.core.models import ModelClient
from argos.i18n import t
from argos.routing.categorizer import TaskCategory
from argos.routing.config import RoutingConfig
from argos.routing.resolver import RouteDecision, resolve

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
        with self._lock:
            decision = resolve(self._routing, category=category, tool=tool)
            client = self._clients.get(decision.tier)
            if client is None:
                client = self._client_factory(decision.tier)
                if client is None:
                    raise ConfigError(t("route.factory_returned_none", tier=decision.tier))
                self._clients[decision.tier] = client
            decision = replace(decision, step=step)
            self._history.append(decision)
            return client, decision

    def history(self) -> list[RouteDecision]:
        return list(self._history)

    @property
    def routing(self) -> RoutingConfig:
        return self._routing
