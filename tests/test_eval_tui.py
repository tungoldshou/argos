"""#7 T7+T8 TUI /eval slash 命令测试。"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from argos_agent.tui import commands as tui_cmd
from argos_agent.eval.results import append
from argos_agent.eval.runner import EvalResult, PASS_PASSED, PASS_FAILED


# ── parse_slash / COMMAND_HELP ───────────────────────────────────────


def test_eval_command_in_commands_dict():
    """COMMAND_HELP 收录 eval(spec §7 T7)。"""
    assert "eval" in tui_cmd.COMMAND_HELP


def test_eval_command_parsed_as_known():
    """parse_slash 解析 /eval → known=True。"""
    sc = tui_cmd.parse_slash("/eval")
    assert sc is not None
    assert sc.name == "eval"
    assert sc.known is True
    assert sc.arg == ""


def test_eval_run_subcommand_parsed():
    sc = tui_cmd.parse_slash("/eval run bug_fix_001")
    assert sc is not None
    assert sc.name == "eval"
    assert sc.arg == "run bug_fix_001"


def test_eval_compare_subcommand_parsed():
    sc = tui_cmd.parse_slash("/eval compare bug_fix_001:cheap bug_fix_001:strong")
    assert sc is not None
    assert sc.name == "eval"
    assert sc.arg == "compare bug_fix_001:cheap bug_fix_001:strong"


# ── 构造 fake ArgosApp(只取 _eval_* 方法,避开 App.__init__) ─────────


class _FakeApp:
    """ArgosApp 的最小替代(只暴露 _eval_cmd / _eval_run_cmd / _eval_compare_cmd)。"""
    def __init__(self):
        from argos_agent.tui.app import ArgosApp
        self._session_id = "test-session"

    async def _eval_cmd(self, log, arg: str) -> None:
        from argos_agent.tui.app import ArgosApp
        return await ArgosApp._eval_cmd(self, log, arg)

    async def _eval_run_cmd(self, log, task_id: str) -> None:
        from argos_agent.tui.app import ArgosApp
        return await ArgosApp._eval_run_cmd(self, log, task_id)

    async def _eval_compare_cmd(self, log, a: str, b: str) -> None:
        from argos_agent.tui.app import ArgosApp
        return await ArgosApp._eval_compare_cmd(self, log, a, b)


class _FakeLog:
    """最小 transcript 替代:append_line 收集到 list。"""
    def __init__(self):
        self.lines: list[tuple[str, str]] = []

    async def append_line(self, text: str, kind: str = "info") -> None:
        self.lines.append((text, kind))

    def joined(self) -> str:
        return "\n".join(t for t, _ in self.lines)


# ── /eval 无参 ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_eval_no_args_no_runs_prints_message(tmp_path, monkeypatch):
    """无 run → 友好提示,不假绿。"""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    from argos_agent.eval import results as _results
    monkeypatch.setattr(_results, "_RUNS_DIR", tmp_path / "eval" / "runs")
    app = _FakeApp()
    log = _FakeLog()
    await app._eval_cmd(log, "")
    text = log.joined()
    assert "尚未跑过 eval" in text


@pytest.mark.asyncio
async def test_eval_no_args_lists_runs(tmp_path, monkeypatch):
    """有 run → 表格 + 摘要。"""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    from argos_agent.eval import results as _results
    monkeypatch.setattr(_results, "_RUNS_DIR", tmp_path / "eval" / "runs")
    now = time.time()
    r1 = EvalResult(
        task_id="bug_fix_001_off_by_one", run_id="a1a1a1a1a1a1",
        model_tier="cheap", started_at=now, finished_at=now, duration_s=120.0,
        pass_status=PASS_PASSED, verify_cmd="pytest -q", verify_detail="ok",
        tampered=(), tokens_in=100, tokens_out=50, cost_usd=0.013, steps=8,
        worktree_path="/tmp", isolation_fallback=None, error=None,
        corpus_version=1, goal="g",
    )
    r2 = EvalResult(
        task_id="refactor_001_extract_helper", run_id="b2b2b2b2b2b2",
        model_tier="strong", started_at=now, finished_at=now, duration_s=95.0,
        pass_status=PASS_PASSED, verify_cmd="pytest -q", verify_detail="ok",
        tampered=(), tokens_in=5000, tokens_out=2000, cost_usd=0.087, steps=12,
        worktree_path="/tmp", isolation_fallback=None, error=None,
        corpus_version=1, goal="g",
    )
    append(r1, base=tmp_path / "eval")
    append(r2, base=tmp_path / "eval")
    app = _FakeApp()
    log = _FakeLog()
    await app._eval_cmd(log, "")
    text = log.joined()
    assert "bug_fix_001_off_by_one" in text
    assert "refactor_001_extract_helper" in text
    assert "a1a1a1a1a1a1" in text or "cheap" in text
    assert "Pass rate" in text


@pytest.mark.asyncio
async def test_eval_unknown_subcommand_errors():
    app = _FakeApp()
    log = _FakeLog()
    await app._eval_cmd(log, "garbage")
    text = log.joined()
    assert "用法" in text


# ── /eval run ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_eval_run_unknown_task_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    from argos_agent.eval import corpus as _corpus
    monkeypatch.setattr(_corpus, "_corpus_root", lambda: tmp_path / "nope")
    app = _FakeApp()
    log = _FakeLog()
    await app._eval_run_cmd(log, "nonexistent_task_zz")
    text = log.joined()
    assert "未找到 task" in text


@pytest.mark.asyncio
async def test_eval_run_happy_path_appends_and_prints(tmp_path, monkeypatch):
    """/eval run bug_fix_001 → 调 runner + 落 JSONL + 打印结果。"""
    from tests.eval._seed_corpus import write_seed_corpus
    from tests.eval._fakes import FakeWorktree, make_fake_loop, make_fake_loop_factory
    from argos_agent.eval import runner as _runner_mod
    from argos_agent.daemon import worktree as _wt_mod

    root = tmp_path / "corpus"
    write_seed_corpus(root)
    monkeypatch.setenv("ARGOS_EVAL_CORPUS_DIR", str(root))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    loop = make_fake_loop()
    monkeypatch.setattr(_wt_mod, "WorktreeManager",
                        lambda *a, **kw: FakeWorktree(tmp_path / "wt",
                                                      **{k: v for k, v in kw.items() if k == "fail_create"}))
    real_init = _runner_mod.EvalRunner.__init__
    def _init(self, **kw):
        if "loop_factory" not in kw:
            kw["loop_factory"] = make_fake_loop_factory(loop)
        real_init(self, **kw)
    monkeypatch.setattr(_runner_mod.EvalRunner, "__init__", _init)

    app = _FakeApp()
    log = _FakeLog()
    await app._eval_run_cmd(log, "bug_fix_001_off_by_one")
    text = log.joined()
    assert "bug_fix_001_off_by_one" in text
    assert "passed" in text
    assert "run_id=" in text
    # 走 _eval_run_cmd → Path.home() / ".argos" / "eval" / "runs"
    assert (tmp_path / ".argos" / "eval" / "runs").exists()


# ── /eval compare ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_eval_compare_requires_colon_or_matches_ids(tmp_path, monkeypatch):
    """compare 缺冒号时,会用纯 id(此时 task_id 必须一致)。"""
    from tests.eval._seed_corpus import write_seed_corpus
    from argos_agent.eval import runner as _runner_mod
    from argos_agent.daemon import worktree as _wt_mod
    from tests.eval._fakes import FakeWorktree, make_fake_loop

    root = tmp_path / "corpus"
    write_seed_corpus(root)
    monkeypatch.setenv("ARGOS_EVAL_CORPUS_DIR", str(root))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    loop_cheap = make_fake_loop(cost_usd=0.013)
    loop_strong = make_fake_loop(cost_usd=0.087)
    def factory(model_tier: str):
        return loop_cheap if model_tier == "cheap" else loop_strong
    monkeypatch.setattr(_wt_mod, "WorktreeManager",
                        lambda *a, **kw: FakeWorktree(tmp_path / "wt",
                                                      **{k: v for k, v in kw.items() if k == "fail_create"}))
    real_init = _runner_mod.EvalRunner.__init__
    def _init(self, **kw):
        if "loop_factory" not in kw:
            kw["loop_factory"] = factory
        real_init(self, **kw)
    monkeypatch.setattr(_runner_mod.EvalRunner, "__init__", _init)

    app = _FakeApp()
    log = _FakeLog()
    await app._eval_compare_cmd(log, "bug_fix_001_off_by_one:cheap", "bug_fix_001_off_by_one:strong")
    text = log.joined()
    assert "A/B" in text
    assert "A/B Eval Report" in text


@pytest.mark.asyncio
async def test_eval_compare_mismatched_ids_errors():
    app = _FakeApp()
    log = _FakeLog()
    await app._eval_compare_cmd(log, "bug_fix_001:cheap", "refactor_001:strong")
    text = log.joined()
    assert "task_id 不一致" in text


@pytest.mark.asyncio
async def test_eval_compare_unknown_task_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    from argos_agent.eval import corpus as _corpus
    monkeypatch.setattr(_corpus, "_corpus_root", lambda: tmp_path / "nope")
    app = _FakeApp()
    log = _FakeLog()
    await app._eval_compare_cmd(log, "nonexistent_zz:cheap", "nonexistent_zz:strong")
    text = log.joined()
    assert "未找到 task" in text
