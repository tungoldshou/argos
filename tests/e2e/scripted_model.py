"""确定性模型替身(契约 §7 ModelClient 形状):按脚本逐轮吐文本,离线、可证伪。

真 AgentLoop 仍真抽代码/真沙箱执行/真跑 verify;只有'模型生成什么'被脚本化,
让铁证 e2e 在 CI 离线确定性复现(不连真 LLM)。脚本耗尽重复最后一条(避免崩)。
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from argos_agent.core.models import ModelTier


class ScriptedModelClient:
    def __init__(self, scripts: list[str], *, tier_name: str = "worker") -> None:
        if not scripts:
            raise ValueError("scripts 至少 1 条")
        self._scripts = list(scripts)
        self._idx = 0
        # AgentLoop 可能读 model.tier(契约 §7);给一个兼容 ModelTier。
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
        # 模拟流式:逐字符吐(loop 侧拼回完整文本,行为与真 ModelClient 一致)。
        for ch in text:
            yield ch

    async def complete(self, messages: list[dict], *, system: str) -> str:
        return self._next()
