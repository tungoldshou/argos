# tests/test_loop_multiturn.py
import pytest
from argos_agent.core.loop import AgentLoop, LoopConfig
from argos_agent.core.verify_gate import Verdict
from argos_agent.sandbox.backend import ExecResult
from argos_agent.tui.events import EventBus
from argos_agent.memory.store import ArgosStore


class _EchoModel:
    """把它【看到的 messages(role+content)】记录下来,便于断言历史是否带入。
    输出一句可辨识的 assistant 回答,用于验证 assistant 回复也跨轮带回(非单边历史)。"""
    def __init__(self): self.seen = []
    async def stream(self, messages, *, system, system_dynamic=None):
        self.seen.append([(m["role"], m["content"]) for m in messages])
        for ch in "我已处理本轮请求。": yield ch


class _FakeSandbox:
    def spawn(self, *, workspace, namespace, allow_workflow=True, read_only=False): pass
    def exec_code(self, code): return ExecResult(stdout="", value_repr="", exc="")
    def close(self): pass


class _NoCmdVerifier:
    def verify(self, verify_cmd, *, attempts=1):
        return Verdict.unverifiable(detail="(无)", tampered=[], attempts=attempts)


@pytest.mark.asyncio
async def test_second_run_sees_first_turn_history(tmp_path):
    store = ArgosStore(db_path=str(tmp_path / "a.db"))
    model = _EchoModel()
    def mk():
        return AgentLoop(store=store, bus=EventBus(), sandbox=_FakeSandbox(), broker=None,
                         model=model, verifier=_NoCmdVerifier(), config=LoopConfig())
    async for _ in mk().run("第一轮:做个贪吃蛇", "sess-A"):
        pass
    async for _ in mk().run("好的", "sess-A"):
        pass
    # 第二轮模型看到的 messages(role, content):必须既带回第一轮 user 目标,
    # 也带回第一轮 assistant 回答 —— 否则就是"单边历史"(只记用户提过啥、不记 agent 答过啥)。
    last_seen = model.seen[-1]
    assert any(r == "user" and "贪吃蛇" in c for r, c in last_seen), "第二轮应带入第一轮 user 目标"
    assert any(r == "assistant" for r, c in last_seen), "第二轮应带入第一轮 assistant 回答(非单边历史)"
    store.close()


class _EmptyFinalModel:
    """最终段输出纯空白(模型用空 turn 宣布完成)——复现"空 assistant 答复"路径。"""
    async def stream(self, messages, *, system, system_dynamic=None):
        for ch in "   ":   # 纯空白,strip 后为空
            yield ch


@pytest.mark.asyncio
async def test_empty_final_answer_still_persists_assistant(tmp_path):
    """高优先级修复:即使本轮最终 assistant 文本为空(空 turn 宣布完成),也要落一条占位
    assistant —— 否则连续多轮在 DB 堆出连续 user,模型看不出是独立任务=用户看到的"没串上下文"。
    删掉占位逻辑(恢复 `if text.strip():` 守卫)该测试即失败(非恒真式)。"""
    store = ArgosStore(db_path=str(tmp_path / "empty.db"))

    def mk():
        return AgentLoop(store=store, bus=EventBus(), sandbox=_FakeSandbox(), broker=None,
                         model=_EmptyFinalModel(), verifier=_NoCmdVerifier(), config=LoopConfig())
    async for _ in mk().run("第一轮任务", "sess-E"):
        pass
    async for _ in mk().run("第二轮任务", "sess-E"):
        pass
    roles = [m["role"] for m in store.get_messages("sess-E")]
    assert not any(roles[i] == "user" and roles[i + 1] == "user" for i in range(len(roles) - 1)), \
        f"空 assistant 答复不得导致连续 user 历史:{roles}"
    assert roles.count("assistant") >= 2, f"每轮都应落一条 assistant(空答复用占位):{roles}"
    store.close()


@pytest.mark.asyncio
async def test_loop_reuse_resets_run_state(tmp_path):
    """run() 起手必须 _reset_run_state:污染上一轮残留状态后跑一轮,残留必须被清零
    (本轮 _EchoModel 不产代码 → 0 action)。删掉 _reset_run_state 该测试即失败(非恒真式)。"""
    store = ArgosStore(db_path=str(tmp_path / "b.db"))
    loop = AgentLoop(store=store, bus=EventBus(), sandbox=_FakeSandbox(), broker=None,
                     model=_EchoModel(), verifier=_NoCmdVerifier(), config=LoopConfig())
    # 模拟上一轮跑完留下的脏状态
    loop._actions = 99
    loop._tok_in = 12345
    loop._tok_out = 6789
    loop._fail_count = 7
    async for _ in loop.run("新一轮", "s"):
        pass
    assert loop._actions == 0, "run() 起手必须重置 _actions(本轮无代码动作)"
    assert loop._tok_in == 0 and loop._tok_out == 0, "run() 起手必须重置 token 累计"
    assert loop._fail_count == 0, "run() 起手必须重置 _fail_count"
    store.close()
