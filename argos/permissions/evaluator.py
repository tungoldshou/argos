from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TYPE_CHECKING
from urllib.parse import urlparse

from argos.i18n import t
from argos.permissions.config import PermissionsConfig
from argos.permissions.mode import PermissionMode, parse_permission_mode
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


def _run_command_is_low_risk(args: dict[str, Any]) -> bool:
    if not isinstance(args, dict):
        return False
    cmd = args.get("command") or args.get("cmd")
    if not isinstance(cmd, str):
        return False
    try:
        from argos.tools.shell import command_is_low_risk
        return command_is_low_risk(cmd)
    except Exception:  # noqa: BLE001
        return False


def _command_tokens(args: dict[str, Any]) -> list[str]:
    cmd = args.get("command") or args.get("cmd")
    if not isinstance(cmd, str):
        return []
    try:
        return shlex.split(cmd)
    except ValueError:
        return []


def _run_command_requires_approval(args: dict[str, Any]) -> bool:
    parts = _command_tokens(args)
    if not parts:
        return True
    bin_name = Path(parts[0]).name
    lowered = [p.lower() for p in parts]
    if bin_name == "git":
        return any(tok in {"push"} for tok in lowered[1:])
    if bin_name in {"npm", "pnpm", "yarn"}:
        return "publish" in lowered
    if bin_name in {"twine"}:
        return "upload" in lowered
    if bin_name in {"gh"}:
        return any(tok in {"release", "workflow"} for tok in lowered[1:])
    if any(tok in {"deploy", "release", "publish"} for tok in lowered):
        return True
    if bin_name in {"ssh", "scp", "rsync", "nc", "telnet"}:
        return True
    return False


def _write_inside_workspace(args: dict[str, Any], workspace: str | Path | None) -> bool:
    if workspace is None:
        return False
    path = args.get("path") or args.get("file") or args.get("filepath")
    if not isinstance(path, str):
        return False
    try:
        target = Path(path).expanduser().resolve(strict=False)
        root = Path(workspace).expanduser().resolve(strict=False)
        target.relative_to(root)
        return True
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
    config: PermissionsConfig,
    workspace: str | Path | None = None,
    risk: str = "medium",
    permission_mode: PermissionMode | str | None = None,
    reviewer_available: bool = False,
) -> DecisionMeta:
    arg_str = _arg_str(args)
    mode = parse_permission_mode(permission_mode, default=parse_permission_mode(config.mode))

    if mode is PermissionMode.FULL_ACCESS:
        return DecisionMeta(
            decision="approve",
            trigger="permission:full-access",
            reason="Full Access: Argos policy checks bypassed",
        )

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
            return soft_allow_meta

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

    if mode is PermissionMode.SMART_APPROVAL:
        if action in {"web_search", "web_extract", "browser_navigate", "browser_snapshot", "browser_screenshot"}:
            return DecisionMeta(decision="approve", trigger="permission:smart:web", reason="Smart Approval: public web action")
        if action == "run_command":
            if _run_command_requires_approval(args):
                return DecisionMeta(decision="ask", trigger="permission:smart:approval-required", reason="Smart Approval: publish/deploy/private-network command")
            if _run_command_needs_net(args):
                return DecisionMeta(decision="approve", trigger="permission:smart:network", reason="Smart Approval: common public network command")
            from argos import config as _argos_config
            if _run_command_is_low_risk(args) or _argos_config.sandbox_enabled():
                return DecisionMeta(decision="approve", trigger="permission:smart:local", reason="Smart Approval: local development command")
            return DecisionMeta(decision="ask", trigger="permission:smart:review", reason="Smart Approval: unknown local command")
        if action in ("write_file", "edit_file"):
            if _write_inside_workspace(args, workspace):
                return DecisionMeta(decision="approve", trigger="permission:smart:workspace-write", reason="Smart Approval: workspace write")
            return DecisionMeta(decision="ask", trigger="permission:smart:outside-workspace", reason="Smart Approval: write outside workspace")
        if action.startswith("computer_"):
            return DecisionMeta(decision="ask", trigger="permission:smart:computer", reason="Smart Approval: computer control requires confirmation")
        if risk == "low":
            return DecisionMeta(decision="approve", trigger="permission:smart:low-risk", reason="Smart Approval: low-risk action")
        return DecisionMeta(
            decision="ask",
            trigger="permission:smart:review" if reviewer_available else "permission:smart:ask",
            reason="Smart Approval: uncertain action",
        )

    return DecisionMeta(
        decision="ask",
        trigger="permission:smart:ask",
        reason="Smart Approval: unknown permission mode fallback",
    )
