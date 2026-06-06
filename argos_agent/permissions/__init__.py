"""Smart approval + 硬规则 auto-deny(spec 2026-06-06)。

模块入口:暴露 `get_config` / `reload_config` / `evaluate` / `get_audit_log`。
evaluator 在 Task 4 补;audit 在 Task 6 补。"""
from __future__ import annotations

from argos_agent.permissions.audit import (
    AuditLog,
    get_audit_log,
    _reset_audit,
)
from argos_agent.permissions.config import (
    PermissionsConfig,
    PermissionsConfigError,
    RuleEntry,
    ToolLevelOverride,
    get_config,
    reload_config,
    _reset_config,
)
from argos_agent.permissions.evaluator import (
    DecisionMeta,
    evaluate,
)
from argos_agent.permissions.hard_rules import (
    HARD_PATH_DENYLIST,
    HARD_SHELL_RULES,
    check_hard_shell,
    is_argos_own_env,
    is_env_file,
    is_env_template,
    is_system_path,
    is_workspace_path,
)
from argos_agent.permissions.secrets import (
    SECRET_PATTERNS,
    find_secret_in_content,
    MAX_SCAN_BYTES,
)

__all__ = [
    "PermissionsConfig", "PermissionsConfigError", "RuleEntry", "ToolLevelOverride",
    "HARD_PATH_DENYLIST", "HARD_SHELL_RULES",
    "check_hard_shell", "is_system_path", "is_workspace_path",
    "is_env_file", "is_env_template", "is_argos_own_env",
    "SECRET_PATTERNS", "find_secret_in_content", "MAX_SCAN_BYTES",
    "get_config", "reload_config", "_reset_config",
    "evaluate", "DecisionMeta",
    "AuditLog", "get_audit_log", "_reset_audit",
]
