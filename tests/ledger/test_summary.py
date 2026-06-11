"""人话模板 summarize() 测试 — 确定性,不调模型。"""
from __future__ import annotations

import pytest
from argos_agent.ledger.summary import summarize


class TestFilesystemSummaries:
    def test_write_file_with_path(self):
        s = summarize("write_file", {"path": "/tmp/report.md", "lines": 120})
        assert "report.md" in s
        assert "120" in s

    def test_write_file_no_lines(self):
        s = summarize("write_file", {"path": "a.py"})
        assert "a.py" in s
        assert "写入" in s

    def test_edit_file(self):
        s = summarize("edit_file", {"path": "main.py", "lines_added": 5, "lines_removed": 2})
        assert "main.py" in s
        assert "5" in s
        assert "2" in s

    def test_read_file(self):
        s = summarize("read_file", {"path": "config.json"})
        assert "config.json" in s
        assert "读取" in s

    def test_delete_file(self):
        s = summarize("delete_file", {"path": "old.log"})
        assert "old.log" in s
        assert "删除" in s

    def test_list_dir(self):
        s = summarize("list_dir", {"path": "/tmp/workspace"})
        assert "目录" in s


class TestShellSummaries:
    def test_run_shell_with_command(self):
        s = summarize("run_shell", {"command": "pytest tests/ -q"})
        assert "pytest" in s

    def test_bash_long_command_truncated(self):
        long_cmd = "x" * 100
        s = summarize("bash", {"command": long_cmd})
        assert "…" in s
        assert len(s) < 200

    def test_run_shell_no_command(self):
        s = summarize("run_shell", {})
        assert "shell" in s.lower() or "命令" in s


class TestNetworkSummaries:
    def test_web_fetch(self):
        s = summarize("web_fetch", {"url": "https://example.com/api"})
        assert "GET" in s or "example.com" in s

    def test_web_search(self):
        s = summarize("web_search", {"query": "argos agent"})
        assert "argos agent" in s

    def test_http_post(self):
        s = summarize("http_post", {"url": "https://api.example.com/send"})
        assert "POST" in s or "example.com" in s


class TestBrowserSummaries:
    def test_browser_navigate(self):
        s = summarize("browser_navigate", {"url": "https://google.com"})
        assert "导航" in s or "google.com" in s

    def test_browser_click(self):
        s = summarize("browser_click", {"selector": "#submit-btn"})
        assert "点击" in s or "submit" in s

    def test_browser_fill(self):
        s = summarize("browser_fill", {"selector": "#email", "value": "test@x.com"})
        assert "填写" in s or "email" in s

    def test_browser_screenshot(self):
        s = summarize("browser_screenshot", {})
        assert "截图" in s


class TestFallback:
    def test_unknown_action(self):
        s = summarize("custom_tool_xyz", {"foo": "bar"})
        assert "custom_tool_xyz" in s
        assert "执行" in s

    def test_empty_args(self):
        s = summarize("write_file", {})
        assert "写入" in s  # 诚实降级,不崩
