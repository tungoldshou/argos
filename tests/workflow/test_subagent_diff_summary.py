"""Internal documentation."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from argos.workflow.spec import AgentTask
from argos.workflow.subagent import SubAgentFactory


def _make_git_worktree_with_changes(tmp_path: Path, *, n_files: int = 1,
                                     additions: int = 10) -> Path:
    """Internal documentation."""
    import subprocess as _sp
    wt = tmp_path / "wt"
    wt.mkdir()
    _sp.run(["git", "-C", str(wt), "init", "-q"], check=True)
    _sp.run(["git", "-C", str(wt), "config", "user.email", "t@t"], check=True)
    _sp.run(["git", "-C", str(wt), "config", "user.name", "t"], check=True)
    (wt / ".gitkeep").write_text("init")
    _sp.run(["git", "-C", str(wt), "add", "-A"], check=True)
    _sp.run(["git", "-C", str(wt), "commit", "-q", "-m", "init"], check=True)
    for i in range(n_files):
        (wt / f"f{i}.py").write_text("x = 1\n" * additions)
    return wt


@pytest.mark.asyncio
async def test_default_mode_omits_full_diff_from_output(
    tmp_path, scripted_model_factory, requires_sandbox,
):
    """Internal documentation."""
    from argos.workflow.subagent import SubAgentFactory as _SAF
    task = AgentTask(prompt="改 {item}", tool_scope="full", isolation="worktree",
                     verify="true")
    base = tmp_path / "base"
    base.mkdir()
    (base / "init.py").write_text("# init")
    subprocess.run(["git", "-C", str(base), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(base), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(base), "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", str(base), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(base), "commit", "-q", "-m", "init"], check=True)
    factory = _SAF.for_test(workspace=base, model_factory=scripted_model_factory)
    big_diff = "diff --git a/f.py b/f.py\nindex 1234..5678 100644\n" + "x\n" * 5000
    monkeypatched = _SAF._capture_diff_text.__get__(factory, type(factory))
    import argos.workflow.subagent as _sa_mod
    _sa_mod.SubAgentFactory._capture_diff_text = staticmethod(lambda wd: big_diff)

    res = await factory.run_task(
        task, item="x", agent_id="s#a", on_phase=lambda *a: None,
    )
    _sa_mod.SubAgentFactory._capture_diff_text = staticmethod(monkeypatched)

    assert "diff --git" not in str(res.output), (
        f"默认模式 output 不该含 'diff --git',实得 output[:200]={str(res.output)[:200]}"
    )
    assert res.diff_summary is not None, "默认模式应有 diff_summary"
    assert res.diff_ref is not None, "默认模式应有 diff_ref(完整 diff 落盘路径)"
    assert Path(res.diff_ref).exists(), f"diff_ref 路径不存在:{res.diff_ref}"
    assert res.verdict is not None


@pytest.mark.asyncio
async def test_diff_ref_recovers_full_diff(tmp_path, scripted_model_factory, requires_sandbox):
    """Internal documentation."""
    import argos.workflow.subagent as _sa_mod
    base = tmp_path / "base2"
    base.mkdir()
    subprocess.run(["git", "-C", str(base), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(base), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(base), "config", "user.name", "t"], check=True)
    (base / ".g").write_text("i")
    subprocess.run(["git", "-C", str(base), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(base), "commit", "-q", "-m", "i"], check=True)
    factory = SubAgentFactory.for_test(workspace=base, model_factory=scripted_model_factory)
    big = "diff --git a/foo.py b/foo.py\n@@ -1 +1 @@\n-old\n+new\n" * 100
    _sa_mod.SubAgentFactory._capture_diff_text = staticmethod(lambda wd: big)

    task = AgentTask(prompt="改", tool_scope="full", isolation="worktree", verify="true")
    res = await factory.run_task(
        task, item="x", agent_id="s#b", on_phase=lambda *a: None,
    )
    assert res.diff_ref is not None
    full = Path(res.diff_ref).read_text(encoding="utf-8")
    assert full.startswith("diff --git"), f"diff_ref 读出来不是完整 diff:head={full[:80]}"
    assert len(full) == len(big)


@pytest.mark.asyncio
async def test_parallel_agents_output_bounded_not_linear_in_diff_size(
    tmp_path, scripted_model_factory, requires_sandbox,
):
    """Internal documentation."""
    import argos.workflow.subagent as _sa_mod
    base = tmp_path / "base3"
    base.mkdir()
    subprocess.run(["git", "-C", str(base), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(base), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(base), "config", "user.name", "t"], check=True)
    (base / ".g").write_text("i")
    subprocess.run(["git", "-C", str(base), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(base), "commit", "-q", "-m", "i"], check=True)
    factory = SubAgentFactory.for_test(workspace=base, model_factory=scripted_model_factory)
    big = "diff --git a/foo.py b/foo.py\n" + "x = 1\n" * 1000  # ~5KB
    _sa_mod.SubAgentFactory._capture_diff_text = staticmethod(lambda wd: big)

    outs: list[str] = []
    for i in range(3):
        task = AgentTask(prompt=f"改 {i}", tool_scope="full", isolation="worktree",
                         verify="true")
        res = await factory.run_task(
            task, item="x", agent_id=f"s#c{i}", on_phase=lambda *a: None,
        )
        outs.append(str(res.output))
    total = sum(len(o) for o in outs)
    assert total < 2000, f"默认模式父级 output 不该线性膨胀(总长={total},预期 < 2000)"


@pytest.mark.asyncio
async def test_inline_diff_true_keeps_legacy_behavior(
    tmp_path, scripted_model_factory, requires_sandbox,
):
    """Internal documentation."""
    import argos.workflow.subagent as _sa_mod
    from argos.core.models import CredentialPool
    from argos.core.verify_gate import Verifier
    from argos.memory.store import ArgosStore
    from argos.sandbox.egress import EgressPolicy
    from argos.tools.receipts import ReceiptSigner
    import os

    base = tmp_path / "base4"
    base.mkdir()
    subprocess.run(["git", "-C", str(base), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(base), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(base), "config", "user.name", "t"], check=True)
    (base / ".g").write_text("i")
    subprocess.run(["git", "-C", str(base), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(base), "commit", "-q", "-m", "i"], check=True)

    factory = SubAgentFactory(
        base_workspace=base, pool=CredentialPool(["k"]),
        egress=EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set()),
        signer=ReceiptSigner(key=os.urandom(32)),
        verifier=Verifier(max_rounds=2),
        store_factory=lambda: ArgosStore(db_path=":memory:"),
        model_factory=scripted_model_factory,
        inline_diff=True,
    )
    big = "diff --git a/legacy.py b/legacy.py\n-old\n+new\n" * 200
    _sa_mod.SubAgentFactory._capture_diff_text = staticmethod(lambda wd: big)

    task = AgentTask(prompt="改", tool_scope="full", isolation="worktree", verify="true")
    res = await factory.run_task(
        task, item="x", agent_id="s#d", on_phase=lambda *a: None,
    )
    assert "diff --git" in str(res.output), (
        f"inline_diff=True 应保留旧行为,output 应含 'diff --git',实得 {str(res.output)[:200]}"
    )
    assert res.diff_ref is None
    assert res.diff_summary is None


@pytest.mark.asyncio
async def test_no_changes_leaves_diff_fields_empty(tmp_path, scripted_model_factory, requires_sandbox):
    """Internal documentation."""
    import argos.workflow.subagent as _sa_mod
    base = tmp_path / "base5"
    base.mkdir()
    subprocess.run(["git", "-C", str(base), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(base), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(base), "config", "user.name", "t"], check=True)
    (base / ".g").write_text("i")
    subprocess.run(["git", "-C", str(base), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(base), "commit", "-q", "-m", "i"], check=True)
    factory = SubAgentFactory.for_test(workspace=base, model_factory=scripted_model_factory)
    _sa_mod.SubAgentFactory._capture_diff_text = staticmethod(lambda wd: None)

    task = AgentTask(prompt="不改", tool_scope="full", isolation="worktree", verify="true")
    res = await factory.run_task(
        task, item="x", agent_id="s#e", on_phase=lambda *a: None,
    )
    assert res.diff_ref is None
    assert res.diff_file_count == 0
    assert "diff 摘要" not in str(res.output)


def test_summarize_diff_extracts_counts():
    """Internal documentation."""
    from argos.workflow.subagent import SubAgentFactory
    diff = (
        "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-old\n+new\n"
        "diff --git a/b.py b/b.py\n@@ -1 +1 @@\n-x\n+y\n"
    )
    summary, count = SubAgentFactory._summarize_diff(diff)
    assert count == 2
    assert "2 files" in summary or "2 个文件" in summary


def test_diff_journal_defaults_to_argos_config_dir(tmp_path, monkeypatch):
    """Internal documentation."""
    from argos.workflow.subagent import SubAgentFactory

    cfg_dir = tmp_path / "cfg"
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))

    ref = SubAgentFactory._persist_diff_journal("agent-a", "diff --git a/x b/x\n")

    expected = cfg_dir / "workflow" / "diffs" / "agent-a.diff"
    assert Path(ref) == expected
    assert expected.read_text(encoding="utf-8").startswith("diff --git")
