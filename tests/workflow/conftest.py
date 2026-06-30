import pytest

from tests.e2e.scripted_model import ScriptedModelClient


@pytest.fixture
def scripted_model_factory():
    # 子 agent:无代码块的纯文本答复 → loop 催一轮后以文字收尾(read+reason 场景)
    def make(profile=None):
        return ScriptedModelClient(["这是对目标的简要总结与结论。"])
    return make


@pytest.fixture
def workflow_loop(tmp_path, scripted_model_factory, requires_sandbox, monkeypatch):
    """Task 9 集成:真 AgentLoop(父用 scripted 模型,gate=AUTO,真沙箱,注入 engine 工厂)。
    父 step0 在 act 段提议工作流 → loop 钩子校验+审批+异步跑引擎+结果回灌;step1 收尾。

    requires_sandbox 依赖:无沙箱后端的平台(mac 缺 sandbox-exec、Linux 缺 bwrap/unshare)
    直接 skip,绝不 mock 把沙箱测试假跑过。
    工作流现已默认 on(autonomy flip, batch5)。本 fixture 保留显式 setenv("ARGOS_WORKFLOWS", "1")
    以对抗任何上游测试把它改成 "0" 的情况,确保集成路径确定走工作流分支。
    """
    monkeypatch.setenv("ARGOS_WORKFLOWS", "1")
    from argos.core.loop import AgentLoop, LoopConfig
    from argos.core.verify_gate import Verifier
    from argos.memory.store import ArgosStore
    from argos.sandbox.broker import CapabilityBroker
    from argos.sandbox.egress import EgressPolicy
    from argos.sandbox.executor import select_backend
    from argos.tools.receipts import ReceiptSigner
    from argos.tui.events import EventBus
    from argos.approval import ApprovalGate, ApprovalLevel
    from argos.workflow.engine import WorkflowEngine
    from tests.e2e.scripted_model import ScriptedModelClient
    import os

    # parent 模型:step0 提议工作流,step1 收尾(无代码)
    parent_scripts = [
        '我来编排。\n```python\npropose_workflow({\n'
        '    "name": "demo", "description": "演示",\n'
        '    "stages": [{"id": "r", "op": "fan_out", "over": ["a"],\n'
        '                "agent": {"prompt": "看 {item}", "tool_scope": "read"}}],\n'
        '})\n```',
        '工作流已完成,结论已汇总。',
    ]
    parent_model = ScriptedModelClient(parent_scripts)
    gate = ApprovalGate(ApprovalLevel.AUTO)
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    signer = ReceiptSigner(key=os.urandom(32))
    broker = CapabilityBroker(gate=gate, egress=egress, signer=signer, workspace=tmp_path)

    def _bridge(action, args):
        v, _ = broker._execute(action, args)
        return v

    # 平台感知:macOS → Seatbelt,Linux → bwrap/unshare。CI 跨平台跑不绑死 mac。
    sandbox = select_backend()(broker_handler=_bridge)
    cfg = LoopConfig(model_tier="worker", verify_cmd=None, max_rounds=2, max_steps=8,
                     compaction=True, approval_level=ApprovalLevel.AUTO)
    engine_factory = lambda: WorkflowEngine.for_test(workspace=tmp_path,
                                                     model_factory=scripted_model_factory)
    return AgentLoop(store=ArgosStore(db_path=":memory:"), bus=EventBus(), sandbox=sandbox,
                     broker=broker, model=parent_model, verifier=Verifier(max_rounds=2),
                     config=cfg, workspace=tmp_path, verify_dir=tmp_path,
                     workflow_engine_factory=engine_factory)


@pytest.fixture
def voting_model_factory():
    # 3 个 voter:前 2 个投 YES,第 3 个投 NO(用确定的投票标记,不靠 NLP)
    from tests.e2e.scripted_model import ScriptedModelClient

    class _Factory:
        def __init__(self):
            self._n = 0
        def __call__(self, profile=None):
            self._n += 1
            if self._n <= 2:
                return ScriptedModelClient(["[VOTE:YES] 该问题真实存在,确认。"])
            return ScriptedModelClient(["[VOTE:NO] 不成立。"])
    return _Factory()


@pytest.fixture
def counting_model_factory():
    import asyncio
    from argos.core.models import ModelTier

    class _Factory:
        def __init__(self):
            self.peak_concurrency = 0
            self._active = 0
        def __call__(self, profile=None):
            outer = self
            class _M:
                tier = ModelTier(name="worker", model="c", base_url="memory://", max_tokens=64)
                async def stream(self, messages, *, system, system_dynamic=None):
                    outer._active += 1
                    outer.peak_concurrency = max(outer.peak_concurrency, outer._active)
                    await asyncio.sleep(0.05)
                    outer._active -= 1
                    yield "并发计数结果。"
            return _M()
    return _Factory()


@pytest.fixture
def slow_model_factory():
    # 慢模型:stream 睡久(卡在 sleep)→ 好让取消发生在中途,验证 RAII 拆资源。
    import asyncio
    from argos.core.models import ModelTier

    def make(profile=None):
        class _Slow:
            tier = ModelTier(name="worker", model="slow", base_url="memory://", max_tokens=64)

            async def stream(self, messages, *, system, system_dynamic=None):
                await asyncio.sleep(30)   # 卡在这,等取消
                yield "永远到不了"
        return _Slow()
    return make


@pytest.fixture
def failing_model_factory():
    class _Boom:
        from argos.core.models import ModelTier
        tier = ModelTier(name="worker", model="boom", base_url="memory://", max_tokens=64)

        async def stream(self, messages, *, system, system_dynamic=None):
            raise RuntimeError("boom")
            yield  # 让它是 async generator

    def make(profile=None):
        return _Boom()
    return make
