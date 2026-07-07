from __future__ import annotations

import enum


class PermissionMode(enum.StrEnum):
    SMART_APPROVAL = "smart"
    FULL_ACCESS = "full"

    @property
    def label(self) -> str:
        return "Smart Approval" if self is PermissionMode.SMART_APPROVAL else "Full Access"


def parse_permission_mode(value: object, *, default: PermissionMode = PermissionMode.SMART_APPROVAL) -> PermissionMode:
    if isinstance(value, PermissionMode):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower().replace("-", "_")
        if normalized in {"smart", "smart_approval"}:
            return PermissionMode.SMART_APPROVAL
        if normalized in {"full", "full_access"}:
            return PermissionMode.FULL_ACCESS
    return default
