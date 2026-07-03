from __future__ import annotations

import pytest

from argos.core.loop import AgentLoop, LoopConfig
from argos.core.honesty import HONESTY_SYSTEM, UNTRUSTED_OPEN, UNTRUSTED_CLOSE
from argos.core.types import Verdict
from argos.memory.store import MemoryRecord
from argos.sandbox.backend import ExecResult
from argos.tui.events import EventBus, TokenDelta


class CapturingModel:
    def __init__(self, scripts):
        self._s = scripts
        self._i = 0
        self.systems: list[str] = []
        self.system_dynamics: list[str] = []

    async def stream(self, messages, *, system, system_dynamic=None):
        self.systems.append(system)
        self.system_dynamics.append(system_dynamic or "")
        text = self._s[min(self._i, len(self._s) - 1)]
        self._i += 1
        for ch in text:
            yield ch


class FakeSandbox:
    def spawn(self, *, workspace, namespace, allow_workflow=True, read_only=False): ...
    def exec_code(self, code): return ExecResult(stdout="ran", value_repr="", exc="")
    def close(self): ...


class PassVerifier:
    def verify(self, verify_cmd, *, attempts=1):
        return Verdict.passed(detail="[exit_code=0]", verify_cmd=verify_cmd, attempts=attempts)


class FakeStore:
    def __init__(self): self.events = []
    def append_event(self, sid, ev): self.events.append(ev)
    def append_message(self, sid, **kw): return "m0"


class RecallStore(FakeStore):
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
    monkeypatch.setattr("argos.skills.recall", lambda *a, **k: [])
    model = CapturingModel(["完成。"])
    loop = _loop(model, FakeStore())
    async for _ in loop.run("写个文件", "s"):
        pass
    assert model.systems, "模型没被调用"
    assert model.systems[0].startswith(HONESTY_SYSTEM)
    assert "<environment>" in model.systems[0]
    assert UNTRUSTED_OPEN not in model.systems[0]


@pytest.mark.asyncio
async def test_env_context_injected_into_safe_segment(monkeypatch, tmp_path):
    monkeypatch.setattr("argos.skills.recall", lambda *a, **k: [])
    model = CapturingModel(["完成。"])
    loop = AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=FakeSandbox(), broker=None,
        model=model, verifier=PassVerifier(),
        config=LoopConfig(verify_cmd=None, max_steps=4),
        workspace=tmp_path,
    )
    async for _ in loop.run("你在什么目录?", "s"):
        pass
    sys_prompt = model.systems[0]
    assert sys_prompt.startswith(HONESTY_SYSTEM)
    assert "<environment>" in sys_prompt
    assert str(tmp_path) in sys_prompt
    assert "don't probe them at runtime" in sys_prompt
    assert UNTRUSTED_OPEN not in sys_prompt


@pytest.mark.asyncio
async def test_project_mode_run_guards_existing_tests(monkeypatch, tmp_path):
    from argos import runtime
    monkeypatch.setattr("argos.skills.recall", lambda *a, **k: [])
    (tmp_path / "test_existing.py").write_text("def test(): assert True\n")
    runtime.use_project(str(tmp_path))
    try:
        model = CapturingModel(["完成。"])
        loop = AgentLoop(
            store=FakeStore(), bus=EventBus(), sandbox=FakeSandbox(), broker=None,
            model=model, verifier=PassVerifier(),
            config=LoopConfig(verify_cmd=None, max_steps=4), workspace=tmp_path,
        )
        async for _ in loop.run("改点东西", "s"):
            pass
        (tmp_path / "test_existing.py").write_text("def test(): pass  # 偷偷改弱\n")
        assert any("test_existing.py" in f for f in runtime.detect_tampering())
    finally:
        runtime.use_sandbox()


@pytest.mark.asyncio
async def test_skills_recalled_into_untrusted_without_store_recall(monkeypatch):
    from argos import skills as _skills
    fake = _skills.Skill(name="py-test-runner", description="跑 pytest", trust="builtin",
                         enabled=True, body="用 `pytest -q` 跑测试。")
    monkeypatch.setattr("argos.skills.recall", lambda *a, **k: [fake])
    model = CapturingModel(["完成。"])
    loop = _loop(model, FakeStore())
    async for _ in loop.run("帮我跑测试", "s"):
        pass
    stable_prompt = model.systems[0]
    dynamic_prompt = model.system_dynamics[0]
    assert stable_prompt.startswith(HONESTY_SYSTEM)
    assert UNTRUSTED_OPEN in dynamic_prompt
    assert "py-test-runner" in dynamic_prompt


@pytest.mark.asyncio
async def test_contract_injected_for_structured_task(monkeypatch):
    monkeypatch.setattr("argos.skills.recall", lambda *a, **k: [])
    model = CapturingModel(["完成。"])
    loop = _loop(model, FakeStore())
    async for _ in loop.run("设计一个用户管理的 REST API 端点", "s"):
        pass
    sys_prompt = model.systems[0]
    assert sys_prompt.startswith(HONESTY_SYSTEM)
    assert "Structured Engineering Task" in sys_prompt and "[C1]" in sys_prompt


@pytest.mark.asyncio
async def test_no_contract_for_unstructured_task(monkeypatch):
    monkeypatch.setattr("argos.skills.recall", lambda *a, **k: [])
    model = CapturingModel(["完成。"])
    loop = _loop(model, FakeStore())
    async for _ in loop.run("写一篇关于猫的散文", "s"):
        pass
    sys_prompt = model.systems[0]
    assert sys_prompt.startswith(HONESTY_SYSTEM)
    assert "结构化工程任务" not in sys_prompt and "[C1]" not in sys_prompt
    assert UNTRUSTED_OPEN not in sys_prompt


@pytest.mark.asyncio
async def test_w3_store_recall_injects_untrusted_after_honesty():
    model = CapturingModel(["完成。"])
    loop = _loop(model, RecallStore())
    async for _ in loop.run("修复导入错误", "s"):
        pass
    stable_prompt = model.systems[0]
    dynamic_prompt = model.system_dynamics[0]
    assert stable_prompt.startswith(HONESTY_SYSTEM)
    assert UNTRUSTED_OPEN in dynamic_prompt
    assert UNTRUSTED_CLOSE in dynamic_prompt
    assert "修过同样的导入错误" in dynamic_prompt
    assert "命中" in dynamic_prompt
    assert HONESTY_SYSTEM in stable_prompt
    assert UNTRUSTED_OPEN in dynamic_prompt


@pytest.mark.asyncio
async def test_w3_scrubber_strips_echoed_fence_from_token_delta():
    leaked = f"正常前缀{UNTRUSTED_OPEN}偷藏的内部记忆{UNTRUSTED_CLOSE}正常后缀。"
    model = CapturingModel([leaked])
    loop = _loop(model, FakeStore())
    deltas = []
    async for ev in loop.run("g", "s"):
        if isinstance(ev, TokenDelta):
            deltas.append(ev.text)
    out = "".join(deltas)
    assert UNTRUSTED_OPEN not in out
    assert UNTRUSTED_CLOSE not in out
    assert "偷藏的内部记忆" not in out
    assert "正常前缀" in out
    assert "正常后缀。" in out
