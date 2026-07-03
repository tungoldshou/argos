"""Internal documentation."""
from __future__ import annotations

import dataclasses
import pytest

from argos.capability.manifest import Capability


# ------------------------------------------------------------------
# ------------------------------------------------------------------

def _cap(**kwargs) -> Capability:
    """Internal documentation."""
    defaults = dict(
        name="web_search",
        kind="tool",
        risk="low",
    )
    defaults.update(kwargs)
    return Capability(**defaults)


# ------------------------------------------------------------------
# ------------------------------------------------------------------

def test_basic_construction():
    """Internal documentation."""
    cap = _cap()
    assert cap.name == "web_search"
    assert cap.kind == "tool"
    assert cap.risk == "low"
    assert cap.reversible is None
    assert cap.egress_hosts == ()
    assert cap.schema is None
    assert cap.verify_hint == ""
    assert cap.visibility == "all"
    assert cap.dispatch is None


def test_full_construction():
    """Internal documentation."""
    def _exec(**kw):
        return "result"

    cap = Capability(
        name="run_command",
        kind="tool",
        risk="high",
        reversible=False,
        egress_hosts=("example.com",),
        schema={"type": "object", "properties": {"cmd": {"type": "string"}}},
        verify_hint="exit code 0 = passed",
        visibility="developer",
        dispatch=_exec,
    )
    assert cap.name == "run_command"
    assert cap.risk == "high"
    assert cap.reversible is False
    assert cap.egress_hosts == ("example.com",)
    assert cap.schema is not None
    assert cap.verify_hint == "exit code 0 = passed"
    assert cap.visibility == "developer"
    assert cap.dispatch is _exec


def test_risk_none_allowed_in_manifest():
    """Internal documentation."""
    cap = _cap(risk=None)
    assert cap.risk is None


def test_reversible_can_be_true_false_or_none():
    """Internal documentation."""
    assert _cap(reversible=True).reversible is True
    assert _cap(reversible=False).reversible is False
    assert _cap(reversible=None).reversible is None


# ------------------------------------------------------------------
# ------------------------------------------------------------------

def test_frozen_immutable():
    """Internal documentation."""
    cap = _cap()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cap.name = "other"  # type: ignore[misc]


def test_frozen_egress_hosts_tuple():
    """Internal documentation."""
    cap = _cap(egress_hosts=("api.openai.com", "duckduckgo.com"))
    assert isinstance(cap.egress_hosts, tuple)


# ------------------------------------------------------------------
# ------------------------------------------------------------------

def test_empty_name_rejected():
    """Internal documentation."""
    with pytest.raises(ValueError, match="name"):
        _cap(name="")


def test_whitespace_only_name_rejected():
    """Internal documentation."""
    with pytest.raises(ValueError, match="name"):
        _cap(name="   ")


def test_invalid_kind_rejected():
    """Internal documentation."""
    with pytest.raises(ValueError, match="kind"):
        _cap(kind="unknown_kind")  # type: ignore[arg-type]


def test_invalid_visibility_rejected():
    """Internal documentation."""
    with pytest.raises(ValueError, match="visibility"):
        _cap(visibility="admin")  # type: ignore[arg-type]


# ------------------------------------------------------------------
# ------------------------------------------------------------------

@pytest.mark.parametrize("kind", [
    "tool", "mcp", "computer", "browser", "hook", "skill", "lsp", "plugin",
])
def test_all_valid_kinds(kind):
    """Internal documentation."""
    cap = _cap(kind=kind)
    assert cap.kind == kind


@pytest.mark.parametrize("vis", ["all", "developer"])
def test_all_valid_visibility(vis):
    """Internal documentation."""
    cap = _cap(visibility=vis)
    assert cap.visibility == vis


# ------------------------------------------------------------------
# dispatch
# ------------------------------------------------------------------

def test_dispatch_callable():
    """Internal documentation."""
    called = []

    def handler(**kw):
        called.append(kw)
        return "ok"

    cap = _cap(dispatch=handler)
    result = cap.dispatch(cmd="echo hi")
    assert result == "ok"
    assert called == [{"cmd": "echo hi"}]


def test_dispatch_none_is_default():
    """Internal documentation."""
    cap = _cap()
    assert cap.dispatch is None
