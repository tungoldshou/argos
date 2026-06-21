"""提示词工具暴露测试:此前 6 个 LSP 工具 + propose_dom_verify 已绑进命名空间却在系统提示里
完全隐形(callable-yet-invisible),便宜模型只能靠撞运气调到。修复后:

  · propose_dom_verify 进基础 _TOOLS(browser 任务的 DOM 验证,始终可见)。
  · 6 个 LSP 工具按需可见 —— 仅当配了 ~/.argos/lsp.json(servers 非空)时由 _build_system_pair 注入
    (默认不占便宜模型预算)。
"""
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


def test_lsp_tools_constant_lists_all_six():
    for name in ("lsp_definition", "lsp_references", "lsp_hover",
                 "lsp_document_symbols", "lsp_workspace_symbols", "lsp_diagnostics"):
        assert name in LSP_TOOLS, f"{name} 应在 LSP_TOOLS 段"


def test_lsp_tools_absent_from_default_prompt():
    """默认(无 LSP 配置)→ LSP 工具不进系统提示(不占预算)。"""
    assert "lsp_definition" not in HONESTY_SYSTEM


def test_lsp_injected_when_server_configured(monkeypatch, tmp_path):
    """lsp.json 存在且 servers 非空 → LSP 段注入。"""
    loop = _loop()
    # 用 tmp_path 中一个真实存在的文件来满足 .exists() 检查
    fake_lsp_json = tmp_path / "lsp.json"
    fake_lsp_json.write_text("{}")
    monkeypatch.setattr("argos.lsp.config.LSP_CONFIG_PATH", fake_lsp_json)
    monkeypatch.setattr("argos.lsp.config.load",
                        lambda path=None: types.SimpleNamespace(servers={"python": 1}))
    stable, _ = loop._build_system_pair("改点代码")
    assert "lsp_definition" in stable and "lsp_references" in stable


def test_lsp_not_injected_when_no_server(monkeypatch, tmp_path):
    """lsp.json 存在但 servers 空 → 不注入。"""
    loop = _loop()
    fake_lsp_json = tmp_path / "lsp.json"
    fake_lsp_json.write_text("{}")
    monkeypatch.setattr("argos.lsp.config.LSP_CONFIG_PATH", fake_lsp_json)
    monkeypatch.setattr("argos.lsp.config.load",
                        lambda path=None: types.SimpleNamespace(servers={}))
    stable, _ = loop._build_system_pair("改点代码")
    assert "lsp_definition" not in stable


def test_lsp_not_injected_when_config_file_absent(monkeypatch, tmp_path):
    """lsp.json 不存在(默认用户) → 不注入,即便 load() 返回默认 python server。

    这是修复 P2 bug 的铁证:load() 文件不存在时返回 BUILTIN_DEFAULT_CONFIG(含 python
    server),旧门控 `if _load_lsp().servers:` 对所有默认用户都 True;新门控加了
    LSP_CONFIG_PATH.exists() 前置检查,文件不存在则短路不注入。
    """
    loop = _loop()
    # 指向一个不存在的路径
    absent_path = tmp_path / "nonexistent_lsp.json"
    monkeypatch.setattr("argos.lsp.config.LSP_CONFIG_PATH", absent_path)
    # load() 仍返回有 servers 的默认配置(复现旧 bug 场景)
    monkeypatch.setattr("argos.lsp.config.load",
                        lambda path=None: types.SimpleNamespace(servers={"python": 1}))
    stable, _ = loop._build_system_pair("随便一个目标")
    assert "lsp_definition" not in stable, (
        "默认用户(无 lsp.json)不应在提示词中看到 LSP 工具段"
    )


def test_lsp_config_error_degrades_silently(monkeypatch, tmp_path):
    """LSP 配置读取抛错 → 诚实降级为不注入,不阻断 run。"""
    def _boom(path=None):
        raise RuntimeError("lsp.json 坏了")
    loop = _loop()
    # 文件存在才能触发 load()；让 load() 抛错测试降级
    fake_lsp_json = tmp_path / "lsp.json"
    fake_lsp_json.write_text("{}")
    monkeypatch.setattr("argos.lsp.config.LSP_CONFIG_PATH", fake_lsp_json)
    monkeypatch.setattr("argos.lsp.config.load", _boom)
    stable, _ = loop._build_system_pair("改点代码")
    assert "lsp_definition" not in stable  # 不崩、不注入
