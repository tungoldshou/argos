from __future__ import annotations

import argparse
import io
import json

import pytest

from argos.cli import headless
from argos.core.types import Verdict
from argos.protocol.events import (
    CostUpdate, Error, Escalation, PhaseChange, TokenDelta, VerifyVerdict,
)


class _FakeLoop:
    def __init__(self, events):
        self._events = events

    async def run(self, goal, session_id, attachments=None):
        for ev in self._events:
            yield ev


class _FakeGate:
    def __init__(self):
        self.listener = None
        self.responded = []

    def set_ask_listener(self, fn):
        self.listener = fn

    def respond(self, call_id, decision):
        self.responded.append((call_id, decision))
        return True


class _FakeComponents:
    def __init__(self, loop, gate):
        self._loop = loop
        self.gate = gate
        self.workspace = "/tmp"
        self.closed = False

    def close(self):
        self.closed = True


def _args(**kw):
    ns = argparse.Namespace(prompt="do the thing", as_json=False, auto=False,
                            verify_cmd=None, project="/tmp", model=None, quiet=False)
    for k, v in kw.items():
        setattr(ns, k, v)
    return ns


def _wire(monkeypatch, events):
    gate = _FakeGate()
    loop = _FakeLoop(events)
    comp = _FakeComponents(loop, gate)
    monkeypatch.setattr("argos.app_factory.build_components", lambda **kw: comp)
    monkeypatch.setattr("argos.app_factory.build_loop_factory", lambda c: (lambda: loop))
    return comp, gate, loop


def _cost():
    return CostUpdate(tokens_in=10, tokens_out=5, cost_usd=0.001, elapsed_s=1.0)


def test_self_verified_pass_labeled_distinctly(monkeypatch, capsys):
    events = [TokenDelta(text="done"),
              VerifyVerdict(verdict=Verdict.passed_self("[exit_code=0]", "pytest", 1))]
    _wire(monkeypatch, events)
    code = headless.run_exec(_args(prompt="x", as_json=True))
    assert code == 0
    obj = json.loads(capsys.readouterr().out)
    assert obj["verdict"] == "passed_self"
    assert obj["self_verified"] is True
    assert obj["is_error"] is False


def test_user_verified_pass_is_plain_passed(monkeypatch, capsys):
    events = [VerifyVerdict(verdict=Verdict.passed("[exit_code=0]", "pytest", 1))]
    _wire(monkeypatch, events)
    headless.run_exec(_args(prompt="x", as_json=True))
    obj = json.loads(capsys.readouterr().out)
    assert obj["verdict"] == "passed" and obj["self_verified"] is False


def test_effort_threaded_from_args(monkeypatch):
    from argos.routing.effort import EffortLevel
    captured = {}

    def _bc(**kw):
        captured.update(kw)
        return _FakeComponents(_FakeLoop([TokenDelta(text="x")]), _FakeGate())
    monkeypatch.setattr("argos.app_factory.build_components", _bc)
    monkeypatch.setattr("argos.app_factory.build_loop_factory",
                        lambda c: (lambda: _FakeLoop([TokenDelta(text="x")])))
    headless.run_exec(_args(prompt="x", effort="high"))
    assert captured.get("effort") == EffortLevel.HIGH


def test_missing_prompt_returns_2(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert headless.run_exec(_args(prompt=None)) == 2


def test_reads_prompt_from_stdin(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("fix the bug"))
    captured = {}
    real_loop = _FakeLoop([VerifyVerdict(verdict=Verdict.passed("[exit_code=0]", "pytest", 1))])

    class _Comp(_FakeComponents):
        pass
    comp = _Comp(real_loop, _FakeGate())

    def _bc(**kw):
        captured["prompt_seen"] = True
        return comp
    monkeypatch.setattr("argos.app_factory.build_components", _bc)
    monkeypatch.setattr("argos.app_factory.build_loop_factory", lambda c: (lambda: real_loop))
    assert headless.run_exec(_args(prompt="-")) == 0


def test_passed_verdict_exit_0_and_prints_result(monkeypatch, capsys):
    events = [PhaseChange(phase="report", actions=1), TokenDelta(text="all done"),
              VerifyVerdict(verdict=Verdict.passed("[exit_code=0]", "pytest", 1))]
    comp, _, _ = _wire(monkeypatch, events)
    code = headless.run_exec(_args(prompt="x"))
    assert code == 0
    assert comp.closed is True
    out = capsys.readouterr()
    assert "all done" in out.out
    assert "passed" in out.err


def test_failed_verdict_exit_1(monkeypatch):
    events = [VerifyVerdict(verdict=Verdict.failed("[exit_code=1]", "pytest", 2))]
    _wire(monkeypatch, events)
    assert headless.run_exec(_args(prompt="x")) == 1


def test_unverifiable_verdict_exit_1(monkeypatch):
    events = [VerifyVerdict(verdict=Verdict.unverifiable("tampered", ["test_x.py"], 1))]
    _wire(monkeypatch, events)
    assert headless.run_exec(_args(prompt="x")) == 1


def test_no_verdict_completes_exit_0(monkeypatch):
    _wire(monkeypatch, [TokenDelta(text="here is the answer")])
    assert headless.run_exec(_args(prompt="what is 2+2")) == 0


def test_escalation_exit_1(monkeypatch):
    events = [Escalation(reason="我没搞定,试过 X", attempts=3, last_failure="exit 1")]
    _wire(monkeypatch, events)
    assert headless.run_exec(_args(prompt="x")) == 1


def test_error_event_exit_1(monkeypatch):
    _wire(monkeypatch, [Error(message="boom")])
    assert headless.run_exec(_args(prompt="x")) == 1


def test_json_envelope(monkeypatch, capsys):
    events = [TokenDelta(text="hi"), _cost(),
              VerifyVerdict(verdict=Verdict.passed("[exit_code=0]", "pytest", 1))]
    _wire(monkeypatch, events)
    code = headless.run_exec(_args(prompt="x", as_json=True))
    assert code == 0
    obj = json.loads(capsys.readouterr().out)
    assert obj["verdict"] == "passed"
    assert obj["is_error"] is False
    assert obj["cost_usd"] == 0.001
    assert obj["session_id"].startswith("exec-")
    assert obj["result"] == "hi"


def test_non_auto_installs_autodeny_listener(monkeypatch):
    comp, gate, _ = _wire(monkeypatch, [TokenDelta(text="x")])
    headless.run_exec(_args(prompt="x", auto=False))
    assert gate.listener is not None
    gate.listener("call-123", {"action": "run_command"})
    assert ("call-123", "deny") in gate.responded


def test_auto_does_not_install_listener(monkeypatch):
    comp, gate, _ = _wire(monkeypatch, [TokenDelta(text="x")])
    headless.run_exec(_args(prompt="x", auto=True))
    assert gate.listener is None


def test_build_components_runtime_error_exit_2(monkeypatch):
    def _boom(**kw):
        raise RuntimeError("未配置 API key")
    monkeypatch.setattr("argos.app_factory.build_components", _boom)
    assert headless.run_exec(_args(prompt="x")) == 2


def test_build_components_config_error_exit_2(monkeypatch, capsys):
    from argos.config import ConfigError

    def _boom(**kw):
        raise ConfigError("profile 'nope' 不存在(可用:[default])")

    monkeypatch.setattr("argos.app_factory.build_components", _boom)
    code = headless.run_exec(_args(prompt="x", model="nope"))
    assert code == 2
    err = capsys.readouterr().err
    assert "不存在" in err
    assert "Traceback" not in err


def test_trivial_verify_cmd_exits_2_fast(monkeypatch, capsys):
    """#17 CONTRACT C: trivial --verify echo exits 2 without calling build_components."""
    called = {}

    def _boom(**kw):
        called["build"] = True
        raise AssertionError("不该到达 build_components")

    monkeypatch.setattr("argos.app_factory.build_components", _boom)
    code = headless.run_exec(_args(prompt="x", verify_cmd="echo ok"))
    assert code == 2
    assert not called, "build_components should NOT have been called for trivial verify"
    err = capsys.readouterr().err
    assert "trivial" in err


def test_trivial_verify_cmd_true_exits_2(monkeypatch, capsys):
    def _should_not_be_called(**kw):
        raise AssertionError("build_components should not be called for trivial verify cmd")

    monkeypatch.setattr("argos.app_factory.build_components", _should_not_be_called)
    code = headless.run_exec(_args(prompt="x", verify_cmd="true"))
    assert code == 2


def test_progress_lines_go_to_stderr_not_stdout(monkeypatch, capsys):
    events = [
        PhaseChange(phase="plan", actions=0),
        PhaseChange(phase="act", actions=1),
        TokenDelta(text="output here"),
        PhaseChange(phase="report", actions=0),
        VerifyVerdict(verdict=Verdict.passed("[exit_code=0]", "pytest", 1)),
    ]
    _wire(monkeypatch, events)
    code = headless.run_exec(_args(prompt="x"))
    assert code == 0
    out, err = capsys.readouterr()
    assert "phase" in err
    assert "phase →" not in out


def test_quiet_flag_suppresses_progress(monkeypatch, capsys):
    events = [
        PhaseChange(phase="plan", actions=0),
        PhaseChange(phase="act", actions=1),
        TokenDelta(text="result"),
        PhaseChange(phase="report", actions=0),
        VerifyVerdict(verdict=Verdict.passed("[exit_code=0]", "pytest", 1)),
    ]
    _wire(monkeypatch, events)
    code = headless.run_exec(_args(prompt="x", quiet=True))
    assert code == 0
    out, err = capsys.readouterr()
    assert "phase →" not in err
    assert "result" in out
