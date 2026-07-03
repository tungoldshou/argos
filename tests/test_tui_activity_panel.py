from __future__ import annotations

import json

import pytest

from argos.tui.widgets.activity_panel import ActivityPanel
from argos.skills_runtime.events import SkillRunStart, SkillRunEnd


def test_skill_catalog_summary_renamed():
    panel = ActivityPanel()
    summary_method = getattr(panel, "_skill_catalog_summary", None)
    assert summary_method is not None, "ActivityPanel 必须有 _skill_catalog_summary 方法"


def test_skill_section_present_in_compose():
    panel = ActivityPanel()
    sections = list(panel.compose())
    titles = [s.border_title for s in sections]
    assert "Skill Catalog" in titles, f"期望 'Skill Catalog' 在 compose 列表,实际 {titles}"
    assert "Skill" in titles, f"期望 'Skill' (singular) 在 compose 列表,实际 {titles}"


def test_skill_section_after_lsp_section_in_compose():
    panel = ActivityPanel()
    titles = [s.border_title for s in panel.compose()]
    lsp_idx = titles.index("LSP")
    skill_idx = titles.index("Skill")
    assert skill_idx == lsp_idx + 1, f"期望 'Skill' 紧接 'LSP',实际 LSP@{lsp_idx} Skill@{skill_idx}"


def test_skill_section_renders_start_state():
    panel = ActivityPanel()
    ev = SkillRunStart(skill_name="verify", args={"timeout": 30})
    handler = getattr(panel, "_on_skill_run_start", None)
    assert handler is not None, "ActivityPanel 必须有 _on_skill_run_start 方法"
    handler(ev)
    summary = panel._skill_summary()
    assert "verify" in summary
    assert "started" in summary


def test_skill_section_renders_end_state_after_start():
    panel = ActivityPanel()
    panel._on_skill_run_start(SkillRunStart(skill_name="simplify", args={}))
    panel._on_skill_run_end(SkillRunEnd(
        skill_name="simplify", verdict="failed", duration_ms=1234,
        finding_count=3, error_count=0,
    ))
    summary = panel._skill_summary()
    assert "simplify" in summary
    assert "failed" in summary
    assert "1.2s" in summary or "1234ms" in summary


def test_mcp_summary_honors_argos_config_dir(tmp_path, monkeypatch):
    from argos import mcp_native

    home = tmp_path / "home"
    cfg_dir = tmp_path / "argos-config"
    home.mkdir()
    cfg_dir.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(mcp_native, "CONFIG_PATH", None)
    (cfg_dir / "mcp.json").write_text(json.dumps({
        "servers": {
            "enabled": {"command": "example"},
            "disabled": {"command": "example", "enabled": False},
        },
    }), encoding="utf-8")

    summary = ActivityPanel._mcp_summary()

    assert "1" in summary
    assert "configured" in summary or "已配置" in summary
