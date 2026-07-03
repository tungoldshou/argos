"""Internal documentation."""
from __future__ import annotations

import os
import pytest
from pathlib import Path

from argos.core.loop import AgentLoop, LoopConfig
from argos.core.verify_gate import Verdict
from argos.protocol.events import EventBus, VerifyVerdict, PhaseChange
from argos.sandbox.backend import ExecResult



class _CompletingModel:
    """Internal documentation."""
    last_usage: dict = {}

    async def stream(self, messages, *, system="", system_dynamic=""):
        for ch in "任务完成了。":
            yield ch


class _ImplementingModel:
    """Internal documentation."""
    last_usage: dict = {}

    def __init__(self) -> None:
        self._i = 0

    async def stream(self, messages, *, system="", system_dynamic=""):
        scripts = ["```python\nwrite_file('impl.py', 'x = 1')\n```", "实现完成。"]
        t = scripts[min(self._i, len(scripts) - 1)]
        self._i += 1
        for ch in t:
            yield ch


class _FakeSandbox:
    def spawn(self, *, workspace, namespace, allow_workflow=True, read_only=False): ...
    def exec_code(self, code): return ExecResult(stdout="", value_repr="", exc="")
    def close(self): ...


class _RecordingVerifier:
    """Internal documentation."""
    def __init__(self) -> None:
        self.received_cmds: list[str | None] = []

    def verify(self, verify_cmd: str | None, *, attempts: int = 1) -> Verdict:
        self.received_cmds.append(verify_cmd)
        if verify_cmd:
            return Verdict.passed(detail="[exit_code=0]", verify_cmd=verify_cmd, attempts=attempts)
        return Verdict.unverifiable(detail="(无 verify_cmd)", tampered=[], attempts=attempts)


class _FailingVerifier:
    """Internal documentation."""
    def __init__(self) -> None:
        self.received_cmds: list[str | None] = []

    def verify(self, verify_cmd: str | None, *, attempts: int = 1) -> Verdict:
        self.received_cmds.append(verify_cmd)
        if verify_cmd:
            return Verdict.failed(detail="[exit_code=1]", verify_cmd=verify_cmd, attempts=attempts)
        return Verdict.unverifiable(detail="(无 verify_cmd)", tampered=[], attempts=attempts)


class _FakeStore:
    def append_event(self, sid, ev): ...
    def append_message(self, sid, **kw): return "m0"
    def ensure_session(self, sid, **kw): ...


def _make_loop(
    *,
    verifier=None,
    verify_cmd: str | None = None,
    max_steps: int = 5,
    capability_hints: dict[str, str] | None = None,
    model=None,
) -> AgentLoop:
    """Internal documentation."""
    return AgentLoop(
        store=_FakeStore(),
        bus=EventBus(),
        sandbox=_FakeSandbox(),
        broker=None,
        model=model or _CompletingModel(),
        verifier=verifier or _RecordingVerifier(),
        config=LoopConfig(verify_cmd=verify_cmd, max_steps=max_steps, max_rounds=1),
        capability_hints=capability_hints,
    )


def _collect_events(loop: AgentLoop, goal: str) -> list:
    """Internal documentation."""
    import asyncio

    async def _run():
        return [ev async for ev in loop.run(goal, "s")]

    return asyncio.run(_run())



def test_auto_l1_strategy_in_pytest_workspace(tmp_path: Path) -> None:
    """Internal documentation."""
    (tmp_path / "conftest.py").write_text("")

    class _ImplementingModel:
        """Internal documentation."""
        last_usage: dict = {}

        def __init__(self) -> None:
            self._i = 0

        async def stream(self, messages, *, system="", system_dynamic=""):
            scripts = [
                "```python\nwrite_file('sort.py', 'def sort(x):\\n    return sorted(x)')\n```",
                "实现完成。",
            ]
            t = scripts[min(self._i, len(scripts) - 1)]
            self._i += 1
            for ch in t:
                yield ch

    verifier = _RecordingVerifier()
    loop = AgentLoop(
        store=_FakeStore(),
        bus=EventBus(),
        sandbox=_FakeSandbox(),
        broker=None,
        model=_ImplementingModel(),
        verifier=verifier,
        config=LoopConfig(verify_cmd=None, max_steps=5, max_rounds=1),
    )
    loop._workspace = tmp_path

    _collect_events(loop, "implement a sort function")

    assert verifier.received_cmds, "verifier 必须至少被调一次"
    received = verifier.received_cmds[0]
    assert received is not None, "有 pytest 工作区应产 L1 策略 cmd（非 None）"
    assert "pytest" in received.lower(), f"L1 cmd 应含 pytest，实际：{received!r}"


def test_auto_strategy_sets_verify_cmd_on_loop(tmp_path: Path) -> None:
    """Internal documentation."""
    (tmp_path / "conftest.py").write_text("")

    loop = _make_loop()
    loop._workspace = tmp_path

    cmd = loop._pick_strategy_cmd("implement feature")
    assert cmd is not None
    assert "pytest" in cmd.lower()



def test_blacklisted_strategy_cmd_degrades_to_no_test(tmp_path: Path, monkeypatch) -> None:
    """Internal documentation."""
    from argos.verify import strategy as _strat_mod
    from argos.verify.strategy import VerifyStrategy, WorkspaceFacts

    _l5_only = (
        VerifyStrategy(
            level="L5", kind="evidence_trail", cmd=None, target=None,
            rationale_human="no machine check", confidence=0.0,
        ),
    )

    def _fake_generate(goal, *, workspace_facts, capability_hints=None):
        return _l5_only

    monkeypatch.setattr(_strat_mod, "generate", _fake_generate)

    (tmp_path / "conftest.py").write_text("")
    verifier = _RecordingVerifier()
    loop = _make_loop(verifier=verifier, model=_ImplementingModel())
    loop._workspace = tmp_path

    events = _collect_events(loop, "implement feature")

    assert verifier.received_cmds, "verifier 必须被调"
    assert verifier.received_cmds[0] is None, (
        f"所有策略降 L5 后 verifier 应收到 None，实际：{verifier.received_cmds[0]!r}"
    )

    phases = [ev.phase for ev in events if isinstance(ev, PhaseChange)]
    assert "report" in phases


def test_trivial_cmd_in_strategy_degrades_gracefully(tmp_path: Path, monkeypatch) -> None:
    """Internal documentation."""
    from argos.verify import strategy as _strat_mod
    from argos.verify.strategy import VerifyStrategy

    _echo_then_l5 = (
        VerifyStrategy(
            level="L1", kind="exit_code", cmd="echo ok", target=None,
            rationale_human="trivial cmd", confidence=0.5,
        ),
        VerifyStrategy(
            level="L5", kind="evidence_trail", cmd=None, target=None,
            rationale_human="fallback", confidence=0.0,
        ),
    )

    monkeypatch.setattr(_strat_mod, "generate", lambda *a, **kw: _echo_then_l5)

    verifier = _RecordingVerifier()
    loop = _make_loop(verifier=verifier, model=_ImplementingModel())
    loop._workspace = tmp_path

    _collect_events(loop, "implement feature")

    assert verifier.received_cmds[0] is None, (
        "trivial cmd echo 应被拒，降 L5 后 verifier 收到 None"
    )


def test_non_allowlisted_cmd_in_strategy_degrades_gracefully(tmp_path: Path, monkeypatch) -> None:
    """Internal documentation."""
    from argos.verify import strategy as _strat_mod
    from argos.verify.strategy import VerifyStrategy

    _curl_then_l5 = (
        VerifyStrategy(
            level="L1", kind="exit_code", cmd="curl http://localhost/health", target=None,
            rationale_human="curl check", confidence=0.5,
        ),
        VerifyStrategy(
            level="L5", kind="evidence_trail", cmd=None, target=None,
            rationale_human="fallback", confidence=0.0,
        ),
    )

    monkeypatch.setattr(_strat_mod, "generate", lambda *a, **kw: _curl_then_l5)

    verifier = _RecordingVerifier()
    loop = _make_loop(verifier=verifier, model=_ImplementingModel())
    loop._workspace = tmp_path

    _collect_events(loop, "implement feature")

    assert verifier.received_cmds[0] is None, (
        "curl 不在 ALLOWED_CMDS，应被拒降 L5 → verifier 收到 None"
    )



@pytest.mark.parametrize("send_goal", [
    "send an email to alice@example.com",
    "发邮件给张三",
    "notify the user via SMS",
    "purchase product id 42",
])
def test_send_goal_no_strategy_cmd(send_goal: str, tmp_path: Path) -> None:
    """Internal documentation."""
    (tmp_path / "conftest.py").write_text("")

    loop = _make_loop()
    loop._workspace = tmp_path

    cmd = loop._pick_strategy_cmd(send_goal)
    assert cmd is None, (
        f"发送类 goal 不应产 strategy cmd，实际：{cmd!r}（goal: {send_goal!r}）"
    )



def test_explicit_verify_cmd_takes_priority(tmp_path: Path) -> None:
    """Internal documentation."""
    (tmp_path / "conftest.py").write_text("")

    verifier = _RecordingVerifier()
    loop = AgentLoop(
        store=_FakeStore(),
        bus=EventBus(),
        sandbox=_FakeSandbox(),
        broker=None,
        model=_CompletingModel(),
        verifier=verifier,
        config=LoopConfig(verify_cmd="pytest my_tests/", max_steps=5, max_rounds=1),
    )
    loop._workspace = tmp_path

    _collect_events(loop, "implement feature")

    assert verifier.received_cmds, "verifier 必须被调"
    assert verifier.received_cmds[0] == "pytest my_tests/", (
        f"显式 verify_cmd 应优先，实际收到：{verifier.received_cmds[0]!r}"
    )


def test_proposed_verify_takes_priority_over_strategy(tmp_path: Path) -> None:
    """Internal documentation."""
    (tmp_path / "conftest.py").write_text("")

    verifier = _RecordingVerifier()
    loop = _make_loop(verifier=verifier)
    loop._workspace = tmp_path

    loop._on_propose_verify("pytest tests/")
    assert loop._verify_cmd == "pytest tests/"

    result = loop._pick_strategy_cmd("implement feature")
    assert loop._verify_cmd == "pytest tests/", "propose_verify 的 cmd 不应被策略覆盖"



def test_no_verify_strategy_env_disables_generation(tmp_path: Path, monkeypatch) -> None:
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_NO_VERIFY_STRATEGY", "1")

    (tmp_path / "conftest.py").write_text("")
    verifier = _RecordingVerifier()
    loop = _make_loop(verifier=verifier, model=_ImplementingModel())
    loop._workspace = tmp_path

    events = _collect_events(loop, "implement a sort function")

    assert verifier.received_cmds, "verifier 必须被调"
    assert verifier.received_cmds[0] is None, (
        "ARGOS_NO_VERIFY_STRATEGY=1 时不应产生 strategy cmd"
    )

    from argos.protocol.events import Escalation
    phases = [ev.phase for ev in events if isinstance(ev, PhaseChange)]
    escalations = [ev for ev in events if isinstance(ev, Escalation)]
    assert "report" in phases
    assert not escalations


def test_no_verify_strategy_env_empty_string_still_enables(tmp_path: Path, monkeypatch) -> None:
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_NO_VERIFY_STRATEGY", "")

    (tmp_path / "conftest.py").write_text("")
    loop = _make_loop()
    loop._workspace = tmp_path

    cmd = loop._pick_strategy_cmd("implement feature")
    assert cmd is not None and "pytest" in cmd.lower()



def test_capability_hints_passed_to_generate(tmp_path: Path, monkeypatch) -> None:
    """Internal documentation."""
    from argos.verify import strategy as _strat_mod

    received_hints: list[dict] = []

    original_generate = _strat_mod.generate

    def _spy_generate(goal, *, workspace_facts, capability_hints=None):
        received_hints.append(capability_hints or {})
        return original_generate(goal, workspace_facts=workspace_facts,
                                 capability_hints=capability_hints)

    monkeypatch.setattr(_strat_mod, "generate", _spy_generate)

    (tmp_path / "conftest.py").write_text("")
    hints = {"pytest_cmd": "pytest tests/ -x", "extra_key": "extra_val"}
    loop = _make_loop(capability_hints=hints)
    loop._workspace = tmp_path

    loop._pick_strategy_cmd("implement feature")

    assert received_hints, "generate 必须被调"
    assert received_hints[0].get("pytest_cmd") == "pytest tests/ -x", (
        f"capability_hints 未被透传，实际：{received_hints[0]!r}"
    )


def test_capability_hints_pytest_cmd_used_as_verify_cmd(tmp_path: Path) -> None:
    """Internal documentation."""
    (tmp_path / "conftest.py").write_text("")

    loop = _make_loop(capability_hints={"pytest_cmd": "pytest tests/unit -x"})
    loop._workspace = tmp_path

    cmd = loop._pick_strategy_cmd("implement feature")
    assert cmd is not None
    assert "pytest tests/unit -x" in cmd, f"应用 pytest_cmd hint，实际：{cmd!r}"



def test_pick_strategy_cmd_does_not_mutate_verify_cmd(tmp_path: Path) -> None:
    """Internal documentation."""
    (tmp_path / "conftest.py").write_text("")

    loop = _make_loop()
    loop._workspace = tmp_path
    loop._verify_cmd = None

    loop._pick_strategy_cmd("implement feature")

    assert loop._verify_cmd is None, "_pick_strategy_cmd 不应副作用修改 _verify_cmd"


def test_pick_strategy_cmd_returns_none_on_exception(tmp_path: Path, monkeypatch) -> None:
    """Internal documentation."""
    from argos.verify import strategy as _strat_mod

    monkeypatch.setattr(_strat_mod, "generate", lambda *a, **kw: 1 / 0)

    loop = _make_loop()
    loop._workspace = tmp_path

    cmd = loop._pick_strategy_cmd("implement feature")
    assert cmd is None, "generate 异常时应 fail-closed 返 None"


def test_pick_strategy_cmd_nonexistent_workspace() -> None:
    """Internal documentation."""
    loop = _make_loop()
    loop._workspace = Path("/nonexistent/path/xyz_does_not_exist")

    cmd = loop._pick_strategy_cmd("implement feature")
    assert cmd is None


def test_pick_strategy_cmd_skips_l3(tmp_path: Path, monkeypatch) -> None:
    """Internal documentation."""
    from argos.verify import strategy as _strat_mod
    from argos.verify.strategy import VerifyStrategy

    _l3_then_l5 = (
        VerifyStrategy(
            level="L3", kind="dom_assert", cmd=None, target="body",
            rationale_human="dom check", confidence=0.6,
        ),
        VerifyStrategy(
            level="L5", kind="evidence_trail", cmd=None, target=None,
            rationale_human="fallback", confidence=0.0,
        ),
    )
    monkeypatch.setattr(_strat_mod, "generate", lambda *a, **kw: _l3_then_l5)

    loop = _make_loop()
    loop._workspace = tmp_path

    cmd = loop._pick_strategy_cmd("update webpage")
    assert cmd is None, "L3 候选应被跳过，降 L5 → None"
