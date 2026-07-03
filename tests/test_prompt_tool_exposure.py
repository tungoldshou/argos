"""Internal documentation."""
from __future__ import annotations

import types

from argos.core.honesty import HONESTY_SYSTEM, LSP_TOOLS
from argos.core.loop import AgentLoop, LoopConfig
from argos.core.verify_gate import Verifier
from argos.tui.events import EventBus
from tests.test_loop_codeact import FakeModel, FakeStore
from tests.test_loop_verify_propose import _ProposeSandbox


def _loop() -> AgentLoop:
    return AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=_ProposeSandbox(lambda c: None),
        broker=None, model=FakeModel([]), verifier=Verifier(),
        config=LoopConfig(verify_cmd=None),
    )


def test_propose_dom_verify_documented_in_base_prompt():
    assert "propose_dom_verify" in HONESTY_SYSTEM


def test_external_info_is_routed_before_shell_escape_hatches():
    """Weather/latest facts must prefer web tools, not ad-hoc curl in CodeAct."""
    assert HONESTY_SYSTEM.index("External or real-time information") < HONESTY_SYSTEM.index(
        "Doable with Python or a shell command"
    )
    assert "do not use run_command/curl or Python HTTP libraries for web facts" in HONESTY_SYSTEM


def test_lsp_tools_constant_lists_all_six():
    for name in ("lsp_definition", "lsp_references", "lsp_hover",
                 "lsp_document_symbols", "lsp_workspace_symbols", "lsp_diagnostics"):
        assert name in LSP_TOOLS, f"{name} 应在 LSP_TOOLS 段"


def test_lsp_tools_absent_from_default_prompt():
    """Internal documentation."""
    assert "lsp_definition" not in HONESTY_SYSTEM


def test_lsp_injected_when_server_configured(monkeypatch, tmp_path):
    """Internal documentation."""
    loop = _loop()
    fake_lsp_json = tmp_path / "lsp.json"
    fake_lsp_json.write_text("{}")
    monkeypatch.setattr("argos.lsp.config.LSP_CONFIG_PATH", fake_lsp_json)
    monkeypatch.setattr("argos.lsp.config.load",
                        lambda path=None: types.SimpleNamespace(servers={"python": 1}))
    stable, _ = loop._build_system_pair("改点代码")
    assert "lsp_definition" in stable and "lsp_references" in stable


def test_lsp_injected_from_argos_config_dir(monkeypatch, tmp_path):
    """Internal documentation."""
    loop = _loop()
    cfg_dir = tmp_path / ".argos"
    cfg_dir.mkdir()
    (cfg_dir / "lsp.json").write_text("{}")
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr("argos.lsp.config.LSP_CONFIG_PATH", None)
    monkeypatch.setattr("argos.lsp.config.load",
                        lambda path=None: types.SimpleNamespace(servers={"python": 1}))

    stable, _ = loop._build_system_pair("改点代码")

    assert "lsp_definition" in stable and "lsp_references" in stable


def test_lsp_not_injected_when_no_server(monkeypatch, tmp_path):
    """Internal documentation."""
    loop = _loop()
    fake_lsp_json = tmp_path / "lsp.json"
    fake_lsp_json.write_text("{}")
    monkeypatch.setattr("argos.lsp.config.LSP_CONFIG_PATH", fake_lsp_json)
    monkeypatch.setattr("argos.lsp.config.load",
                        lambda path=None: types.SimpleNamespace(servers={}))
    stable, _ = loop._build_system_pair("改点代码")
    assert "lsp_definition" not in stable


def test_lsp_not_injected_when_config_file_absent(monkeypatch, tmp_path):
    """Internal documentation."""
    loop = _loop()
    absent_path = tmp_path / "nonexistent_lsp.json"
    monkeypatch.setattr("argos.lsp.config.LSP_CONFIG_PATH", absent_path)
    monkeypatch.setattr("argos.lsp.config.load",
                        lambda path=None: types.SimpleNamespace(servers={"python": 1}))
    stable, _ = loop._build_system_pair("随便一个目标")
    assert "lsp_definition" not in stable, (
        "默认用户(无 lsp.json)不应在提示词中看到 LSP 工具段"
    )


def test_lsp_config_error_degrades_silently(monkeypatch, tmp_path):
    """Internal documentation."""
    def _boom(path=None):
        raise RuntimeError("lsp.json 坏了")
    loop = _loop()
    fake_lsp_json = tmp_path / "lsp.json"
    fake_lsp_json.write_text("{}")
    monkeypatch.setattr("argos.lsp.config.LSP_CONFIG_PATH", fake_lsp_json)
    monkeypatch.setattr("argos.lsp.config.load", _boom)
    stable, _ = loop._build_system_pair("改点代码")
    assert "lsp_definition" not in stable
