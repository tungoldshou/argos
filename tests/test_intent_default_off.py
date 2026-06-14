"""方向 A(2026-06-14):intent 确认门【默认关】——理解即行动,确认只在副作用层。

背景:真机体验问题——输入"你好"被意图确认门拦下(≤5字判空泛)+ 调 LLM 解析(42s)+ 超时
取消。调研(Claude Code / Cursor / Aider / Codex / Copilot)显示主流 coding agent 一致采用
"理解即行动 + 副作用层确认",无一在每次输入前强制回显结构化意图卡。

故 Argos 把 intent 确认门从【默认开】翻成【默认关】:
- 默认 build_components → intent_engine is None → loop 跳过意图门(行为零变更路径)→ goal 直接进 loop。
- 显式 ARGOS_INTENT=1 才启用 NL→Goal 意图确认(降级为可选,而非默认必经)。
- ARGOS_NO_INTENT=1 仍幂等强制关(向后兼容)。
确认仍由已有副作用层守:CapabilityBroker + ApprovalGate + Trust Dial + Seatbelt 沙箱。
"""
import pytest

import argos.app_factory as af


def _build(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_DB_PATH", str(tmp_path / "argos.db"))
    monkeypatch.setattr(af.config, "WORKER_KEYS", ["k-test"])  # 非空避免诚实拒绝
    return af.build_components(workspace=str(tmp_path / "ws"))


def test_intent_engine_off_by_default(tmp_path, monkeypatch):
    """默认(无 ARGOS_INTENT)→ intent_engine is None:意图门不挡路,理解即行动。"""
    monkeypatch.delenv("ARGOS_INTENT", raising=False)
    monkeypatch.delenv("ARGOS_NO_INTENT", raising=False)
    c = _build(tmp_path, monkeypatch)
    try:
        assert c.intent_engine is None, "intent 确认门必须默认关(对齐业界:理解即行动)"
    finally:
        c.close()


def test_intent_engine_on_when_explicitly_enabled(tmp_path, monkeypatch):
    """ARGOS_INTENT=1 → 显式启用 intent 引擎(可选 NL→Goal 意图确认)。"""
    monkeypatch.setenv("ARGOS_INTENT", "1")
    monkeypatch.delenv("ARGOS_NO_INTENT", raising=False)
    c = _build(tmp_path, monkeypatch)
    try:
        assert c.intent_engine is not None, "ARGOS_INTENT=1 应启用 intent 引擎"
    finally:
        c.close()


def test_no_intent_forces_off_even_if_intent_set(tmp_path, monkeypatch):
    """ARGOS_NO_INTENT=1 优先(幂等强制关),即便 ARGOS_INTENT=1 也关。"""
    monkeypatch.setenv("ARGOS_INTENT", "1")
    monkeypatch.setenv("ARGOS_NO_INTENT", "1")
    c = _build(tmp_path, monkeypatch)
    try:
        assert c.intent_engine is None, "ARGOS_NO_INTENT=1 必须强制关(向后兼容)"
    finally:
        c.close()
