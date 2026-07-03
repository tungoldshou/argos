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
    def __init__(self) -> None:
        self.tier = _Tier()
        self.last_usage = {"input_tokens": 0, "output_tokens": 0,
                           "cache_read": 0, "cache_creation": 0}
        self.calls = 0

    async def stream(self, messages, *, system, system_dynamic=None):
        self.calls += 1
        if self.calls < 6:
            yield "```python\n# act\n```\n"
            return
        for ch in "完成。":
            yield ch


class _FakeSandbox:
    def spawn(self, *, workspace, namespace, allow_workflow=True, read_only=False): ...
    def exec_code(self, code): return ExecResult(stdout="", value_repr="", exc="")
    def close(self): ...


class _PassedVerifier:
    def verify(self, verify_cmd, *, attempts=1):
        return Verdict.passed(detail="ok", verify_cmd=verify_cmd, attempts=attempts)




@pytest.fixture
def mem_root(monkeypatch, tmp_path):
    root = tmp_path / "memory"
    monkeypatch.setenv("ARGOS_MEMORY_DIR", str(root))
    yield root


def test_user_goal_is_captured_on_passed_run(mem_root, tmp_path):
    store = None
    from argos.memory.store import ArgosStore
    store = ArgosStore(db_path=":memory:")
    store.ensure_session("s", title="t", model="worker", system_snapshot="")
    cfg = LoopConfig(max_steps=10, compaction=False, compact_threshold=0.0,
                     verify_cmd="pytest -q")
    loop = AgentLoop(store=store, bus=EventBus(), sandbox=_FakeSandbox(), broker=None,
                     model=_DoneModel(), verifier=_PassedVerifier(), config=cfg,
                     workspace=tmp_path)
    pid = mem_auto.project_id_for(loop._workspace)
    goal_text = "把 X 修好并加测试"
    async def _drain():
        out = []
        async for ev in loop.run(goal_text, "s"):
            out.append(ev)
        return out
    import asyncio
    events = asyncio.run(_drain())
    from argos.tui.events import VerifyVerdict
    verdicts = [e.verdict for e in events if isinstance(e, VerifyVerdict)]
    assert verdicts and verdicts[0].status == "passed"
    from argos.memory.auto import _project_path, _read_jsonl
    rows = _read_jsonl(_project_path(pid))
    successes = [r for r in rows if r.key.startswith("run_success.")]
    assert successes, "应有一条 run_success 落库"
    assert goal_text in successes[-1].value, (
        f"goal 应在落库的 value 里,实得 {successes[-1].value!r}"
    )


def test_user_goal_assigned_at_run_start(tmp_path):
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


def test_loop_default_dirs_honor_argos_config_dir(tmp_path, monkeypatch):
    from argos import config as C
    from argos.memory.store import ArgosStore

    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(C, "_ENV", {})
    store = ArgosStore(db_path=":memory:")

    loop = AgentLoop(
        store=store, bus=EventBus(), sandbox=_FakeSandbox(), broker=None,
        model=_DoneModel(), verifier=_PassedVerifier(), config=LoopConfig(),
    )

    assert loop._workspace == tmp_path / "workspace"
    assert loop._verify_dir == tmp_path / "verify"


def test_loop_explicit_dirs_override_argos_config_dir(tmp_path, monkeypatch):
    from argos import config as C
    from argos.memory.store import ArgosStore

    workspace = tmp_path / "ws"
    verify_dir = tmp_path / "vd"
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(C, "_ENV", {})
    store = ArgosStore(db_path=":memory:")

    loop = AgentLoop(
        store=store, bus=EventBus(), sandbox=_FakeSandbox(), broker=None,
        model=_DoneModel(), verifier=_PassedVerifier(), config=LoopConfig(),
        workspace=workspace, verify_dir=verify_dir,
    )

    assert loop._workspace == workspace
    assert loop._verify_dir == verify_dir
