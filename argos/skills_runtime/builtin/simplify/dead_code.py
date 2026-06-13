"""Pass 3 — dead code heuristic(未使用公共符号,spec §2.5 Pass 3 / D7)。

- 符号提取:regex 找 `def name(` / `function name(` / `const name =` / `let name =` /
  `export function name(` / `pub fn name(`(Rust)。
- 使用扫描:全 workspace `\\b<name>\\b` 模式(排除定义行)。
- 判定"可能死代码"(三条件 AND):(a) 函数体 > 5 行;(b) workspace 无 `\\b<name>\\b`;
  (c) 不在 `__all__` + 文件名非 `__init__.py` + 无 docstring。
- severity=info(启发,可能反射/插件加载等场景,用户决定)。
- 白名单:`tests/**` 跳过;`**/cli.py` 跳过;`**/__main__.py` 跳过。"""
from __future__ import annotations

import re
from pathlib import Path

from argos.skills_runtime.analysis import Finding


_FN_DEF_RE = re.compile(
    r"^(?P<indent>\s*)(?:export\s+)?(?:async\s+)?(?:def|fn|function|pub\s+fn)\s+(?P<name>\w+)\s*\(",
    re.MULTILINE,
)
_CONST_DEF_RE = re.compile(
    r"^(?P<indent>\s*)(?:export\s+)?(?:const|let|var)\s+(?P<name>\w+)\s*=",
    re.MULTILINE,
)
_ALL_RE = re.compile(r"__all__\s*=\s*\[(.*?)\]", re.DOTALL)
_DOCSTRING_RE = re.compile(r'^\s*("""|\'\'\')', re.MULTILINE)

_SKIP_PATH_PATTERNS = ("tests/**",)
_SKIP_FILENAMES = frozenset({"cli.py", "__main__.py", "__init__.py"})


def _is_skipped_path(relpath: str) -> bool:
    import fnmatch
    if any(fnmatch.fnmatch(relpath, p) for p in _SKIP_PATH_PATTERNS):
        return True
    if any(relpath.endswith(name) for name in _SKIP_FILENAMES):
        return True
    return False


def _is_source_file(p: Path) -> bool:
    return p.suffix.lower() in {".py", ".js", ".ts", ".rs", ".pyi", ".jsx", ".tsx"}


def _has_docstring(text: str, name_offset: int) -> bool:
    """函数体起始后 1 行内是否含 docstring。"""
    after = text[name_offset: name_offset + 200]
    return bool(_DOCSTRING_RE.match(after))


def _function_body_length(text: str, name_offset: int) -> int:
    """简化:从 def 起到下一个 def 同缩进行(行数)。"""
    indent_match = re.match(r"^(\s*)", text[name_offset:])
    if not indent_match:
        return 0
    indent = len(indent_match.group(1))
    body_start = text.find("\n", name_offset) + 1
    if body_start == 0:
        return 0
    rest = text[body_start:]
    lines = rest.split("\n")
    count = 0
    for line in lines[1:]:
        if line.strip() == "":
            count += 1
            continue
        line_indent = len(line) - len(line.lstrip())
        if line_indent <= indent:
            break
        count += 1
    return count


def _in_all(all_content: str, name: str) -> bool:
    """__all__ 列表里是否含 name(粗略 token match)。"""
    return bool(re.search(rf"\b{re.escape(name)}\b", all_content))


def detect_dead_code(workspace: Path) -> tuple[Finding, ...]:
    if not workspace.exists():
        return ()
    definitions: list[tuple[Path, str, int, int, int]] = []
    all_text_per_file: dict[Path, str] = {}
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
        all_text_per_file[f] = text
        for m in _FN_DEF_RE.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            body_len = _function_body_length(text, m.start())
            if body_len < 1:
                continue
            definitions.append((f, m.group("name"), line, body_len, m.start()))
    findings: list[Finding] = []
    for f_def, name, line, body_len, def_offset in definitions:
        usage_count = 0
        for f, text in all_text_per_file.items():
            for m in re.finditer(rf"\b{re.escape(name)}\b", text):
                usage_count += 1
        if usage_count > 1:
            continue
        relpath = str(f_def.relative_to(workspace))
        text = all_text_per_file[f_def]
        all_match = _ALL_RE.search(text)
        if all_match and _in_all(all_match.group(1), name):
            continue
        if _has_docstring(text, def_offset):
            continue
        findings.append(Finding(
            severity="info",
            category="dead_code",
            file=relpath, line=line, snippet=None,
            message=f"possibly unused function: {name} ({body_len} lines, no usage in workspace)",
            suggestion="confirm unused, then delete (recoverable via git history)",
        ))
    return tuple(findings)
