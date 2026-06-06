"""Pass 1 — secret 扫描(9 条 regex + 跳过/降级白名单,spec §2.4 / D4)。

- 9 条 regex:手写覆盖 AWS / GitHub / OpenAI / **Anthropic (sk-ant-*, D4 新增)** /
  private key / .env committed / hardcoded password。
- **跳过白名单**(D4):`SKIP_BASENAMES` 命中 → 完全跳过不扫,避免 user-controlled
  秘密存储(`.env.local` / `secrets.toml` / `*.pem` / `*.key`)误报。
- **降级白名单**:`DOWNGRADE_PATH_PATTERNS` 命中 → severity 降为 info(仍扫)。
- 二进制 / 1MB+ 文件 → 静默跳过。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from argos_agent.skills_runtime.analysis import Finding


# 9 条 regex(spec §2.4 / D4)
@dataclass(frozen=True)
class _SecretPattern:
    name: str            # finding.message 用
    regex: re.Pattern
    severity: str         # "error" / "warning"
    description: str     # suggestion 字段用


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
        name="Anthropic API key",   # D4 新增(必须排在 OpenAI 之前:sk-ant- 也满足
        # 扩展后的 OpenAI regex `sk-[A-Za-z0-9-_]{20,}` —— OpenAI 在前会把 Anthropic
        # key 误报为 OpenAI,触发"假阳性转移",反令用户怀疑 Anthropic 报点错。)
        regex=re.compile(r"sk-ant-[A-Za-z0-9-_]{20,}"),
        severity="error",
        description="rotate key + use env var",
    ),
    _SecretPattern(
        name="OpenAI API key",
        # 含 sk-proj-<id>-<secret> 现代项目 key 格式:body 允许 -_/字母数字
        # (与 sk-ant- 同档字符集,保 D4 收尾). 历史 sk-... 旧 key 仍命中。
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


# 跳过白名单(完全跳过不扫,D4 / spec §2.4)
# 注意:.env(裸)不跳过(只发一条 committed warning,内容不扫);.env.X 才跳过。
SKIP_BASENAMES: frozenset[str] = frozenset({
    ".env.example",   # 模板 — 不算 committed
    "secrets.toml",
})
# 注:.env / .env.local / .env.* 用 fnmatch 后缀
SKIP_SUFFIXES: tuple[str, ...] = (".pem", ".key")
SKIP_BASENAME_PATTERNS: tuple[str, ...] = (".env*", "secrets.toml", "*.pem", "*.key")


# 降级白名单(降 severity 到 info,spec §2.4)
DOWNGRADE_PATH_PATTERNS: tuple[str, ...] = (
    "tests/fixtures/**",
    "docs/**",
    "**/example*",
    "**/sample*",
)


# 文件大小 / 二进制 上限
_MAX_FILE_BYTES: int = 1_000_000   # 1MB
_SNIPPET_MAX: int = 120
_BINARY_EXTS: frozenset[str] = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".tar", ".gz",
    ".pyc", ".so", ".dll", ".dylib", ".bin",
})


def _should_skip(path: Path, relpath: str) -> bool:
    """D4 跳过白名单命中 → True(完全不扫)。

    重要:裸 .env **不**跳过(只发 committed warning,内容不扫)。
    """
    name = path.name
    # 精确 basename 匹配
    if name in SKIP_BASENAMES:
        return True
    # .env.local / .env.production / .env.* 前缀 + 任意后缀(裸 .env 除外)
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
    """降级白名单 → severity = info。"""
    import fnmatch
    for pat in DOWNGRADE_PATH_PATTERNS:
        if fnmatch.fnmatch(relpath, pat):
            return True
    return False


def _is_binary(path: Path) -> bool:
    """extension 黑名单(spec §2.4)。"""
    return path.suffix.lower() in _BINARY_EXTS


def _trunc_snippet(s: str) -> str:
    return s if len(s) <= _SNIPPET_MAX else s[:_SNIPPET_MAX]


def scan_file_for_secrets(
    file: Path,
    *,
    relpath: str,
    workspace: Path,
) -> tuple[Finding, ...]:
    """单文件扫 secret → 0..N 条 Finding。

    Args:
        file: 绝对路径。
        relpath: workspace-relative 路径(给 Finding.file 用)。
        workspace: workspace 根(给降级白名单判定用)。

    Returns:
        tuple[Finding, ...](空 = 无 finding;元组不可变)。
    """
    # 跳过白名单(D4)
    if _should_skip(file, relpath):
        return ()
    # 二进制文件
    if _is_binary(file):
        return ()
    # 1MB+ 文件
    try:
        if file.stat().st_size > _MAX_FILE_BYTES:
            return ()
    except OSError:
        return ()
    # 扫
    findings: list[Finding] = []
    downgrade = _is_downgrade(relpath)
    # 路径基础检查:裸 .env 文件 → 1 条 warning(committed)+ **不扫内容**
    # (.env 是 user-controlled secret 存储,不应当做泄漏源 — D4)
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
    # 读
    try:
        text = file.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ()
    for pat in SECRET_PATTERNS:
        # .env file committed 模式按文件名判断,不走内容匹配
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
