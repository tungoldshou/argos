"""装配层(契约 §3/§5/§6/§7):build_components 组装全栈 + build_loop_factory 产可注入 loop。

注:config.WORKER_KEYS 在 import 时固化,故测试用 monkeypatch.setattr 直改 af.config 属性
(确定性 + 自动撤销),不用 setenv+reload(reload 会跨测试泄漏全局 config)。
"""
import pytest

import argos_agent.app_factory as af
from argos_agent.core.loop import AgentLoop
from argos_agent.core.models import ModelClient
from argos_agent.core.verify_gate import Verifier
from argos_agent.memory.store import ArgosStore
from argos_agent.sandbox.broker import CapabilityBroker


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
    # 诚实:无 key 不假装能跑,抛带指引的 RuntimeError(入口捕获→demo 态)。
    monkeypatch.setattr(af.config, "WORKER_KEYS", [])
    with pytest.raises(RuntimeError, match="key"):
        af.build_components(workspace=str(tmp_path / "ws"))


def test_build_loop_factory_yields_agentloop(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_DB_PATH", str(tmp_path / "argos.db"))
    monkeypatch.setattr(af.config, "WORKER_KEYS", ["k-test"])
    c = af.build_components(workspace=str(tmp_path / "ws"))
    factory = af.build_loop_factory(c)
    loop = factory()
    assert isinstance(loop, AgentLoop)
    # 每次 factory() 新建 EventBus(每轮一条事件流),但共享 store/sandbox/broker(持久)。
    assert factory().bus is not loop.bus
    assert factory().store is c.store
    assert factory().sandbox is c.sandbox
    c.close()


def test_premium_flag_picks_premium_tier(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_DB_PATH", str(tmp_path / "argos.db"))
    monkeypatch.setattr(af.config, "WORKER_KEYS", ["k-worker"])
    monkeypatch.setattr(af.config, "PREMIUM_KEY", "k-premium")
    c = af.build_components(workspace=str(tmp_path / "ws"), premium=True)
    assert c.model.tier.name == "premium"
    c.close()
