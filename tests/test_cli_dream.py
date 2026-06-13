"""T10:argos dream CLI 子命令验收测试(TDD)。

覆盖:
  1. test_cli_dream_report_empty — ARGOS_DREAMS_DIR 指空目录,返 0 + 输出含"暂无"
  2. test_cli_dream_report_shows_latest — 写两天报告文件,输出最新文件最后一行计数
  3. test_cli_dream_no_key_degrades — monkeypatch build_components 抛 RuntimeError →
     输出含 "argos setup" 提示,执行了 consolidate(不炸),返 0
  7. test_cli_dream_has_key_promotion — has-key 晋升路径回归测试:
     - skills_root 必须是 ~/.argos/skills 而非 learning/skills（Blocking-2）
     - B 侧 runner 必须收到带 hint 的 goal（Blocking-1）
     - 晋升产物落在正确目录
"""
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


# ── 辅助:构造 args namespace ────────────────────────────────────────────


def _args(report: bool = False) -> argparse.Namespace:
    ns = argparse.Namespace()
    ns.report = report
    return ns


# ── 1. --report 空目录 → 诚实空态 ───────────────────────────────────────


def test_cli_dream_report_empty(tmp_path, monkeypatch, capsys):
    """ARGOS_DREAMS_DIR 指 tmp 空目录,run_dream(--report) → 输出含"暂无",返 0。"""
    monkeypatch.setenv("ARGOS_DREAMS_DIR", str(tmp_path))

    from argos.cli.dream import run_dream
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

    from argos.cli.dream import run_dream
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

    from argos.cli.dream import run_dream
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
        from argos.memory.consolidate import ConsolidationReport
        return ConsolidationReport(merged=0, archived=0)

    with (
        patch("argos.app_factory.build_components",
              side_effect=RuntimeError("no API key")),
        patch("argos.memory.consolidate.consolidate", side_effect=_fake_consolidate),
    ):
        from argos.cli import dream as _dream_mod
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
        from argos.tui.app import ArgosApp
        from argos.tui.commands import parse_slash
        from argos.tui.fakeloop import FakeLoop
        from argos.tui.widgets.transcript import Transcript

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
        from argos.tui.app import ArgosApp
        from argos.tui.commands import parse_slash
        from argos.tui.fakeloop import FakeLoop
        from argos.tui.widgets.transcript import Transcript

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
        from argos.tui.app import ArgosApp
        from argos.tui.commands import parse_slash
        from argos.tui.fakeloop import FakeLoop
        from argos.tui.widgets.transcript import Transcript

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


# ── 7. has-key 晋升路径回归测试（Blocking-1 + Blocking-2 双钉）──────────────────


def test_cli_dream_has_key_promotion(tmp_path, monkeypatch, capsys):
    """CLI has-key 路径回归：runner_factory 注入 hint（Blocking-1）+ skills_root 正确（Blocking-2）。

    设计原则：
    - 用真实 CLI 装配（不绕过 run_dream），这样回归才有意义；
    - monkeypatch EvalRunner / WorktreeManager / build_components 防副作用；
    - FakeEvalRunner 区分 A 侧（hint=None → fail）和 B 侧（hint 含 "可参考"  → pass）；
    - spy task.goal 确认 B 侧确实收到了带 hint 的 goal；
    - 断言晋升产物落在 tmp_skills_root（对应 skills.USER_DIR），不在 learning/skills。
    """
    from argos.learning.candidates import save_candidate
    from argos.learning.distiller import SkillCandidate

    # ── 构建 tmp 目录体系 ──────────────────────────────────────────────────
    candidates_root = tmp_path / "candidates"
    skills_root = tmp_path / "skills"      # 替换 USER_DIR 指向
    dreams_dir = tmp_path / "dreams"
    memory_dir = tmp_path / "memory"
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)

    # 种 2 个相似候选（workspace 存在 + verify_cmd 有效）
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

    # ── spy：记录 B 侧 runner.run() 收到的 task.goal ──────────────────────
    b_side_goals: list[str] = []

    @dataclass
    class _FakeResult:
        pass_status: str

    class _FakeEvalRunner:
        """区分 A/B 侧：任何调用前先判断是否被 HintedRunner 包裹。"""
        def run(self, task, *, model_tier: str = "default"):
            # 直接调用（A 侧，hint=None 路径）→ failed；让 B>A 成立。
            return _FakeResult(pass_status="failed")

    class _FakeHintedRunner:
        """模拟 HintedRunner.run()：记录 hinted goal，返回 passed。"""
        def __init__(self, inner, hint, max_hint_len=4000):
            self.inner = inner
            self.hint = hint
            self.max_hint_len = max_hint_len

        def run(self, task, *, model_tier: str = "default"):
            truncated = (self.hint or "")[:self.max_hint_len]
            hinted_goal = f"可参考以下已验证经验:\n{truncated}\n\n---\n\n{task.goal}"
            b_side_goals.append(hinted_goal)
            return _FakeResult(pass_status="passed")

    # ── fake model（narrate 用） ────────────────────────────────────────────
    fake_model = MagicMock()
    fake_model.complete = AsyncMock(return_value="模拟叙述文本")

    # fake comps
    fake_comps = MagicMock()
    fake_comps.model = fake_model

    # ── monkeypatch：重定向单一来源 + 注入 fake runner/components ─────────────
    # 重定向 skills.USER_DIR（Blocking-2 的单一来源）→ tmp skills_root
    monkeypatch.setattr("argos.skills.USER_DIR", skills_root)
    monkeypatch.setattr("argos.cli.dream._DEFAULT_SKILLS_DIR", skills_root)
    # 重定向 candidates DEFAULT_ROOT → tmp candidates_root
    monkeypatch.setattr("argos.learning.candidates.DEFAULT_ROOT", candidates_root)
    monkeypatch.setattr("argos.cli.dream._DEFAULT_CANDIDATES_DIR", candidates_root)
    # 重定向 dreams_dir / memory_dir（环境变量）
    monkeypatch.setenv("ARGOS_DREAMS_DIR", str(dreams_dir))
    monkeypatch.setenv("ARGOS_MEMORY_DIR", str(memory_dir))

    # build_components 返回 fake_comps（有 key 路径）
    monkeypatch.setattr("argos.app_factory.build_components",
                        MagicMock(return_value=fake_comps))
    # 替换 EvalRunner 构造（返回 fake） + WorktreeManager（no-op）
    monkeypatch.setattr("argos.eval.runner.EvalRunner",
                        MagicMock(return_value=_FakeEvalRunner()))
    monkeypatch.setattr("argos.daemon.worktree.WorktreeManager",
                        MagicMock(return_value=MagicMock()))
    # 替换 HintedRunner（用我们的 spy 版）—— 这是 Blocking-1 回归核心
    monkeypatch.setattr("argos.learning.dream.HintedRunner", _FakeHintedRunner)

    # ── 跑 CLI ────────────────────────────────────────────────────────────
    import importlib
    import argos.cli.dream as dream_mod
    importlib.reload(dream_mod)   # 让 module-level import 的 _DEFAULT_SKILLS_DIR 生效

    ns = argparse.Namespace()
    ns.report = False
    code = dream_mod.run_dream(ns)
    out = capsys.readouterr().out

    assert code == 0, f"run_dream 应返回 0，实得 {code}；stdout={out!r}"

    # ── Blocking-2：晋升产物必须落在 skills_root（~/.argos/skills 等价），不在 learning/skills ──
    skill_mds = list(skills_root.glob("*/SKILL.md"))
    assert len(skill_mds) >= 1, (
        f"晋升产物应落在 skills_root={skills_root}，实际为空；"
        f"出现在 learning/skills = {list((tmp_path / 'learning' / 'skills').glob('**/*') if (tmp_path / 'learning' / 'skills').exists() else [])}"
    )

    # ── Blocking-1：B 侧 runner 必须收到含 "可参考" hint 的 goal ──────────────
    assert len(b_side_goals) >= 1, (
        "B 侧 runner(HintedRunner) 没有被调用；说明 _runner_factory 没有注入 hint。"
    )
    assert any("可参考" in g for g in b_side_goals), (
        f"B 侧 task.goal 应含 '可参考'（hint 前置），实得：{b_side_goals[:3]}"
    )


# ── 8. EvalRunner 必须收到 loop_factory（Review High #1 回归钉）──────────────


def test_cli_dream_eval_runner_receives_loop_factory(tmp_path, monkeypatch, capsys):
    """CLI has-key 路径中 EvalRunner 构造必须传入非 None 的 loop_factory。

    回归钉（Review High #1）：原实现 cli/dream.py:169 缺失 loop_factory 参数，
    导致 runner.run() 直接返回 PASS_ERROR，A/B 两侧恒相等，晋升永不发生。

    验证方式：用 spy 捕获 EvalRunner(...)  构造调用参数，断言 loop_factory is not None。
    回退验证：把 loop_factory 传参从 cli/dream.py 删掉，此测试必须 FAIL。
    """
    from argos.learning.candidates import save_candidate
    from argos.learning.distiller import SkillCandidate

    # ── 最小目录体系（只需触发 has-key 分支到 EvalRunner 构造即可）────────────
    candidates_root = tmp_path / "candidates"
    skills_root = tmp_path / "skills"
    dreams_dir = tmp_path / "dreams"
    memory_dir = tmp_path / "memory"
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)

    # 种一个候选（让 pipeline 有材料可处理）
    cand = SkillCandidate(
        name="learned",
        body_markdown="# fix\n\n```python\nprint('ok')\n```",
        verify_cmd="true",
        skill_md_path=Path("unused"),
    )
    save_candidate(cand, root=candidates_root, source_run="spy001aaaa11",
                   workspace=str(ws), goal="fix connection timeout")

    # ── spy：捕获 EvalRunner 构造参数 ─────────────────────────────────────
    captured_kwargs: list[dict] = []

    def _spy_eval_runner(*args, **kwargs):
        captured_kwargs.append({"args": args, "kwargs": kwargs})
        # 返回一个极简 fake runner（不需要真正跑 eval）
        fake = MagicMock()
        fake.run = MagicMock(return_value=MagicMock(pass_status="failed"))
        return fake

    # ── fake comps + build_run_stack ─────────────────────────────────────
    fake_model = MagicMock()
    fake_model.complete = AsyncMock(return_value="叙述文本")
    fake_comps = MagicMock()
    fake_comps.model = fake_model

    # build_run_stack → 返回一个 RunStack-like fake，其 loop_factory 是可调用的
    fake_run_stack = MagicMock()
    fake_run_stack.loop_factory = MagicMock(return_value=MagicMock())  # 非 None

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
    capsys.readouterr()  # 不关心输出

    # ── 核心断言：EvalRunner 必须被构造，且收到非 None 的 loop_factory ──────
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
