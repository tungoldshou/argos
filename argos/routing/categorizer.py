"""Internal documentation."""
from __future__ import annotations

import enum
import re

LONG_RUN_THRESHOLD = 20


class TaskCategory(enum.Enum):
    """Internal documentation."""
    FILE_EDIT = "file_edit"
    REFACTOR = "refactor"
    TEST_WRITE = "test_write"
    VERIFY = "verify"
    PLAN = "plan"
    LONG_RUN = "long_run"
    AUTO_CAPTURE = "auto_capture"
    SIMPLE_READ = "simple_read"


_TEST_MARKERS = ("assert ", "pytest", "def test_", "TestCase", "unittest")

_WRITE_RE = re.compile(
    r"""write_file\(\s*(?P<q>['\"])(?P<path>.+?)(?P=q)\s*,\s*(?P<q2>['\"])(?P<content>.*?)(?P=q2)\s*\)""",
    re.DOTALL,
)
_EDIT_RE = re.compile(
    r"""edit_file\(\s*(?P<q>['\"])(?P<path>.+?)(?P=q)\s*,\s*(?P<q2>['\"])(?P<old>.*?)(?P=q2)\s*,\s*(?P<q3>['\"])(?P<new>.*?)(?P=q3)""",
    re.DOTALL,
)


def _line_count(s: str) -> int:
    return len(s.splitlines())


def _edit_scale(code: str) -> int | None:
    """Internal documentation."""
    m = _EDIT_RE.search(code)
    if not m:
        return None
    return _line_count(m.group("new")) - _line_count(m.group("old"))


def _write_lines(code: str) -> int | None:
    m = _WRITE_RE.search(code)
    if not m:
        return None
    return _line_count(m.group("content"))


def _has_test_marker(code: str) -> bool:
    return any(m in code for m in _TEST_MARKERS)


def categorize(*, tool: str | None = None, code: str | None = None,
               phase: str = "act", step: int = 0) -> TaskCategory:
    """Internal documentation."""
    try:
        if phase == "plan":
            return TaskCategory.PLAN
        if phase == "verify":
            return TaskCategory.VERIFY
        if step >= LONG_RUN_THRESHOLD:
            return TaskCategory.LONG_RUN
        if tool in ("run_command", "lsp_diagnostics"):
            return TaskCategory.AUTO_CAPTURE
        if code and _has_test_marker(code):
            return TaskCategory.TEST_WRITE
        if code and "edit_file(" in code:
            scale = _edit_scale(code)
            if scale is None or scale < 5:
                return TaskCategory.FILE_EDIT
            return TaskCategory.REFACTOR
        if tool in ("read_file", "search_files"):
            return TaskCategory.SIMPLE_READ
        if code and "write_file(" in code:
            return TaskCategory.FILE_EDIT
        return TaskCategory.SIMPLE_READ
    except Exception:  # noqa: BLE001
        return TaskCategory.SIMPLE_READ
