"""packaging/install.sh 单元测试。

通过把脚本里"调外部命令"的函数 stub 化,测纯逻辑分支。
实现:把 install.sh 拆成可被 source 的 shell 函数(顶部 set -e 后做边界检查),
测试用 bash -c 'source packaging/install.sh; _test_* ...' 跑。

MVP:本任务测 3 个分支:
1. uname -m = arm64 → 进入下载分支
2. uname -m = x86_64 → 友好退出("not yet supported")
3. uname -m = arm64 但 OS != Darwin → 友好退出
"""
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT = Path(__file__).parent.parent / "packaging" / "install.sh"


def test_script_exists():
    assert SCRIPT.exists(), f"缺少 {SCRIPT}"


def test_syntax_check():
    """bash -n 应不报错(语法正确)。"""
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 0, f"bash -n 失败: {result.stderr}"


def test_x86_64_exits_with_friendly_message(tmp_path):
    """x86_64 架构应友好退出,exit 1。"""
    # 直接 source 脚本然后用 stub uname
    src = SCRIPT.read_text()
    # 在脚本顶部注入 stub uname / curl
    stubbed = (
        'uname() { echo "x86_64"; }\n'
        'export -f uname\n'
        + src
    )
    result = subprocess.run(
        ["bash", "-c", stubbed],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0, f"x86_64 应退出非 0,实际 {result.returncode}: {result.stdout}"
    out = (result.stdout + result.stderr).lower()
    assert "not yet supported" in out or "x86_64" in out, (
        f"未给友好提示: {out!r}"
    )


def test_non_darwin_exits_with_friendly_message(tmp_path):
    """arm64 + Linux 应友好退出。"""
    src = SCRIPT.read_text()
    stubbed = (
        'uname() {\n'
        '  case "$1" in\n'
        '    -m) echo "arm64" ;;\n'
        '    -s) echo "Linux" ;;\n'
        '  esac\n'
        '}\n'
        'export -f uname\n'
        + src
    )
    result = subprocess.run(
        ["bash", "-c", stubbed],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0
    out = (result.stdout + result.stderr).lower()
    assert "darwin" in out or "macos" in out, f"未给 macOS 提示: {out!r}"
