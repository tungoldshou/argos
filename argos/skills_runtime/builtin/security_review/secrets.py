from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from argos.skills_runtime.analysis import Finding


@dataclass(frozen=True)
class _SecretPattern:
    name: str
    regex: re.Pattern
    severity: str         # "error" / "warning"
    description: str


SECRET_PATTERNS: tuple[_SecretPattern, ...] = (
    _SecretPattern(
        name="AWS access key",
        regex=re.compile(r"AKIA[0-9A-Z]{16}"),
        severity="error",
        description="rotate key + use AWS IAM role / env var",
    ),
    _SecretPattern(
        name="AWS secret access key",
        regex=re.compile(
            r"(?i)aws_secret_access_key\s*=\s*[\"'][A-Za-z0-9/+=]{40}[\"']"
        ),
        severity="error",
        description="rotate key + use env var",
    ),
    _SecretPattern(
        name="GitHub token (classic)",
        regex=re.compile(r"ghp_[A-Za-z0-9]{36}"),
        severity="error",
        description="rotate token + use env var",
    ),
    _SecretPattern(
        name="GitHub token (fine-grained)",
        regex=re.compile(r"github_pat_[A-Za-z0-9_]{82}"),
        severity="error",
        description="rotate token + use env var",
    ),
    _SecretPattern(
        name="Anthropic API key",
        regex=re.compile(r"sk-ant-[A-Za-z0-9-_]{20,}"),
        severity="error",
        description="rotate key + use env var",
    ),
    _SecretPattern(
        name="OpenAI API key",
        regex=re.compile(r"sk-[A-Za-z0-9-_]{20,}"),
        severity="error",
        description="rotate key + use env var",
    ),
    _SecretPattern(
        name="Private key block",
        regex=re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
        severity="error",
        description="remove committed private key + rotate",
    ),
    _SecretPattern(
        name=".env file committed",
        regex=re.compile(r"^\.env$"),
        severity="warning",
        description="add to .gitignore + use .env.example template",
    ),
    _SecretPattern(
        name="hardcoded password",
        regex=re.compile(
            r"(?i)(password|passwd|pwd)\s*=\s*[\"'][^\"'\s]{4,}[\"']"
        ),
        severity="warning",
        description="move to env var / secrets manager",
    ),
)


SKIP_BASENAMES: frozenset[str] = frozenset({
    ".env.example",
    "secrets.toml",
})
SKIP_SUFFIXES: tuple[str, ...] = (".pem", ".key")
SKIP_BASENAME_PATTERNS: tuple[str, ...] = (".env*", "secrets.toml", "*.pem", "*.key")


DOWNGRADE_PATH_PATTERNS: tuple[str, ...] = (
    "tests/fixtures/**",
    "docs/**",
    "**/example*",
    "**/sample*",
)


_MAX_FILE_BYTES: int = 1_000_000   # 1MB
_SNIPPET_MAX: int = 120
_BINARY_EXTS: frozenset[str] = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".tar", ".gz",
    ".pyc", ".so", ".dll", ".dylib", ".bin",
})


def _should_skip(path: Path, relpath: str) -> bool:
    name = path.name
    if name in SKIP_BASENAMES:
        return True
    if name.startswith(".env.") or name == ".env.local":
        return True
    # secrets.toml
    if name == "secrets.toml":
        return True
    # *.pem / *.key
    if path.suffix in SKIP_SUFFIXES:
        return True
    return False


def _is_downgrade(relpath: str) -> bool:
    import fnmatch
    for pat in DOWNGRADE_PATH_PATTERNS:
        if fnmatch.fnmatch(relpath, pat):
            return True
    return False


def _is_binary(path: Path) -> bool:
    return path.suffix.lower() in _BINARY_EXTS


def _trunc_snippet(s: str) -> str:
    return s if len(s) <= _SNIPPET_MAX else s[:_SNIPPET_MAX]


def scan_file_for_secrets(
    file: Path,
    *,
    relpath: str,
    workspace: Path,
) -> tuple[Finding, ...]:
    if _should_skip(file, relpath):
        return ()
    if _is_binary(file):
        return ()
    try:
        if file.stat().st_size > _MAX_FILE_BYTES:
            return ()
    except OSError:
        return ()
    findings: list[Finding] = []
    downgrade = _is_downgrade(relpath)
    if file.name == ".env":
        findings.append(Finding(
            severity="info" if downgrade else "warning",
            category="secret",
            file=relpath,
            line=1,
            snippet=None,
            message=".env file committed" + (" (downgraded to info)" if downgrade else ""),
            suggestion="add to .gitignore + use .env.example template",
        ))
        return tuple(findings)
    try:
        text = file.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ()
    for pat in SECRET_PATTERNS:
        if pat.name == ".env file committed":
            continue
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
                category="secret",
                file=relpath,
                line=line_no,
                snippet=snippet,
                message=f"{pat.name} detected" + (" (downgraded to info)" if downgrade else ""),
                suggestion=pat.description,
            ))
    return tuple(findings)
