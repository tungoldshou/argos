"""任务分类(契约 §11;spec §5):从 (tool, code, phase, step) 推出 TaskCategory。

启发式只看静态文本,无 LLM 调用 → 0 token;任何异常(正则不命中 / 类型错)都兜底
SIMPLE_READ,绝不抛(spec D9)。
"""
from __future__ import annotations

import enum
import re

LONG_RUN_THRESHOLD = 20


class TaskCategory(enum.Enum):
    """8 类别固定枚举(spec §4.1)。避免自由字符串 → 拼写错导致静默回退 default。"""
    FILE_EDIT = "file_edit"
    REFACTOR = "refactor"
    TEST_WRITE = "test_write"
    VERIFY = "verify"
    PLAN = "plan"
    LONG_RUN = "long_run"
    AUTO_CAPTURE = "auto_capture"
    SIMPLE_READ = "simple_read"


_TEST_MARKERS = ("assert ", "pytest", "def test_", "TestCase", "unittest")

# write_file(path, content) — 抓 path 与 content
_WRITE_RE = re.compile(
    r"""write_file\(\s*(?P<q>['\"])(?P<path>.+?)(?P=q)\s*,\s*(?P<q2>['\"])(?P<content>.*?)(?P=q2)\s*\)""",
    re.DOTALL,
)
# edit_file(path, old, new, all_occurrences=False) — 抓 old 与 new
_EDIT_RE = re.compile(
    r"""edit_file\(\s*(?P<q>['\"])(?P<path>.+?)(?P=q)\s*,\s*(?P<q2>['\"])(?P<old>.*?)(?P=q2)\s*,\s*(?P<q3>['\"])(?P<new>.*?)(?P=q3)""",
    re.DOTALL,
)


def _line_count(s: str) -> int:
    return len(s.splitlines())


def _edit_scale(code: str) -> int | None:
    """edit_file 改了多少行(new - old)。解析失败返 None(让上层兜底 FILE_EDIT)。"""
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
    """(tool, code, phase, step) → TaskCategory。启发式,无 LLM,异常兜底 SIMPLE_READ。

    判定顺序(短路返回):
      1. phase == "plan"      → PLAN
      2. phase == "verify"    → VERIFY
      3. step >= 20           → LONG_RUN
      4. tool in auto_capture → AUTO_CAPTURE
      5. code 含 test marker  → TEST_WRITE
      6. code 含 edit_file    → FILE_EDIT(scale<5) / REFACTOR(scale>=5)
      7. tool in read_*       → SIMPLE_READ
      8. code 含 write_file   → FILE_EDIT
      9. 兜底                 → SIMPLE_READ
    """
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
    except Exception:  # noqa: BLE001 — 启发式永不该崩 run(spec D9)
        return TaskCategory.SIMPLE_READ
