"""`_user_goal` 潜在 bug 回归测试(core/loop.py)。

bug:`run()` 起始只把 goal append 到 messages/store,从未赋给 `self._user_goal`。
后果:收尾时 `capture_event("run_success", goal=self._user_goal, ...)` 落库的 goal 恒
为空串 → 长期记忆里所有"成功 run"都成了"无 goal 的成功" → 按"goal 相似度召回"时
"成功可学习"这条召回路径被一票否决。

修法:run() 起始赋 `self._user_goal = goal`。本测试钉死"loop 完成真把 goal 传给
capture_event"——既验证修复,又防止以后被回滚。
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from argos.core.loop import AgentLoop, LoopConfig
from argos.core.verify_gate import Verdict
from argos.memory import auto as mem_auto
from argos.sandbox.backend import ExecResult
from argos.tui.events import EventBus


# ── fakes ─────────────────────────────────────────────────────────────


@dataclass
class _Tier:
    context_window: int = 100_000
    name: str = "default"
    model: str = "fake-model"


class _DoneModel:
    """前 5 轮吐代码块(让 step 跑到 ≥5),第 6 轮无代码块宣布完成 → 走 verify → passed。"""
    def __init__(self) -> None:
        self.tier = _Tier()
        self.last_usage = {"input_tokens": 0, "output_tokens": 0,
                           "cache_read": 0, "cache_creation": 0}
        self.calls = 0

    async def stream(self, messages, *, system, system_dynamic=None):
        self.calls += 1
        # 前 5 次:有 code 块 → 触发动作计数;step 会跑到 5
        if self.calls < 6:
            yield "```python\n# act\n```\n"
            return
        # 第 6 次:无代码块 → 走 verify 收尾
        for ch in "完成。":
            yield ch


class _FakeSandbox:
    def spawn(self, *, workspace, namespace, allow_workflow=True, read_only=False): ...
    def exec_code(self, code): return ExecResult(stdout="", value_repr="", exc="")
    def close(self): ...


class _PassedVerifier:
    def verify(self, verify_cmd, *, attempts=1):
        return Verdict.passed(detail="ok", verify_cmd=verify_cmd, attempts=attempts)


# ── 验收:goal 真被记到落库事件里 ────────────────────────────────────


@pytest.fixture
def mem_root(monkeypatch, tmp_path):
    root = tmp_path / "memory"
    monkeypatch.setenv("ARGOS_MEMORY_DIR", str(root))
    yield root


def test_user_goal_is_captured_on_passed_run(mem_root, tmp_path):
    """完成(passed)且 ≥5 步 → capture_event('run_success', goal=...) 落库,
    落库的 goal 字段【非空、等于传入的 goal】(回归 bug:之前恒空串)。"""
    store = None  # loop 自己起一个 in-memory store 即可
    from argos.memory.store import ArgosStore
    store = ArgosStore(db_path=":memory:")
    store.ensure_session("s", title="t", model="worker", system_snapshot="")
    cfg = LoopConfig(max_steps=10, compaction=False, compact_threshold=0.0,
                     verify_cmd="pytest -q")
    loop = AgentLoop(store=store, bus=EventBus(), sandbox=_FakeSandbox(), broker=None,
                     model=_DoneModel(), verifier=_PassedVerifier(), config=cfg,
                     workspace=tmp_path)
    # 落库路径 = project_id(loop._workspace)= mem_auto.project_id_for(loop._workspace)
    pid = mem_auto.project_id_for(loop._workspace)
    goal_text = "把 X 修好并加测试"
    async def _drain():
        out = []
        async for ev in loop.run(goal_text, "s"):
            out.append(ev)
        return out
    import asyncio
    events = asyncio.run(_drain())
    # 真跑过 verify 并 passed(防测空过)
    from argos.tui.events import VerifyVerdict
    verdicts = [e.verdict for e in events if isinstance(e, VerifyVerdict)]
    assert verdicts and verdicts[0].status == "passed"
    # 落库验证:run_success 行的 value 形如 "{goal} (key_cmd=...)",goal 必须是我们的 goal
    from argos.memory.auto import _project_path, _read_jsonl
    rows = _read_jsonl(_project_path(pid))
    successes = [r for r in rows if r.key.startswith("run_success.")]
    assert successes, "应有一条 run_success 落库"
    assert goal_text in successes[-1].value, (
        f"goal 应在落库的 value 里,实得 {successes[-1].value!r}"
    )


def test_user_goal_assigned_at_run_start(tmp_path):
    """run() 起始后 _user_goal 已赋值(不是事后才设),让收尾路径 100% 命中。"""
    from argos.memory.store import ArgosStore
    store = ArgosStore(db_path=":memory:")
    store.ensure_session("s", title="t", model="worker", system_snapshot="")
    loop = AgentLoop(store=store, bus=EventBus(), sandbox=_FakeSandbox(), broker=None,
                     model=_DoneModel(), verifier=_PassedVerifier(),
                     config=LoopConfig(max_steps=10, compaction=False,
                                       compact_threshold=0.0, verify_cmd="pytest -q"),
                     workspace=tmp_path)
    goal_text = "abc"
    import asyncio
    async def _go():
        async for _ in loop.run(goal_text, "s"):
            pass
    asyncio.run(_go())
    assert loop._user_goal == goal_text
