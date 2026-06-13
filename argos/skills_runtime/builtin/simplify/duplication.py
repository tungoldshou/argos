"""Pass 1 — duplication detection(token-level shingle,spec §2.5 Pass 1)。

- shingle 大小 = 20 token;窗口 = 整文件分 token(用 re.findall(r"\\w+|[^\\w\\s]"))。
- 哈希 = blake2b(digest_size=8);**3+ 命中同 hash** → duplicate finding。
- 白名单:`tests/**` / `docs/**` / `**/migrations/**` 跳过。
- 单文件 > 5000 token 跳过该 pass。"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from pathlib import Path

from argos.skills_runtime.analysis import Finding


_TOKEN_RE = re.compile(r"\w+|[^\w\s]")
_SHINGLE_SIZE = 20
_MIN_HASH_HITS = 3   # 3+ 命中 = duplicate
_MAX_FILE_TOKENS = 5000

_SKIP_PATH_PATTERNS = ("tests/**", "docs/**", "**/migrations/**")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text)


def _is_skipped_path(relpath: str) -> bool:
    import fnmatch
    return any(fnmatch.fnmatch(relpath, p) for p in _SKIP_PATH_PATTERNS)


def _is_source_file(p: Path) -> bool:
    return p.suffix.lower() in {".py", ".js", ".ts", ".rs", ".pyi", ".jsx", ".tsx"}


def _shingle_hashes(tokens: list[str]) -> list[tuple[str, int]]:
    """返 (hash, start_token_idx) 列表;start_token_idx 用来定位 file:line。"""
    out: list[tuple[str, int]] = []
    for i in range(len(tokens) - _SHINGLE_SIZE + 1):
        shingle = " ".join(tokens[i:i + _SHINGLE_SIZE])
        h = hashlib.blake2b(shingle.encode("utf-8"), digest_size=8).hexdigest()
        out.append((h, i))
    return out


def detect_duplicates(workspace: Path) -> tuple[Finding, ...]:
    """扫 workspace → tuple of duplicate findings(3+ 命中)。"""
    if not workspace.exists():
        return ()
    by_hash: dict[str, list[tuple[Path, int]]] = defaultdict(list)
    file_tokens: dict[Path, list[str]] = {}

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
        tokens = _tokenize(text)
        if len(tokens) > _MAX_FILE_TOKENS:
            continue
        file_tokens[f] = tokens
        for h, idx in _shingle_hashes(tokens):
            by_hash[h].append((f, idx))

    findings: list[Finding] = []
    for h, occurrences in by_hash.items():
        if len(occurrences) < _MIN_HASH_HITS:
            continue
        # dedup 同一文件 + 同一 shingle start token idx
        seen_files_idx: set[tuple[Path, int]] = set()
        uniq_occurrences: list[tuple[Path, int]] = []
        for f, idx in occurrences:
            if (f, idx) in seen_files_idx:
                continue
            seen_files_idx.add((f, idx))
            uniq_occurrences.append((f, idx))
        if len(uniq_occurrences) < _MIN_HASH_HITS:
            continue
        first_f, first_idx = uniq_occurrences[0]
        # 简化:line = 1(精确需用 token 字符 offset 算;本期 v1 简化)
        line_no = 1
        locs = [f"{f.relative_to(workspace)}:{line_no}" for f, _ in uniq_occurrences[:5]]
        findings.append(Finding(
            severity="warning",
            category="duplicate",
            file=str(first_f.relative_to(workspace)),
            line=line_no,
            snippet=f"3+ shingle matches across {len(uniq_occurrences)} locations",
            message=f"duplicate · {len(uniq_occurrences)} occurrences · {', '.join(locs)}",
            suggestion="extract to common helper (see first snippet)",
        ))
    return tuple(findings)
