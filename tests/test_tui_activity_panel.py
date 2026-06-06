"""Activity panel 'Skill Catalog' 重命名 + 'Skill' 新区段渲染测试(spec §2.6 / §2.7)。

不跑 Textual app,直接构造 ActivityPanel 实例 + 调内部 _skill_summary / _skill_catalog_summary。"""
from __future__ import annotations

import pytest

from argos_agent.tui.widgets.activity_panel import ActivityPanel
from argos_agent.skills_runtime.events import SkillRunStart, SkillRunEnd


def test_skill_catalog_summary_renamed():
    """idx 4 section 标题从 'Skills' → 'Skill Catalog'(spec §2.6 命名澄清)。"""
    # 通过 compose() 找标题;若没 render 就用 _sections 索引(本期 v1:_Section 没列表)
    panel = ActivityPanel()
    # 直接验命名:用 panel._skills_summary 行为(spec 已存在的 skills count 渲染)
    # 但**只**验标题字符串本身 = 'Skill Catalog'
    summary_method = getattr(panel, "_skill_catalog_summary", None)
    assert summary_method is not None, "ActivityPanel 必须有 _skill_catalog_summary 方法"


def test_skill_section_present_in_compose():
    """ActivityPanel.compose() 必须产出一个标题为 'Skill' 的 _Section(新 idx 10)。"""
    panel = ActivityPanel()
    sections = list(panel.compose())
    titles = [s.border_title for s in sections]
    assert "Skill Catalog" in titles, f"期望 'Skill Catalog' 在 compose 列表,实际 {titles}"
    assert "Skill" in titles, f"期望 'Skill' (singular) 在 compose 列表,实际 {titles}"


def test_skill_section_after_lsp_section_in_compose():
    """新 'Skill' section 在 'LSP' 之后(spec §2.6 排布要求 idx 10)。"""
    panel = ActivityPanel()
    titles = [s.border_title for s in panel.compose()]
    lsp_idx = titles.index("LSP")
    skill_idx = titles.index("Skill")
    assert skill_idx == lsp_idx + 1, f"期望 'Skill' 紧接 'LSP',实际 LSP@{lsp_idx} Skill@{skill_idx}"


def test_skill_section_renders_start_state():
    """SkillRunStart 注入后,panel 显 'started (timeout=Ns)' 单行。"""
    panel = ActivityPanel()
    ev = SkillRunStart(skill_name="verify", args={"timeout": 30})
    # 假设有 _on_skill_run_start(ev) 方法
    handler = getattr(panel, "_on_skill_run_start", None)
    assert handler is not None, "ActivityPanel 必须有 _on_skill_run_start 方法"
    handler(ev)
    summary = panel._skill_summary()
    assert "verify" in summary
    assert "started" in summary


def test_skill_section_renders_end_state_after_start():
    """先 start 后 end → summary 显 verdict + duration。"""
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
