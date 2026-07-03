"""Internal documentation."""
from __future__ import annotations

from argos.approval import ApprovalLevel
from argos.permissions import get_config
from argos.permissions.evaluator import evaluate


def _d(action, args, *, gate_level, low_risk_auto, risk):
    return evaluate(action, args, gate_level=gate_level, config=get_config(),
                    low_risk_auto=low_risk_auto, risk=risk).decision


def test_trusted_at_least_as_permissive_as_cautious_for_cage_actions():
    """Internal documentation."""
    cases = [
        ("read_file", {"path": "a"}, "low"),
        ("web_search", {"query": "x"}, "low"),
        ("run_command", {"command": "pytest -q"}, "medium"),
    ]
    for action, args, risk in cases:
        cautious = _d(action, args, gate_level=ApprovalLevel.CONFIRM, low_risk_auto=True, risk=risk)
        trusted = _d(action, args, gate_level=ApprovalLevel.ACCEPT_EDITS, low_risk_auto=False, risk=risk)
        assert cautious == "approve", (action, cautious)
        assert trusted == "approve", f"Trusted 比 Cautious 更烦人(反转 bug):{action} 得 {trusted}"


def test_trusted_auto_accepts_edits():
    """Internal documentation."""
    for action in ("write_file", "edit_file"):
        trusted = _d(action, {"path": "a.py", "content": "x"},
                     gate_level=ApprovalLevel.ACCEPT_EDITS, low_risk_auto=False, risk="medium")
        assert trusted == "approve", f"{action} 应在 ACCEPT_EDITS 下自动批"


def test_trusted_still_asks_or_denies_dangerous():
    """Internal documentation."""
    assert _d("browser_click", {}, gate_level=ApprovalLevel.ACCEPT_EDITS,
              low_risk_auto=False, risk="medium") == "ask"
    assert _d("run_command", {"command": "rm -rf /"}, gate_level=ApprovalLevel.ACCEPT_EDITS,
              low_risk_auto=False, risk="medium") == "deny"


def test_cautious_writes_unchanged():
    """Internal documentation."""
    assert _d("write_file", {"path": "a", "content": "x"},
              gate_level=ApprovalLevel.CONFIRM, low_risk_auto=True, risk="medium") == "ask"



def test_accept_edits_still_asks_on_secret_write():
    """Internal documentation."""
    from argos.permissions.evaluator import evaluate
    from argos.permissions import get_config

    # AWS access key pattern: AKIA + 16 uppercase alphanumeric chars
    aws_key = "AKIAIOSFODNN7EXAMPLE"
    meta = evaluate(
        "write_file",
        {"path": "config.py", "content": f'AWS_ACCESS_KEY_ID = "{aws_key}"'},
        gate_level=ApprovalLevel.ACCEPT_EDITS,
        config=get_config(),
        low_risk_auto=False,
        risk="medium",
    )
    assert meta.decision == "ask", (
        f"ACCEPT_EDITS 下含 secret 的写操作应 ask,得 {meta.decision!r}(trigger={meta.trigger!r})"
    )
    assert meta.trigger.startswith("secret:"), (
        f"trigger 应以 'secret:' 开头,得 {meta.trigger!r}"
    )


def test_accept_edits_still_denies_system_path_write():
    """Internal documentation."""
    from argos.permissions.evaluator import evaluate
    from argos.permissions import get_config

    for path in ("/etc/cron.d/x", "~/.ssh/authorized_keys"):
        meta = evaluate(
            "write_file",
            {"path": path, "content": "x"},
            gate_level=ApprovalLevel.ACCEPT_EDITS,
            config=get_config(),
            low_risk_auto=False,
            risk="medium",
        )
        assert meta.decision == "deny", (
            f"ACCEPT_EDITS 下系统路径 {path!r} 写应 deny,得 {meta.decision!r}(trigger={meta.trigger!r})"
        )
        assert "hard_rule:system_path:" in meta.trigger, (
            f"trigger 应含 'hard_rule:system_path:',得 {meta.trigger!r}"
        )
