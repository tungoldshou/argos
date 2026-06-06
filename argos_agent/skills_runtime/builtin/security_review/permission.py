"""Pass 3 — permission check(Python + JS/TS 危险 API,spec §2.4 Pass 3)。

- regex 扫 `os.system` / `subprocess.Popen(shell=True)` / `eval` / `exec` / `pickle.loads` /
  `__import__`(Python);`child_process.exec` / `eval` / `new Function` / `innerHTML` /
  `dangerouslySetInnerHTML`(JS/TS)。
- **whitelist 降级**:`tests/**` / `**/test_*.py` / `**/*_test.py` / `**/*.test.ts` /
  `**/conftest.py` → severity 降 info(测试代码里 `eval` 多是合理 fixture)。
- 不支持语言(Go / Java / C++)→ 1 条 info 提示"language not supported"(spec D15)。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from argos_agent.skills_runtime.analysis import Finding


@dataclass(frozen=True)
class _PermissionPattern:
    name: str
    regex: re.Pattern
    severity: str
    suggestion: str


PYTHON_PATTERNS: tuple[_PermissionPattern, ...] = (
    _PermissionPattern(
        name="os.system",
        regex=re.compile(r"os\.system\s*\("),
        severity="warning",
        suggestion="use subprocess.run([...]) with shell=False",
    ),
    _PermissionPattern(
        name="subprocess shell=True",
        regex=re.compile(r"subprocess\.[A-Za-z_]+\([^)]*shell\s*=\s*True"),
        severity="error",
        suggestion="use shell=False + list args",
    ),
    _PermissionPattern(
        name="eval",
        regex=re.compile(r"(?<![\w.])eval\s*\("),
        severity="error",
        suggestion="use ast.literal_eval or refactor",
    ),
    _PermissionPattern(
        name="exec",
        regex=re.compile(r"(?<![\w.])exec\s*\("),
        severity="error",
        suggestion="avoid dynamic exec; refactor",
    ),
    _PermissionPattern(
        name="pickle.loads",
        regex=re.compile(r"pickle\.loads?\s*\("),
        severity="warning",
        suggestion="use json or signed data",
    ),
    _PermissionPattern(
        name="__import__",
        regex=re.compile(r"__import__\s*\("),
        severity="warning",
        suggestion="use importlib.import_module",
    ),
)


JS_TS_PATTERNS: tuple[_PermissionPattern, ...] = (
    _PermissionPattern(
        name="child_process.exec",
        # match either `child_process.exec(` or `require("child_process")` import marker
        regex=re.compile(r"(child_process\.exec\s*\(|require\s*\(\s*['\"]child_process['\"]\s*\))"),
        severity="error",
        suggestion="use execFile with args array",
    ),
    _PermissionPattern(
        name="child_process.execSync",
        regex=re.compile(r"child_process\.execSync\s*\("),
        severity="error",
        suggestion="use execFileSync with args array",
    ),
    _PermissionPattern(
        name="eval",
        regex=re.compile(r"(?<![\w.])eval\s*\("),
        severity="error",
        suggestion="avoid dynamic eval",
    ),
    _PermissionPattern(
        name="new Function",
        regex=re.compile(r"new\s+Function\s*\("),
        severity="error",
        suggestion="avoid dynamic function construction",
    ),
    _PermissionPattern(
        name="innerHTML assignment",
        regex=re.compile(r"\.innerHTML\s*="),
        severity="warning",
        suggestion="use textContent or sanitize input",
    ),
    _PermissionPattern(
        name="dangerouslySetInnerHTML",
        regex=re.compile(r"dangerouslySetInnerHTML"),
        severity="warning",
        suggestion="sanitize or avoid",
    ),
)


# 扩展名 → (patterns, 标记)
_EXT_TABLE: Mapping[str, tuple[Sequence[_PermissionPattern], str]] = {
    ".py": (PYTHON_PATTERNS, "python"),
    ".pyi": (PYTHON_PATTERNS, "python"),
    ".js": (JS_TS_PATTERNS, "javascript"),
    ".jsx": (JS_TS_PATTERNS, "javascript"),
    ".ts": (JS_TS_PATTERNS, "typescript"),
    ".tsx": (JS_TS_PATTERNS, "typescript"),
    ".mjs": (JS_TS_PATTERNS, "javascript"),
    ".cjs": (JS_TS_PATTERNS, "javascript"),
}

# whitelist 降级(测试代码)
_TEST_PATH_PATTERNS: tuple[str, ...] = (
    "tests/**",
    "**/test_*.py",
    "**/test_*.js",
    "**/test_*.ts",
    "**/*_test.py",
    "**/*_test.js",
    "**/*_test.ts",
    "**/*.test.ts",
    "**/*.spec.ts",
    "**/conftest.py",
)

_SNIPPET_MAX = 120
_BINARY_EXTS: frozenset[str] = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".tar", ".gz",
    ".pyc", ".so", ".dll", ".dylib", ".bin",
})


def _is_test_path(relpath: str) -> bool:
    import fnmatch
    return any(fnmatch.fnmatch(relpath, p) for p in _TEST_PATH_PATTERNS)


def _trunc_snippet(s: str) -> str:
    return s if len(s) <= _SNIPPET_MAX else s[:_SNIPPET_MAX]


def scan_file_for_permission_issues(
    file: Path,
    *,
    relpath: str,
    workspace: Path,
) -> tuple[Finding, ...]:
    """单文件扫危险 API → 0..N 条 Finding。"""
    ext = file.suffix.lower()
    if ext in _BINARY_EXTS:
        return ()  # 二进制静默跳
    entry = _EXT_TABLE.get(ext)
    if entry is None:
        if ext:
            return (Finding(
                severity="info",
                category="permission",
                file=relpath, line=1, snippet=None,
                message=f"language not supported: {ext} (Python + JS/TS + Rust only in v1)",
                suggestion=None,
            ),)
        return ()
    patterns, lang = entry
    try:
        text = file.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ()
    findings: list[Finding] = []
    downgrade = _is_test_path(relpath)
    for pat in patterns:
        for m in pat.regex.finditer(text):
            line_no = text.count("\n", 0, m.start()) + 1
            line_start = text.rfind("\n", 0, m.start()) + 1
            line_end = text.find("\n", m.start())
            if line_end == -1:
                line_end = len(text)
            snippet = _trunc_snippet(text[line_start:line_end].strip())
            sev = "info" if downgrade else pat.severity
            findings.append(Finding(
                severity=sev,
                category="permission",
                file=relpath, line=line_no, snippet=snippet,
                message=f"[{lang}] {pat.name} detected" + (" (downgraded to info)" if downgrade else ""),
                suggestion=pat.suggestion,
            ))
    return tuple(findings)
