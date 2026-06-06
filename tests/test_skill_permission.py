"""Pass 3 permission check 单元测试(spec §2.4 Pass 3)。"""
from __future__ import annotations

from pathlib import Path

import pytest

from argos_agent.skills_runtime.builtin.security_review.permission import (
    scan_file_for_permission_issues,
    PYTHON_PATTERNS,
    JS_TS_PATTERNS,
)


def test_python_os_system_detected(tmp_path):
    f = tmp_path / "script.py"
    f.write_text('import os\nos.system("ls")\n')
    findings = scan_file_for_permission_issues(f, relpath="script.py", workspace=tmp_path)
    assert any(f.severity == "warning" and "os.system" in f.message.lower() for f in findings)


def test_python_subprocess_shell_true_detected(tmp_path):
    f = tmp_path / "script.py"
    f.write_text('import subprocess\nsubprocess.Popen(cmd, shell=True)\n')
    findings = scan_file_for_permission_issues(f, relpath="script.py", workspace=tmp_path)
    assert any(f.severity == "error" and "shell=true" in f.message.lower() for f in findings)


def test_python_eval_detected(tmp_path):
    f = tmp_path / "script.py"
    f.write_text('eval("1+1")\n')
    findings = scan_file_for_permission_issues(f, relpath="script.py", workspace=tmp_path)
    assert any(f.severity == "error" and "eval" in f.message.lower() for f in findings)


def test_python_exec_detected(tmp_path):
    f = tmp_path / "script.py"
    f.write_text('exec("x=1")\n')
    findings = scan_file_for_permission_issues(f, relpath="script.py", workspace=tmp_path)
    assert any(f.severity == "error" and "exec" in f.message.lower() for f in findings)


def test_python_pickle_detected(tmp_path):
    f = tmp_path / "script.py"
    f.write_text('import pickle\npickle.loads(data)\n')
    findings = scan_file_for_permission_issues(f, relpath="script.py", workspace=tmp_path)
    assert any("pickle" in f.message.lower() for f in findings)


def test_python_import_detected(tmp_path):
    f = tmp_path / "script.py"
    f.write_text('module = __import__("os")\n')
    findings = scan_file_for_permission_issues(f, relpath="script.py", workspace=tmp_path)
    assert any("__import__" in f.message.lower() for f in findings)


# ── JS/TS ───────────────────────────────────────────────────────

def test_js_child_process_exec_detected(tmp_path):
    f = tmp_path / "script.js"
    f.write_text('const { exec } = require("child_process");\nexec("ls");\n')
    findings = scan_file_for_permission_issues(f, relpath="script.js", workspace=tmp_path)
    assert any(f.severity == "error" and "child_process" in f.message.lower() for f in findings)


def test_js_eval_detected(tmp_path):
    f = tmp_path / "script.js"
    f.write_text('eval("1+1");\n')
    findings = scan_file_for_permission_issues(f, relpath="script.js", workspace=tmp_path)
    assert any(f.severity == "error" and "eval" in f.message.lower() for f in findings)


def test_js_new_function_detected(tmp_path):
    f = tmp_path / "script.js"
    f.write_text('const f = new Function("return 1");\n')
    findings = scan_file_for_permission_issues(f, relpath="script.js", workspace=tmp_path)
    assert any(f.severity == "error" and "new function" in f.message.lower() for f in findings)


def test_js_inner_html_warning(tmp_path):
    f = tmp_path / "app.js"
    f.write_text('el.innerHTML = userInput;\n')
    findings = scan_file_for_permission_issues(f, relpath="app.js", workspace=tmp_path)
    assert any(f.severity == "warning" and "innerhtml" in f.message.lower() for f in findings)


# ── whitelist 降级 ──────────────────────────────────────────────

def test_tests_directory_eval_downgraded_to_info(tmp_path):
    """tests/ 路径命中 → severity 降 info(测试代码里 eval 多是合理 fixture)。"""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    f = tests_dir / "test_x.py"
    f.write_text('eval("1+1")\n')
    findings = scan_file_for_permission_issues(f, relpath="tests/test_x.py", workspace=tmp_path)
    # 降级到 info
    assert any(f.severity == "info" and "eval" in f.message.lower() for f in findings)
    assert all(f.severity != "error" for f in findings)


def test_conftest_py_in_tests_downgraded(tmp_path):
    """tests/conftest.py → 降级 info。"""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    f = tests_dir / "conftest.py"
    f.write_text('eval("x=1")\n')
    findings = scan_file_for_permission_issues(f, relpath="tests/conftest.py", workspace=tmp_path)
    assert any(f.severity == "info" for f in findings)


# ── 边界 ─────────────────────────────────────────────────────────

def test_unsupported_language_partial(tmp_path):
    """Go / Java / C++ 等不支持语言 → 1 条 info(spec D15:MVP 仅 Python + JS/TS + Rust)。"""
    f = tmp_path / "main.go"
    f.write_text('package main\n')
    findings = scan_file_for_permission_issues(f, relpath="main.go", workspace=tmp_path)
    # 至少 1 条 info 提示"语言不扫"
    assert any("language not supported" in f.message.lower() for f in findings)


def test_finding_has_snippet_and_line(tmp_path):
    """每条 finding 必含 file/line/snippet。"""
    f = tmp_path / "script.py"
    f.write_text('# comment\neval("x")\n')
    findings = scan_file_for_permission_issues(f, relpath="script.py", workspace=tmp_path)
    fi = next(f for f in findings if "eval" in f.message.lower())
    assert fi.line == 2
    assert fi.file == "script.py"
    assert fi.snippet is not None
