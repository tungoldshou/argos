"""W3(契约 §10):loop 把诚实召回链 + StreamingContextScrubber 接进主循环。

两条铁证:
  ① store 带 recall → system = compose_system(HONESTY_SYSTEM, untrusted=format_untrusted(...)),
     即 HONESTY_SYSTEM 在前、untrusted 围栏段在后(注入顺序锁死);且模型若把围栏标记吐回,
     StreamingContextScrubber 把围栏及其间内容剥掉,不泄露给 UI(TokenDelta)。
  ② 无可召回 store(test fake 无 recall) → 诚实降级为 HONESTY_SYSTEM only(不假装召回发生过)。
"""
from __future__ import annotations

import pytest

from argos_agent.core.loop import AgentLoop, LoopConfig
from argos_agent.core.honesty import HONESTY_SYSTEM, UNTRUSTED_OPEN, UNTRUSTED_CLOSE
from argos_agent.core.types import Verdict
from argos_agent.memory.store import MemoryRecord
from argos_agent.sandbox.backend import ExecResult
from argos_agent.tui.events import EventBus, TokenDelta


class CapturingModel:
    """记录每次 stream 收到的 system;按脚本逐 run 出 text。"""
    def __init__(self, scripts):
        self._s = scripts
        self._i = 0
        self.systems: list[str] = []

    async def stream(self, messages, *, system):
        self.systems.append(system)
        text = self._s[min(self._i, len(self._s) - 1)]
        self._i += 1
        for ch in text:
            yield ch


class FakeSandbox:
    def spawn(self, *, workspace, namespace): ...
    def exec_code(self, code): return ExecResult(stdout="ran", value_repr="", exc="")
    def close(self): ...


class PassVerifier:
    def verify(self, verify_cmd, *, attempts=1):
        return Verdict.passed(detail="[exit_code=0]", verify_cmd=verify_cmd, attempts=attempts)


class FakeStore:
    """无 recall —— 触发 W3 诚实降级。"""
    def __init__(self): self.events = []
    def append_event(self, sid, ev): self.events.append(ev)
    def append_message(self, sid, **kw): return "m0"


class RecallStore(FakeStore):
    """带 recall 的 store —— 返回一条命中记忆 (record, reason)。"""
    def recall(self, goal, *, k=3, sim_min=0.4):
        rec = MemoryRecord(
            id="m1", goal="修过同样的导入错误", verdict="passed",
            model="MiniMax-M2", fact=None, ts=0.0,
        )
        return [(rec, "命中：goal 相似 0.88 + verdict=passed")]


def _loop(model, store):
    return AgentLoop(
        store=store, bus=EventBus(), sandbox=FakeSandbox(), broker=None,
        model=model, verifier=PassVerifier(),
        config=LoopConfig(verify_cmd=None, max_steps=4),
    )


@pytest.mark.asyncio
async def test_w3_no_store_recall_degrades_to_honesty_only(monkeypatch):
    # 隔离 store 召回降级这条不变量:把 skills 召回打桩成空,排除 skills 注入的干扰
    # (skills 召回独立于 store,不依赖它的 recall;本测试只断言「无 store.recall → 无记忆注入」)。
    monkeypatch.setattr("argos_agent.skills.recall", lambda *a, **k: [])
    model = CapturingModel(["完成。"])
    loop = _loop(model, FakeStore())  # 无 recall
    async for _ in loop.run("写个文件", "s"):
        pass
    assert model.systems, "模型没被调用"
    # 诚实降级:无 store.recall 且无 skill 命中 → system 就是纯 HONESTY_SYSTEM,不夹 untrusted 围栏。
    assert model.systems[0] == HONESTY_SYSTEM
    assert UNTRUSTED_OPEN not in model.systems[0]


@pytest.mark.asyncio
async def test_skills_recalled_into_untrusted_without_store_recall(monkeypatch):
    """skills 召回独立于 store:即便 store 没有 recall,命中的 skill 也进 untrusted 围栏段
    (安全段 HONESTY 在前)。这是「skills 不需要大模型也能用 + 不需要记忆库也能用」的接线铁证。"""
    from argos_agent import skills as _skills
    fake = _skills.Skill(name="py-test-runner", description="跑 pytest", trust="builtin",
                         enabled=True, body="用 `pytest -q` 跑测试。")
    monkeypatch.setattr("argos_agent.skills.recall", lambda *a, **k: [fake])
    model = CapturingModel(["完成。"])
    loop = _loop(model, FakeStore())  # 无 recall,但 skill 仍应注入
    async for _ in loop.run("帮我跑测试", "s"):
        pass
    sys_prompt = model.systems[0]
    assert sys_prompt.startswith(HONESTY_SYSTEM)          # 安全段在前
    assert UNTRUSTED_OPEN in sys_prompt                   # skill 进了 untrusted 围栏
    assert "py-test-runner" in sys_prompt
    assert sys_prompt.index(HONESTY_SYSTEM) < sys_prompt.index(UNTRUSTED_OPEN)


@pytest.mark.asyncio
async def test_contract_injected_for_structured_task(monkeypatch):
    """结构化工程任务(REST API)→ 安全段 = HONESTY_SYSTEM + 契约 checklist(可信,在 untrusted 之前)。
    契约层是 Argos 差异化资产;此前 loop 从不注入(死代码),现接进 _build_system。"""
    monkeypatch.setattr("argos_agent.skills.recall", lambda *a, **k: [])
    model = CapturingModel(["完成。"])
    loop = _loop(model, FakeStore())
    async for _ in loop.run("设计一个用户管理的 REST API 端点", "s"):
        pass
    sys_prompt = model.systems[0]
    assert sys_prompt.startswith(HONESTY_SYSTEM)
    assert "结构化工程任务" in sys_prompt and "[C1]" in sys_prompt   # REST 契约 checklist 注入


@pytest.mark.asyncio
async def test_no_contract_for_unstructured_task(monkeypatch):
    """非结构化任务(写作)→ 不注入契约(实测契约对开放式任务有害),退裸 HONESTY_SYSTEM。"""
    monkeypatch.setattr("argos_agent.skills.recall", lambda *a, **k: [])
    model = CapturingModel(["完成。"])
    loop = _loop(model, FakeStore())
    async for _ in loop.run("写一篇关于猫的散文", "s"):
        pass
    assert model.systems[0] == HONESTY_SYSTEM   # 无契约、无 untrusted


@pytest.mark.asyncio
async def test_w3_store_recall_injects_untrusted_after_honesty():
    model = CapturingModel(["完成。"])
    loop = _loop(model, RecallStore())
    async for _ in loop.run("修复导入错误", "s"):
        pass
    sys_prompt = model.systems[0]
    # HONESTY_SYSTEM 在前,untrusted 围栏段在后(注入顺序锁死,prompt injection 翻不上去)。
    assert sys_prompt.startswith(HONESTY_SYSTEM)
    assert UNTRUSTED_OPEN in sys_prompt
    assert UNTRUSTED_CLOSE in sys_prompt
    assert sys_prompt.index(HONESTY_SYSTEM) < sys_prompt.index(UNTRUSTED_OPEN)
    # 召回的记忆内容进了 untrusted 段。
    assert "修过同样的导入错误" in sys_prompt
    # reason 一并展示(spec §5.6 可解释召回)。
    assert "命中" in sys_prompt


@pytest.mark.asyncio
async def test_w3_scrubber_strips_echoed_fence_from_token_delta():
    """模型把 untrusted 围栏标记 + 其间内容吐回 → Scrubber 剥掉,不经 TokenDelta 泄露给 UI。"""
    leaked = f"正常前缀{UNTRUSTED_OPEN}偷藏的内部记忆{UNTRUSTED_CLOSE}正常后缀。"
    model = CapturingModel([leaked])
    loop = _loop(model, FakeStore())
    deltas = []
    async for ev in loop.run("g", "s"):
        if isinstance(ev, TokenDelta):
            deltas.append(ev.text)
    out = "".join(deltas)
    # 围栏标记及其间内容被剥掉;围栏外的正常文本保留。
    assert UNTRUSTED_OPEN not in out
    assert UNTRUSTED_CLOSE not in out
    assert "偷藏的内部记忆" not in out
    assert "正常前缀" in out
    assert "正常后缀。" in out
