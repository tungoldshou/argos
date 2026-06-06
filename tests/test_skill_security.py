"""`/security-review` 整合 + 3 pass 编排测试(spec §2.4 / D5 / D12)。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from argos_agent.skills_runtime.analysis import (
    AnalysisSkillContext,
    AnalysisSkillResult,
    Finding,
)
from argos_agent.skills_runtime import registry
from argos_agent.skills_runtime.builtin.security_review import run as sr_run
from argos_agent.skills_runtime.builtin.security_review.secrets import scan_file_for_secrets
from argos_agent.skills_runtime.builtin.security_review.audit import audit_dependencies
from argos_agent.skills_runtime.builtin.security_review.permission import scan_file_for_permission_issues


@pytest.fixture(autouse=True)
def _clean():
    registry._reset_registry()
    yield
    registry._reset_registry()


def _ctx(workspace: Path) -> AnalysisSkillContext:
    return AnalysisSkillContext(workspace=workspace, approval_level="auto", run_id="r1")


# ── 3 pass 各自集成 ─────────────────────────────────────────────

def test_pass1_secret_finds_planted(tmp_path):
    """planted secret 必被 Pass 1 找到(验整合)。"""
    f = tmp_path / "leak.py"
    f.write_text('token = "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"\n')
    findings = scan_file_for_secrets(f, relpath="leak.py", workspace=tmp_path)
    assert any(f.severity == "error" and f.category == "secret" for f in findings)


def test_pass2_dep_audit_missing_tool_yields_error_severity(tmp_path):
    """Pass 2 缺工具 → error severity(防假绿)。"""
    (tmp_path / "package-lock.json").write_text("{}")

    def _raise(*a, **kw):
        raise FileNotFoundError("npm")

    with patch("argos_agent.skills_runtime.builtin.security_review.audit.subprocess.run", side_effect=_raise):
        findings = audit_dependencies(tmp_path, rel_workspace=tmp_path)
    assert any(f.severity == "error" and f.category == "dep_audit" for f in findings)


def test_pass3_permission_finds_eval(tmp_path):
    """Pass 3 找到 eval() → error finding。"""
    f = tmp_path / "bad.py"
    f.write_text('eval("1+1")\n')
    findings = scan_file_for_permission_issues(f, relpath="bad.py", workspace=tmp_path)
    assert any(f.severity == "error" and f.category == "permission" for f in findings)


# ── 整合 run() ──────────────────────────────────────────────────

def test_security_review_full_pipeline_planted_secret(tmp_path):
    """完整 `/security-review` 跑在含 planted secret 的 fixture → 至少 1 条 finding。"""
    (tmp_path / "leak.py").write_text('token = "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"\n')
    (tmp_path / "bad.py").write_text('eval("1+1")\n')
    with patch(
        "argos_agent.skills_runtime.builtin.security_review.audit.detect_lockfiles",
        return_value=set(),
    ):
        result = asyncio.run(sr_run({"path": None}, _ctx(tmp_path)))
    assert result.verdict == "failed"
    assert any(f.category == "secret" for f in result.findings)
    assert any(f.category == "permission" for f in result.findings)
    assert result.duration_ms >= 0


def test_security_review_zero_findings_workspace(tmp_path):
    """无 secret / 无 eval / 无 lockfile → verdict=passed, summary 含 '0 findings'。"""
    (tmp_path / "clean.py").write_text('x = 1\n')

    with patch(
        "argos_agent.skills_runtime.builtin.security_review.audit.detect_lockfiles",
        return_value=set(),
    ):
        result = asyncio.run(sr_run({"path": None}, _ctx(tmp_path)))
    assert result.verdict == "passed"
    assert "0 findings" in result.summary


def test_security_review_dep_audit_missing_tool_makes_verdict_failed(tmp_path):
    """Pass 2 缺工具 → error severity finding → verdict=failed(spec D5 防假绿)。"""
    (tmp_path / "package-lock.json").write_text("{}")
    (tmp_path / "clean.py").write_text("x = 1\n")

    def _raise(*a, **kw):
        raise FileNotFoundError("npm")

    with patch("argos_agent.skills_runtime.builtin.security_review.audit.subprocess.run", side_effect=_raise):
        result = asyncio.run(sr_run({"path": None}, _ctx(tmp_path)))
    assert result.verdict == "failed"
    assert any(f.severity == "error" and f.category == "dep_audit" for f in result.findings)
    assert "SUB-PASS SKIPPED" in result.summary or any("SUB-PASS SKIPPED" in f.message for f in result.findings)


def test_security_review_one_pass_failure_does_not_block_others(tmp_path):
    """某 pass 内部异常 → 不阻断其他 pass;verdict=partial(spec §2.4 失败不阻断)。"""
    (tmp_path / "bad.py").write_text('eval("1+1")\n')

    with patch(
        "argos_agent.skills_runtime.builtin.security_review._PASSES",
        [
            ("secrets", lambda ws, ctx: (_ for _ in ()).throw(RuntimeError("boom"))),
            ("permission", lambda ws, ctx: scan_file_for_permission_issues(
                ws / "bad.py", relpath="bad.py", workspace=ws,
            )),
        ],
    ):
        result = asyncio.run(sr_run({"path": None}, _ctx(tmp_path)))
    assert result.verdict in ("partial", "failed")
    assert any("permission" in f.category for f in result.findings)
    assert any("boom" in e for e in result.errors)


# ── dedup / 排序 / trunc(spec §2.4 / D12 / §3)────────────────

def test_security_review_dedup_same_file_line_category_message(tmp_path):
    """同 file:line:category:message → 去重(防 regex 重复命中同 snippet)。"""
    f = tmp_path / "leak.py"
    f.write_text('a = "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789" "AKIAIOSFODNN7EXAMPLE"\n')
    with patch(
        "argos_agent.skills_runtime.builtin.security_review.audit.detect_lockfiles",
        return_value=set(),
    ):
        result = asyncio.run(sr_run({"path": None}, _ctx(tmp_path)))
    cats = [f.category for f in result.findings]
    assert cats.count("secret") == 2


def test_security_review_findings_sorted_error_warning_info(tmp_path):
    """findings 排序:error > warning > info;同 severity 按 file:line(spec §2.4)。"""
    (tmp_path / "a.py").write_text('password = "hunter2hunter2"\n')
    (tmp_path / "b.py").write_text('eval("1+1")\n')
    with patch(
        "argos_agent.skills_runtime.builtin.security_review.audit.detect_lockfiles",
        return_value=set(),
    ):
        result = asyncio.run(sr_run({"path": None}, _ctx(tmp_path)))
    sevs = [f.severity for f in result.findings]
    err_idxs = [i for i, s in enumerate(sevs) if s == "error"]
    warn_idxs = [i for i, s in enumerate(sevs) if s == "warning"]
    if err_idxs and warn_idxs:
        assert max(err_idxs) < min(warn_idxs)


# ── 边界 ───────────────────────────────────────────────────────

def test_security_review_binary_file_skipped_silently(tmp_path):
    """二进制文件 → Pass 1 静默跳 + Pass 3 不扫 → 无 finding。"""
    f = tmp_path / "blob.bin"
    f.write_bytes(b"\x00\x01\xff\xfe")
    with patch(
        "argos_agent.skills_runtime.builtin.security_review.audit.detect_lockfiles",
        return_value=set(),
    ):
        result = asyncio.run(sr_run({"path": None}, _ctx(tmp_path)))
    assert result.verdict == "passed"


def test_security_review_1mb_file_skipped(tmp_path):
    """> 1MB 文件 → Pass 1 跳过;Pass 3 同。"""
    f = tmp_path / "big.py"
    f.write_text("# header\n" + "x = 1\n" * 200_000)
    with patch(
        "argos_agent.skills_runtime.builtin.security_review.audit.detect_lockfiles",
        return_value=set(),
    ):
        result = asyncio.run(sr_run({"path": None}, _ctx(tmp_path)))
    assert result.verdict == "passed"


# ── 路径 scope ─────────────────────────────────────────────────

def test_security_review_with_specific_path(tmp_path):
    """`/security-review src/auth.py` → 只扫该文件。"""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text('token = "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"\n')
    (tmp_path / "other.py").write_text('token = "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"\n')
    with patch(
        "argos_agent.skills_runtime.builtin.security_review.audit.detect_lockfiles",
        return_value=set(),
    ):
        result = asyncio.run(sr_run({"path": "src/auth.py"}, _ctx(tmp_path)))
    files = {f.file for f in result.findings}
    assert "src/auth.py" in files or "auth.py" in files
    assert all("other" not in (f.file or "") for f in result.findings)


# ── summary format ─────────────────────────────────────────────

def test_security_review_summary_contains_finding_count(tmp_path):
    """summary 含 finding count + verdict 字符串(spec §2.4 输出例)。"""
    (tmp_path / "leak.py").write_text('token = "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"\n')
    with patch(
        "argos_agent.skills_runtime.builtin.security_review.audit.detect_lockfiles",
        return_value=set(),
    ):
        result = asyncio.run(sr_run({"path": None}, _ctx(tmp_path)))
    assert "failed" in result.summary
    assert "1 finding" in result.summary
