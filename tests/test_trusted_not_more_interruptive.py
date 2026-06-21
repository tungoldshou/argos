"""P0 反转修复:Trusted(ACCEPT_EDITS)绝不比 Cautious(CONFIRM+low_risk_auto)更烦人。

此前 bug:3-mode 重设把 Trusted 映射到 ACCEPT_EDITS,但 trust_dial L3 既不置 low_risk_auto、
lvl 又是 "accept_edits";而 evaluator 牢笼放行短路硬性要求 low_risk_auto 且 lvl=="confirm"。
两个条件都不满足 → Trusted 对牢笼内动作全部弹卡询问,比默认 Cautious 还烦人("升级信任"反向)。

修复:accept_edits 独立于 low_risk_auto 拿到与 Cautious 同样的牢笼放行,并额外自动批
write_file/edit_file(名副其实"接受编辑")→ Trusted 严格 ≥ Cautious。
"""
from __future__ import annotations

from argos.approval import ApprovalLevel
from argos.permissions import get_config
from argos.permissions.evaluator import evaluate


def _d(action, args, *, gate_level, low_risk_auto, risk):
    return evaluate(action, args, gate_level=gate_level, config=get_config(),
                    low_risk_auto=low_risk_auto, risk=risk).decision


def test_trusted_at_least_as_permissive_as_cautious_for_cage_actions():
    """牢笼内动作:凡 Cautious 自动批的,Trusted 必须也自动批(反转铁证)。"""
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
    """ACCEPT_EDITS 名副其实:自动批 write_file/edit_file(medium)—— Trusted 比 Cautious 更松,正确方向。"""
    for action in ("write_file", "edit_file"):
        trusted = _d(action, {"path": "a.py", "content": "x"},
                     gate_level=ApprovalLevel.ACCEPT_EDITS, low_risk_auto=False, risk="medium")
        assert trusted == "approve", f"{action} 应在 ACCEPT_EDITS 下自动批"


def test_trusted_still_asks_or_denies_dangerous():
    """护栏:Trusted 只放行牢笼内 + 编辑;非牢笼中危仍 ask,hard-rule 危险命令仍 deny。"""
    assert _d("browser_click", {}, gate_level=ApprovalLevel.ACCEPT_EDITS,
              low_risk_auto=False, risk="medium") == "ask"
    assert _d("run_command", {"command": "rm -rf /"}, gate_level=ApprovalLevel.ACCEPT_EDITS,
              low_risk_auto=False, risk="medium") == "deny"


def test_cautious_writes_unchanged():
    """不放宽默认档:write_file 在 Cautious 下仍 ask(本修复只动 accept_edits 语义)。"""
    assert _d("write_file", {"path": "a", "content": "x"},
              gate_level=ApprovalLevel.CONFIRM, low_risk_auto=True, risk="medium") == "ask"


# ── 安全回归:accept_edits 牢笼放行必须在 secret/hard-path 检查之后 ──────────────
# P2 锁:即便在 ACCEPT_EDITS(Trusted)档位下,secret 命中 → ask,系统路径 → deny。
# 证明新的 accept_edits 放行分支是在 hard-rule / secret 检查之后短路,不会绕过护栏。

def test_accept_edits_still_asks_on_secret_write():
    """ACCEPT_EDITS 下,写含 AWS key 的内容 → decision=='ask'(secret 命中 D8 锁不旁路)。"""
    from argos.permissions.evaluator import evaluate
    from argos.permissions import get_config

    # AWS access key pattern: AKIA + 16 uppercase alphanumeric chars
    aws_key = "AKIAIOSFODNN7EXAMPLE"   # AKIA + 16 chars — 命中 SECRET_PATTERNS[0]
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
    """ACCEPT_EDITS 下,写系统路径 → decision=='deny'(hard-path 规则不旁路)。"""
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
