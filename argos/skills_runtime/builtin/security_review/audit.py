"""Pass 2 — dep audit(shell out to npm/pip/cargo audit,spec §2.4 Pass 2 / D5 防假绿)。

- detect_lockfiles(workspace) → set[str]:顺序检 npm / pip / cargo lockfile。
- audit_dependencies(workspace) → tuple[Finding, ...]:跑各 lockfile 审计工具,合并 finding。
- **D5 防假绿硬约束**:工具缺失(`FileNotFoundError` on spawn)→ 1 条
  `Finding(severity=error, category=dep_audit, ...)`(非 info;**否则 verdict=passed
  假绿,直接违"不撒谎"护城河**);summary 加粗 `⚠ SUB-PASS SKIPPED: <tool>` 让用户必看见。
- 不**自动**装工具(同 hooks spec D11:用户责任)。"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Mapping

from argos.skills_runtime.analysis import Finding


# lockfile → argv 映射
_LOCKFILE_TABLE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("npm", ("npm", "audit", "--json")),
    ("pip", ("pip-audit", "-r", "requirements.txt", "--format=json")),
    ("cargo", ("cargo", "audit", "--json")),
)

_LOCKFILE_FILES: Mapping[str, str] = {
    "npm": "package-lock.json",
    "pip": "requirements.txt",
    "cargo": "Cargo.lock",
}


def detect_lockfiles(workspace: Path) -> set[str]:
    """扫 workspace 根,返存在的 lockfile 类型集合。"""
    detected: set[str] = set()
    for tool, fname in _LOCKFILE_FILES.items():
        if (workspace / fname).exists():
            detected.add(tool)
    return detected


def audit_lockfile(workspace: Path, tool: str) -> tuple[Finding, ...]:
    """跑单个工具审计;返 tuple of Finding。

    Raises:
        FileNotFoundError: 工具二进制未装(spec D5 → caller 必须转 error finding)。
    """
    argv: tuple[str, ...] | None = None
    for t, a in _LOCKFILE_TABLE:
        if t == tool:
            argv = a
            break
    if argv is None:
        return ()
    proc = subprocess.run(
        list(argv), cwd=str(workspace), capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0 and not proc.stdout.strip():
        # 工具报 err 且无 stdout → 1 条 error finding
        return (Finding(
            severity="error",
            category="dep_audit",
            file=None, line=None, snippet=None,
            message=f"{tool} audit failed: exit={proc.returncode}, stderr={proc.stderr[:200]}",
            suggestion="check tool installation / lockfile format",
        ),)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return (Finding(
            severity="error",
            category="dep_audit",
            file=None, line=None, snippet=None,
            message=f"{tool} audit returned malformed JSON",
            suggestion="check tool output / lockfile format",
        ),)
    return _parse_audit_output(tool, data)


def _parse_audit_output(tool: str, data: dict) -> tuple[Finding, ...]:
    """解析各工具 JSON → tuple[Finding, ...]。"""
    findings: list[Finding] = []
    vulns = data.get("vulnerabilities") or data.get("advisories") or {}
    for pkg_name, info in vulns.items():
        if tool == "npm":
            sev_str = (info.get("severity") or "unknown").lower()
            via = info.get("via") or []
            cve = next(
                (v.get("url", "").split("/")[-1] for v in via if isinstance(v, dict) and v.get("url")),
                "CVE-UNKNOWN",
            )
            summary = next(
                (v.get("title", "") for v in via if isinstance(v, dict) and v.get("title")),
                "(no description)",
            )
            findings.append(Finding(
                severity=_sev_to_level(sev_str),
                category="dep_vuln",
                file=None, line=None, snippet=None,
                message=f"{pkg_name}@{sev_str} · {cve} ({summary})",
                suggestion="upgrade to fixed version",
            ))
        elif tool == "pip":
            sev_str = (info.get("severity") or "unknown").lower()
            findings.append(Finding(
                severity=_sev_to_level(sev_str),
                category="dep_vuln",
                file=None, line=None, snippet=None,
                message=f"{info.get('name', pkg_name)}@{info.get('version', '?')} · {info.get('vuln_id', 'ID-UNKNOWN')}",
                suggestion="upgrade to fixed version",
            ))
        elif tool == "cargo":
            findings.append(Finding(
                severity=_sev_to_level(info.get("severity", "unknown")),
                category="dep_vuln",
                file=None, line=None, snippet=None,
                message=f"{pkg_name} · {info.get('id', 'ID-UNKNOWN')} ({info.get('title', '')})",
                suggestion="upgrade to fixed version",
            ))
    return tuple(findings)


def _sev_to_level(sev: str) -> str:
    """critical/high → error;medium → warning;low/unknown → info。"""
    sev = sev.lower()
    if sev in ("critical", "high"):
        return "error"
    if sev == "medium":
        return "warning"
    return "info"


def audit_dependencies(workspace: Path, *, rel_workspace: Path) -> tuple[Finding, ...]:
    """主入口:扫所有 lockfile + 跑审计 + 合并 finding。

    **D5 防假绿**:每个工具 `FileNotFoundError` → 1 条 error severity finding
    (`category=dep_audit`),不静默丢;summary 由 caller 加粗 `⚠ SUB-PASS SKIPPED`。
    """
    findings: list[Finding] = []
    for tool in detect_lockfiles(workspace):
        try:
            findings.extend(audit_lockfile(workspace, tool))
        except FileNotFoundError:
            tool_name = _LOCKFILE_FILES[tool]
            findings.append(Finding(
                severity="error",   # ← D5 防假绿:NOT info
                category="dep_audit",
                file=None, line=None, snippet=None,
                message=(
                    f"SUB-PASS SKIPPED: {tool_name} not installed "
                    f"(detected {tool} lockfile but audit tool missing)"
                ),
                suggestion=(
                    "install: npm i -g npm  ||  pip install pip-audit  "
                    "||  cargo install cargo-audit"
                ),
            ))
        except subprocess.TimeoutExpired:
            findings.append(Finding(
                severity="error",
                category="dep_audit",
                file=None, line=None, snippet=None,
                message=f"SUB-PASS TIMEOUT: {tool} audit > 60s",
                suggestion="retry or skip this lockfile",
            ))
    return tuple(findings)
