"""Internal documentation."""
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
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(af.config, "DEFAULT_KEYS", ["k-test"])
    c = af.build_components(workspace=str(tmp_path / "ws"))
    assert isinstance(c.store, ArgosStore)
    assert isinstance(c.broker, CapabilityBroker)
    assert isinstance(c.verifier, Verifier)
    assert isinstance(c.model, ModelClient)
    c.close()


def test_build_components_refuses_without_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_DB_PATH", str(tmp_path / "argos.db"))
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(af.config, "DEFAULT_KEYS", [])
    with pytest.raises(RuntimeError, match="key"):
        af.build_components(workspace=str(tmp_path / "ws"))


def test_build_loop_factory_yields_agentloop(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_DB_PATH", str(tmp_path / "argos.db"))
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(af.config, "DEFAULT_KEYS", ["k-test"])
    c = af.build_components(workspace=str(tmp_path / "ws"))
    factory = af.build_loop_factory(c)
    loop = factory()
    assert isinstance(loop, AgentLoop)
    assert factory().bus is not loop.bus
    assert factory().store is c.store
    assert factory().sandbox is c.sandbox
    c.close()


def test_build_run_stack_uses_reloaded_permissions_config(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    from argos.approval import ApprovalLevel
    from argos.core.loop import LoopConfig
    from argos.permissions.config import PermissionsConfig

    old_cfg = PermissionsConfig(default_level="observe")
    reloaded_cfg = PermissionsConfig(default_level="confirm")

    c = MagicMock(spec=af.AppComponents)
    c.config = LoopConfig(model_tier="default", approval_level=ApprovalLevel.CONFIRM)
    c.workspace = tmp_path
    c.registry = None
    c.browser_controller = None
    c.mcp_manager = None
    c.permissions_config = old_cfg

    captured: dict[str, object] = {}

    def _fake_stack(**kwargs):
        captured.update(kwargs)
        return MagicMock(), MagicMock(), MagicMock()

    monkeypatch.setattr(af, "_permissions_get_config", lambda: reloaded_cfg)
    monkeypatch.setattr(af, "_make_gate_broker_sandbox", _fake_stack)

    af.build_run_stack(c, workspace=tmp_path)

    assert captured["perm_config"] is reloaded_cfg
    assert captured["perm_config"] is not old_cfg


def test_model_override_picks_named_profile(tmp_path, monkeypatch):
    """Internal documentation."""
    import json
    monkeypatch.setenv("ARGOS_DB_PATH", str(tmp_path / "argos.db"))
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.json").write_text(json.dumps({"active": "a", "models": {
        "a": {"protocol": "openai", "base_url": "http://x/v1", "model": "m-a", "api_key_env": "AK"},
        "b": {"protocol": "anthropic", "base_url": "https://y", "model": "m-b", "api_key_env": "BK"}}}))
    (tmp_path / ".env").write_text("AK=ka\nBK=kb\n")
    monkeypatch.setenv("ARGOS_WORKSPACE", str(tmp_path / "ws"))
    c = af.build_components(workspace=str(tmp_path / "ws"), model_override="b")
    assert c.model.tier.name == "b" and c.model.tier.model == "m-b"
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


def test_build_components_default_workspace_honors_argos_config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("ARGOS_WORKSPACE", raising=False)
    monkeypatch.setenv("ARGOS_DB_PATH", str(tmp_path / "argos.db"))
    (tmp_path / "config.json").write_text(__import__("json").dumps({
        "active": "local", "models": {"local": {"protocol": "openai",
        "base_url": "http://localhost:11434/v1", "model": "qwen2.5-coder",
        "api_key_env": "OLLAMA_API_KEY"}}}))
    (tmp_path / ".env").write_text("OLLAMA_API_KEY=ollama\n")

    c = build_components()
    try:
        assert c.workspace == (tmp_path / "workspace").resolve()
    finally:
        c.close()


def test_build_components_argos_workspace_overrides_config_dir(tmp_path, monkeypatch):
    ws = tmp_path / "explicit-ws"
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("ARGOS_WORKSPACE", str(ws))
    monkeypatch.setenv("ARGOS_DB_PATH", str(tmp_path / "argos.db"))
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "config.json").write_text(__import__("json").dumps({
        "active": "local", "models": {"local": {"protocol": "openai",
        "base_url": "http://localhost:11434/v1", "model": "qwen2.5-coder",
        "api_key_env": "OLLAMA_API_KEY"}}}))
    (cfg / ".env").write_text("OLLAMA_API_KEY=ollama\n")

    c = build_components()
    try:
        assert c.workspace == ws.resolve()
    finally:
        c.close()


def test_routed_profile_without_key_fails_on_select(tmp_path, monkeypatch):
    import json
    from argos.config import ConfigError
    from argos.routing.categorizer import TaskCategory

    monkeypatch.setenv("ARGOS_DB_PATH", str(tmp_path / "argos.db"))
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.json").write_text(json.dumps({
        "active": "a",
        "models": {
            "a": {
                "protocol": "openai",
                "base_url": "https://api.example.com/v1",
                "model": "model-a",
                "api_key_env": "AK",
            },
            "b": {
                "protocol": "openai",
                "base_url": "https://api.example.com/v1",
                "model": "model-b",
                "api_key_env": "BK",
            },
        },
        "routing": {"by_category": {"simple_read": "b"}},
    }))
    (tmp_path / ".env").write_text("AK=secret\n")
    monkeypatch.delenv("BK", raising=False)

    c = af.build_components(workspace=str(tmp_path / "ws"))
    try:
        assert c.router is not None
        with pytest.raises(ConfigError, match="BK"):
            c.router.select(category=TaskCategory.SIMPLE_READ, tool=None)
    finally:
        c.close()


def test_build_components_router_honors_env_local_config_dir(tmp_path, monkeypatch):
    import json
    from argos import config as C

    cfg_dir = tmp_path / "from-env-local"
    cfg_dir.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ARGOS_DB_PATH", str(tmp_path / "argos.db"))
    monkeypatch.delenv("ARGOS_CONFIG_DIR", raising=False)
    monkeypatch.setattr(C, "_ENV", {"ARGOS_CONFIG_DIR": str(cfg_dir)})
    (cfg_dir / "config.json").write_text(json.dumps({
        "active": "local",
        "models": {
            "local": {
                "protocol": "openai",
                "base_url": "https://api.example.com/v1",
                "model": "model-local",
                "api_key_env": "AK",
            },
            "strong": {
                "protocol": "openai",
                "base_url": "https://api.example.com/v1",
                "model": "model-strong",
                "api_key_env": "SK",
            },
        },
        "routing": {"by_category": {"simple_read": "strong"}},
    }))
    (cfg_dir / ".env").write_text("AK=secret\nSK=secret\n")

    c = af.build_components(workspace=str(tmp_path / "ws"))
    try:
        assert c.router is not None
        assert c.router.routing.by_category["simple_read"] == "strong"
    finally:
        c.close()


def test_build_loop_factory_wires_workflow_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_DB_PATH", str(tmp_path / "argos.db"))
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(af.config, "DEFAULT_KEYS", ["k-test"])
    c = af.build_components(workspace=str(tmp_path / "ws"))
    loop = af.build_loop_factory(c)()
    assert loop._workflow_engine_factory is not None
    from argos.workflow.engine import WorkflowEngine
    assert isinstance(c.workflow_engine_factory(), WorkflowEngine)
    c.close()
