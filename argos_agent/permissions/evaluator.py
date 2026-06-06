"""Evaluator 串联 hard → soft → level,带 trigger 标签(spec §2.5, D15 锁)。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TYPE_CHECKING

from argos_agent.approval import ApprovalLevel
from argos_agent.permissions.config import PermissionsConfig
from argos_agent.permissions.hard_rules import (
    HARD_PATH_DENYLIST,
    check_hard_shell,
    is_argos_own_env,
    is_env_file,
    is_env_template,
    is_system_path,
    is_workspace_path,
)
from argos_agent.permissions.secrets import find_secret_in_content

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
) -> DecisionMeta:
    """串联 hard → soft deny → soft allow → soft ask → per-tool → default(spec D15 锁)。

    - secret 命中不走 soft allow 短路(D8 锁):即便 allow 列表命中具体内容仍 ask。
    - hard rule 命中即返,不被任何软规则覆盖(D5 锁)。
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
            return DecisionMeta(
                decision="approve",
                trigger=f"soft_allow:{allow_entry.matcher}",
                rule_name=allow_entry.matcher,
                reason=f"软规则 allow 命中: {allow_entry.matcher}",
            )

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
            return DecisionMeta(
                decision="approve",
                trigger=f"tool_level:{action}=auto",
                reason=f"per-tool {action} = auto",
            )
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
        return DecisionMeta(decision="approve", trigger=f"level:{lvl}", reason=f"default {lvl}")
    elif lvl in ("confirm", "propose", "accept_edits"):
        return DecisionMeta(decision="ask", trigger=f"level:{lvl}", reason=f"default {lvl}")
    elif lvl == "observe":
        return DecisionMeta(decision="deny", trigger=f"level:{lvl}", reason=f"default {lvl}")
    else:
        return DecisionMeta(decision="ask", trigger=f"level:{lvl}", reason=f"default {lvl}")
