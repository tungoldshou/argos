"""Internal documentation."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from argos.eval.benchmarks import terminal_bench as tb


def _stub_report() -> tb.TBBatchReport:
    """Internal documentation."""
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



def test_print_tb_report_contains_pass_at_1_line(capsys):
    """Internal documentation."""
    tb._print_tb_report(_stub_report())
    out = capsys.readouterr().out
    assert "pass@1=100.0%" in out



def test_cmd_tb_output_includes_bsu_esu_when_sync_flag_true(monkeypatch):
    """Internal documentation."""
    args = _make_args(sync_output=True)
    monkeypatch.setattr(tb, "run_subset", lambda *a, **kw: _stub_report())

    buf = io.StringIO()
    with patch.object(tb.sys, "stdout", buf):
        rc = tb.cmd_tb(args)
    assert rc == 0
    out = buf.getvalue()
    from argos.tui.sync_output import CSI_BSU, CSI_ESU
    assert out.startswith(CSI_BSU), f"输出应以 BSU 开头,实际: {out[:30]!r}"
    assert out.endswith(CSI_ESU), f"输出应以 ESU 结尾,实际: {out[-30:]!r}"


def test_cmd_tb_output_omits_brackets_when_sync_flag_false(monkeypatch):
    """Internal documentation."""
    args = _make_args(sync_output=False)
    monkeypatch.setattr(tb, "run_subset", lambda *a, **kw: _stub_report())

    buf = io.StringIO()
    with patch.object(tb.sys, "stdout", buf):
        rc = tb.cmd_tb(args)
    assert rc == 0
    out = buf.getvalue()
    from argos.tui.sync_output import CSI_BSU, CSI_ESU
    assert CSI_BSU not in out
    assert CSI_ESU not in out
    assert "pass@1=100.0%" in out


def test_cmd_tb_json_format_outputs_machine_readable_json(monkeypatch):
    """Internal documentation."""
    args = _make_args(format="json", sync_output=False)
    monkeypatch.setattr(tb, "run_subset", lambda *a, **kw: _stub_report())

    buf = io.StringIO()
    with patch.object(tb.sys, "stdout", buf):
        rc = tb.cmd_tb(args)

    assert rc == 0
    data = json.loads(buf.getvalue())
    assert data["total_seen"] == 2
    assert data["pass_at_1"] == 1.0
    assert data["per_task_status"]["fake_task_1"][0] == "passed"


def test_cmd_tb_auto_flag_passes_none_to_sync_batch(monkeypatch):
    """Internal documentation."""
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


def test_cmd_tb_runner_base_defaults_to_argos_config_dir(monkeypatch, tmp_path):
    """Internal documentation."""
    args = _make_args(sync_output=False)
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path / "cfg"))
    seen: dict[str, Path] = {}

    class Runner:
        _budget_cost_usd = 0.0
        _budget_s = 0.0

    def fake_make_runner(*, base, keep_worktree):
        seen["base"] = base
        return Runner()

    monkeypatch.setattr("argos.cli.eval._make_runner", fake_make_runner)
    monkeypatch.setattr(tb, "run_subset", lambda *a, **kw: _stub_report())

    assert tb.cmd_tb(args) == 0
    assert seen["base"] == tmp_path / "cfg" / "eval"


def test_cmd_tb_true_flag_passes_true_to_sync_batch(monkeypatch):
    """Internal documentation."""
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
    """Internal documentation."""
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



def test_tb_subparser_default_sync_output_is_none():
    """Internal documentation."""
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
    """Internal documentation."""
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    tb.add_tb_subparser(sub)
    with pytest.raises(SystemExit):
        parser.parse_args(["tb", "--subset", "smoke", "--sync-output", "--no-sync-output"])
