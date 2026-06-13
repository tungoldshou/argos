"""自主程度(autonomy)分级 + 预授权 + verify 联动(任务:让 Argos 在可验证的活上
无人值守地自己干完,只在不可验证或不可撤销时才停下来问人)。

Zone 语义:
- GREEN:可验证 + 可撤销(绝大多数编码动作)→ 静默继续,直到 verify passed
- YELLOW:可验证但昂贵/慢,或目标模糊需先澄清 → 任务开头收一轮澄清(复用 plan mode)
- RED:命中 hard_rules(破坏性/系统路径/密钥/越界),或动作不可撤销,或 verdict=unverifiable
  的「声称完成」 → 复用 ApprovalGate 请求审批

关键护城河(铁律):
- hard_rule deny 不可被 preauth 降级(产品护城河)
- verdict=unverifiable + 有声明 verify_cmd → 升级 RED(不假装 passed);verify_cmd=None
  → 走既有的 NO_TEST 路径(不升级)
- 不削弱 verify_gate / hard_rules(只读 Verdict 和 evaluator 决策)
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping

from argos.approval import ApprovalLevel

if TYPE_CHECKING:
    from argos.core.types import Verdict
    from argos.permissions.config import PermissionsConfig


class Zone(enum.Enum):
    """自主程度三色。"""

    GREEN = "green"    # 可验证 + 可撤销 → 静默继续
    YELLOW = "yellow"  # 慢/贵/模糊 → 任务开头收澄清(plan mode)
    RED = "red"        # 危险/不可撤销/不可验证 → 走 ApprovalGate 问人


@dataclass(frozen=True, slots=True)
class AutonomyPolicy:
    """自主策略(可从 PermissionsConfig.preauth 派生 / 默认值)。

    - clarification_required:True=YELLOW 路径走 plan mode 收澄清;False=跳过(让用户自己看)
    - preauth:rule_name → bool 预授权映射(autonomy.classify 据它降级 soft_ask)
    - slow_actions:被认作"慢/贵"的动作子集(reversible=True 时仍 → YELLOW)
    """

    clarification_required: bool = True
    preauth: Mapping[str, bool] = field(default_factory=dict)
    slow_actions: frozenset = field(
        default_factory=lambda: frozenset({"test", "build", "deploy", "publish", "release"})
    )

    @staticmethod
    def from_permissions_config(config: "PermissionsConfig | None") -> "AutonomyPolicy":
        """从 PermissionsConfig 派生 AutonomyPolicy(preauth 透传)。空 config → 默认。"""
        if config is None:
            return AutonomyPolicy()
        return AutonomyPolicy(preauth=dict(config.preauth or {}))


# 慢动作名字的子串匹配表(classify 用 startswith/包含判定)。
def _is_slow_action(action: str, slow: frozenset) -> bool:
    a = (action or "").lower()
    return any(s in a for s in slow)


def _evaluator_decision(
    action: str,
    args: dict,
    config: "PermissionsConfig",
) -> tuple[str, str]:
    """调 evaluator.evaluate 拿 DecisionMeta(decision ∈ {approve, deny, ask}, trigger)。

    evaluator 出错(spec D15 锁)→ 兜底 ask(保守,宁多问不少问)。
    不可达路径(evaluator 必有返回)→ ask 兜底。
    """
    try:
        from argos.permissions.evaluator import evaluate
        meta = evaluate(
            action, args,
            gate_level=ApprovalLevel.CONFIRM,
            config=config,
            workspace=None,
        )
        return (meta.decision, meta.trigger)
    except Exception:  # noqa: BLE001 — autonomy 绝不让 evaluator 错误拖崩
        return ("ask", "evaluator_error")


def classify(
    *,
    action: str,
    args: dict,
    reversible: bool,
    verdict: "Verdict | None",
    config: "PermissionsConfig",
    policy: AutonomyPolicy,
    slow_action: bool | None = None,
    goal_vague: bool | None = None,
) -> tuple[Zone, str]:
    """按 (action, reversible, verdict, ...) 推 Zone + 理由。

    优先级(短路):
    1. irreversible → RED
    2. evaluator hard-rule / system-path / secret 命中 → RED
    3. verdict=unverifiable(由 on_unverifiable_completion 单独处理;这里只接 passed/failed)
    4. evaluator soft_ask + preauth 命中 → GREEN
    5. evaluator soft_ask / per-tool ask / default ask → RED
    6. slow_action / goal_vague → YELLOW
    7. 其他(evaluator approve + reversible=True + verdict passed) → GREEN
    """
    # 1. 不可撤销必升级(语义边界,不是规则层)
    if not reversible:
        return (Zone.RED, "动作不可撤销(reversible=False),需用户确认")

    # 2. evaluator 决策
    decision, trigger = _evaluator_decision(action, args or {}, config)

    # 硬规则 / 系统路径 / secret 触发 → RED,即便 preauth 也不降级(铁律:不削弱 hard_rules)
    if decision == "deny":
        return (Zone.RED, f"硬规则触发:{trigger} — 不可降级")
    if decision == "ask" and (
        trigger.startswith("hard_rule:")
        or trigger.startswith("secret:")
    ):
        return (Zone.RED, f"硬规则触发:{trigger} — 不可降级")

    # 3. verdict=unverifiable 应该被调用方在收尾阶段用 on_unverifiable_completion 拦截,
    #    不会到这一步(收尾时已经处理)。如果传到了 classify(unverifiable + reversible=True),
    #    仍按 RED 处理(不假装通过)。
    if verdict is not None and getattr(verdict, "status", None) == "unverifiable":
        return (Zone.RED, f"verdict=unverifiable:{trigger} — 不假装通过")

    # 3b. verdict=failed → RED(走 bounce/escalate)
    if verdict is not None and getattr(verdict, "status", None) == "failed":
        return (Zone.RED, f"verdict=failed:{trigger} — 走升级路径")

    # 4. soft_ask + preauth 命中 → GREEN
    if decision == "ask" and policy.preauth.get(trigger) is True:
        return (Zone.GREEN, f"预授权降级:{trigger} → 自动")

    # 5. soft_ask / per-tool ask / default ask(无 preauth)→ RED
    if decision == "ask":
        return (Zone.RED, f"需用户审批:{trigger}")

    # 6. slow_action / goal_vague → YELLOW
    eff_slow = slow_action if slow_action is not None else _is_slow_action(action, policy.slow_actions)
    if eff_slow:
        return (Zone.YELLOW, f"慢/贵动作:{action} — 任务开头走 plan mode 收澄清")
    if goal_vague:
        return (Zone.YELLOW, "目标模糊 — 任务开头走 plan mode 收澄清")

    # 7. 默认 GREEN
    return (Zone.GREEN, f"evaluator approve ({trigger}) + 可验证可撤销")


def on_unverifiable_completion(
    *,
    verify_cmd: str | None,
    verdict: "Verdict | None",
    policy: AutonomyPolicy,  # noqa: ARG001 — 预留扩展(后续按 policy 决定 escalate vs ask)
) -> tuple[Zone, str] | None:
    """「声称完成」+ verdict=unverifiable 时的升级处理(任务:不假装 passed)。

    返回:
    - (Zone.RED, reason) → 调用方应走 ApprovalGate 请求审批
    - None → 不升级(让调用方走 NO_TEST 旧路径,verify_cmd=None 的合法场景)

    关键护城河:有声明 verify_cmd 但跑出 unverifiable(篡改/超时)→ 升级 RED。
    """
    if verdict is None or getattr(verdict, "status", None) != "unverifiable":
        return None
    if not verify_cmd:
        # 没声明 verify_cmd → 走既有 NO_TEST 路径(loop.is_honest_completion 兜底),
        # 不升级。模型没声明 verify 是合理路径(unverifiable 仍 NO_TEST 完成)。
        return None
    # 有声明 + 跑出 unverifiable → 升级 RED(篡改/超时/不在白名单都属此类)。
    detail = getattr(verdict, "detail", "") or ""
    return (
        Zone.RED,
        f"verdict=unverifiable 且已声明 verify_cmd={verify_cmd!r} — {detail[:120]} — 升级问人",
    )
