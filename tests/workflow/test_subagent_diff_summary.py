"""子 agent diff 摘要模式验收 — 任务:并行子 agent 默认只回"摘要 + verdict + diff 引用",完整 diff 落盘按需取。

约束:
- 不削弱诚实/可审阅(diff 必须可取到)
- 不破坏现有 workflow 测试与审批预览
- 默认 inline_diff=False(省 token 模式开);inline_diff=True 切回旧行为
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from argos_agent.workflow.spec import AgentTask
from argos_agent.workflow.subagent import SubAgentFactory


# ── 工具 ────────────────────────────────────────────────
def _make_git_worktree_with_changes(tmp_path: Path, *, n_files: int = 1,
                                     additions: int = 10) -> Path:
    """在 tmp_path 构造一个 git 仓库,add N 个文件后改 N 次 → 产生 staged diff。"""
    import subprocess as _sp
    wt = tmp_path / "wt"
    wt.mkdir()
    _sp.run(["git", "-C", str(wt), "init", "-q"], check=True)
    _sp.run(["git", "-C", str(wt), "config", "user.email", "t@t"], check=True)
    _sp.run(["git", "-C", str(wt), "config", "user.name", "t"], check=True)
    # 初始 commit(否则 diff 拿不到)
    (wt / ".gitkeep").write_text("init")
    _sp.run(["git", "-C", str(wt), "add", "-A"], check=True)
    _sp.run(["git", "-C", str(wt), "commit", "-q", "-m", "init"], check=True)
    # 改 N 个文件
    for i in range(n_files):
        (wt / f"f{i}.py").write_text("x = 1\n" * additions)
    return wt


# ── 验收 a: 默认模式 AgentResult 不含整段 diff、含摘要+verdict+引用 ──
@pytest.mark.asyncio
async def test_default_mode_omits_full_diff_from_output(
    tmp_path, scripted_model_factory,
):
    """inline_diff=False(默认)→ output 不含 'diff --git' 字面,含摘要+verdict+引用。"""
    from argos_agent.workflow.subagent import SubAgentFactory as _SAF
    # 子 agent 跑在 worktree 隔离(isolation=worktree)→ _capture_diff 路径触发
    task = AgentTask(prompt="改 {item}", tool_scope="full", isolation="worktree",
                     verify="true")
    # 让 scripted_model 走完(无代码动作,直接 token 收尾)
    # 给工厂一个 base_workspace(worktree_for 会基于它创建 wt)
    base = tmp_path / "base"
    base.mkdir()
    # 预先在工作区里写 1 个文件供子 agent "改"
    (base / "init.py").write_text("# init")
    subprocess.run(["git", "-C", str(base), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(base), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(base), "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", str(base), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(base), "commit", "-q", "-m", "init"], check=True)
    # 子 agent 不会真改文件 —— 我们手动 inject diff 的方式更稳:
    # 让 subagent 跑 → 走 _capture_diff_text → worktree 里有 .gitkeep 等无改动 → diff_ref=None
    # 上面这条路径要 diff 必出,得让它真改。subagent 跑脚本要真改文件,得让模型输出
    # ```python write_file``` —— scripted_model_factory 给的是 "这是对目标的简要总结",没代码动作。
    # 改:用 monkeypatch _capture_diff_text 直接返大段 diff
    factory = _SAF.for_test(workspace=base, model_factory=scripted_model_factory)
    big_diff = "diff --git a/f.py b/f.py\nindex 1234..5678 100644\n" + "x\n" * 5000
    monkeypatched = _SAF._capture_diff_text.__get__(factory, type(factory))
    import argos_agent.workflow.subagent as _sa_mod
    _sa_mod.SubAgentFactory._capture_diff_text = staticmethod(lambda wd: big_diff)

    res = await factory.run_task(
        task, item="x", agent_id="s#a", on_phase=lambda *a: None,
    )
    # 还原(避免污染其它测试)
    _sa_mod.SubAgentFactory._capture_diff_text = staticmethod(monkeypatched)

    # 默认模式:output 不含整段 diff
    assert "diff --git" not in str(res.output), (
        f"默认模式 output 不该含 'diff --git',实得 output[:200]={str(res.output)[:200]}"
    )
    # 摘要存在(files changed 类)
    assert res.diff_summary is not None, "默认模式应有 diff_summary"
    # 引用存在(diff_ref 是路径)
    assert res.diff_ref is not None, "默认模式应有 diff_ref(完整 diff 落盘路径)"
    assert Path(res.diff_ref).exists(), f"diff_ref 路径不存在:{res.diff_ref}"
    # verdict 仍填
    assert res.verdict is not None


# ── 验收 b: 按引用能取回完整 diff ──────────────────────────
@pytest.mark.asyncio
async def test_diff_ref_recovers_full_diff(tmp_path, scripted_model_factory):
    """diff_ref 路径读出来的文本以 'diff --git' 开头(完整 diff 可取回)。"""
    import argos_agent.workflow.subagent as _sa_mod
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
    # 长度至少跟原 big 一样
    assert len(full) == len(big)


# ── 验收 c: 多子 agent 并行时父级上下文不再线性膨胀 ────────
@pytest.mark.asyncio
async def test_parallel_agents_output_bounded_not_linear_in_diff_size(
    tmp_path, scripted_model_factory,
):
    """3 个子 agent 各 5KB diff → output 总长 << 15KB(默认模式)。"""
    import argos_agent.workflow.subagent as _sa_mod
    base = tmp_path / "base3"
    base.mkdir()
    subprocess.run(["git", "-C", str(base), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(base), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(base), "config", "user.name", "t"], check=True)
    (base / ".g").write_text("i")
    subprocess.run(["git", "-C", str(base), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(base), "commit", "-q", "-m", "i"], check=True)
    factory = SubAgentFactory.for_test(workspace=base, model_factory=scripted_model_factory)
    # 模拟每个子 agent 5KB diff
    big = "diff --git a/foo.py b/foo.py\n" + "x = 1\n" * 1000  # ~5KB
    _sa_mod.SubAgentFactory._capture_diff_text = staticmethod(lambda wd: big)

    # 串行跑 3 个(避免真并发污染 tmp_path 状态)
    outs: list[str] = []
    for i in range(3):
        task = AgentTask(prompt=f"改 {i}", tool_scope="full", isolation="worktree",
                         verify="true")
        res = await factory.run_task(
            task, item="x", agent_id=f"s#c{i}", on_phase=lambda *a: None,
        )
        outs.append(str(res.output))
    total = sum(len(o) for o in outs)
    # 3 个 5KB diff = 15KB;默认模式 → 总长 < 2KB(各 ~500B 摘要)
    assert total < 2000, f"默认模式父级 output 不该线性膨胀(总长={total},预期 < 2000)"


# ── 验收 d: 开关切回全文模式行为如旧 ────────────────────
@pytest.mark.asyncio
async def test_inline_diff_true_keeps_legacy_behavior(
    tmp_path, scripted_model_factory,
):
    """inline_diff=True → output 含 'diff --git'(旧行为),diff_ref/diff_summary 留空。"""
    import argos_agent.workflow.subagent as _sa_mod
    from argos_agent.core.models import CredentialPool
    from argos_agent.core.verify_gate import Verifier
    from argos_agent.memory.store import ArgosStore
    from argos_agent.sandbox.egress import EgressPolicy
    from argos_agent.tools.receipts import ReceiptSigner
    import os

    base = tmp_path / "base4"
    base.mkdir()
    subprocess.run(["git", "-C", str(base), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(base), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(base), "config", "user.name", "t"], check=True)
    (base / ".g").write_text("i")
    subprocess.run(["git", "-C", str(base), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(base), "commit", "-q", "-m", "i"], check=True)

    # 直接构造 + inline_diff=True
    factory = SubAgentFactory(
        base_workspace=base, pool=CredentialPool(["k"]),
        egress=EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set()),
        signer=ReceiptSigner(key=os.urandom(32)),
        verifier=Verifier(max_rounds=2),
        store_factory=lambda: ArgosStore(db_path=":memory:"),
        model_factory=scripted_model_factory,
        inline_diff=True,  # 切回旧行为
    )
    big = "diff --git a/legacy.py b/legacy.py\n-old\n+new\n" * 200
    _sa_mod.SubAgentFactory._capture_diff_text = staticmethod(lambda wd: big)

    task = AgentTask(prompt="改", tool_scope="full", isolation="worktree", verify="true")
    res = await factory.run_task(
        task, item="x", agent_id="s#d", on_phase=lambda *a: None,
    )
    # 旧路径:output 含整段 diff
    assert "diff --git" in str(res.output), (
        f"inline_diff=True 应保留旧行为,output 应含 'diff --git',实得 {str(res.output)[:200]}"
    )
    # 旧路径:diff_ref / diff_summary 留空
    assert res.diff_ref is None
    assert res.diff_summary is None


# ── 边界:worktree 无改动 ──────────────────────────────────
@pytest.mark.asyncio
async def test_no_changes_leaves_diff_fields_empty(tmp_path, scripted_model_factory):
    """worktree 没改动 → diff_ref=None, diff_file_count=0, output 不变(无摘要段)。"""
    import argos_agent.workflow.subagent as _sa_mod
    base = tmp_path / "base5"
    base.mkdir()
    subprocess.run(["git", "-C", str(base), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(base), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(base), "config", "user.name", "t"], check=True)
    (base / ".g").write_text("i")
    subprocess.run(["git", "-C", str(base), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(base), "commit", "-q", "-m", "i"], check=True)
    factory = SubAgentFactory.for_test(workspace=base, model_factory=scripted_model_factory)
    # _capture_diff_text 返 None(模拟 git 报"无改动")
    _sa_mod.SubAgentFactory._capture_diff_text = staticmethod(lambda wd: None)

    task = AgentTask(prompt="不改", tool_scope="full", isolation="worktree", verify="true")
    res = await factory.run_task(
        task, item="x", agent_id="s#e", on_phase=lambda *a: None,
    )
    assert res.diff_ref is None
    assert res.diff_file_count == 0
    assert "diff 摘要" not in str(res.output)


# ── _summarize_diff 单元测试 ────────────────────────────
def test_summarize_diff_extracts_counts():
    """_summarize_diff(diff_text) 返 (summary, file_count)。"""
    from argos_agent.workflow.subagent import SubAgentFactory
    diff = (
        "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-old\n+new\n"
        "diff --git a/b.py b/b.py\n@@ -1 +1 @@\n-x\n+y\n"
    )
    summary, count = SubAgentFactory._summarize_diff(diff)
    assert count == 2
    assert "2 files" in summary or "2 个文件" in summary
