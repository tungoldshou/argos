"""P4 阶段2：verify 策略生成接线集成测试。

覆盖规则：
1. 有 pytest 工作区且无 verify_cmd → 自动 L1 策略走门（验证 verifier 收到了 cmd）
2. 策略 cmd 被白名单拒 → 诚实降级链（下一候选 → L5 → 旧 NO_TEST 路径）
3. 发送类 goal → 直接 NO_TEST（generate() 内硬编码 L5，不碰 _run_verify）
4. 显式 verify_cmd 优先（用户声明压倒推断）
5. ARGOS_NO_VERIFY_STRATEGY=1 → 关闭，回归旧行为（no verify_cmd = NO_TEST）
"""
from __future__ import annotations

import os
import pytest
from pathlib import Path

from argos_agent.core.loop import AgentLoop, LoopConfig
from argos_agent.core.verify_gate import Verdict
from argos_agent.protocol.events import EventBus, VerifyVerdict, PhaseChange
from argos_agent.sandbox.backend import ExecResult


# ─── 测试替身 ──────────────────────────────────────────────────────────────────

class _CompletingModel:
    """每次 stream 均无代码块（宣布完成），不执行任何动作。"""
    last_usage: dict = {}

    async def stream(self, messages, *, system="", system_dynamic=""):
        for ch in "任务完成了。":
            yield ch


class _FakeSandbox:
    def spawn(self, *, workspace, namespace, allow_workflow=True, read_only=False): ...
    def exec_code(self, code): return ExecResult(stdout="", value_repr="", exc="")
    def close(self): ...


class _RecordingVerifier:
    """记录 verify 被调时传入的 verify_cmd，返回 passed（验证通过）。"""
    def __init__(self) -> None:
        self.received_cmds: list[str | None] = []

    def verify(self, verify_cmd: str | None, *, attempts: int = 1) -> Verdict:
        self.received_cmds.append(verify_cmd)
        if verify_cmd:
            return Verdict.passed(detail="[exit_code=0]", verify_cmd=verify_cmd, attempts=attempts)
        return Verdict.unverifiable(detail="(无 verify_cmd)", tampered=[], attempts=attempts)


class _FailingVerifier:
    """每次都返回 failed，用于测试降级链。"""
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
) -> AgentLoop:
    """构造最小 AgentLoop（不跑真模型/真沙箱）。"""
    return AgentLoop(
        store=_FakeStore(),
        bus=EventBus(),
        sandbox=_FakeSandbox(),
        broker=None,
        model=_CompletingModel(),
        verifier=verifier or _RecordingVerifier(),
        config=LoopConfig(verify_cmd=verify_cmd, max_steps=max_steps, max_rounds=1),
        capability_hints=capability_hints,
    )


def _collect_events(loop: AgentLoop, goal: str) -> list:
    """同步收集 loop.run 的所有事件（asyncio.run）。"""
    import asyncio

    async def _run():
        return [ev async for ev in loop.run(goal, "s")]

    return asyncio.run(_run())


# ─── 测试 1：有 pytest 工作区且无 verify_cmd → 自动 L1 策略走门 ─────────────────

def test_auto_l1_strategy_in_pytest_workspace(tmp_path: Path) -> None:
    """有 conftest.py（pytest 信号）+ 无 verify_cmd → _pick_strategy_cmd 产 L1 pytest，
    verifier 收到非 None 的 cmd（策略生效）。"""
    (tmp_path / "conftest.py").write_text("")  # pytest 信号

    verifier = _RecordingVerifier()
    loop = AgentLoop(
        store=_FakeStore(),
        bus=EventBus(),
        sandbox=_FakeSandbox(),
        broker=None,
        model=_CompletingModel(),
        verifier=verifier,
        config=LoopConfig(verify_cmd=None, max_steps=5, max_rounds=1),
    )
    loop._workspace = tmp_path  # 指向有 conftest.py 的工作区

    _collect_events(loop, "implement a sort function")

    # verifier 必须收到非 None 的命令（策略生效）
    assert verifier.received_cmds, "verifier 必须至少被调一次"
    received = verifier.received_cmds[0]
    assert received is not None, "有 pytest 工作区应产 L1 策略 cmd（非 None）"
    assert "pytest" in received.lower(), f"L1 cmd 应含 pytest，实际：{received!r}"


def test_auto_strategy_sets_verify_cmd_on_loop(tmp_path: Path) -> None:
    """策略生效后 loop._verify_cmd 应被设为策略产生的 cmd（可供 bounce 复用）。"""
    (tmp_path / "conftest.py").write_text("")

    loop = _make_loop()
    loop._workspace = tmp_path

    # 直接调 _pick_strategy_cmd（不走完整 run，单元测试）
    cmd = loop._pick_strategy_cmd("implement feature")
    assert cmd is not None
    assert "pytest" in cmd.lower()


# ─── 测试 2：策略 cmd 被白名单拒 → 诚实降级链 ──────────────────────────────────

def test_blacklisted_strategy_cmd_degrades_to_no_test(tmp_path: Path, monkeypatch) -> None:
    """策略生成的所有 cmd 都过不了白名单 / 只有 L5 → verifier 收到 None → NO_TEST 诚实路径。

    用 monkeypatch 替换 generate，让它只返回 L5（模拟所有 cmd 被拒的终态）。
    """
    from argos_agent.verify import strategy as _strat_mod
    from argos_agent.verify.strategy import VerifyStrategy, WorkspaceFacts

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
    loop = _make_loop(verifier=verifier)
    loop._workspace = tmp_path

    events = _collect_events(loop, "implement feature")

    # verifier 必须收到 None（L5 → 旧 NO_TEST 路径）
    assert verifier.received_cmds, "verifier 必须被调"
    assert verifier.received_cmds[0] is None, (
        f"所有策略降 L5 后 verifier 应收到 None，实际：{verifier.received_cmds[0]!r}"
    )

    # 走 NO_TEST 诚实路径 → 必须到 report（不 Escalation）
    phases = [ev.phase for ev in events if isinstance(ev, PhaseChange)]
    assert "report" in phases


def test_trivial_cmd_in_strategy_degrades_gracefully(tmp_path: Path, monkeypatch) -> None:
    """策略产的 cmd 首 token 在 _TRIVIAL_VERIFY_BINS（如 echo）→ 被拒跳过 → 降至 L5 → NO_TEST。"""
    from argos_agent.verify import strategy as _strat_mod
    from argos_agent.verify.strategy import VerifyStrategy

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
    loop = _make_loop(verifier=verifier)
    loop._workspace = tmp_path

    _collect_events(loop, "implement feature")

    # echo 被拒后降至 L5 → verifier 收到 None
    assert verifier.received_cmds[0] is None, (
        "trivial cmd echo 应被拒，降 L5 后 verifier 收到 None"
    )


def test_non_allowlisted_cmd_in_strategy_degrades_gracefully(tmp_path: Path, monkeypatch) -> None:
    """策略产的 cmd 首 token 不在 ALLOWED_CMDS（如 curl）→ 被拒 → 降 L5 → NO_TEST。"""
    from argos_agent.verify import strategy as _strat_mod
    from argos_agent.verify.strategy import VerifyStrategy

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
    loop = _make_loop(verifier=verifier)
    loop._workspace = tmp_path

    _collect_events(loop, "implement feature")

    assert verifier.received_cmds[0] is None, (
        "curl 不在 ALLOWED_CMDS，应被拒降 L5 → verifier 收到 None"
    )


# ─── 测试 3：发送类 goal → 直接 NO_TEST ─────────────────────────────────────────

@pytest.mark.parametrize("send_goal", [
    "send an email to alice@example.com",
    "发邮件给张三",
    "notify the user via SMS",
    "purchase product id 42",
])
def test_send_goal_no_strategy_cmd(send_goal: str, tmp_path: Path) -> None:
    """发送/购买/通知类 goal：generate() 内硬编码 L5 → _pick_strategy_cmd 返 None。
    不碰执行任何 cmd（传输层成功 ≠ 任务正确的红线）。"""
    (tmp_path / "conftest.py").write_text("")  # 即使有 pytest 环境也 L5-only

    loop = _make_loop()
    loop._workspace = tmp_path

    cmd = loop._pick_strategy_cmd(send_goal)
    assert cmd is None, (
        f"发送类 goal 不应产 strategy cmd，实际：{cmd!r}（goal: {send_goal!r}）"
    )


# ─── 测试 4：显式 verify_cmd 优先 ───────────────────────────────────────────────

def test_explicit_verify_cmd_takes_priority(tmp_path: Path) -> None:
    """LoopConfig.verify_cmd 已设 → 策略生成不触发（_pick_strategy_cmd 不会被调到，
    因为 `self._verify_cmd is None` 的前置条件不满足）。"""
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

    # verifier 收到的 cmd 必须是显式配置的，不是策略产生的
    assert verifier.received_cmds, "verifier 必须被调"
    assert verifier.received_cmds[0] == "pytest my_tests/", (
        f"显式 verify_cmd 应优先，实际收到：{verifier.received_cmds[0]!r}"
    )


def test_proposed_verify_takes_priority_over_strategy(tmp_path: Path) -> None:
    """act 阶段 agent propose_verify('pytest tests/') 后 _verify_cmd 已设 →
    策略生成不触发（_verify_cmd is None 前置不满足）。"""
    (tmp_path / "conftest.py").write_text("")

    verifier = _RecordingVerifier()
    loop = _make_loop(verifier=verifier)
    loop._workspace = tmp_path

    # 模拟 agent 已 propose_verify
    loop._on_propose_verify("pytest tests/")
    assert loop._verify_cmd == "pytest tests/"

    # _pick_strategy_cmd 此时不应覆盖
    result = loop._pick_strategy_cmd("implement feature")
    # _pick_strategy_cmd 是纯函数（不改 _verify_cmd）；调用方在 _verify_cmd is None 时才调它
    # 这里验证 _verify_cmd 未被改变（loop 逻辑的前置条件保证了不会走到 _pick_strategy_cmd）
    assert loop._verify_cmd == "pytest tests/", "propose_verify 的 cmd 不应被策略覆盖"


# ─── 测试 5：ARGOS_NO_VERIFY_STRATEGY=1 关闭 → 回归旧行为 ───────────────────────

def test_no_verify_strategy_env_disables_generation(tmp_path: Path, monkeypatch) -> None:
    """ARGOS_NO_VERIFY_STRATEGY=1 → 策略生成被跳过，verify_cmd 保持 None → NO_TEST 诚实路径。"""
    monkeypatch.setenv("ARGOS_NO_VERIFY_STRATEGY", "1")

    (tmp_path / "conftest.py").write_text("")
    verifier = _RecordingVerifier()
    loop = _make_loop(verifier=verifier)
    loop._workspace = tmp_path

    events = _collect_events(loop, "implement a sort function")

    # 策略关闭 → verifier 收到 None（旧 NO_TEST 行为）
    assert verifier.received_cmds, "verifier 必须被调"
    assert verifier.received_cmds[0] is None, (
        "ARGOS_NO_VERIFY_STRATEGY=1 时不应产生 strategy cmd"
    )

    # 走诚实 NO_TEST 完成路径（到 report，无 Escalation）
    from argos_agent.protocol.events import Escalation
    phases = [ev.phase for ev in events if isinstance(ev, PhaseChange)]
    escalations = [ev for ev in events if isinstance(ev, Escalation)]
    assert "report" in phases
    assert not escalations


def test_no_verify_strategy_env_empty_string_still_enables(tmp_path: Path, monkeypatch) -> None:
    """ARGOS_NO_VERIFY_STRATEGY='' (空串) → 不禁用（os.environ.get 返回空串，bool 为 False）。"""
    monkeypatch.setenv("ARGOS_NO_VERIFY_STRATEGY", "")

    (tmp_path / "conftest.py").write_text("")
    loop = _make_loop()
    loop._workspace = tmp_path

    cmd = loop._pick_strategy_cmd("implement feature")
    # 空串不禁用 → pytest 工作区仍应产 cmd
    # 注意：_pick_strategy_cmd 本身不看环境变量（env check 在 _drive 里）；
    # 这里只测 pick 本身不受空串影响
    assert cmd is not None and "pytest" in cmd.lower()


# ─── 测试 6：capability_hints 被透传 ────────────────────────────────────────────

def test_capability_hints_passed_to_generate(tmp_path: Path, monkeypatch) -> None:
    """loop 构造时传入 capability_hints → _pick_strategy_cmd 透传给 generate()。"""
    from argos_agent.verify import strategy as _strat_mod

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
    """capability_hints['pytest_cmd'] = 自定义命令 → _pick_strategy_cmd 产出该自定义命令。"""
    (tmp_path / "conftest.py").write_text("")

    loop = _make_loop(capability_hints={"pytest_cmd": "pytest tests/unit -x"})
    loop._workspace = tmp_path

    cmd = loop._pick_strategy_cmd("implement feature")
    assert cmd is not None
    assert "pytest tests/unit -x" in cmd, f"应用 pytest_cmd hint，实际：{cmd!r}"


# ─── 测试 7：_pick_strategy_cmd 纯函数不变性 ────────────────────────────────────

def test_pick_strategy_cmd_does_not_mutate_verify_cmd(tmp_path: Path) -> None:
    """_pick_strategy_cmd 不修改 self._verify_cmd（是纯查询，由 _drive 决定是否赋值）。"""
    (tmp_path / "conftest.py").write_text("")

    loop = _make_loop()
    loop._workspace = tmp_path
    loop._verify_cmd = None

    loop._pick_strategy_cmd("implement feature")

    # _pick_strategy_cmd 只返回，不修改 _verify_cmd
    assert loop._verify_cmd is None, "_pick_strategy_cmd 不应副作用修改 _verify_cmd"


def test_pick_strategy_cmd_returns_none_on_exception(tmp_path: Path, monkeypatch) -> None:
    """generate() 内部抛异常 → _pick_strategy_cmd fail-closed 返 None（不崩 run）。"""
    from argos_agent.verify import strategy as _strat_mod

    monkeypatch.setattr(_strat_mod, "generate", lambda *a, **kw: 1 / 0)

    loop = _make_loop()
    loop._workspace = tmp_path

    cmd = loop._pick_strategy_cmd("implement feature")
    assert cmd is None, "generate 异常时应 fail-closed 返 None"


def test_pick_strategy_cmd_nonexistent_workspace() -> None:
    """workspace 不存在 → probe_workspace 返空 WorkspaceFacts → 仍不崩（fail-closed）。"""
    loop = _make_loop()
    loop._workspace = Path("/nonexistent/path/xyz_does_not_exist")

    cmd = loop._pick_strategy_cmd("implement feature")
    # 无 pytest/cargo 等框架 → 无 L1 → 降 L5 → None
    assert cmd is None


def test_pick_strategy_cmd_skips_l3(tmp_path: Path, monkeypatch) -> None:
    """L3 dom_assert 候选（cmd=None，需外部 browser executor）→ 跳过 → 降 L5 → None。"""
    from argos_agent.verify import strategy as _strat_mod
    from argos_agent.verify.strategy import VerifyStrategy

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
