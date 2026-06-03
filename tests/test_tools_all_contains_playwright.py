"""验 ALL_TOOLS 包含 Playwright 4 件 + 名字/描述存在。"""
import pytest


def test_all_tools_contains_4_playwright_tools():
    from argos_agent.tools import ALL_TOOLS
    names = {t.name for t in ALL_TOOLS}
    assert "navigate" in names
    assert "snapshot" in names
    assert "click" in names
    assert "type_text" in names


def test_all_tools_navigate_description_mentions_browser():
    from argos_agent.tools import ALL_TOOLS
    nav = next(t for t in ALL_TOOLS if t.name == "navigate")
    assert "browser" in (nav.description or "").lower() or "url" in (nav.description or "").lower()


def test_existing_7_tools_still_present():
    """回归:7 既有工具不因这次 append 丢。"""
    from argos_agent.tools import ALL_TOOLS
    names = {t.name for t in ALL_TOOLS}
    for name in ("read_file", "write_file", "edit_file", "run_command",
                 "web_search", "web_extract", "search_files"):
        assert name in names, f"lost tool: {name}"
