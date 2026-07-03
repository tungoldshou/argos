from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TYPE_CHECKING
from urllib.parse import urlparse

from argos.approval import ApprovalLevel
from argos.i18n import t
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
    if not isinstance(args, dict):
        return str(args)
    server = args.get("server")
    tool = args.get("tool")
    if isinstance(server, str) and isinstance(tool, str) and server.strip() and tool.strip():
        return f"{server.strip()}/{tool.strip()}"
    for key in ("cmd", "command"):
        v = args.get(key)
        if isinstance(v, str):
            return v
    url = args.get("url")
    if isinstance(url, str):
        parsed = urlparse(url.strip())
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
        if parsed.netloc:
            return parsed.netloc.lower()
    for key in ("path", "file", "filepath"):
        v = args.get(key)
        if isinstance(v, str):
            return str(Path(v).expanduser().resolve(strict=False))
    return repr(args)


def _gate_level_str(level: ApprovalLevel | str | None) -> str:
    if level is None:
        return "confirm"
    if isinstance(level, ApprovalLevel):
        return level.value
    return str(level)


def _run_command_needs_net(args: dict[str, Any]) -> bool:
    if not isinstance(args, dict):
        return False
    cmd = args.get("command") or args.get("cmd")
    if not isinstance(cmd, str):
        return False
    try:
        from argos.tools.shell import command_needs_network
        return command_needs_network(cmd)
    except Exception:  # noqa: BLE001
        return False


def _check_hard_path_write(args: dict[str, Any], *, workspace: str | Path | None) -> DecisionMeta | None:
    path = args.get("path") or args.get("file") or args.get("filepath")
    if not isinstance(path, str):
        return None
    if is_env_template(path):
        return None
    if is_argos_own_env(path):
        return None
    if is_system_path(path):
        for prefix in HARD_PATH_DENYLIST:
            p_resolved = str(Path(path).expanduser().resolve())
            if p_resolved.startswith(prefix):
                return DecisionMeta(
                    decision="deny",
                    trigger=f"hard_rule:system_path:{prefix}",
                    reason=t("perm2.eval.system_path_deny", prefix=prefix),
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
    arg_str = _arg_str(args)

    if action == "run_command":
        rule = check_hard_shell(arg_str)
        if rule is not None:
            return DecisionMeta(
                decision="deny",
                trigger=f"hard_rule:{rule}",
                rule_name=rule,
                reason=t("perm2.eval.hard_shell_deny", rule=rule),
            )

    if action in ("write_file", "edit_file"):
        meta = _check_hard_path_write(args, workspace=workspace)
        if meta is not None:
            return meta

    if action.startswith("computer_"):
        computer_rule = check_computer_hard_rules(action, args)
        if computer_rule is not None:
            return DecisionMeta(
                decision="ask",
                trigger=f"hard_rule:{computer_rule}",
                rule_name=computer_rule,
                reason=t("perm2.eval.computer_hard_ask", rule=computer_rule),
            )

    secret_name: str | None = None
    if action in ("write_file", "edit_file"):
        content = args.get("content")
        if isinstance(content, str):
            secret_name = find_secret_in_content(content)
        elif isinstance(content, dict):
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
            reason=t("perm2.eval.soft_deny_reason", matcher=deny_entry.matcher),
        )

    if secret_name is None:
        allow_entry = config.match_allow(action, arg_str)
        if allow_entry is not None:
            soft_allow_meta = DecisionMeta(
                decision="approve",
                trigger=f"soft_allow:{allow_entry.matcher}",
                rule_name=allow_entry.matcher,
                reason=t("perm2.eval.soft_allow_reason", matcher=allow_entry.matcher),
            )
            return _apply_trust_semantics(soft_allow_meta, action=action,
                                          ask_readonly=ask_readonly,
                                          reversible_lookup=reversible_lookup)

    if secret_name is not None:
        return DecisionMeta(
            decision="ask",
            trigger=f"secret:{secret_name}",
            secret_pattern=secret_name,
            reason=t("perm2.eval.secret_ask_reason", name=secret_name),
        )

    # 4. Soft ask
    ask_entry = config.match_ask(action, arg_str)
    if ask_entry is not None:
        return DecisionMeta(
            decision="ask",
            trigger=f"soft_ask:{ask_entry.matcher}",
            rule_name=ask_entry.matcher,
            reason=t("perm2.eval.soft_ask_reason", matcher=ask_entry.matcher),
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
        #
        _is_accept_edits = (lvl == "accept_edits")
        from argos import config as _argos_config
        _sandbox_on = _argos_config.sandbox_enabled()
        _cautious_cage_ok = (
            risk == "low"
            or (action == "run_command" and _sandbox_on and not _run_command_needs_net(args))
            or (_is_accept_edits and action in ("write_file", "edit_file"))
        )
        _cage_auto = _is_accept_edits or (low_risk_auto and lvl == "confirm")
        if _cage_auto and not ask_readonly and _cautious_cage_ok:
            _why = t("perm2.eval.trusted_accept_edits_cage") if _is_accept_edits else t("perm2.eval.cautious_cage")
            base = DecisionMeta(decision="approve", trigger=t("perm2.eval.cage_trigger"), reason=_why)
        else:
            base = DecisionMeta(decision="ask", trigger=f"level:{lvl}", reason=f"default {lvl}")
    elif lvl == "observe":
        return DecisionMeta(decision="deny", trigger=f"level:{lvl}", reason=f"default {lvl}")
    else:
        base = DecisionMeta(decision="ask", trigger=f"level:{lvl}", reason=f"default {lvl}")

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
    if meta.decision == "deny":
        return meta

    if ask_readonly:
        if meta.decision == "approve":
            return DecisionMeta(
                decision="ask",
                trigger=t("perm2.eval.l0_trigger"),
                reason=t("perm2.eval.l0_reason"),
            )
        return meta

    if reversible_lookup is not None:
        is_level_default = meta.trigger.startswith("level:")
        if not is_level_default:
            return meta
        try:
            rev = reversible_lookup(action)
        except Exception:  # noqa: BLE001
            rev = None
        if rev is True:
            return DecisionMeta(
                decision="approve",
                trigger=t("perm2.eval.l2_approve_trigger"),
                reason=t("perm2.eval.l2_approve_reason", action=action),
            )
        if meta.decision == "approve":
            return DecisionMeta(
                decision="ask",
                trigger=t("perm2.eval.l2_ask_trigger", trigger=meta.trigger),
                reason=t("perm2.eval.l2_ask_reason", action=action),
            )
        return meta

    return meta
