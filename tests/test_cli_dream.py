from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest




def _args(report: bool = False) -> argparse.Namespace:
    ns = argparse.Namespace()
    ns.report = report
    return ns


def test_cli_dream_default_dirs_honor_argos_config_dir(tmp_path, monkeypatch):
    from argos import config as C
    from argos.cli import dream

    cfg_dir = tmp_path / "cfg"
    monkeypatch.delenv("ARGOS_DREAMS_DIR", raising=False)
    monkeypatch.delenv("ARGOS_MEMORY_DIR", raising=False)
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(C, "_ENV", {})

    assert dream._dreams_dir() == cfg_dir / "dreams"
    assert dream._memory_dir() == cfg_dir / "memory"




def test_cli_dream_report_empty(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ARGOS_DREAMS_DIR", str(tmp_path))

    from argos.cli.dream import run_dream
    code = run_dream(_args(report=True))
    out = capsys.readouterr().out
    assert code == 0
    assert "暂无" in out




def test_cli_dream_report_shows_latest(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ARGOS_DREAMS_DIR", str(tmp_path))

    old = tmp_path / "2020-01-01.jsonl"
    old.write_text(
        json.dumps({"ts": 1577836800.0, "units_total": 1, "promoted": 0,
                    "rejected": 0, "skipped": 1, "memory_merged": 0, "memory_archived": 0}) + "\n"
    )
    new = tmp_path / "2020-01-02.jsonl"
    line1 = json.dumps({"ts": 1577923200.0, "units_total": 2, "promoted": 1,
                         "rejected": 0, "skipped": 1, "memory_merged": 0, "memory_archived": 0})
    line2 = json.dumps({"ts": 1577926800.0, "units_total": 5, "promoted": 3,
                         "rejected": 1, "skipped": 1, "memory_merged": 2, "memory_archived": 4})
    new.write_text(line1 + "\n" + line2 + "\n")

    from argos.cli.dream import run_dream
    code = run_dream(_args(report=True))
    out = capsys.readouterr().out
    assert code == 0
    assert "units_total=5" in out and "promoted=3" in out




@pytest.mark.parametrize("bad_payload", [[], 42, "str", True])
def test_cli_dream_report_non_dict_does_not_crash(tmp_path, monkeypatch, capsys, bad_payload):
    monkeypatch.setenv("ARGOS_DREAMS_DIR", str(tmp_path))

    report_file = tmp_path / "2020-01-01.jsonl"
    report_file.write_text(json.dumps(bad_payload) + "\n")

    from argos.cli.dream import run_dream
    code = run_dream(_args(report=True))
    out = capsys.readouterr().out
    assert code == 0
    assert "格式异常" in out




def test_cli_dream_no_key_degrades(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ARGOS_DREAMS_DIR", str(tmp_path / "dreams"))
    monkeypatch.setenv("ARGOS_MEMORY_DIR", str(tmp_path / "memory"))
    (tmp_path / "dreams").mkdir()
    (tmp_path / "memory").mkdir()

    consolidate_called = []

    def _fake_consolidate(memory_dir):
        consolidate_called.append(memory_dir)
        from argos.memory.consolidate import ConsolidationReport
        return ConsolidationReport(merged=0, archived=0)

    with (
        patch("argos.app_factory.build_components",
              side_effect=RuntimeError("no API key")),
        patch("argos.memory.consolidate.consolidate", side_effect=_fake_consolidate),
    ):
        from argos.cli import dream as _dream_mod
        import importlib
        importlib.reload(_dream_mod)

        code = _dream_mod.run_dream(_args(report=False))

    out = capsys.readouterr().out
    assert code == 0
    assert "argos setup" in out
    assert len(consolidate_called) == 1


def test_cli_dream_build_components_error_is_not_reported_as_no_key(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ARGOS_DREAMS_DIR", str(tmp_path / "dreams"))
    monkeypatch.setenv("ARGOS_MEMORY_DIR", str(tmp_path / "memory"))

    with patch("argos.app_factory.build_components", side_effect=ValueError("bad config")):
        from argos.cli import dream as _dream_mod
        code = _dream_mod.run_dream(_args(report=False))

    captured = capsys.readouterr()
    assert code == 1
    assert "argos setup" not in captured.out
    assert "bad config" in captured.err




@pytest.mark.asyncio
async def test_tui_dream_inline_refuses():
    import os
    os.environ["ARGOS_NO_DAEMON"] = "1"
    try:
        from argos.tui.app import ArgosApp
        from argos.tui.commands import parse_slash
        from argos.tui.fakeloop import FakeLoop
        from argos.tui.widgets.transcript import Transcript

        app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
        async with app.run_test() as pilot:
            await pilot.pause()
            cmd = parse_slash("/dream")
            await app._dispatch_slash(cmd)
            txt = app.query_one("#transcript", Transcript).rendered_text
        assert "daemon" in txt.lower() or "inline" in txt.lower()
    finally:
        os.environ.pop("ARGOS_NO_DAEMON", None)


@pytest.mark.asyncio
async def test_tui_dream_inline_refusal_is_error(tmp_path, monkeypatch):
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    cfg_dir = tmp_path / "custom-config"
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))
    log = Log()
    await ArgosApp()._dream_cmd(log, "")

    assert log.lines[0][1] == "error"
    assert str(cfg_dir / "daemon.sock") in log.lines[0][0]
    assert "~/.argos" not in log.lines[0][0]




@pytest.mark.asyncio
async def test_tui_dream_daemon_posts():
    import os
    os.environ["ARGOS_NO_DAEMON"] = "1"
    try:
        from argos.tui.app import ArgosApp
        from argos.tui.commands import parse_slash
        from argos.tui.fakeloop import FakeLoop
        from argos.tui.widgets.transcript import Transcript

        app = ArgosApp(loop_factory=lambda **kw: FakeLoop())

        mock_client = MagicMock()
        mock_client._request = AsyncMock(return_value=(202, {}, '{"state":"dream_started"}'))

        app._with_daemon = True
        app._daemon_client = mock_client
        app._daemon_session_id = "test-session-id"

        async with app.run_test() as pilot:
            await pilot.pause()
            cmd = parse_slash("/dream")
            await app._dispatch_slash(cmd)
            txt = app.query_one("#transcript", Transcript).rendered_text

        mock_client._request.assert_called_once()
        call_args = mock_client._request.call_args
        assert call_args[0][0] == "POST"
        assert "/dream/run" in call_args[0][1]
        assert "已启动" in txt
    finally:
        os.environ.pop("ARGOS_NO_DAEMON", None)


@pytest.mark.asyncio
async def test_tui_dream_unknown_arg_prints_usage_without_posting():
    import os
    os.environ["ARGOS_NO_DAEMON"] = "1"
    try:
        from argos.tui.app import ArgosApp
        from argos.tui.commands import parse_slash
        from argos.tui.fakeloop import FakeLoop
        from argos.tui.widgets.transcript import Transcript

        app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
        mock_client = MagicMock()
        mock_client._request = AsyncMock(return_value=(202, {}, '{"state":"dream_started"}'))
        app._with_daemon = True
        app._daemon_client = mock_client
        app._daemon_session_id = "test-session-id"

        async with app.run_test() as pilot:
            await pilot.pause()
            cmd = parse_slash("/dream typo")
            await app._dispatch_slash(cmd)
            txt = app.query_one("#transcript", Transcript).rendered_text

        mock_client._request.assert_not_called()
        assert "Usage" in txt or "用法" in txt
    finally:
        os.environ.pop("ARGOS_NO_DAEMON", None)




@pytest.mark.asyncio
@pytest.mark.parametrize("bad_report", [[], 42, "string", True])
async def test_tui_dream_status_non_dict_report_does_not_crash(bad_report):
    import json as _json
    import os
    os.environ["ARGOS_NO_DAEMON"] = "1"
    try:
        from argos.tui.app import ArgosApp
        from argos.tui.commands import parse_slash
        from argos.tui.fakeloop import FakeLoop
        from argos.tui.widgets.transcript import Transcript

        app = ArgosApp(loop_factory=lambda **kw: FakeLoop())

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

        assert "格式异常" in txt
    finally:
        os.environ.pop("ARGOS_NO_DAEMON", None)




def test_cli_dream_has_key_promotion(tmp_path, monkeypatch, capsys):
    from argos.learning.candidates import save_candidate
    from argos.learning.distiller import SkillCandidate

    candidates_root = tmp_path / "candidates"
    skills_root = tmp_path / "skills"
    dreams_dir = tmp_path / "dreams"
    memory_dir = tmp_path / "memory"
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)

    def _seed(run_id: str, goal: str) -> None:
        cand = SkillCandidate(
            name="learned",
            body_markdown=f"# {goal}\n\n```python\nprint('ok')\n```",
            verify_cmd="true",
            skill_md_path=Path("unused"),
        )
        save_candidate(cand, root=candidates_root, source_run=run_id,
                       workspace=str(ws), goal=goal)

    _seed("cli001aaaa11", "fix auth timeout issue")
    _seed("cli002bbbb22", "fix auth token expiry issue")

    b_side_goals: list[str] = []

    @dataclass
    class _FakeResult:
        pass_status: str

    class _FakeEvalRunner:
        def run(self, task, *, model_tier: str = "default"):
            return _FakeResult(pass_status="failed")

    class _FakeHintedRunner:
        def __init__(self, inner, hint, max_hint_len=4000):
            self.inner = inner
            self.hint = hint
            self.max_hint_len = max_hint_len

        def run(self, task, *, model_tier: str = "default"):
            truncated = (self.hint or "")[:self.max_hint_len]
            hinted_goal = f"可参考以下已验证经验:\n{truncated}\n\n---\n\n{task.goal}"
            b_side_goals.append(hinted_goal)
            return _FakeResult(pass_status="passed")

    fake_model = MagicMock()
    fake_model.complete = AsyncMock(return_value="模拟叙述文本")

    # fake comps
    fake_comps = MagicMock()
    fake_comps.model = fake_model

    monkeypatch.setattr("argos.skills.USER_DIR", skills_root)
    monkeypatch.setattr("argos.cli.dream._DEFAULT_SKILLS_DIR", skills_root)
    monkeypatch.setattr("argos.learning.candidates.DEFAULT_ROOT", candidates_root)
    monkeypatch.setattr("argos.cli.dream._DEFAULT_CANDIDATES_DIR", candidates_root)
    monkeypatch.setenv("ARGOS_DREAMS_DIR", str(dreams_dir))
    monkeypatch.setenv("ARGOS_MEMORY_DIR", str(memory_dir))

    monkeypatch.setattr("argos.app_factory.build_components",
                        MagicMock(return_value=fake_comps))
    monkeypatch.setattr("argos.eval.runner.EvalRunner",
                        MagicMock(return_value=_FakeEvalRunner()))
    monkeypatch.setattr("argos.daemon.worktree.WorktreeManager",
                        MagicMock(return_value=MagicMock()))
    monkeypatch.setattr("argos.learning.dream.HintedRunner", _FakeHintedRunner)

    import importlib
    import argos.cli.dream as dream_mod
    importlib.reload(dream_mod)

    ns = argparse.Namespace()
    ns.report = False
    code = dream_mod.run_dream(ns)
    out = capsys.readouterr().out

    assert code == 0, f"run_dream 应返回 0，实得 {code}；stdout={out!r}"

    skill_mds = list(skills_root.glob("*/SKILL.md"))
    assert len(skill_mds) >= 1, (
        f"晋升产物应落在 skills_root={skills_root}，实际为空；"
        f"出现在 learning/skills = {list((tmp_path / 'learning' / 'skills').glob('**/*') if (tmp_path / 'learning' / 'skills').exists() else [])}"
    )

    assert len(b_side_goals) >= 1, (
        "B 侧 runner(HintedRunner) 没有被调用；说明 _runner_factory 没有注入 hint。"
    )
    assert any("可参考" in g for g in b_side_goals), (
        f"B 侧 task.goal 应含 '可参考'（hint 前置），实得：{b_side_goals[:3]}"
    )




def test_cli_dream_eval_runner_receives_loop_factory(tmp_path, monkeypatch, capsys):
    from argos.learning.candidates import save_candidate
    from argos.learning.distiller import SkillCandidate

    candidates_root = tmp_path / "candidates"
    skills_root = tmp_path / "skills"
    dreams_dir = tmp_path / "dreams"
    memory_dir = tmp_path / "memory"
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)

    cand = SkillCandidate(
        name="learned",
        body_markdown="# fix\n\n```python\nprint('ok')\n```",
        verify_cmd="true",
        skill_md_path=Path("unused"),
    )
    save_candidate(cand, root=candidates_root, source_run="spy001aaaa11",
                   workspace=str(ws), goal="fix connection timeout")

    captured_kwargs: list[dict] = []

    def _spy_eval_runner(*args, **kwargs):
        captured_kwargs.append({"args": args, "kwargs": kwargs})
        fake = MagicMock()
        fake.run = MagicMock(return_value=MagicMock(pass_status="failed"))
        return fake

    # ── fake comps + build_run_stack ─────────────────────────────────────
    fake_model = MagicMock()
    fake_model.complete = AsyncMock(return_value="叙述文本")
    fake_comps = MagicMock()
    fake_comps.model = fake_model

    fake_run_stack = MagicMock()
    fake_run_stack.loop_factory = MagicMock(return_value=MagicMock())

    # ── monkeypatch ───────────────────────────────────────────────────────
    monkeypatch.setattr("argos.skills.USER_DIR", skills_root)
    monkeypatch.setattr("argos.cli.dream._DEFAULT_SKILLS_DIR", skills_root)
    monkeypatch.setattr("argos.learning.candidates.DEFAULT_ROOT", candidates_root)
    monkeypatch.setattr("argos.cli.dream._DEFAULT_CANDIDATES_DIR", candidates_root)
    monkeypatch.setenv("ARGOS_DREAMS_DIR", str(dreams_dir))
    monkeypatch.setenv("ARGOS_MEMORY_DIR", str(memory_dir))

    monkeypatch.setattr("argos.app_factory.build_components",
                        MagicMock(return_value=fake_comps))
    monkeypatch.setattr("argos.app_factory.build_run_stack",
                        MagicMock(return_value=fake_run_stack))
    monkeypatch.setattr("argos.eval.runner.EvalRunner", _spy_eval_runner)
    monkeypatch.setattr("argos.daemon.worktree.WorktreeManager",
                        MagicMock(return_value=MagicMock()))

    import importlib
    import argos.cli.dream as dream_mod
    importlib.reload(dream_mod)

    ns = argparse.Namespace()
    ns.report = False
    dream_mod.run_dream(ns)
    capsys.readouterr()

    assert len(captured_kwargs) >= 1, (
        "EvalRunner 从未被构造；说明 has-key 分支未到达 runner 装配步骤。"
    )
    kw = captured_kwargs[0]["kwargs"]
    assert "loop_factory" in kw, (
        f"EvalRunner 构造缺少 loop_factory 关键字参数；实际 kwargs={list(kw.keys())}。"
        "\n回退验证：把 loop_factory 传参从 cli/dream.py 删掉，此断言必须触发。"
    )
    assert kw["loop_factory"] is not None, (
        "EvalRunner 收到的 loop_factory 是 None；"
        "runner.run() 将直接返回 PASS_ERROR，A/B 晋升永不发生。"
    )
    assert kw["base_dir"] == dreams_dir / "eval", (
        f"EvalRunner base_dir 应跟随 dreams_dir/eval，实际为 {kw['base_dir']}"
    )
