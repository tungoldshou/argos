"""runtime ContextVar 隔离测试 —— 承重墙主铁证(并发不串台)。"""
import asyncio
from pathlib import Path

from argos_agent import runtime
from argos_agent.runtime import RunContext


def test_set_context_then_current_reads_it(tmp_path):
    ctx = RunContext(workspace=tmp_path / "a", verify_dir=tmp_path / "av")
    token = runtime.set_context(ctx)
    try:
        assert runtime.current().workspace == tmp_path / "a"
    finally:
        runtime.reset(token)


def test_use_project_returns_token_and_sets_project_mode(tmp_path):
    token = runtime.use_project(str(tmp_path))
    try:
        cur = runtime.current()
        assert cur.project_mode is True
        assert cur.workspace == tmp_path.resolve()
        assert cur.verify_dir == tmp_path.resolve()
    finally:
        runtime.reset(token)


def test_concurrent_tasks_isolated(tmp_path):
    """两个并发 task 各设各的 RunContext,各读自己的 —— 探针 ['A','B'] 的代码级落地。"""
    async def worker(tag: str) -> str:
        token = runtime.set_context(RunContext(workspace=tmp_path / tag, verify_dir=tmp_path / tag))
        await asyncio.sleep(0.01)  # 给调度机会交错
        seen = runtime.current().workspace.name
        runtime.reset(token)
        return seen

    async def main():
        return await asyncio.gather(worker("A"), worker("B"))

    assert asyncio.run(main()) == ["A", "B"]


def test_guard_and_detect_read_contextvar(tmp_path):
    """guard_files/detect_tampering 读 ContextVar 的 RunContext(不再读全局)。"""
    ws = tmp_path / "proj"
    ws.mkdir()
    t = ws / "test_x.py"
    t.write_text("orig", encoding="utf-8")
    token = runtime.set_context(RunContext(workspace=ws, verify_dir=ws, project_mode=True))
    try:
        runtime.guard_files(["test_x.py"])
        assert runtime.detect_tampering() == []
        t.write_text("tampered", encoding="utf-8")
        assert any("test_x.py" in c for c in runtime.detect_tampering())
    finally:
        runtime.reset(token)


def test_build_agent_accepts_checkpointer(monkeypatch):
    """build_agent_with_gate 接受 checkpointer 并透传(传 None 时行为不变)。"""
    from argos_agent import core, config
    # config.LLM_KEY 是 import 时常量,必须直接 patch 它(setenv 改不动已算好的常量)
    monkeypatch.setattr(config, "LLM_KEY", "test-key")
    agent, gate = core.build_agent_with_gate(tools=[], verify_cmd=None, goal=None,
                                             compaction=False, checkpointer=None)
    assert agent is not None and gate is None


def test_llm_tier_param_accepted(monkeypatch):
    """_llm 接受 tier 参数(默认 'worker' 行为不变,planner 走 M3 强模型)。
    注:旧 LangChain 路径已隔离到 core._legacy_agent(langchain 不再污染 core 顶层导入),
    故 ChatAnthropic stub patch 到 _legacy_agent。"""
    from argos_agent import config
    from argos_agent.core import _legacy_agent
    monkeypatch.setattr(config, "LLM_KEY", "test-key")
    # 替 ChatAnthropic 为 stub(签名与 plan 一致)
    captured = {}
    def stub_chat(model, api_key, base_url, max_tokens, temperature):
        captured["model"] = model
        return object()
    monkeypatch.setattr(_legacy_agent, "ChatAnthropic", stub_chat)
    _legacy_agent._llm(tier="planner")
    assert "model" in captured


def test_llm_default_tier_is_worker(monkeypatch):
    from argos_agent import config
    from argos_agent.core import _legacy_agent
    monkeypatch.setattr(config, "LLM_KEY", "test-key")
    captured = {}
    def stub_chat(model, api_key, base_url, max_tokens, temperature):
        captured["model"] = model
        return object()
    monkeypatch.setattr(_legacy_agent, "ChatAnthropic", stub_chat)
    _legacy_agent._llm()
    assert captured["model"] == config.LLM_MODEL  # 默认走 LLM_MODEL,行为与旧版一致
