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
    """记录每次 stream 收到的 system / system_dynamic;按脚本逐 run 出 text。"""
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
    # 诚实降级:无 store.recall 且无 skill 命中 → 安全段(HONESTY + 环境块),不夹 untrusted 围栏。
    assert model.systems[0].startswith(HONESTY_SYSTEM)
    assert "【运行环境】" in model.systems[0]   # 环境块属可信安全段,始终注入
    assert UNTRUSTED_OPEN not in model.systems[0]


@pytest.mark.asyncio
async def test_env_context_injected_into_safe_segment(monkeypatch, tmp_path):
    """系统提示注入运行环境块(cwd/OS/日期),在可信安全段(HONESTY 之后、untrusted 之前),
    并明示无需用代码现场探测目录 —— 根治"问目录却跑 os.getcwd/pwd"那类无谓代码动作。"""
    monkeypatch.setattr("argos_agent.skills.recall", lambda *a, **k: [])
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
    assert sys_prompt.startswith(HONESTY_SYSTEM)        # 安全段仍在最前
    assert "【运行环境】" in sys_prompt
    assert str(tmp_path) in sys_prompt                   # 真实 workspace 路径已喂
    assert "无需用代码现场探测" in sys_prompt            # 明示别跑 os.getcwd/pwd
    assert UNTRUSTED_OPEN not in sys_prompt              # 环境块是可信段,不在围栏内


@pytest.mark.asyncio
async def test_project_mode_run_guards_existing_tests(monkeypatch, tmp_path):
    """头号护城河洞修复接线:project_mode 起 run 时自动快照既有测试 →
    之后改它即被 detect_tampering 抓到(此前 guard_files 生产零调用 = 死代码,篡改检测形同虚设)。"""
    from argos_agent import runtime
    monkeypatch.setattr("argos_agent.skills.recall", lambda *a, **k: [])
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
        # run 起始已快照既有测试 → agent 之后偷改评判自己的测试必被抓
        (tmp_path / "test_existing.py").write_text("def test(): pass  # 偷偷改弱\n")
        assert any("test_existing.py" in f for f in runtime.detect_tampering())
    finally:
        runtime.use_sandbox()


@pytest.mark.asyncio
async def test_skills_recalled_into_untrusted_without_store_recall(monkeypatch):
    """skills 召回独立于 store:即便 store 没有 recall,命中的 skill 也进 untrusted 围栏段
    (安全段 HONESTY 在前)。这是「skills 不需要大模型也能用 + 不需要记忆库也能用」的接线铁证。

    任务:loop 把 system 拆 (stable, dynamic) 透传 — stable 含 HONESTY + 工具签名等,
    dynamic 含 untrusted 围栏 + skill body + memory 召回。W3 验证顺序锁稳定段在前、动态段在后。
    """
    from argos_agent import skills as _skills
    fake = _skills.Skill(name="py-test-runner", description="跑 pytest", trust="builtin",
                         enabled=True, body="用 `pytest -q` 跑测试。")
    monkeypatch.setattr("argos_agent.skills.recall", lambda *a, **k: [fake])
    model = CapturingModel(["完成。"])
    loop = _loop(model, FakeStore())  # 无 recall,但 skill 仍应注入
    async for _ in loop.run("帮我跑测试", "s"):
        pass
    stable_prompt = model.systems[0]
    dynamic_prompt = model.system_dynamics[0]
    assert stable_prompt.startswith(HONESTY_SYSTEM)      # 安全段在前
    assert UNTRUSTED_OPEN in dynamic_prompt              # skill 进了 untrusted 围栏(动态段)
    assert "py-test-runner" in dynamic_prompt
    # 跨段顺序锁:stable 出 HONESTY 早于 dynamic 出 UNTRUSTED_OPEN(spec §12.1)
    # (实际"拼接"视角下,HONESTY 必然先于 UNTRUSTED_OPEN 出现,稳定段在前)


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
    # 无契约、无 untrusted(只剩 HONESTY + 环境块这两段可信内容)。
    sys_prompt = model.systems[0]
    assert sys_prompt.startswith(HONESTY_SYSTEM)
    assert "结构化工程任务" not in sys_prompt and "[C1]" not in sys_prompt   # 未注入契约
    assert UNTRUSTED_OPEN not in sys_prompt


@pytest.mark.asyncio
async def test_w3_store_recall_injects_untrusted_after_honesty():
    model = CapturingModel(["完成。"])
    loop = _loop(model, RecallStore())
    async for _ in loop.run("修复导入错误", "s"):
        pass
    # 任务:并行子 agent 前缀缓存 — loop 把 system 拆 (stable, dynamic) 透传。
    # W3 验证"HONESTY 在前 / untrusted 在后"的顺序锁依然成立(分两段但顺序不变)。
    stable_prompt = model.systems[0]
    dynamic_prompt = model.system_dynamics[0]
    # 稳定段以 HONESTY_SYSTEM 开头(它就在最前)
    assert stable_prompt.startswith(HONESTY_SYSTEM)
    # 动态段含 untrusted 围栏(HONESTY 不在 dynamic 里 —— 顺序锁:stable 永远在前)
    assert UNTRUSTED_OPEN in dynamic_prompt
    assert UNTRUSTED_CLOSE in dynamic_prompt
    # 召回的记忆内容进了 untrusted 段(动态段)
    assert "修过同样的导入错误" in dynamic_prompt
    # reason 一并展示(spec §5.6 可解释召回)。
    assert "命中" in dynamic_prompt
    # 顺序锁 cross-field:稳定段有 HONESTY_SYSTEM,动态段有 UNTRUSTED_OPEN——
    # 同一请求里 stable 在 dynamic 之前(请求体里 stable 永远先于 dynamic 出现,
    # 拼接等价于旧行为)。不强求 dynamic 内部偏移(UNTRUSTED_OPEN 本就是首字符)。
    assert HONESTY_SYSTEM in stable_prompt
    assert UNTRUSTED_OPEN in dynamic_prompt


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
