from __future__ import annotations

from argos.permissions.audit import (
    AuditLog,
    get_audit_log,
    _reset_audit,
)
from argos.permissions.config import (
    PermissionsConfig,
    PermissionsConfigError,
    RuleEntry,
    get_config,
    reload_config,
    _reset_config,
)
from argos.permissions.hard_rules import (
    HARD_PATH_DENYLIST,
    HARD_SHELL_RULES,
    check_hard_shell,
    is_argos_own_env,
    is_env_file,
    is_env_template,
    is_system_path,
    is_workspace_path,
)
from argos.permissions.mode import PermissionMode, parse_permission_mode
from argos.permissions.secrets import (
    SECRET_PATTERNS,
    find_secret_in_content,
    MAX_SCAN_BYTES,
)

__all__ = [
    "PermissionsConfig", "PermissionsConfigError", "RuleEntry",
    "HARD_PATH_DENYLIST", "HARD_SHELL_RULES",
    "check_hard_shell", "is_system_path", "is_workspace_path",
    "is_env_file", "is_env_template", "is_argos_own_env",
    "SECRET_PATTERNS", "find_secret_in_content", "MAX_SCAN_BYTES",
    "get_config", "reload_config", "_reset_config",
    "evaluate", "DecisionMeta", "PermissionMode", "parse_permission_mode",
    "AuditLog", "get_audit_log", "_reset_audit",
]


def __getattr__(name: str):
    if name in {"evaluate", "DecisionMeta"}:
        from argos.permissions import evaluator
        return getattr(evaluator, name)
    raise AttributeError(name)
