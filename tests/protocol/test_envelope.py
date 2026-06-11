"""EventEnvelope 测试:黄金字段验证 + round-trip。

P0 只定义格式不接 server。
"""
from __future__ import annotations

import json

import pytest

from argos_agent.protocol.envelope import EventEnvelope, wrap_event
from argos_agent.protocol.events import (
    TokenDelta, PhaseChange, CostUpdate, Error,
    serialize_event, deserialize_event,
)


# ── wrap_event 基础 ────────────────────────────────────────────────────────────

def test_wrap_event_fields():
    """wrap_event 必须填充所有帧字段,v 固定为 1。"""
    ev = TokenDelta(text="hi")
    frame = wrap_event(ev, seq=0, session="sess-1", run="run-abc")
    assert frame.v == 1
    assert frame.seq == 0
    assert frame.kind == "token_delta"
    assert frame.session == "sess-1"
    assert frame.run == "run-abc"
    assert isinstance(frame.id, str) and len(frame.id) > 0
    assert isinstance(frame.ts, float) and frame.ts > 0
    assert frame.data == {"text": "hi"}


def test_wrap_event_default_run_empty():
    """run 省略时默认空串。"""
    ev = TokenDelta(text="x")
    frame = wrap_event(ev, seq=0, session="s")
    assert frame.run == ""


def test_wrap_event_custom_id_and_ts():
    """可显式指定 id 和 ts。"""
    ev = PhaseChange(phase="act", actions=1)
    frame = wrap_event(ev, seq=5, session="s", run="r",
                       ts=1234567890.0, id="deadbeef0123456789ab")
    assert frame.id == "deadbeef0123456789ab"
    assert frame.ts == 1234567890.0


def test_wrap_event_data_matches_serialize():
    """frame.data 应与 serialize_event payload 一致。"""
    ev = CostUpdate(tokens_in=10, tokens_out=5, cost_usd=0.001, elapsed_s=1.0)
    frame = wrap_event(ev, seq=1, session="s")
    expected_data = json.loads(serialize_event(ev))["data"]
    assert frame.data == expected_data


def test_wrap_event_frozen():
    """EventEnvelope 是 frozen dataclass,赋值必须报错。"""
    ev = TokenDelta(text="x")
    frame = wrap_event(ev, seq=0, session="s")
    with pytest.raises((AttributeError, TypeError)):
        frame.seq = 99  # type: ignore[misc]


# ── to_json / from_json round-trip ────────────────────────────────────────────

def test_envelope_to_json_from_json_roundtrip():
    ev = PhaseChange(phase="verify", actions=3)
    frame = wrap_event(ev, seq=7, session="sess-rt", run="run-rt",
                       ts=1000000.0, id="aaaa" * 8)
    blob = frame.to_json()
    back = EventEnvelope.from_json(blob)
    assert back.v == frame.v
    assert back.seq == frame.seq
    assert back.kind == frame.kind
    assert back.id == frame.id
    assert back.ts == frame.ts
    assert back.session == frame.session
    assert back.run == frame.run
    assert back.data == frame.data


def test_envelope_to_json_keys():
    """to_json 必须包含所有协议规定字段。"""
    ev = Error(message="boom")
    frame = wrap_event(ev, seq=0, session="s")
    obj = json.loads(frame.to_json())
    required = {"v", "seq", "kind", "id", "ts", "session", "run", "data"}
    assert required <= obj.keys(), f"缺字段:{required - obj.keys()}"


def test_envelope_from_json_missing_field():
    """from_json 遇到缺字段应 KeyError(fail-loud)。"""
    incomplete = json.dumps({"v": 1, "seq": 0, "kind": "token_delta"})
    with pytest.raises(KeyError):
        EventEnvelope.from_json(incomplete)


# ── 黄金快照:字段值写死 ────────────────────────────────────────────────────────

def test_envelope_golden_snapshot():
    """黄金字段值:to_json 输出的每个字段必须符合预期(ABI 冻结)。"""
    ev = TokenDelta(text="黄金")
    frame = wrap_event(
        ev, seq=42, session="session-golden", run="run-golden",
        ts=1749600000.0, id="goldenid" * 4,
    )
    obj = json.loads(frame.to_json())
    assert obj["v"] == 1
    assert obj["seq"] == 42
    assert obj["kind"] == "token_delta"
    assert obj["id"] == "goldenid" * 4
    assert obj["ts"] == 1749600000.0
    assert obj["session"] == "session-golden"
    assert obj["run"] == "run-golden"
    assert obj["data"] == {"text": "黄金"}


def test_envelope_seq_monotonic():
    """多帧 seq 单调递增(由调用方维护,此测试验证 wrap_event 不自动递增)。"""
    ev = TokenDelta(text="x")
    frames = [wrap_event(ev, seq=i, session="s") for i in range(5)]
    seqs = [f.seq for f in frames]
    assert seqs == list(range(5))


# ── 各种 Event 类型都能 wrap ───────────────────────────────────────────────────

@pytest.mark.parametrize("ev", [
    TokenDelta(text="t"),
    PhaseChange(phase="plan", actions=0),
    Error(message="e"),
    CostUpdate(tokens_in=1, tokens_out=1, cost_usd=None, elapsed_s=0.5),
])
def test_wrap_and_roundtrip_various_events(ev):
    frame = wrap_event(ev, seq=0, session="s")
    blob = frame.to_json()
    back = EventEnvelope.from_json(blob)
    assert back.kind == type(ev).kind
    assert back.data == frame.data
