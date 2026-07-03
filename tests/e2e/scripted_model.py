"""Internal documentation."""
from __future__ import annotations

from collections.abc import AsyncIterator

from argos.core.models import ModelTier


class ScriptedModelClient:
    def __init__(self, scripts: list[str], *, tier_name: str = "worker") -> None:
        if not scripts:
            raise ValueError("scripts 至少 1 条")
        self._scripts = list(scripts)
        self._idx = 0
        self.tier = ModelTier(
            name=tier_name, model="scripted", base_url="memory://", max_tokens=4096
        )

    def _next(self) -> str:
        i = min(self._idx, len(self._scripts) - 1)
        self._idx += 1
        return self._scripts[i]

    async def stream(self, messages: list[dict], *, system: str,
                     system_dynamic: str | None = None) -> AsyncIterator[str]:
        text = self._next()
        for ch in text:
            yield ch

    async def complete(self, messages: list[dict], *, system: str) -> str:
        return self._next()
