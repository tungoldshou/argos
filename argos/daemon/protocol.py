"""daemon HTTP 协议常量 + 错误码(spec §2.5 + §3)。"""
from __future__ import annotations

# Header
HEADER_SESSION = "X-Argos-Session"

# Error codes(spec §2.5 / §3)
CODE_MISSING_SESSION = "missing_session"
CODE_BAD_REQUEST = "bad_request"
CODE_NOT_FOUND = "not_found"
CODE_INVALID_TRANSITION = "invalid_transition"
CODE_BUSY = "busy"
CODE_INTERNAL = "internal"
CODE_SESSION_READONLY = "session_readonly"
CODE_APPROVAL_NOT_PENDING = "approval_not_pending"
