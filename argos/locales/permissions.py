"""permissions/trust_dial.py + approval.py 用户可见文案 (Wave 2d).

key 命名空间: perm.* / approval.*
ZH 值 = 重构前的原始串 verbatim (一字不差)。
EN 值 = 语义对等的自然英文,以 "Error:" 开头对应 ZH "错误:" 开头。
"""
from __future__ import annotations

EN: dict[str, str] = {
    # ── trust_dial.py: _HUMAN_LABELS ─────────────────────────────────────────

    "perm.label.l0": "Ask me at every step",
    "perm.label.l1": "Ask only for dangerous actions",
    "perm.label.l2": "Ask only for irreversible actions",
    "perm.label.l3": "Auto-approve same-type actions after first approval this session",
    "perm.label.l4": "Fully autonomous (HARD RULES still enforced)",

    # ── trust_dial.py: _DESCRIPTIONS ─────────────────────────────────────────

    "perm.desc.l0": (
        "Most conservative mode. Every tool call pauses for your confirmation,"
        " including read-only operations."
        " Best for first-time use or when you are completely uncertain about the task."
    ),
    "perm.desc.l1": (
        "Only high-risk actions (deleting files, running shell commands, network requests, etc.)"
        " pause for confirmation; low-risk actions (reading files, listing directories)"
        " are automatically allowed."
    ),
    "perm.desc.l2": (
        "Only irreversible actions pause for confirmation"
        " (requires the reversible field in the P2 capability manifest);"
        " reversible actions are automatically allowed."
        " Note: protection depends on the accuracy of capability declarations."
    ),
    "perm.desc.l3": (
        "Once you approve an action type in this session,"
        " the same type is automatically allowed"
        " (equivalent to ACCEPT_EDITS extended to all categories);"
        " new action types still require first-time confirmation."
        " Cache is cleared when the session ends."
    ),
    "perm.desc.l4": (
        "Fully autonomous: all tool calls are automatically allowed, equivalent to the old /yolo."
        " HARD RULES (system paths, dangerous shell commands, secret detection)"
        " are still enforced and cannot be bypassed."
        " A red indicator is shown in the TUI header."
    ),

    # ── trust_dial.py: to_approval_semantics() description strings ────────────

    "perm.sem.desc.l0": "Confirm everything: ask at every step (including read-only actions)",
    "perm.sem.desc.l1": "Ask for dangerous actions: high-risk pauses, low-risk auto-allowed",
    "perm.sem.desc.l2": (
        "Ask for irreversible actions only:"
        " uses capability manifest reversible field; reversible actions auto-allowed"
    ),
    "perm.sem.desc.l3": (
        "Auto-approve same-type actions after first approval this session"
        " (equivalent to ACCEPT_EDITS extended to all action categories)"
    ),
    "perm.sem.desc.l4": "Fully autonomous: all tools auto-allowed, HARD RULES still enforced",
    "perm.sem.desc.unknown": "Unknown trust level {level}, falling back to confirm",

    # ── trust_dial.py: _LEVEL_RELAXED_DESCRIPTION ────────────────────────────

    "perm.relaxed.l0": "confirmation of all actions (including read-only)",
    "perm.relaxed.l1": "confirmation of dangerous actions",
    "perm.relaxed.l2": "confirmation of irreversible actions",
    "perm.relaxed.l3": "session-level approval cache for same-type actions",
    "perm.relaxed.l4": "full autonomy (all tools auto-allowed)",

    # ── trust_dial.py: escalation_warning() f-strings ────────────────────────

    "perm.escalation.to_l4": (
        "⚠ You are switching to \"{to_label}\" mode."
        " This relaxes \"{from_desc}\" protection:"
        " all tool calls will execute automatically without step-by-step confirmation."
        " HARD RULES (dangerous commands, system paths, secret detection)"
        " are still enforced and cannot be bypassed."
        " If in doubt, stay at your current level."
    ),
    "perm.escalation.generic": (
        "⚠ You are relaxing the \"{from_desc}\" confirmation requirement,"
        " switching to \"{to_label}\"."
        " This means more actions will execute automatically with fewer interruptions."
        " HARD RULES still enforce dangerous actions,"
        " but lower confirmation frequency means mistakes may execute before being caught."
        " This setting takes effect for the current session."
    ),

    # ── approval.py: Decision.reason strings ─────────────────────────────────

    "approval.reason.auto": "AUTO level — auto-approved",
    "approval.reason.observe": "OBSERVE level: observe-only, side-effects not executed",
    "approval.reason.session_cached": "session-approved",
    "approval.reason.timeout": "approval timed out, defaulting to deny",
    "approval.reason.session_cancelled": "session terminated",

    # ── approval.py: tool error / rejection strings ───────────────────────────

    "approval.err.no_gate": (
        "Error: this tool requires user approval but no approval context is available,"
        " denying by default."
    ),
    "approval.err.async_path": (
        "Error: sync tool wrapper received an async call path — this is an internal error."
    ),
    "approval.err.in_loop": (
        "Error: sync tool cannot await approval inside an event loop;"
        " use the async version instead."
    ),
    "approval.err.denied": (
        "User denied this action ({reason})."
        " Please try a different approach or explain to the user why it is needed."
    ),
    "approval.err.denied_no_reason": "No reason provided",
}

ZH: dict[str, str] = {
    # ── trust_dial.py: _HUMAN_LABELS ─────────────────────────────────────────

    "perm.label.l0": "每一步都问我",
    "perm.label.l1": "只有危险操作才问",
    "perm.label.l2": "只有不可逆操作才问",
    "perm.label.l3": "同类操作批准后本会话放行",
    "perm.label.l4": "全自治（HARD RULES 仍拦）",

    # ── trust_dial.py: _DESCRIPTIONS ─────────────────────────────────────────

    "perm.desc.l0": (
        "最保守模式。每一个工具调用都会暂停等你确认，包括只读操作。"
        "适合初次使用或对任务完全不确定时。"
    ),
    "perm.desc.l1": (
        "只对高风险操作（删除文件、执行 shell 命令、网络请求等）暂停等确认；"
        "低风险操作（读取文件、列目录）自动放行。"
    ),
    "perm.desc.l2": (
        "只对不可逆操作暂停等确认（依赖 P2 能力 manifest 的 reversible 字段）；"
        "可撤销操作自动放行。"
        "注意：reversible 信息来自能力声明，声明不准确时保护力下降。"
    ),
    "perm.desc.l3": (
        "同一类操作在本次会话内批准一次后自动放行（等同于 ACCEPT_EDITS 扩展到所有类别）；"
        "新类操作首次仍需确认。会话结束后缓存清零。"
    ),
    "perm.desc.l4": (
        "全自治模式：所有工具调用自动放行，等同于旧 /yolo。"
        "HARD RULES（系统路径、危险 shell 命令、secret 检测）仍然强制拦截，永不绕过。"
        "TUI 头部显示红色警示灯。"
    ),

    # ── trust_dial.py: to_approval_semantics() description strings ────────────

    "perm.sem.desc.l0": "全量确认：每步都问（含只读操作）",
    "perm.sem.desc.l1": "危险才问：高风险操作暂停，低风险自动放行",
    "perm.sem.desc.l2": (
        "不可逆才问：依赖 capability manifest reversible 字段；可逆操作自动放行"
    ),
    "perm.sem.desc.l3": (
        "同类批过后本会话放行（等同于 ACCEPT_EDITS 扩展到所有操作类别）"
    ),
    "perm.sem.desc.l4": "全自治：所有工具自动放行，HARD RULES 仍强制拦截",
    "perm.sem.desc.unknown": "未知档位 {level}，降级 confirm",

    # ── trust_dial.py: _LEVEL_RELAXED_DESCRIPTION ────────────────────────────

    "perm.relaxed.l0": "所有操作（含只读）的逐步确认",
    "perm.relaxed.l1": "危险操作的确认",
    "perm.relaxed.l2": "不可逆操作的确认",
    "perm.relaxed.l3": "同类操作的会话级批准缓存",
    "perm.relaxed.l4": "全自治（所有工具自动放行）",

    # ── trust_dial.py: escalation_warning() f-strings ────────────────────────

    "perm.escalation.to_l4": (
        "⚠ 你正在切换到「{to_label}」模式。"
        "这意味着放宽了「{from_desc}」的保护，"
        "所有工具调用将自动执行，不再逐步确认。"
        "HARD RULES（危险命令、系统路径、secret 检测）仍然强制拦截，无法绕过。"
        "如有任何疑虑，建议保持当前档位。"
    ),
    "perm.escalation.generic": (
        "⚠ 你正在放宽「{from_desc}」的确认要求，切换到「{to_label}」。"
        "这意味着更多操作将自动执行，减少中断。"
        "HARD RULES 仍然强制拦截危险操作，但确认频率降低意味着错误操作被发现前可能已执行。"
        "确认后该设置在本会话内生效。"
    ),

    # ── approval.py: Decision.reason strings ─────────────────────────────────

    "approval.reason.auto": "AUTO 档放手",
    "approval.reason.observe": "OBSERVE 档:只看不执行副作用",
    "approval.reason.session_cached": "session 已批准",
    "approval.reason.timeout": "审批超时,默认拒绝",
    "approval.reason.session_cancelled": "session 终止",

    # ── approval.py: tool error / rejection strings ───────────────────────────

    "approval.err.no_gate": (
        "错误:该工具需要用户审批但当前没有审批上下文,默认拒绝。"
    ),
    "approval.err.async_path": (
        "错误:同步工具包装器收到了异步调用路径,这是内部错误。"
    ),
    "approval.err.in_loop": (
        "错误:同步工具不能在事件循环中等待审批,请改用异步版本。"
    ),
    "approval.err.denied": (
        "用户拒绝执行该操作({reason})。"
        "请尝试其他做法或向用户解释为什么需要它。"
    ),
    "approval.err.denied_no_reason": "未提供原因",
}
