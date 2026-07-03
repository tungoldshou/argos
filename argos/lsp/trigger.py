from __future__ import annotations

import re

# match write_file('path', 'content') or write_file("path", "content")
_WRITE_FILE_RE = re.compile(
    r"""\bwrite_file\(\s*(['"])([^'"]+)\1\s*,\s*((['"])((?:\\.|(?!\4).)*)\4)""",
    re.DOTALL,
)
_EDIT_FILE_PATH_RE = re.compile(
    r"""\bedit_file\(\s*(['"])([^'"]+)\1\s*,""",
)


def extract_file_writes(code: str) -> list[tuple[str, str]]:
    if not code:
        return []
    writes: list[tuple[str, str]] = []
    for m in _WRITE_FILE_RE.finditer(code):
        path = m.group(2)
        raw_body = m.group(5)
        content = raw_body.encode("utf-8").decode("unicode_escape", errors="replace")
        writes.append((path, content))
    return writes


def extract_file_paths(code: str) -> list[str]:
    if not code:
        return []
    paths: list[str] = []
    for m in _WRITE_FILE_RE.finditer(code):
        p = m.group(2)
        if p not in paths:
            paths.append(p)
    for m in _EDIT_FILE_PATH_RE.finditer(code):
        p = m.group(2)
        if p not in paths:
            paths.append(p)
    return paths
