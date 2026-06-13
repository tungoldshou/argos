"""装配层(契约 §3/§5/§6/§7):build_components 组装全栈 + build_loop_factory 产可注入 loop。

注:config.WORKER_KEYS 在 import 时固化,故测试用 monkeypatch.setattr 直改 af.config 属性
(确定性 + 自动撤销),不用 setenv+reload(reload 会跨测试泄漏全局 config)。
"""
import pytest

import argos.app_factory as af
from argos.app_factory import build_components
from argos.core.loop import AgentLoop
from argos.core.models import ModelClient
from argos.core.verify_gate import Verifier
from argos.memory.store import ArgosStore
from argos.sandbox.broker import CapabilityBroker


def test_build_components_assembles_full_stack(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_DB_PATH", str(tmp_path / "argos.db"))
    monkeypatch.setattr(af.config, "WORKER_KEYS", ["k-test"])  # 非空避免诚实拒绝
    c = af.build_components(workspace=str(tmp_path / "ws"))
    assert isinstance(c.store, ArgosStore)
    assert isinstance(c.broker, CapabilityBroker)
    assert isinstance(c.verifier, Verifier)
    assert isinstance(c.model, ModelClient)
    c.close()


def test_build_components_refuses_without_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_DB_PATH", str(tmp_path / "argos.db"))
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path / "cfg"))   # 空目录:走旧 env 回退路径
    # 诚实:无 key 不假装能跑,抛带指引的 RuntimeError(入口捕获→demo 态)。
    monkeypatch.setattr(af.config, "DEFAULT_KEYS", [])
    with pytest.raises(RuntimeError, match="key"):
        af.build_components(workspace=str(tmp_path / "ws"))


def test_build_loop_factory_yields_agentloop(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_DB_PATH", str(tmp_path / "argos.db"))
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path / "cfg"))   # 空目录:走旧 env 回退路径
    monkeypatch.setattr(af.config, "DEFAULT_KEYS", ["k-test"])
    c = af.build_components(workspace=str(tmp_path / "ws"))
    factory = af.build_loop_factory(c)
    loop = factory()
    assert isinstance(loop, AgentLoop)
    # 每次 factory() 新建 EventBus(每轮一条事件流),但共享 store/sandbox/broker(持久)。
    assert factory().bus is not loop.bus
    assert factory().store is c.store
    assert factory().sandbox is c.sandbox
    c.close()


def test_model_override_picks_named_profile(tmp_path, monkeypatch):
    """--model NAME(取代旧 --premium):本次启动用指定的具名 profile,而非当前 active。"""
    import json
    monkeypatch.setenv("ARGOS_DB_PATH", str(tmp_path / "argos.db"))
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.json").write_text(json.dumps({"active": "a", "models": {
        "a": {"protocol": "openai", "base_url": "http://x/v1", "model": "m-a", "api_key_env": "AK"},
        "b": {"protocol": "anthropic", "base_url": "https://y", "model": "m-b", "api_key_env": "BK"}}}))
    (tmp_path / ".env").write_text("AK=ka\nBK=kb\n")
    monkeypatch.setenv("ARGOS_WORKSPACE", str(tmp_path / "ws"))
    c = af.build_components(workspace=str(tmp_path / "ws"), model_override="b")
    assert c.model.tier.name == "b" and c.model.tier.model == "m-b"   # 用了指定 profile,不是 active 'a'
    c.close()


def test_build_components_uses_active_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.json").write_text(__import__("json").dumps({
        "active": "local", "models": {"local": {"protocol": "openai",
        "base_url": "http://localhost:11434/v1", "model": "qwen2.5-coder",
        "api_key_env": "OLLAMA_API_KEY"}}}))
    (tmp_path / ".env").write_text("OLLAMA_API_KEY=ollama\n")
    monkeypatch.setenv("ARGOS_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("ARGOS_DB_PATH", str(tmp_path / "argos.db"))
    c = build_components()
    assert c.model.tier.model == "qwen2.5-coder" and c.model.tier.protocol == "openai"
    c.close()


def test_build_loop_factory_wires_workflow_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_DB_PATH", str(tmp_path / "argos.db"))
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path / "cfg"))   # 空目录:走旧 env 回退路径
    monkeypatch.setattr(af.config, "DEFAULT_KEYS", ["k-test"])
    c = af.build_components(workspace=str(tmp_path / "ws"))
    loop = af.build_loop_factory(c)()
    assert loop._workflow_engine_factory is not None
    # 工厂能产出一个 WorkflowEngine
    from argos.workflow.engine import WorkflowEngine
    assert isinstance(c.workflow_engine_factory(), WorkflowEngine)
    c.close()
