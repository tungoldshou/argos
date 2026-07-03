from pathlib import Path

from argos.learning.candidates import StoredCandidate
from argos.learning.dream import (
    SIM_THRESHOLD, cluster_candidates, synthesize, _token_sim, _strip_code_blocks,
)


def _sc(name: str, goal: str, verify: str = "pytest -q",
        run: str = "run000000000000", body: str = "# s\n```python\nx = 1\n```",
        workspace: str | None = "/tmp/p") -> StoredCandidate:
    return StoredCandidate(
        name=name, body_markdown=body, verify_cmd=verify,
        source_run=run, workspace=workspace, goal=goal, path=Path("/dev/null"),
    )


def test_token_sim_basics():
    assert _token_sim("fix login bug pytest", "fix login bug pytest") == 1.0
    assert _token_sim("alpha beta", "gamma delta") == 0.0


def test_cluster_groups_similar_goals():
    a = _sc("a", "fix login auth bug", run="run1aaaaaaaaaaaa")
    b = _sc("b", "fix login auth timeout bug", run="run2bbbbbbbbbbbb")
    c = _sc("c", "generate sales report csv", run="run3cccccccccccc")
    units = cluster_candidates([a, b, c])
    sizes = sorted(len(u.sources) for u in units)
    assert sizes == [1, 2]


def test_cluster_cap_limits_units():
    goals = [
        "parse csv ledger", "render svg chart", "deploy docker swarm",
        "train embedding model", "refactor auth middleware", "benchmark redis cache",
    ]
    cands = [_sc(f"s{i}", goals[i], verify=f"pytest tests/t{i}.py",
                 run=f"run{i:013d}") for i in range(6)]
    units = cluster_candidates(cands, max_units=3)
    assert len(units) == 3


def test_cluster_oversized_truncates_and_holds_over():
    from argos.learning.dream import MAX_UNIT_SOURCES
    cands = [_sc(f"s{i}", f"fix login auth bug attempt {i}",
                 run=f"run{i:013d}") for i in range(7)]
    units = cluster_candidates(cands)
    assert len(units) == 1
    assert len(units[0].sources) == MAX_UNIT_SOURCES == 5
    picked_runs = {s.source_run for u in units for s in u.sources}
    assert picked_runs == {f"run{i:013d}" for i in range(5)}
    assert "run0000000000005" not in picked_runs
    assert "run0000000000006" not in picked_runs


def test_strip_code_blocks_removes_all_fences():
    txt = "前文\n```python\nevil()\n```\n中文\n```\nrm -rf /\n```\n尾"
    out = _strip_code_blocks(txt)
    assert "evil" not in out and "rm -rf" not in out
    assert "前文" in out and "尾" in out


def test_strip_code_blocks_removes_tilde_fences():
    txt = "前文\n~~~python\nevil()\n~~~\n尾"
    out = _strip_code_blocks(txt)
    assert "evil" not in out
    assert "前文" in out and "尾" in out


def test_strip_code_blocks_truncates_unclosed_fence():
    txt = "前文\n```python\nevil_unclosed()"
    out = _strip_code_blocks(txt)
    assert "evil_unclosed" not in out
    assert "前文" in out


def test_synthesize_code_only_from_sources_model_only_narrative():
    a = _sc("a", "fix login bug", run="run1aaaaaaaaaaaa",
            body="# a\n```python\nlogin_fix_alpha()\n```")
    b = _sc("b", "fix login auth bug", run="run2bbbbbbbbbbbb",
            body="# b\n```python\nlogin_fix_beta()\n```")
    units = cluster_candidates([a, b])
    unit = next(u for u in units if len(u.sources) == 2)

    evil_narrative = "适用于登录类修复。\n```python\nfabricated_by_model()\n```"
    cand = synthesize(unit, narrative=evil_narrative)
    assert cand is not None
    md = cand.body_markdown
    assert "login_fix_alpha()" in md and "login_fix_beta()" in md
    assert "run1aaaaaaaa" in md and "run2bbbbbbbb" in md
    assert "fabricated_by_model" not in md
    assert "适用于登录类修复" in md
    assert "enabled: false" in md


def test_synthesize_no_narrative_uses_template():
    a = _sc("a", "fix login bug", run="run1aaaaaaaaaaaa")
    b = _sc("b", "fix login auth bug", run="run2bbbbbbbbbbbb")
    unit = next(u for u in cluster_candidates([a, b]) if len(u.sources) == 2)
    cand = synthesize(unit, narrative=None)
    assert cand is not None
    assert "本技能综合自" in cand.body_markdown


def test_narrative_prompt_contains_goals_and_no_code_request():
    from argos.learning.dream import narrative_prompt
    a = _sc("a", "fix login bug", run="run1aaaaaaaaaaaa")
    b = _sc("b", "fix login auth bug", run="run2bbbbbbbbbbbb")
    unit = next(u for u in cluster_candidates([a, b]) if len(u.sources) == 2)
    p = narrative_prompt(unit)
    assert "fix login bug" in p and "不要代码" in p


# ── Task 6:HintedRunner + build_eval_tasks ──────────────────────

def test_build_eval_tasks_skips_missing_workspace(tmp_path):
    from argos.learning.dream import build_eval_tasks, DreamUnit

    existing_ws = tmp_path / "ws_real"
    existing_ws.mkdir()

    s_good = StoredCandidate(
        name="good", body_markdown="# s", verify_cmd="pytest -q",
        source_run="run_good_12345678",
        workspace=str(existing_ws), goal="fix the login bug",
        path=Path("/dev/null"),
    )
    s_missing = StoredCandidate(
        name="miss", body_markdown="# s", verify_cmd="pytest -q",
        source_run="run_miss_12345678",
        workspace="/nonexistent/path/that/doesnt/exist",
        goal="render svg chart", path=Path("/dev/null"),
    )
    unit = DreamUnit(sources=(s_good, s_missing))
    tasks, gone = build_eval_tasks(unit)

    assert len(tasks) == 1, f"应只有 1 个有效 task,得 {len(tasks)}"
    assert tasks[0].working_dir == existing_ws
    assert len(gone) == 1
    assert gone[0].source_run == "run_miss_12345678"


def test_hinted_runner_prepends_hint_to_goal(tmp_path):
    from argos.learning.dream import HintedRunner
    from argos.eval.corpus import EvalTask

    captured_goals: list[str] = []

    class _CapturingRunner:
        def run(self, task, *, model_tier: str):
            captured_goals.append(task.goal)
            class _R:
                pass_status = "passed"
            return _R()

    inner = _CapturingRunner()
    hint_text = "经验提示文本:已验证过的修复方式"
    hinted = HintedRunner(inner=inner, hint=hint_text)

    task = EvalTask(
        id="t-hint", category="self_check", difficulty="easy",
        title="hint test", goal="写一个登录修复脚本",
        verify_cmd="true", setup_cmd=None, expected_files=(),
        working_dir=tmp_path, corpus_version=1,
    )
    hinted.run(task, model_tier="default")

    assert len(captured_goals) == 1
    g = captured_goals[0]
    assert g.startswith("可参考以下已验证经验"), f"goal 应以提示语开头,得: {g[:40]!r}"
    assert hint_text in g, "goal 应含 hint"
    assert "写一个登录修复脚本" in g, "goal 应保留原 goal"


def test_hinted_runner_truncates_long_hint(tmp_path):
    from argos.learning.dream import HintedRunner
    from argos.eval.corpus import EvalTask

    captured_goals: list[str] = []

    class _CapturingRunner:
        def run(self, task, *, model_tier: str):
            captured_goals.append(task.goal)
            class _R:
                pass_status = "passed"
            return _R()

    inner = _CapturingRunner()
    long_hint = "经验A " * 1001
    assert len(long_hint) > 4000, "前置条件:long_hint 应超过 4000 字符"

    hinted = HintedRunner(inner=inner, hint=long_hint)
    assert hinted.max_hint_len == 4000, (
        f"HintedRunner 应有 max_hint_len=4000 字段,实得 {getattr(hinted, 'max_hint_len', '缺失')}"
    )

    task = EvalTask(
        id="t-long", category="self_check", difficulty="easy",
        title="truncate test", goal="完成任务",
        verify_cmd="true", setup_cmd=None, expected_files=(),
        working_dir=tmp_path, corpus_version=1,
    )
    hinted.run(task, model_tier="default")

    assert len(captured_goals) == 1
    g = captured_goals[0]
    separator = "\n\n---\n\n"
    assert separator in g, "goal 中应含分隔符"
    prefix, _, original = g.partition(separator)
    hint_in_prefix = prefix.split("\n", 1)[1] if "\n" in prefix else prefix
    assert len(hint_in_prefix) <= 4000, (
        f"截断后 hint 不应超过 max_hint_len=4000,实得 {len(hint_in_prefix)}"
    )
    assert len(hint_in_prefix) < len(long_hint), (
        f"hint 应被截断,截断后 {len(hint_in_prefix)} < 原始 {len(long_hint)}"
    )
    assert "完成任务" in g, "原始 goal 应保留在末尾"
