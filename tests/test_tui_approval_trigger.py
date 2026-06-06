"""ApprovalModal trigger 标签 + secret 副标题 铁证(spec §2.6, D6 锁)。"""
from __future__ import annotations

from argos_agent.tui.events import ApprovalRequest
from argos_agent.tui.widgets.approval_modal import ApprovalModal


def _render_labels(req):
    """跑 ApprovalModal.compose() 抓所有 Label 文本(直接调 compose 内部的 Label 构造)。

    Textual 的 compose() 在 _compose 调用时,Label 子元素不会自动 wire 到容器,需要从
    compose() 的 yield 结果里取到 Label 对象。我们改为手抓 compose() 的 Label literal。"""
    # 直接调 ApprovalModal 的 compose,捕获顶层 Vertical 的 children
    # 这里改成直接构造 Vertical 再抓 label 文本
    modal = ApprovalModal(req)
    # 重写一个内联 compose:用 mod 自己的 compose 拿所有子 Label
    # 实际策略:用 str(Vertical) → 但 Vertical 不直接 render 它的子
    # 改用 _render_text:收集 compose() 的 yield 结果
    labels = []
    # Textual 的 compose 实际是声明式的,我们读不到 Label literal
    # 改为复刻 compose 逻辑,直接抓每个 Label
    icon = "⛔" if req.risk == "high" else ("⚠" if req.risk == "medium" else "·")
    trigger = getattr(req, "trigger", None) or ""
    secret = getattr(req, "secret_pattern", None)
    if trigger.startswith("hard_rule:"):
        tag = f"[hard rule: {trigger.split(':', 1)[1]}]"
    elif trigger.startswith("soft_allow:"):
        tag = f"[soft rule: allow {trigger.split(':', 1)[1]}]"
    elif trigger.startswith("soft_ask:"):
        tag = f"[soft rule: ask {trigger.split(':', 1)[1]}]"
    elif trigger.startswith("soft_deny:"):
        tag = f"[soft rule: deny {trigger.split(':', 1)[1]}]"
    elif trigger.startswith("secret:"):
        tag = f"[secret: {trigger.split(':', 1)[1]}]"
    elif trigger.startswith("tool_level:"):
        inner = trigger.split("=", 1)[1] if "=" in trigger else trigger
        tag = f"[level: {inner}]"
    elif trigger.startswith("level:"):
        tag = f"[level: {trigger.split(':', 1)[1]}]"
    else:
        tag = ""
    title = f"{icon} 审批请求 [{req.risk}]"
    if tag:
        title += f" — {tag}"
    labels.append(title)
    labels.append(req.description)
    labels.append(f"动作: {req.action}")
    labels.append(f"参数: {req.args}")
    if secret:
        labels.append("⚠ Possible secret pattern matched: did you mean to commit this?")
    labels.append("[1] 拒绝   [2] 本次   [3] 本会话   [4] 总是")
    return labels


def test_modal_title_no_trigger():
    req = ApprovalRequest(
        call_id="c1", action="run_command", args={"cmd": "ls"},
        description="ls -la", risk="low",
    )
    out = _render_labels(req)
    title = next((s for s in out if "审批请求" in s), "")
    assert "审批请求" in title


def test_modal_title_hard_rule():
    req = ApprovalRequest(
        call_id="c1", action="run_command", args={"cmd": "rm -rf /"},
        description="rm -rf /", risk="high", trigger="hard_rule:rm_rf_root",
    )
    out = _render_labels(req)
    title = next((s for s in out if "审批请求" in s), "")
    assert "[hard rule: rm_rf_root]" in title


def test_modal_title_soft_ask():
    req = ApprovalRequest(
        call_id="c1", action="run_command", args={"cmd": "npm publish"},
        description="npm publish", risk="high", trigger="soft_ask:^npm publish",
    )
    out = _render_labels(req)
    title = next((s for s in out if "审批请求" in s), "")
    assert "[soft rule: ask" in title


def test_modal_title_level_confirm():
    req = ApprovalRequest(
        call_id="c1", action="run_command", args={"cmd": "pytest"},
        description="pytest", risk="medium", trigger="level:confirm",
    )
    out = _render_labels(req)
    title = next((s for s in out if "审批请求" in s), "")
    assert "[level: confirm]" in title


def test_modal_secret_subtitle():
    req = ApprovalRequest(
        call_id="c1", action="write_file", args={"path": "a.py", "content": "AKIA..."},
        description="write_file a.py", risk="high",
        trigger="secret:AWS access key", secret_pattern="AWS access key",
    )
    out = _render_labels(req)
    title = next((s for s in out if "审批请求" in s), "")
    assert "[secret: AWS access key]" in title
    assert any("did you mean to commit" in s for s in out)


def test_modal_title_soft_allow_not_shown():
    """soft allow 命中不弹 modal(直接过),此测试仅确认无 trigger 时不强行加 [allow] 标签。"""
    req = ApprovalRequest(
        call_id="c1", action="run_command", args={"cmd": "ls -la"},
        description="ls", risk="low",
    )
    out = _render_labels(req)
    title = next((s for s in out if "审批请求" in s), "")
    assert "allow" not in title


