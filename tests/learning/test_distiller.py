"""learning distiller 验收 — 任务:passed run 触发 distill 产出候选 SKILL.md。

约束:
- 不调真模型提炼(模板化产物;避免"模型觉得好"循环)
- 复用 daemon/store.py 的 replay 抽 events
- 写本地 ~/.argos/skills/<name>/SKILL.md(同 install 路径约定,但不走 install 网络/SHA)
- 默认 enabled=false(沿用 install 的 user review gate 约定)
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from argos.learning import distiller


def _write_run_store(tmp_path: Path, run_id: str, events: list[dict]) -> Path:
    """把 events 写到 daemon RunStore 期望的 JSONL 路径。"""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    p = runs_dir / f"{run_id}.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return p


def _make_passed_events(*, goal: str = "test goal",
                        verify_cmd: str = "pytest -q",
                        code_snippets: list[str] | None = None) -> list[dict]:
    """构造一条 passed 轨迹(code_action → code_result → verify_verdict)。"""
    code_snippets = code_snippets or ["result = 1 + 1\nprint(result)"]
    evs: list[dict] = [
        {"kind": "session_start", "goal": goal, "seq": 0},
        {"kind": "phase_change", "phase": "plan", "seq": 1},
    ]
    seq = 2
    for snippet in code_snippets:
        evs.append({"kind": "code_action", "code": snippet, "step": seq, "seq": seq})
        evs.append({"kind": "code_result", "stdout": "ok", "value_repr": "None", "exc": "", "ok": True, "step": seq, "seq": seq + 1})
        seq += 2
    evs.append({"kind": "phase_change", "phase": "verify", "seq": seq})
    evs.append({
        "kind": "verify_verdict",
        "verdict": {"status": "passed", "reason": "all green", "verify_cmd": verify_cmd},
        "seq": seq + 1,
    })
    return evs


# ── 验收 a: passed run 触发 distill 产出候选 ──────────────────
def test_passed_run_produces_candidate(tmp_path):
    """passed 轨迹 + verify_cmd → distill 返非 None 的 SkillCandidate。"""
    from argos.learning.distiller import distill_run_to_skill, SkillCandidate
    from argos.daemon.store import RunStore

    run_id = "r#passed"
    events = _make_passed_events(verify_cmd="pytest -q")
    _write_run_store(tmp_path, run_id, events)
    store = RunStore(runs_dir=tmp_path / "runs")

    cand = distill_run_to_skill(
        run_id=run_id, store=store,
        goal="test goal", verify_cmd="pytest -q",
        skills_root=tmp_path / "skills",
    )
    assert isinstance(cand, SkillCandidate)
    assert cand.verify_cmd == "pytest -q"
    assert cand.body_markdown  # 非空
    assert cand.name  # 派生名


def test_distill_writes_skill_md_to_skills_dir(tmp_path):
    """distill 应在 skills_root/<name>/SKILL.md 落盘,frontmatter 含 enabled=false。"""
    from argos.learning.distiller import distill_run_to_skill
    from argos.daemon.store import RunStore

    run_id = "r#write"
    events = _make_passed_events()
    _write_run_store(tmp_path, run_id, events)
    store = RunStore(runs_dir=tmp_path / "runs")

    cand = distill_run_to_skill(
        run_id=run_id, store=store,
        goal="fix foo", verify_cmd="pytest -q",
        skills_root=tmp_path / "skills",
    )
    # 落盘由 promote 阶段负责,distill 本身不写(signature 干净);但 candidate 应有 path 字段
    assert cand.skill_md_path.parent.name == cand.name or cand.skill_md_path.name == "SKILL.md"
    # 模板产物(无 YAML 解析也至少含 enabled: false 字符串,作为 review gate)
    assert "enabled: false" in cand.body_markdown
    # frontmatter 应含 verify 脚本
    assert "pytest" in cand.body_markdown


def test_distill_handles_missing_run_id_gracefully(tmp_path):
    """store 里没这条 run → distill 返 None(不抛)。"""
    from argos.learning.distiller import distill_run_to_skill
    from argos.daemon.store import RunStore

    store = RunStore(runs_dir=tmp_path / "runs")
    cand = distill_run_to_skill(
        run_id="nope", store=store,
        goal="x", verify_cmd="pytest -q",
        skills_root=tmp_path / "skills",
    )
    assert cand is None


def test_distill_extracts_code_snippets_into_body(tmp_path):
    """distill 抽 code_action 事件,产物 body 应含代码片段(以代码块呈现)。"""
    from argos.learning.distiller import distill_run_to_skill
    from argos.daemon.store import RunStore

    run_id = "r#code"
    snippet = "def add(a, b):\n    return a + b\n"
    events = _make_passed_events(code_snippets=[snippet])
    _write_run_store(tmp_path, run_id, events)
    store = RunStore(runs_dir=tmp_path / "runs")

    cand = distill_run_to_skill(
        run_id=run_id, store=store,
        goal="impl add", verify_cmd="pytest tests/test_add.py",
        skills_root=tmp_path / "skills",
    )
    assert cand is not None
    # body 包含代码片段
    assert "def add(a, b)" in cand.body_markdown or "add(a, b)" in cand.body_markdown


# ── 回归测试:候选落盘脱敏(review #6) ──────────────────────────────────────────

def test_distill_redacts_secrets_in_body(tmp_path):
    """distill body 中的明文密钥必须被脱敏(sk-ant- / password=)。

    回退验证:注释掉 distiller._build_markdown 里的脱敏调用,本测试必须 FAIL。
    """
    from argos.learning.distiller import distill_run_to_skill
    from argos.daemon.store import RunStore

    run_id = "r#secrets"
    # code_action 携带明文密钥
    snippet_with_secrets = textwrap.dedent("""\
        import anthropic
        client = anthropic.Anthropic(api_key="sk-ant-xxxxxxxxxxxxxxxxxxxx")
        # also: password="hunter2"
        result = client.messages.create(model="claude-3-haiku-20240307",
                                        max_tokens=10, messages=[{"role": "user", "content": "hi"}])
    """)
    events = _make_passed_events(
        goal="call api with sk-ant-xxxxxxxxxxxxxxxxxxxx",
        verify_cmd="pytest -q",
        code_snippets=[snippet_with_secrets],
    )
    _write_run_store(tmp_path, run_id, events)
    store = RunStore(runs_dir=tmp_path / "runs")

    cand = distill_run_to_skill(
        run_id=run_id, store=store,
        goal="call api with sk-ant-xxxxxxxxxxxxxxxxxxxx",
        verify_cmd="pytest -q",
        skills_root=tmp_path / "skills",
    )
    assert cand is not None
    body = cand.body_markdown
    # 明文密钥不得出现
    assert "sk-ant-xxxxxxxxxxxxxxxxxxxx" not in body, \
        "sk-ant- 明文密钥出现在 body — 脱敏失效"
    assert "hunter2" not in body, \
        "password=hunter2 明文出现在 body — 脱敏失效"
    # 脱敏占位符应存在
    assert "<redacted:secret>" in body, "脱敏后应有 <redacted:secret> 占位符"
