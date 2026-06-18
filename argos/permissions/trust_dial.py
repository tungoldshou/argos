"""Trust Dial L0-L4 核心 —— 替代 /yolo 黑话的人话信任拨盘。

设计来源：docs/argos-v6-design.md §6（信任面）。

**红线约束**（来自设计评审团）：
- HARD RULES 永不被拨盘降级：任何档位下 hard_rules_immune() 均返回 True。
- 升档(拨盘数值变大)必须返回非空警示文案；降档返回空串。
- 拨盘建议(suggest_escalation)绝不静默自动升档，只返回带警示的建议对象。
- 纯核心模型：不依赖 TUI / approval.py 实例；approval.py 的 ApprovalLevel 只作
  映射目标，读值不修改。

集成依赖注记：approval.py ApprovalLevel 枚举值（v 字段）用于 to_approval_semantics 映射，
只读取枚举成员，不修改该文件。
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# TrustLevel 枚举
# ─────────────────────────────────────────────────────────────────────────────

class TrustLevel(enum.IntEnum):
    """信任拨盘五档，数值越大自治程度越高。

    不要直接用数字比较 —— 用枚举成员名，防止将来插档。
    """
    L0_EVERY_STEP     = 0   # 每一步都问我
    L1_DANGEROUS_ONLY = 1   # 只有危险操作才问
    L2_IRREVERSIBLE_ONLY = 2   # 只有不可逆操作才问
    L3_SESSION_TRUSTED = 3   # 同类操作批准过后本次会话放行
    L4_AUTONOMOUS     = 4   # 全自治（HARD RULES 仍拦）

    @property
    def label_human(self) -> str:
        """人话标签（TUI 显示用）。"""
        return _HUMAN_LABELS[self]

    @property
    def description(self) -> str:
        """档位完整说明（TUI 设置页/帮助文本用）。"""
        return _DESCRIPTIONS[self]


# 人话标签表（独立字典，枚举定义后填充）
_HUMAN_LABELS: dict[TrustLevel, str] = {
    TrustLevel.L0_EVERY_STEP:      "每一步都问我",
    TrustLevel.L1_DANGEROUS_ONLY:  "只有危险操作才问",
    TrustLevel.L2_IRREVERSIBLE_ONLY: "只有不可逆操作才问",
    TrustLevel.L3_SESSION_TRUSTED: "同类操作批准后本会话放行",
    TrustLevel.L4_AUTONOMOUS:      "全自治（HARD RULES 仍拦）",
}

_DESCRIPTIONS: dict[TrustLevel, str] = {
    TrustLevel.L0_EVERY_STEP: (
        "最保守模式。每一个工具调用都会暂停等你确认，包括只读操作。"
        "适合初次使用或对任务完全不确定时。"
    ),
    TrustLevel.L1_DANGEROUS_ONLY: (
        "只对高风险操作（删除文件、执行 shell 命令、网络请求等）暂停等确认；"
        "低风险操作（读取文件、列目录）自动放行。"
    ),
    TrustLevel.L2_IRREVERSIBLE_ONLY: (
        "只对不可逆操作暂停等确认（依赖 P2 能力 manifest 的 reversible 字段）；"
        "可撤销操作自动放行。"
        "注意：reversible 信息来自能力声明，声明不准确时保护力下降。"
    ),
    TrustLevel.L3_SESSION_TRUSTED: (
        "同一类操作在本次会话内批准一次后自动放行（等同于 ACCEPT_EDITS 扩展到所有类别）；"
        "新类操作首次仍需确认。会话结束后缓存清零。"
    ),
    TrustLevel.L4_AUTONOMOUS: (
        "全自治模式：所有工具调用自动放行，等同于旧 /yolo。"
        "HARD RULES（系统路径、危险 shell 命令、secret 检测）仍然强制拦截，永不绕过。"
        "TUI 头部显示红色警示灯。"
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# to_approval_semantics：映射到 ApprovalLevel
# ─────────────────────────────────────────────────────────────────────────────

# ApprovalLevel 枚举值字符串常量（来自 approval.py，只读不改）
_AL_OBSERVE      = "observe"        # ApprovalLevel.OBSERVE
_AL_CONFIRM      = "confirm"        # ApprovalLevel.CONFIRM
_AL_ACCEPT_EDITS = "accept_edits"   # ApprovalLevel.ACCEPT_EDITS
_AL_AUTO         = "auto"           # ApprovalLevel.AUTO


def to_approval_semantics(level: TrustLevel) -> dict[str, Any]:
    """将 TrustLevel 映射到现有审批语义字典。

    返回字典字段说明：
    - ``approval_level``（str）：对应 ApprovalLevel 枚举的 value 字符串，
      由 ApprovalGate.set_level 使用（集成阶段接线，本模块不直接调用 gate）。
    - ``description``（str）：人话说明，供 TUI 提示和审批弹窗使用。
    - ``reversible_check``（bool）：是否需要 reversible 字段过滤（L2 特有依赖）。
    - ``hard_rules_immune``（bool）：永远为 True，契约断言点
      ——任何档位映射结果都不含绕过 hard rules 的字段。

    **契约不变量**：所有档位的 ``hard_rules_immune`` 字段必须为 True。
    任何调用方都可以断言 ``to_approval_semantics(lvl)["hard_rules_immune"] is True``。
    """
    _base: dict[str, Any] = {
        "hard_rules_immune": True,  # 不变量：HARD RULES 永不降级，任何档位均 True
    }

    if level is TrustLevel.L0_EVERY_STEP:
        return {
            **_base,
            "approval_level": _AL_CONFIRM,
            "description": "全量确认：每步都问（含只读操作）",
            "reversible_check": False,
            # L0 额外语义：连只读操作也要问，实现时 gate 应忽略 risk level 短路
            "ask_readonly": True,
        }

    if level is TrustLevel.L1_DANGEROUS_ONLY:
        return {
            **_base,
            "approval_level": _AL_CONFIRM,
            "description": "危险才问：高风险操作暂停，低风险自动放行",
            "reversible_check": False,
            "ask_readonly": False,
            # low_risk_auto：兑现"低风险自动放行"——evaluator 默认决策处对 registry risk=low 的动作
            # (web_search/web_extract/read_file/search_files 等只读)自动放行,不弹卡;中/高危照旧 ask。
            # 仅 L1 置 True;普通 CONFIRM(未经 trust dial)不置,行为不变(2026-06-18 修)。
            "low_risk_auto": True,
        }

    if level is TrustLevel.L2_IRREVERSIBLE_ONLY:
        return {
            **_base,
            "approval_level": _AL_CONFIRM,
            "description": "不可逆才问：依赖 capability manifest reversible 字段；可逆操作自动放行",
            # reversible_check=True → gate._evaluate 传入 reversible_lookup。
            # gate.set_reversible_lookup() 由 app_factory 从 CapabilityRegistry 构造注入；
            # 未注入时 evaluator 保守退化：所有动作均 ask（fail-closed，不假装放行）。
            "reversible_check": True,
            "ask_readonly": False,
        }

    if level is TrustLevel.L3_SESSION_TRUSTED:
        return {
            **_base,
            "approval_level": _AL_ACCEPT_EDITS,
            "description": "同类批过后本会话放行（等同于 ACCEPT_EDITS 扩展到所有操作类别）",
            "reversible_check": False,
            "ask_readonly": False,
        }

    if level is TrustLevel.L4_AUTONOMOUS:
        return {
            **_base,
            "approval_level": _AL_AUTO,
            "description": "全自治：所有工具自动放行，HARD RULES 仍强制拦截",
            "reversible_check": False,
            "ask_readonly": False,
            # 警示标志：TUI 应在头部显示红色 ⏻ 灯
            "show_yolo_indicator": True,
        }

    # 防御性兜底（穷举 IntEnum 理论上不会到这里）
    return {**_base, "approval_level": _AL_CONFIRM, "description": f"未知档位 {level}，降级 confirm",
            "reversible_check": False, "ask_readonly": False}


# ─────────────────────────────────────────────────────────────────────────────
# HARD RULES 永不降级 —— 契约函数
# ─────────────────────────────────────────────────────────────────────────────

def hard_rules_immune() -> bool:
    """契约函数：HARD RULES 在任何 TrustLevel 下均免于降级。

    永远返回 True。调用方不得缓存"false"分支——该函数不存在 false 返回值。
    签名保留 -> bool 便于断言：``assert hard_rules_immune()``。

    HARD RULES 包括（但不限于）：
    - 危险 shell 命令（rm -rf /、dd if=、mkfs 等，见 hard_rules.py）
    - 系统路径写保护（/System、/usr、~/.ssh 等）
    - secret pattern 检测并提示（D8 锁）
    """
    return True


# ─────────────────────────────────────────────────────────────────────────────
# escalation_warning：升档人话警示
# ─────────────────────────────────────────────────────────────────────────────

# 各档位涉及的"放宽了什么"的人话描述（供警示文案组装用）
_LEVEL_RELAXED_DESCRIPTION: dict[TrustLevel, str] = {
    TrustLevel.L0_EVERY_STEP:      "所有操作（含只读）的逐步确认",
    TrustLevel.L1_DANGEROUS_ONLY:  "危险操作的确认",
    TrustLevel.L2_IRREVERSIBLE_ONLY: "不可逆操作的确认",
    TrustLevel.L3_SESSION_TRUSTED: "同类操作的会话级批准缓存",
    TrustLevel.L4_AUTONOMOUS:      "全自治（所有工具自动放行）",
}


def escalation_warning(from_level: TrustLevel, to_level: TrustLevel) -> str:
    """返回升档操作的人话警示文案；降档返回空串。

    升档（to_level 数值 > from_level 数值）：返回非空警示，说明放宽了什么权限，
    以及这意味着什么风险。

    降档（to_level 数值 <= from_level 数值）：返回空串（降档收紧权限，无需警示）。

    设计红线（§6）：
    - 升档警示必须非空 —— TUI 必须展示它，不得静默。
    - HARD RULES 在任何档位仍然生效，警示文案应诚实说明这一点。
    """
    if int(to_level) <= int(from_level):
        return ""  # 降档：收紧权限，无需警示

    # 升档：构造警示文案
    from_desc = _LEVEL_RELAXED_DESCRIPTION[from_level]
    to_label = to_level.label_human

    # 特殊情况：升到 L4（全自治）需要最强警示
    if to_level is TrustLevel.L4_AUTONOMOUS:
        return (
            f"⚠ 你正在切换到「{to_label}」模式。"
            f"这意味着放宽了「{from_desc}」的保护，"
            f"所有工具调用将自动执行，不再逐步确认。"
            f"HARD RULES（危险命令、系统路径、secret 检测）仍然强制拦截，无法绕过。"
            f"如有任何疑虑，建议保持当前档位。"
        )

    return (
        f"⚠ 你正在放宽「{from_desc}」的确认要求，切换到「{to_label}」。"
        f"这意味着更多操作将自动执行，减少中断。"
        f"HARD RULES 仍然强制拦截危险操作，但确认频率降低意味着错误操作被发现前可能已执行。"
        f"确认后该设置在本会话内生效。"
    )


# ─────────────────────────────────────────────────────────────────────────────
# EscalationSuggestion —— 建议对象（永远带警示文案）
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class EscalationSuggestion:
    """拨盘升档建议（由 suggest_escalation 返回）。

    **红线**（设计 §6）：该对象只是建议，永不自动升档；
    必须由用户显式确认才能生效。``warning`` 字段不得为空串。
    """
    from_level: TrustLevel
    suggested_level: TrustLevel
    warning: str        # 永不为空 —— TUI 必须展示
    reason: str         # 触发理由（"同类操作已连续允许 N 次"）
    trigger_count: int  # 触发计数（供 TUI 渲染"已允许 N 次"）

    def __post_init__(self) -> None:
        # 契约断言：warning 不得为空（防御性校验，正常路径不会触发）
        if not self.warning:
            raise ValueError("EscalationSuggestion.warning 不得为空（设计 §6 红线）")


# ─────────────────────────────────────────────────────────────────────────────
# suggest_escalation：基于历史的升档建议（绝不静默自动升档）
# ─────────────────────────────────────────────────────────────────────────────

# 连续允许同类操作 N 次后触发建议
_SUGGEST_THRESHOLD = 5


def suggest_escalation(
    history: list[dict[str, Any]],
    *,
    current_level: TrustLevel = TrustLevel.L0_EVERY_STEP,
    threshold: int = _SUGGEST_THRESHOLD,
) -> EscalationSuggestion | None:
    """分析操作历史，若同类操作连续 ≥ threshold 次被允许，返回升档建议；否则返回 None。

    Args:
        history: 操作历史列表，每项为 dict，含字段：
            - ``action``（str）：工具/能力名称。
            - ``decision``（str）：``"approved"`` / ``"denied"`` / ``"asked"``。
            - ``kind``（可选 str）：操作分类（无则用 action 本身）。
        current_level: 当前 TrustLevel，低于 L4 时才触发建议。
        threshold: 连续允许次数阈值（默认 5）。

    Returns:
        EscalationSuggestion（永远带非空 warning）或 None。

    **红线**：
    - 本函数只返回建议，绝不执行升档。
    - 返回的建议对象 warning 字段必须非空（由 EscalationSuggestion.__post_init__ 断言）。
    - 建议等级不得超过 L3_SESSION_TRUSTED（不主动建议 L4 全自治）。
    """
    if not history:
        return None

    # 已是最高档（L4）或次高档（L3）→ 无需建议
    if current_level >= TrustLevel.L3_SESSION_TRUSTED:
        return None

    # 统计各类操作的连续允许计数
    # "同类" = history 中 kind 字段相同（无 kind 则用 action）
    consecutive_counts: dict[str, int] = {}
    for entry in history:
        if not isinstance(entry, dict):
            continue
        decision = entry.get("decision", "")
        kind = entry.get("kind") or entry.get("action", "")
        if not kind:
            continue
        if decision == "approved":
            consecutive_counts[kind] = consecutive_counts.get(kind, 0) + 1
        # 被拒绝则重置（只算连续）
        elif decision == "denied":
            consecutive_counts[kind] = 0

    # 找最高连续允许计数
    if not consecutive_counts:
        return None

    top_kind = max(consecutive_counts, key=lambda k: consecutive_counts[k])
    top_count = consecutive_counts[top_kind]

    if top_count < threshold:
        return None

    # 建议升到下一档（不超过 L3）
    next_level_value = min(int(current_level) + 1, int(TrustLevel.L3_SESSION_TRUSTED))
    next_level = TrustLevel(next_level_value)

    warning = escalation_warning(current_level, next_level)
    # escalation_warning 对升档必返非空；此处双保险
    if not warning:
        warning = (
            f"⚠ 你正在考虑从「{current_level.label_human}」升级到「{next_level.label_human}」。"
            f"确认操作将减少中断，但也意味着减少了人工确认机会。"
        )

    return EscalationSuggestion(
        from_level=current_level,
        suggested_level=next_level,
        warning=warning,
        reason=f"操作类别「{top_kind}」已连续被允许 {top_count} 次（阈值 {threshold}）",
        trigger_count=top_count,
    )
