"""`argos eval tb` 的 sync output 集成测试。

覆盖:
- cmd_tb 的 --sync-output / --no-sync-output / (auto) 三档 flag
- 报告块按 flag 决定是否被 sync_batch 包住 / 输出是否含 BSU/ESU

实测 A/B 看视觉差不在本测试覆盖范围(需要真 TTY),只能验证 flag 行为。
"""
from __future__ import annotations

import argparse
import io
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from argos_agent.eval.benchmarks import terminal_bench as tb


def _stub_report() -> tb.TBBatchReport:
    """最小 TBBatchReport,字段够用,跑 print 不崩。"""
    return tb.TBBatchReport(
        total_seen=2,
        supported=1,
        unsupported=1,
        passed=1,
        failed=0,
        error=0,
        setup_failed=0,
        skipped=1,
        pass_at_1=1.0,
        results=(),
        unsupported_reasons={"unsupported_no_setup": 1},
        per_task_status={
            "fake_task_1": ("passed", "all good"),
            "fake_task_2": ("skipped", "missing setup"),
        },
    )


def _make_args(**overrides) -> argparse.Namespace:
    base = dict(
        subset="smoke", model="default", budget=0.01, budget_s=10,
        keep_worktree=False, format="text",
        sync_output=None,  # default auto
    )
    base.update(overrides)
    return argparse.Namespace(**base)


# ── _print_tb_report 自身(纯文本,不负责 sync) ──

def test_print_tb_report_contains_pass_at_1_line(capsys):
    """报告块照常打印 pass@1 这一行(独立函数不掺 sync 逻辑)。"""
    tb._print_tb_report(_stub_report())
    out = capsys.readouterr().out
    assert "pass@1=100.0%" in out


# ── cmd_tb 对 flag 的端到端处理 ──

def test_cmd_tb_output_includes_bsu_esu_when_sync_flag_true(monkeypatch):
    """`--sync-output` → 输出以 BSU 开头、ESU 结尾。"""
    args = _make_args(sync_output=True)
    monkeypatch.setattr(tb, "run_subset", lambda *a, **kw: _stub_report())

    buf = io.StringIO()
    with patch.object(tb.sys, "stdout", buf):
        rc = tb.cmd_tb(args)
    assert rc == 0
    out = buf.getvalue()
    from argos_agent.tui.sync_output import CSI_BSU, CSI_ESU
    assert out.startswith(CSI_BSU), f"输出应以 BSU 开头,实际: {out[:30]!r}"
    assert out.endswith(CSI_ESU), f"输出应以 ESU 结尾,实际: {out[-30:]!r}"


def test_cmd_tb_output_omits_brackets_when_sync_flag_false(monkeypatch):
    """`--no-sync-output` → 输出不含 BSU/ESU(纯文本)。"""
    args = _make_args(sync_output=False)
    monkeypatch.setattr(tb, "run_subset", lambda *a, **kw: _stub_report())

    buf = io.StringIO()
    with patch.object(tb.sys, "stdout", buf):
        rc = tb.cmd_tb(args)
    assert rc == 0
    out = buf.getvalue()
    from argos_agent.tui.sync_output import CSI_BSU, CSI_ESU
    assert CSI_BSU not in out
    assert CSI_ESU not in out
    # 但报告内容照样在
    assert "pass@1=100.0%" in out


def test_cmd_tb_auto_flag_passes_none_to_sync_batch(monkeypatch):
    """sync_output=None(auto) → 把判断交给 sync_batch 现场 probe(不要预判 enabled)。"""
    args = _make_args(sync_output=None)

    @contextmanager
    def spy_sync_batch(stream, enabled=None):
        spy_sync_batch.calls += 1
        spy_sync_batch.last_enabled = enabled
        yield

    spy_sync_batch.calls = 0
    spy_sync_batch.last_enabled = "unset"

    monkeypatch.setattr(tb, "sync_batch", spy_sync_batch)
    monkeypatch.setattr(tb, "run_subset", lambda *a, **kw: _stub_report())

    rc = tb.cmd_tb(args)
    assert rc == 0
    assert spy_sync_batch.calls == 1
    assert spy_sync_batch.last_enabled is None, (
        "sync_output=None(auto) 应让 sync_batch 现场 probe,不要预判 enabled"
    )


def test_cmd_tb_true_flag_passes_true_to_sync_batch(monkeypatch):
    """sync_output=True → sync_batch 收到 enabled=True(强制走,跳过 probe)。"""
    args = _make_args(sync_output=True)

    @contextmanager
    def spy_sync_batch(stream, enabled=None):
        spy_sync_batch.calls += 1
        spy_sync_batch.last_enabled = enabled
        yield

    spy_sync_batch.calls = 0
    spy_sync_batch.last_enabled = "unset"

    monkeypatch.setattr(tb, "sync_batch", spy_sync_batch)
    monkeypatch.setattr(tb, "run_subset", lambda *a, **kw: _stub_report())

    rc = tb.cmd_tb(args)
    assert rc == 0
    assert spy_sync_batch.calls == 1
    assert spy_sync_batch.last_enabled is True


def test_cmd_tb_false_flag_passes_false_to_sync_batch(monkeypatch):
    """sync_output=False → sync_batch 收到 enabled=False(显式 no-op,跳过 probe)。"""
    args = _make_args(sync_output=False)

    @contextmanager
    def spy_sync_batch(stream, enabled=None):
        spy_sync_batch.calls += 1
        spy_sync_batch.last_enabled = enabled
        yield

    spy_sync_batch.calls = 0
    spy_sync_batch.last_enabled = "unset"

    monkeypatch.setattr(tb, "sync_batch", spy_sync_batch)
    monkeypatch.setattr(tb, "run_subset", lambda *a, **kw: _stub_report())

    rc = tb.cmd_tb(args)
    assert rc == 0
    assert spy_sync_batch.calls == 1
    assert spy_sync_batch.last_enabled is False


# ── argparse 子解析器构造 ──

def test_tb_subparser_default_sync_output_is_none():
    """不传 --sync-output/--no-sync-output → sync_output 默认 None(自动探测)。"""
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    tb.add_tb_subparser(sub)
    args = parser.parse_args(["tb", "--subset", "smoke"])
    assert args.sync_output is None


def test_tb_subparser_sync_output_flag_sets_true():
    """--sync-output → sync_output=True。"""
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    tb.add_tb_subparser(sub)
    args = parser.parse_args(["tb", "--subset", "smoke", "--sync-output"])
    assert args.sync_output is True


def test_tb_subparser_no_sync_output_flag_sets_false():
    """--no-sync-output → sync_output=False。"""
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    tb.add_tb_subparser(sub)
    args = parser.parse_args(["tb", "--subset", "smoke", "--no-sync-output"])
    assert args.sync_output is False


def test_tb_subparser_flags_are_mutually_exclusive():
    """同时传 --sync-output 和 --no-sync-output → argparse 报错(互斥组)。"""
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    tb.add_tb_subparser(sub)
    with pytest.raises(SystemExit):
        parser.parse_args(["tb", "--subset", "smoke", "--sync-output", "--no-sync-output"])