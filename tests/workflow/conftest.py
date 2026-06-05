import pytest

from tests.e2e.scripted_model import ScriptedModelClient


@pytest.fixture
def scripted_model_factory():
    # 子 agent:无代码块的纯文本答复 → loop 催一轮后以文字收尾(read+reason 场景)
    def make(profile=None):
        return ScriptedModelClient(["这是对目标的简要总结与结论。"])
    return make


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
