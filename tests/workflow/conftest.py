import pytest

from tests.e2e.scripted_model import ScriptedModelClient


@pytest.fixture
def scripted_model_factory():
    # 子 agent:无代码块的纯文本答复 → loop 催一轮后以文字收尾(read+reason 场景)
    def make(profile=None):
        return ScriptedModelClient(["这是对目标的简要总结与结论。"])
    return make


@pytest.fixture
def counting_model_factory():
    import asyncio
    from argos_agent.core.models import ModelTier

    class _Factory:
        def __init__(self):
            self.peak_concurrency = 0
            self._active = 0
        def __call__(self, profile=None):
            outer = self
            class _M:
                tier = ModelTier(name="worker", model="c", base_url="memory://", max_tokens=64)
                async def stream(self, messages, *, system):
                    outer._active += 1
                    outer.peak_concurrency = max(outer.peak_concurrency, outer._active)
                    await asyncio.sleep(0.05)
                    outer._active -= 1
                    yield "并发计数结果。"
            return _M()
    return _Factory()


@pytest.fixture
def failing_model_factory():
    class _Boom:
        from argos_agent.core.models import ModelTier
        tier = ModelTier(name="worker", model="boom", base_url="memory://", max_tokens=64)

        async def stream(self, messages, *, system):
            raise RuntimeError("boom")
            yield  # 让它是 async generator

    def make(profile=None):
        return _Boom()
    return make
