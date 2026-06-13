"""`/simplify` 3-pass 单元测试(spec §2.5 / D6 / D7)。"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from argos.skills_runtime.analysis import (
    AnalysisSkillContext,
    AnalysisSkillResult,
)
from argos.skills_runtime import registry
from argos.skills_runtime.builtin.simplify import run as simp_run
from argos.skills_runtime.builtin.simplify.duplication import (
    detect_duplicates,
)
from argos.skills_runtime.builtin.simplify.complexity import (
    detect_complex_functions,
)
from argos.skills_runtime.builtin.simplify.dead_code import detect_dead_code


@pytest.fixture(autouse=True)
def _clean():
    registry._reset_registry()
    yield
    registry._reset_registry()


def _ctx(workspace: Path) -> AnalysisSkillContext:
    return AnalysisSkillContext(workspace=workspace, approval_level="auto", run_id="r1")


# ── Pass 1 duplicate(spec §2.5 Pass 1)────────────────────────

def test_duplicate_token_level_same_block_3_files(tmp_path):
    """完全相同 25-token 块在 3 个文件 → 1 finding(3 occurrences)。"""
    block = "def validate_user_input(value, max_length=100, *, raise_on_missing=True):\n    if not value:\n        return False\n"
    for name in ("a.py", "b.py", "c.py"):
        (tmp_path / name).write_text(block)
    findings = detect_duplicates(tmp_path)
    assert any(f.category == "duplicate" for f in findings)


def test_duplicate_similar_blocks_no_match(tmp_path):
    """改 1 字符的 30-token 函数体 → token-level 不匹(0 duplicate finding)。"""
    for i, name in enumerate(("a.py", "b.py")):
        body = f"def f(x):\n    y = x + {i}\n    return y * 2\n"
        (tmp_path / name).write_text(body)
    findings = detect_duplicates(tmp_path)
    assert not any(f.category == "duplicate" for f in findings)


def test_duplicate_whitelist_tests_dir_skipped(tmp_path):
    """tests/fixtures/** 命中 → 跳过(白名单,spec §2.5)。"""
    (tmp_path / "tests" / "fixtures").mkdir(parents=True)
    block = "def f():\n    return 'value-to-match-twice-twice-twice-twice-twice-twice-twice-twice-twice'\n"
    (tmp_path / "tests" / "fixtures" / "a.py").write_text(block)
    (tmp_path / "tests" / "fixtures" / "b.py").write_text(block)
    (tmp_path / "tests" / "fixtures" / "c.py").write_text(block)
    findings = detect_duplicates(tmp_path)
    assert not any(f.category == "duplicate" for f in findings)


def test_duplicate_large_file_skipped(tmp_path):
    """> 5000 token 文件 → 跳过该 pass(防 token 化慢)。"""
    big = "x = 1\n" * 3000
    f = tmp_path / "big.py"
    f.write_text(big)
    findings = detect_duplicates(tmp_path)
    assert not any(f.category == "duplicate" for f in findings)


# ── Pass 2 complexity(spec §2.5 Pass 2 / D6)────────────────

def test_complexity_16_branches_yields_finding(tmp_path):
    """函数体含 16 个分支 → 1 finding(severity=warning)。"""
    body_lines = ["def f(x):"] + [f"    if x > {i}:" for i in range(8)] + [f"    elif x == {i}:" for i in range(8)] + ["        return x"]
    f = tmp_path / "comp.py"
    f.write_text("\n".join(body_lines) + "\n")
    findings = detect_complex_functions(tmp_path)
    assert any(f.category == "complexity" and f.severity == "warning" for f in findings)


def test_complexity_under_threshold_no_finding(tmp_path):
    """< 15 分支 → 0 finding。"""
    body_lines = ["def f(x):"] + [f"    if x > {i}:" for i in range(5)] + ["        return x"]
    f = tmp_path / "simple.py"
    f.write_text("\n".join(body_lines) + "\n")
    findings = detect_complex_functions(tmp_path)
    assert not any(f.category == "complexity" for f in findings)


def test_complexity_tests_whitelist_skipped(tmp_path):
    """tests/ 命中 → 跳过(spec §2.5)。"""
    (tmp_path / "tests").mkdir()
    body_lines = ["def f(x):"] + [f"    if x > {i}:" for i in range(20)] + ["        return x"]
    f = tmp_path / "tests" / "test_x.py"
    f.write_text("\n".join(body_lines) + "\n")
    findings = detect_complex_functions(tmp_path)
    assert not any(f.category == "complexity" for f in findings)


# ── Pass 3 dead code(spec §2.5 Pass 3 / D7)─────────────────

def test_dead_code_unused_function_detected(tmp_path):
    """未使用的 public 函数 → 1 info finding。"""
    (tmp_path / "mod.py").write_text(
        "def unused_func(x, y, z):\n    return x + y + z\n\n"
        "def main():\n    return 42\n"
    )
    findings = detect_dead_code(tmp_path)
    assert any(f.severity == "info" and f.category == "dead_code" and "unused_func" in f.message for f in findings)


def test_dead_code_used_function_not_flagged(tmp_path):
    """被用的函数 → 0 finding。"""
    (tmp_path / "mod.py").write_text(
        "def used_func():\n    return 1\n\nprint(used_func())\n"
    )
    findings = detect_dead_code(tmp_path)
    assert not any("used_func" in f.message for f in findings)


def test_dead_code_all_whitelist_function_skipped(tmp_path):
    """`__all__` 里的函数 → 跳(导出为 API 表面)。"""
    (tmp_path / "mod.py").write_text(
        "__all__ = ['public_api']\n"
        "def public_api(x, y, z):\n    return x + y + z\n"
    )
    findings = detect_dead_code(tmp_path)
    assert not any("public_api" in f.message for f in findings)


def test_dead_code_cli_main_skipped(tmp_path):
    """cli.py / __main__.py 文件 → 跳过(main entry point 常被反射调)。"""
    (tmp_path / "cli.py").write_text(
        "def entry_point(x, y, z):\n    return x + y + z\n"
    )
    findings = detect_dead_code(tmp_path)
    assert not any("entry_point" in f.message for f in findings)


# ── 整合 run() ──────────────────────────────────────────────

def test_simplify_full_pipeline_planted_duplicate(tmp_path):
    """planted duplicate → 1 finding → verdict=failed。"""
    block = "def validate_user_input(value, max_length=100, *, raise_on_missing=True):\n    if not value:\n        return False\n"
    for name in ("a.py", "b.py", "c.py"):
        (tmp_path / name).write_text(block)
    result = asyncio.run(simp_run({"path": None}, _ctx(tmp_path)))
    assert result.verdict == "failed"
    assert any(f.category == "duplicate" for f in result.findings)


def test_simplify_zero_findings_workspace(tmp_path):
    """空 workspace → verdict=passed, summary 含 '0 findings'。"""
    result = asyncio.run(simp_run({"path": None}, _ctx(tmp_path)))
    assert result.verdict == "passed"
    assert "0 findings" in result.summary


def test_simplify_top_10_truncation(tmp_path):
    """> 10 finding → top-N 截断(spec §2.5 D6)。"""
    for i in range(15):
        block = f"def fn_{i}():\n    return '{'x' * 50}'\n" * 3
        (tmp_path / f"a_{i}.py").write_text(block)
        (tmp_path / f"b_{i}.py").write_text(block)
        (tmp_path / f"c_{i}.py").write_text(block)
    result = asyncio.run(simp_run({"path": None, "top": 5}, _ctx(tmp_path)))
    assert len(result.findings) <= 5
