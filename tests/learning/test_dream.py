"""dream:聚类 + 综合的铁律测试。"""
from pathlib import Path

from argos_agent.learning.candidates import StoredCandidate
from argos_agent.learning.dream import (
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
    assert sizes == [1, 2]  # a+b 同簇,c 单例


def test_cluster_cap_limits_units():
    """6 个真正互不相似的候选 → 6 单例 → 单例道封顶 max_units=3。"""
    goals = [
        "parse csv ledger", "render svg chart", "deploy docker swarm",
        "train embedding model", "refactor auth middleware", "benchmark redis cache",
    ]
    cands = [_sc(f"s{i}", goals[i], verify=f"pytest tests/t{i}.py",
                 run=f"run{i:013d}") for i in range(6)]
    units = cluster_candidates(cands, max_units=3)
    assert len(units) == 3


def test_cluster_oversized_truncates_and_holds_over():
    """超大簇截取+留宿:7 个高相似候选 → 恰好 1 个 unit、5 个源;余 2 个不进任何 unit。"""
    from argos_agent.learning.dream import MAX_UNIT_SOURCES
    cands = [_sc(f"s{i}", f"fix login auth bug attempt {i}",
                 run=f"run{i:013d}") for i in range(7)]
    units = cluster_candidates(cands)
    assert len(units) == 1
    assert len(units[0].sources) == MAX_UNIT_SOURCES == 5
    picked_runs = {s.source_run for u in units for s in u.sources}
    assert picked_runs == {f"run{i:013d}" for i in range(5)}  # 保序取前 5
    # 被留宿的 2 个源不出现在任何 unit 里(保持未消费,下晚再整合)
    assert "run0000000000005" not in picked_runs
    assert "run0000000000006" not in picked_runs


def test_strip_code_blocks_removes_all_fences():
    txt = "前文\n```python\nevil()\n```\n中文\n```\nrm -rf /\n```\n尾"
    out = _strip_code_blocks(txt)
    assert "evil" not in out and "rm -rf" not in out
    assert "前文" in out and "尾" in out


def test_strip_code_blocks_removes_tilde_fences():
    """对抗:波浪 fence(~~~)也是合法 markdown 代码块,同样必须剥除。"""
    txt = "前文\n~~~python\nevil()\n~~~\n尾"
    out = _strip_code_blocks(txt)
    assert "evil" not in out
    assert "前文" in out and "尾" in out


def test_strip_code_blocks_truncates_unclosed_fence():
    """对抗:模型截断输出开了 fence 没关 → 从残留标记起截断到串尾。"""
    txt = "前文\n```python\nevil_unclosed()"
    out = _strip_code_blocks(txt)
    assert "evil_unclosed" not in out
    assert "前文" in out


def test_synthesize_code_only_from_sources_model_only_narrative():
    """铁律:模型输出的代码块绝不进产物;源代码段逐字保留并标注 source_run。"""
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
    assert "login_fix_alpha()" in md and "login_fix_beta()" in md  # 源逐字保留
    assert "run1aaaaaaaa" in md and "run2bbbbbbbb" in md           # source_run 标注
    assert "fabricated_by_model" not in md                          # 模型代码被剥
    assert "适用于登录类修复" in md                                  # 叙述层保留
    assert "enabled: false" in md                                   # 晋升前不生效


def test_synthesize_no_narrative_uses_template():
    a = _sc("a", "fix login bug", run="run1aaaaaaaaaaaa")
    b = _sc("b", "fix login auth bug", run="run2bbbbbbbbbbbb")
    unit = next(u for u in cluster_candidates([a, b]) if len(u.sources) == 2)
    cand = synthesize(unit, narrative=None)
    assert cand is not None  # 叙述层降级,功能不死
    assert "本技能综合自" in cand.body_markdown


def test_narrative_prompt_contains_goals_and_no_code_request():
    from argos_agent.learning.dream import narrative_prompt
    a = _sc("a", "fix login bug", run="run1aaaaaaaaaaaa")
    b = _sc("b", "fix login auth bug", run="run2bbbbbbbbbbbb")
    unit = next(u for u in cluster_candidates([a, b]) if len(u.sources) == 2)
    p = narrative_prompt(unit)
    assert "fix login bug" in p and "不要代码" in p
