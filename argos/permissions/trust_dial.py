"""Trust Dial L0-L4 核心 —— 替代 /yolo 黑话的人话信任拨盘。

设计来源：docs/argos-v6-design.md §6（信任面）。

**红线约束**（来自设计评审团）：
- HARD RULES 永不被拨盘降级：任何档位下 hard_rules_immune() 均返回 True。
- 升档(拨盘数值变大)必须返回非空警示文案；降档返回空串。
- 纯核心模型：不依赖 TUI / approval.py 实例；approval.py 的 ApprovalLevel 只作
  映射目标，读值不修改。

2026-06-20 重设(Claude Code/Codex 风):用户面向收敛为 3 个模式 —— Cautious(默认,=L1)/
Trusted(=L3)/Autonomous(=L4),bare `/trust` 在三者间循环;L0 隐藏为 /trust paranoid,
L2 弃用(不可逆保护并入 hard rule)。内部仍保留 L0-L4 枚举与 ApprovalLevel 映射。
历史的 suggest_escalation/EscalationSuggestion(无生产调用方)已删除。

集成依赖注记：approval.py ApprovalLevel 枚举值（v 字段）用于 to_approval_semantics 映射，
只读取枚举成员，不修改该文件。
"""
from __future__ import annotations

import enum
from typing import Any

from argos.i18n import t


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
        return t(_HUMAN_LABELS[self])

    @property
    def description(self) -> str:
        """档位完整说明（TUI 设置页/帮助文本用）。"""
        return t(_DESCRIPTIONS[self])

    @property
    def mode_name(self) -> str:
        """3-mode 用户面向名(2026-06-20 重设,Claude Code/Codex 风):
        L1→Cautious / L3→Trusted / L4→Autonomous 是三个可见档;L0→Paranoid 隐藏档
        (/trust paranoid);L2→Irreversible-only 已弃用(语义由 hard rule 覆盖)。"""
        return _MODE_NAMES[self]


# ─────────────────────────────────────────────────────────────────────────────
# 3-mode 用户面向层(L1/L3/L4 = 三个可见模式;L0 隐藏;L2 弃用)
# ─────────────────────────────────────────────────────────────────────────────

_MODE_NAMES: dict[TrustLevel, str] = {
    TrustLevel.L0_EVERY_STEP:        "Paranoid",            # 隐藏:/trust paranoid
    TrustLevel.L1_DANGEROUS_ONLY:    "Cautious",            # 默认
    TrustLevel.L2_IRREVERSIBLE_ONLY: "Irreversible-only",   # 弃用(语义并入 hard rule)
    TrustLevel.L3_SESSION_TRUSTED:   "Trusted",
    TrustLevel.L4_AUTONOMOUS:        "Autonomous",
}

# 三个可见模式的循环顺序(bare `/trust` 依次切换;Claude Code Shift+Tab 式)。
# L0(Paranoid)与 L2(弃用)不在环上 —— 只能显式 /trust paranoid / 隐藏别名进入。
TRUST_CYCLE: tuple[TrustLevel, ...] = (
    TrustLevel.L1_DANGEROUS_ONLY,
    TrustLevel.L3_SESSION_TRUSTED,
    TrustLevel.L4_AUTONOMOUS,
)


def next_in_cycle(level: TrustLevel) -> TrustLevel:
    """返回循环中的下一个可见模式(Cautious→Trusted→Autonomous→Cautious)。
    不在环上的档(L0 Paranoid / L2 弃用)先归一到环:L0→Cautious 起步,L2→Trusted。"""
    if level not in TRUST_CYCLE:
        # 归一:退出隐藏/弃用档时进入最接近的可见模式。
        if level is TrustLevel.L0_EVERY_STEP:
            return TrustLevel.L1_DANGEROUS_ONLY
        return TrustLevel.L3_SESSION_TRUSTED
    idx = TRUST_CYCLE.index(level)
    return TRUST_CYCLE[(idx + 1) % len(TRUST_CYCLE)]


# 人话标签表（独立字典，枚举定义后填充）
_HUMAN_LABELS: dict[TrustLevel, str] = {
    TrustLevel.L0_EVERY_STEP:        "perm.label.l0",
    TrustLevel.L1_DANGEROUS_ONLY:    "perm.label.l1",
    TrustLevel.L2_IRREVERSIBLE_ONLY: "perm.label.l2",
    TrustLevel.L3_SESSION_TRUSTED:   "perm.label.l3",
    TrustLevel.L4_AUTONOMOUS:        "perm.label.l4",
}

_DESCRIPTIONS: dict[TrustLevel, str] = {
    TrustLevel.L0_EVERY_STEP:        "perm.desc.l0",
    TrustLevel.L1_DANGEROUS_ONLY:    "perm.desc.l1",
    TrustLevel.L2_IRREVERSIBLE_ONLY: "perm.desc.l2",
    TrustLevel.L3_SESSION_TRUSTED:   "perm.desc.l3",
    TrustLevel.L4_AUTONOMOUS:        "perm.desc.l4",
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
            "description": t("perm.sem.desc.l0"),
            "reversible_check": False,
            # L0 额外语义：连只读操作也要问，实现时 gate 应忽略 risk level 短路
            "ask_readonly": True,
        }

    if level is TrustLevel.L1_DANGEROUS_ONLY:
        return {
            **_base,
            "approval_level": _AL_CONFIRM,
            "description": t("perm.sem.desc.l1"),
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
            "description": t("perm.sem.desc.l2"),
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
            "description": t("perm.sem.desc.l3"),
            "reversible_check": False,
            "ask_readonly": False,
        }

    if level is TrustLevel.L4_AUTONOMOUS:
        return {
            **_base,
            "approval_level": _AL_AUTO,
            "description": t("perm.sem.desc.l4"),
            "reversible_check": False,
            "ask_readonly": False,
            # 警示标志：TUI 应在头部显示红色 ⏻ 灯
            "show_yolo_indicator": True,
        }

    # 防御性兜底（穷举 IntEnum 理论上不会到这里）
    return {**_base, "approval_level": _AL_CONFIRM,
            "description": t("perm.sem.desc.unknown", level=level),
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
    TrustLevel.L0_EVERY_STEP:        "perm.relaxed.l0",
    TrustLevel.L1_DANGEROUS_ONLY:    "perm.relaxed.l1",
    TrustLevel.L2_IRREVERSIBLE_ONLY: "perm.relaxed.l2",
    TrustLevel.L3_SESSION_TRUSTED:   "perm.relaxed.l3",
    TrustLevel.L4_AUTONOMOUS:        "perm.relaxed.l4",
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
    from_desc = t(_LEVEL_RELAXED_DESCRIPTION[from_level])
    to_label = to_level.label_human

    # 特殊情况：升到 L4（全自治）需要最强警示
    if to_level is TrustLevel.L4_AUTONOMOUS:
        return t("perm.escalation.to_l4", to_label=to_label, from_desc=from_desc)

    return t("perm.escalation.generic", from_desc=from_desc, to_label=to_label)
