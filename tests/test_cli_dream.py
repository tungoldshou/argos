"""T10:argos dream CLI 子命令验收测试(TDD)。

覆盖:
  1. test_cli_dream_report_empty — ARGOS_DREAMS_DIR 指空目录,返 0 + 输出含"暂无"
  2. test_cli_dream_report_shows_latest — 写两天报告文件,输出最新文件最后一行计数
  3. test_cli_dream_no_key_degrades — monkeypatch build_components 抛 RuntimeError →
     输出含 "argos setup" 提示,执行了 consolidate(不炸),返 0
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── 辅助:构造 args namespace ────────────────────────────────────────────


def _args(report: bool = False) -> argparse.Namespace:
    ns = argparse.Namespace()
    ns.report = report
    return ns


# ── 1. --report 空目录 → 诚实空态 ───────────────────────────────────────


def test_cli_dream_report_empty(tmp_path, monkeypatch, capsys):
    """ARGOS_DREAMS_DIR 指 tmp 空目录,run_dream(--report) → 输出含"暂无",返 0。"""
    monkeypatch.setenv("ARGOS_DREAMS_DIR", str(tmp_path))

    from argos_agent.cli.dream import run_dream
    code = run_dream(_args(report=True))
    out = capsys.readouterr().out
    assert code == 0
    assert "暂无" in out


# ── 2. --report 读最新文件最后一行 ──────────────────────────────────────


def test_cli_dream_report_shows_latest(tmp_path, monkeypatch, capsys):
    """写两天报告文件,断言打印的是最新文件最后一行的计数。"""
    monkeypatch.setenv("ARGOS_DREAMS_DIR", str(tmp_path))

    # 较旧的文件(2020-01-01)
    old = tmp_path / "2020-01-01.jsonl"
    old.write_text(
        json.dumps({"ts": 1577836800.0, "units_total": 1, "promoted": 0,
                    "rejected": 0, "skipped": 1, "memory_merged": 0, "memory_archived": 0}) + "\n"
    )
    # 最新文件(2020-01-02):两行,应读最后一行
    new = tmp_path / "2020-01-02.jsonl"
    line1 = json.dumps({"ts": 1577923200.0, "units_total": 2, "promoted": 1,
                         "rejected": 0, "skipped": 1, "memory_merged": 0, "memory_archived": 0})
    line2 = json.dumps({"ts": 1577926800.0, "units_total": 5, "promoted": 3,
                         "rejected": 1, "skipped": 1, "memory_merged": 2, "memory_archived": 4})
    new.write_text(line1 + "\n" + line2 + "\n")

    from argos_agent.cli.dream import run_dream
    code = run_dream(_args(report=True))
    out = capsys.readouterr().out
    assert code == 0
    # 最后一行计数:units=5 promoted=3(_fmt_report 真实输出格式)
    assert "units_total=5" in out and "promoted=3" in out


# ── 2b. --report 非 dict 报告内容 → 守卫不崩溃 ─────────────────────────


@pytest.mark.parametrize("bad_payload", [[], 42, "str", True])
def test_cli_dream_report_non_dict_does_not_crash(tmp_path, monkeypatch, capsys, bad_payload):
    """写入非 dict JSON 行到 dreams JSONL;run_dream(--report) 不抛 AttributeError,
    返 0,输出含 '格式异常'。
    """
    monkeypatch.setenv("ARGOS_DREAMS_DIR", str(tmp_path))

    # 写一个 JSONL 文件,最后一行是坏 payload
    report_file = tmp_path / "2020-01-01.jsonl"
    report_file.write_text(json.dumps(bad_payload) + "\n")

    from argos_agent.cli.dream import run_dream
    code = run_dream(_args(report=True))
    out = capsys.readouterr().out
    assert code == 0
    assert "格式异常" in out


# ── 3. 无 key 降级:build_components 抛 RuntimeError ─────────────────────


def test_cli_dream_no_key_degrades(tmp_path, monkeypatch, capsys):
    """monkeypatch build_components 抛 RuntimeError → 输出含"argos setup"提示,
    执行了 consolidate(ARGOS_MEMORY_DIR 指 tmp 不炸),返 0。
    """
    monkeypatch.setenv("ARGOS_DREAMS_DIR", str(tmp_path / "dreams"))
    monkeypatch.setenv("ARGOS_MEMORY_DIR", str(tmp_path / "memory"))
    (tmp_path / "dreams").mkdir()
    (tmp_path / "memory").mkdir()

    consolidate_called = []

    def _fake_consolidate(memory_dir):
        consolidate_called.append(memory_dir)
        from argos_agent.memory.consolidate import ConsolidationReport
        return ConsolidationReport(merged=0, archived=0)

    with (
        patch("argos_agent.app_factory.build_components",
              side_effect=RuntimeError("no API key")),
        patch("argos_agent.memory.consolidate.consolidate", side_effect=_fake_consolidate),
    ):
        from argos_agent.cli import dream as _dream_mod
        # 重新 import 以防模块级缓存干扰
        import importlib
        importlib.reload(_dream_mod)

        code = _dream_mod.run_dream(_args(report=False))

    out = capsys.readouterr().out
    assert code == 0
    assert "argos setup" in out
    assert len(consolidate_called) == 1  # consolidate 真的跑了


# ── 4. TUI:inline 模式 /dream 拒绝 ─────────────────────────────────────


@pytest.mark.asyncio
async def test_tui_dream_inline_refuses():
    """inline session → transcript 输出含"需要 daemon"。"""
    import os
    os.environ["ARGOS_NO_DAEMON"] = "1"
    try:
        from argos_agent.tui.app import ArgosApp
        from argos_agent.tui.commands import parse_slash
        from argos_agent.tui.fakeloop import FakeLoop
        from argos_agent.tui.widgets.transcript import Transcript

        app = ArgosApp(loop_factory=lambda: FakeLoop())
        async with app.run_test() as pilot:
            await pilot.pause()
            cmd = parse_slash("/dream")
            await app._dispatch_slash(cmd)
            txt = app.query_one("#transcript", Transcript).rendered_text
        assert "daemon" in txt.lower() or "inline" in txt.lower()
    finally:
        os.environ.pop("ARGOS_NO_DAEMON", None)


# ── 5. TUI:daemon 模式 /dream → POST /dream/run ─────────────────────────


@pytest.mark.asyncio
async def test_tui_dream_daemon_posts():
    """stub daemon client 断言 /dream/run 发了 POST 且 202 渲染成功文案。"""
    import os
    os.environ["ARGOS_NO_DAEMON"] = "1"
    try:
        from argos_agent.tui.app import ArgosApp
        from argos_agent.tui.commands import parse_slash
        from argos_agent.tui.fakeloop import FakeLoop
        from argos_agent.tui.widgets.transcript import Transcript

        # 提取 /dream 纯函数渲染逻辑测试(不经过 Textual app 的 daemon 探测)
        # 直接测 _dream_cmd 实现中的 daemon 分支 — 注入 mock daemon client
        app = ArgosApp(loop_factory=lambda: FakeLoop())

        # 手动注入 daemon 客户端 stub(模拟已连上 daemon)
        mock_client = MagicMock()
        # _request 必须是 AsyncMock,因为 _dream_cmd 对其做 await
        mock_client._request = AsyncMock(return_value=(202, {}, '{"state":"dream_started"}'))

        app._with_daemon = True
        app._daemon_client = mock_client
        app._daemon_session_id = "test-session-id"

        async with app.run_test() as pilot:
            await pilot.pause()
            cmd = parse_slash("/dream")
            await app._dispatch_slash(cmd)
            txt = app.query_one("#transcript", Transcript).rendered_text

        # 断言发了 POST
        mock_client._request.assert_called_once()
        call_args = mock_client._request.call_args
        assert call_args[0][0] == "POST"
        assert "/dream/run" in call_args[0][1]
        # 断言渲染了成功文案(202 分支 → "Dream 已启动,进度见活动栏。")
        assert "已启动" in txt
    finally:
        os.environ.pop("ARGOS_NO_DAEMON", None)


# ── 6. TUI:/dream status — daemon 返回非 dict report 不崩溃 ──────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_report", [[], 42, "string", True])
async def test_tui_dream_status_non_dict_report_does_not_crash(bad_report):
    """daemon 返回非 dict 的 'report' 值时,/dream status 输出格式错误提示而不炸 App。

    修复评审问题:report = body.get('report') 只守 None;非 dict 值传入
    _fmt_dream_report 会 AttributeError → exit_on_error 退出 App。
    """
    import json as _json
    import os
    os.environ["ARGOS_NO_DAEMON"] = "1"
    try:
        from argos_agent.tui.app import ArgosApp
        from argos_agent.tui.commands import parse_slash
        from argos_agent.tui.fakeloop import FakeLoop
        from argos_agent.tui.widgets.transcript import Transcript

        app = ArgosApp(loop_factory=lambda: FakeLoop())

        mock_client = MagicMock()
        mock_client._request = AsyncMock(
            return_value=(200, {}, _json.dumps({"report": bad_report}))
        )

        app._with_daemon = True
        app._daemon_client = mock_client
        app._daemon_session_id = "test-session-id"

        async with app.run_test() as pilot:
            await pilot.pause()
            cmd = parse_slash("/dream status")
            await app._dispatch_slash(cmd)
            txt = app.query_one("#transcript", Transcript).rendered_text

        # 不应炸,应输出格式错误提示
        assert "格式异常" in txt
    finally:
        os.environ.pop("ARGOS_NO_DAEMON", None)
