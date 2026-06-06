"""Pass 2 — complexity counter(regex, not real McCabe AST,spec §2.5 Pass 2 / D6)。

- 粒度 = 函数级(找 `def name(` / `function name(` / `pub fn name(` / `async fn name(` 起始行)。
- 函数体范围 = 起始到下一个 def/function/pub fn 同缩进行(或 EOF)。
- 计数:`if` / `elif`(Python)/ `for` / `while` / `try` / `except` / `case` / `&&` / `||` / `?:` /
  `match`(Python 3.10+)/ Rust `match` arms。
- 函数 sum > 15 = complexity finding(severity=warning)。
- 白名单:`tests/**` 跳过。"""
from __future__ import annotations

import re
from pathlib import Path

from argos_agent.skills_runtime.analysis import Finding


_FN_START_RE = re.compile(
    r"^(?P<indent>\s*)(?:async\s+)?(?:def|fn|function|pub\s+fn)\s+(?P<name>\w+)\s*\(",
    re.MULTILINE,
)
_BRANCH_TOKENS_RE = re.compile(
    r"\b(if|elif|else|for|while|try|except|case|&&|\|\||\?\:|match)\b"
)
_THRESHOLD = 15

_SKIP_PATH_PATTERNS = ("tests/**",)


def _is_skipped_path(relpath: str) -> bool:
    import fnmatch
    return any(fnmatch.fnmatch(relpath, p) for p in _SKIP_PATH_PATTERNS)


def _is_source_file(p: Path) -> bool:
    return p.suffix.lower() in {".py", ".js", ".ts", ".rs", ".pyi", ".jsx", ".tsx"}


def _detect_functions(text: str) -> list[tuple[str, int, int]]:
    """返 [(name, line_start, line_end), ...]。"""
    fns: list[tuple[str, int, int]] = []
    starts: list[tuple[int, int, str, int]] = []
    for m in _FN_START_RE.finditer(text):
        indent = len(m.group("indent"))
        line = text.count("\n", 0, m.start()) + 1
        starts.append((line, indent, m.group("name"), m.start()))
    for i, (line, indent, name, offset) in enumerate(starts):
        body_end = len(text)
        for j in range(i + 1, len(starts)):
            next_line, next_indent, _, _ = starts[j]
            if next_indent <= indent:
                body_end = text.find("\n", next_line - 1)
                if body_end == -1:
                    body_end = len(text)
                break
        fns.append((name, line, body_end))
    return fns


def _count_branches(body: str) -> int:
    return len(_BRANCH_TOKENS_RE.findall(body))


def detect_complex_functions(workspace: Path) -> tuple[Finding, ...]:
    if not workspace.exists():
        return ()
    findings: list[Finding] = []
    for f in workspace.rglob("*"):
        if not f.is_file() or not _is_source_file(f):
            continue
        try:
            relpath = str(f.relative_to(workspace))
        except ValueError:
            continue
        if _is_skipped_path(relpath):
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name, line_start, body_end in _detect_functions(text):
            line_start_offset = text.rfind("\n", 0, line_start) + 1
            body = text[line_start_offset:body_end]
            n = _count_branches(body)
            if n > _THRESHOLD:
                findings.append(Finding(
                    severity="warning",
                    category="complexity",
                    file=relpath, line=line_start,
                    snippet=f"def {name}(...): # {n} branches",
                    message=f"cyclomatic-ish complexity: {n} (threshold {_THRESHOLD})",
                    suggestion=f"consider splitting {name} into smaller functions",
                ))
    return tuple(findings)
