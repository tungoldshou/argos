"""Evaluator 串联 hard → soft → level,带 trigger 标签(spec §2.5, D15 锁)。"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TYPE_CHECKING

from argos.approval import ApprovalLevel
from argos.permissions.config import PermissionsConfig
from argos.permissions.hard_rules import (
    HARD_PATH_DENYLIST,
    check_hard_shell,
    check_computer_hard_rules,
    is_argos_own_env,
    is_env_file,
    is_env_template,
    is_system_path,
    is_workspace_path,
)
from argos.permissions.secrets import find_secret_in_content

if TYPE_CHECKING:
    pass


DecisionType = Literal["approve", "deny", "ask"]


@dataclass(frozen=True, slots=True)
class DecisionMeta:
    decision: DecisionType
    trigger: str
    reason: str = ""
    secret_pattern: str | None = None
    rule_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "trigger": self.trigger,
            "reason": self.reason,
            "secret_pattern": self.secret_pattern,
            "rule_name": self.rule_name,
        }


def _arg_str(args: dict[str, Any]) -> str:
    """工具参数 → 串(供 matcher 比对);cmd 优先 / command 次之 / path 次之 / 全 args repr 兜底。"""
    if not isinstance(args, dict):
        return str(args)
    for key in ("cmd", "command"):
        v = args.get(key)
        if isinstance(v, str):
            return v
    for key in ("path", "file", "filepath"):
        v = args.get(key)
        if isinstance(v, str):
            return v
    return repr(args)


def _gate_level_str(level: ApprovalLevel | str | None) -> str:
    if level is None:
        return "confirm"
    if isinstance(level, ApprovalLevel):
        return level.value
    return str(level)


def _check_hard_path_write(args: dict[str, Any], *, workspace: str | Path | None) -> DecisionMeta | None:
    """write_file / edit_file 的目标路径系统前缀命中 → deny。"""
    path = args.get("path") or args.get("file") or args.get("filepath")
    if not isinstance(path, str):
        return None
    # .env.example 永 allow
    if is_env_template(path):
        return None
    # ~/.argos/.env 是 Argos 自己的 config
    if is_argos_own_env(path):
        return None
    # 系统路径前缀命中 → deny
    if is_system_path(path):
        # 找命中的 denylist prefix 作 trigger 显式度
        for prefix in HARD_PATH_DENYLIST:
            p_resolved = str(Path(path).expanduser().resolve())
            if p_resolved.startswith(prefix):
                return DecisionMeta(
                    decision="deny",
                    trigger=f"hard_rule:system_path:{prefix}",
                    reason=f"系统路径 {prefix}* 不可写",
                )
    return None


def evaluate(
    action: str,
    args: dict[str, Any],
    *,
    gate_level: ApprovalLevel | str,
    config: PermissionsConfig,
    workspace: str | Path | None = None,
    ask_readonly: bool = False,
    reversible_lookup: "Callable[[str], bool | None] | None" = None,
    low_risk_auto: bool = False,
    risk: str = "medium",
) -> DecisionMeta:
    """串联 hard → soft deny → soft allow → soft ask → per-tool → default(spec D15 锁)。

    - secret 命中不走 soft allow 短路(D8 锁):即便 allow 列表命中具体内容仍 ask。
    - hard rule 命中即返,不被任何软规则覆盖(D5 锁)。
    - ask_readonly=True(L0 语义):跳过"auto 放行"短路,即便低风险动作也升格为 ask。
      仅对评估路径末端的"approve"结果改为 ask;hard/soft deny/secret 路径不受影响。
    - reversible_lookup(L2 语义):Callable[[action], bool|None];True=可逆→放行(audit
      trigger="trust:L2 可逆放行");False/None=不可逆/未知→ ask(保守)。
      仅在评估末端无其他 hard/soft 规则命中时才作用;HARD RULES/secret 路径不受影响。
    """
    arg_str = _arg_str(args)

    # 1. Hard rules:shell 危险命令
    if action == "run_command":
        rule = check_hard_shell(arg_str)
        if rule is not None:
            return DecisionMeta(
                decision="deny",
                trigger=f"hard_rule:{rule}",
                rule_name=rule,
                reason=f"硬规则 {rule} 命中,自动拒",
            )

    # 1b. Hard rules:系统路径 / workspace 边界(写操作)
    if action in ("write_file", "edit_file"):
        meta = _check_hard_path_write(args, workspace=workspace)
        if meta is not None:
            return meta

    # 1e. Hard rules:computer.* 非开发者域(P6a §10)
    # type_text 文本命中金融/验证码模式 → 强制 ask(CONFIRM);
    # open_app  命中支付/银行词表     → 强制 ask(CONFIRM)。
    # 注意:这里返回 "ask"(而非 "deny")——目的是强制人工确认,不是彻底拒绝。
    # autonomy 层 + broker 层需把 trigger.startswith("hard_rule:computer_") 视为不可降级。
    if action.startswith("computer_"):
        computer_rule = check_computer_hard_rules(action, args)
        if computer_rule is not None:
            return DecisionMeta(
                decision="ask",
                trigger=f"hard_rule:{computer_rule}",
                rule_name=computer_rule,
                reason=(
                    f"计算机控制动作命中非开发者域硬规则 {computer_rule!r} —— "
                    "此类操作必须人在场确认,Trust Dial 任何档位下均不可降级。"
                ),
            )

    # 1c. Hard rules:.env 教学样例(永远 allow)→ 无动作,继续
    # 1d. Hard rules:secret pattern(D8 锁 flag-and-ask):write_file/edit_file 看新内容
    secret_name: str | None = None
    if action in ("write_file", "edit_file"):
        content = args.get("content")
        if isinstance(content, str):
            secret_name = find_secret_in_content(content)
        elif isinstance(content, dict):
            # edit_file 的 new_string 字段
            new_s = content.get("new_string") or content.get("content")
            if isinstance(new_s, str):
                secret_name = find_secret_in_content(new_s)

    # 2. Soft deny
    deny_entry = config.match_deny(action, arg_str)
    if deny_entry is not None:
        return DecisionMeta(
            decision="deny",
            trigger=f"soft_deny:{deny_entry.matcher}",
            rule_name=deny_entry.matcher,
            reason=f"软规则 deny 命中: {deny_entry.matcher}",
        )

    # 3. Soft allow(secret 命中时不短路,D8 锁)
    if secret_name is None:
        allow_entry = config.match_allow(action, arg_str)
        if allow_entry is not None:
            soft_allow_meta = DecisionMeta(
                decision="approve",
                trigger=f"soft_allow:{allow_entry.matcher}",
                rule_name=allow_entry.matcher,
                reason=f"软规则 allow 命中: {allow_entry.matcher}",
            )
            return _apply_trust_semantics(soft_allow_meta, action=action,
                                          ask_readonly=ask_readonly,
                                          reversible_lookup=reversible_lookup)

    # 3b. Secret 命中 → ask(D8 锁:在 soft ask 之前,即便 allow 命中也 ask)
    if secret_name is not None:
        return DecisionMeta(
            decision="ask",
            trigger=f"secret:{secret_name}",
            secret_pattern=secret_name,
            reason=f"⚠ Possible secret pattern matched: {secret_name} — did you mean to commit this?",
        )

    # 4. Soft ask
    ask_entry = config.match_ask(action, arg_str)
    if ask_entry is not None:
        return DecisionMeta(
            decision="ask",
            trigger=f"soft_ask:{ask_entry.matcher}",
            rule_name=ask_entry.matcher,
            reason=f"软规则 ask 命中: {ask_entry.matcher}",
        )

    # 5. Per-tool level override
    if action in config.tools:
        lvl = config.tools[action]
        if lvl == "auto":
            tool_meta = DecisionMeta(
                decision="approve",
                trigger=f"tool_level:{action}=auto",
                reason=f"per-tool {action} = auto",
            )
            return _apply_trust_semantics(tool_meta, action=action,
                                          ask_readonly=ask_readonly,
                                          reversible_lookup=reversible_lookup)
        elif lvl in ("confirm", "accept_edits"):
            return DecisionMeta(
                decision="ask",
                trigger=f"tool_level:{action}={lvl}",
                reason=f"per-tool {action} = {lvl}",
            )
        elif lvl == "observe":
            return DecisionMeta(
                decision="deny",
                trigger=f"tool_level:{action}=observe",
                reason=f"per-tool {action} = observe",
            )
        else:
            # propose 走 plan gate(本期同 confirm,SPEC §2.5 fallback)
            return DecisionMeta(
                decision="ask",
                trigger=f"tool_level:{action}={lvl}",
                reason=f"per-tool {action} = {lvl}",
            )

    # 6. Default level
    cfg_default = config.default_level
    if cfg_default is not None:
        lvl = cfg_default
    else:
        lvl = _gate_level_str(gate_level)

    if lvl == "auto":
        base = DecisionMeta(decision="approve", trigger=f"level:{lvl}", reason=f"default {lvl}")
    elif lvl in ("confirm", "propose", "accept_edits"):
        # Cautious(L1「只有危险操作才问」,默认档):自动放行【牢笼内】的动作 —— 低危只读
        # (web_search/web_extract/read_file/search_files)+ run_command(沙箱命令:Seatbelt 关在
        # 牢笼里、网络 OFF、写caged、凭据读拒;危险命令 rm -rf 等已在前面 hard_rule 步 deny)。
        # 只在【牢笼墙】问:出网越界(egress)、越界写、hard-rule/金融。这就是"牢笼内自动跑、只在墙问"
        # (Codex/Claude Code 的丝滑来源,2026-06-20 重设)。仅 low_risk_auto 且非 L0 且 lvl==confirm 时
        # 生效;裸 CONFIRM(测试)不置标志 → 行为不变。中/高危且非沙箱命令(浏览器写/mcp 等)仍 ask。
        if (low_risk_auto and not ask_readonly and lvl == "confirm"
                and (risk == "low" or action == "run_command")):
            base = DecisionMeta(decision="approve", trigger="trust:cautious 牢笼内放行",
                                reason="Cautious:牢笼内动作自动放行(只在牢笼墙/危险操作问)")
        else:
            base = DecisionMeta(decision="ask", trigger=f"level:{lvl}", reason=f"default {lvl}")
    elif lvl == "observe":
        return DecisionMeta(decision="deny", trigger=f"level:{lvl}", reason=f"default {lvl}")
    else:
        base = DecisionMeta(decision="ask", trigger=f"level:{lvl}", reason=f"default {lvl}")

    # 仅对"approve"结果应用 L0/L2 后处理(deny 结果绝不被升格/降级)。
    return _apply_trust_semantics(base, action=action,
                                  ask_readonly=ask_readonly,
                                  reversible_lookup=reversible_lookup)


def _apply_trust_semantics(
    meta: DecisionMeta,
    *,
    action: str,
    ask_readonly: bool,
    reversible_lookup: "Callable[[str], bool | None] | None",
) -> DecisionMeta:
    """L0/L2 后处理:仅作用于评估链末端"approve"结果。

    L0(ask_readonly=True):
      - "approve" → "ask"(trigger="trust:L0 每步确认")。
      - "ask"/"deny" 不变。

    L2(reversible_lookup 非 None):
      - 先查 reversible_lookup(action):
          True   → "approve"(trigger="trust:L2 可逆放行")
          False/None → "ask"(保守,trigger 保持原值)
      - 若原结果已是"ask"/"deny"则不降级(L2 只能放行可逆,不强制拦截)。
      - L2 不升格 deny。

    L0 与 L2 互斥(gate 每次只处于一个语义档位),代码按 ask_readonly 优先。
    """
    if meta.decision == "deny":
        # deny 来自 hard/soft deny;Trust Dial 任何档位都不降级 deny。
        return meta

    if ask_readonly:
        # L0:把所有 approve 升格为 ask
        if meta.decision == "approve":
            return DecisionMeta(
                decision="ask",
                trigger="trust:L0 每步确认",
                reason="L0 档位:只读操作也需确认",
            )
        return meta

    if reversible_lookup is not None:
        # L2:仅作用于"级别默认"产生的 ask 或 approve(trigger 以 level: 开头)。
        # soft_ask/soft_allow/tool_level 命中的决策保持原样(这些是显式配置的规则,L2 不覆盖)。
        # 规则:
        #   trigger=level:* + reversible=True  → approve(trigger="trust:L2 可逆放行")
        #   trigger=level:* + reversible=False/None → ask(保守,维持原 trigger)
        #   trigger 非 level:*(已被软规则命中) → 保持原结果不变
        is_level_default = meta.trigger.startswith("level:")
        if not is_level_default:
            # 软规则/tool_level 命中:L2 不干预
            return meta
        try:
            rev = reversible_lookup(action)
        except Exception:  # noqa: BLE001 — lookup 出错保守处理
            rev = None
        if rev is True:
            return DecisionMeta(
                decision="approve",
                trigger="trust:L2 可逆放行",
                reason=f"L2 档位:动作 {action!r} 声明为可逆,自动放行",
            )
        # False/None → 保守:已有 ask 维持;如果是 approve(level:auto)则升格为 ask
        if meta.decision == "approve":
            return DecisionMeta(
                decision="ask",
                trigger=f"{meta.trigger}:trust:L2 不可逆/未知保守问",
                reason=f"L2 档位:动作 {action!r} 不可逆或 reversible 未知,保守确认",
            )
        return meta

    return meta
