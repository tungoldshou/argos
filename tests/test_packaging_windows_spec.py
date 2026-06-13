"""打包 C 阶段 — Windows build script 结构测试(plan T4)。"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "packaging" / "build_windows.sh"


def test_build_windows_script_exists_and_executable():
    assert SCRIPT.exists(), f"缺 {SCRIPT}"
    import os, stat
    mode = SCRIPT.stat().st_mode
    assert mode & stat.S_IXUSR, f"{SCRIPT.name} 不可执行 (mode={oct(mode)})"


def test_build_windows_script_runs_pyinstaller_onefile():
    """脚本 grep 含 pyinstaller + --onefile + --name argos + --console。"""
    txt = SCRIPT.read_text()
    assert "pyinstaller" in txt
    assert "--onefile" in txt
    assert "--name argos" in txt
    assert "--console" in txt
    # Windows add-data 用 ; 分隔(不是 :)
    assert "schema.sql;argos/memory" in txt, "Windows add-data 应 ; 分隔"


def test_build_windows_script_packs_zip_and_optional_msi():
    """脚本 grep 含 zip "Argos- + candle/light (msi 可选)。"""
    txt = SCRIPT.read_text()
    assert 'zip "Argos-' in txt, "脚本缺 zip \"Argos-...-windows.zip\""
    assert "-x86_64-windows.zip" in txt
    assert "candle" in txt, "脚本缺 candle(WiX 简化方案)"
    assert "light" in txt, "脚本缺 light(WiX 简化方案)"


def test_build_windows_script_excludes_dead_stacks():
    """脚本排除 langchain/langgraph/fastapi/uvicorn。"""
    txt = SCRIPT.read_text()
    for dead in ("langchain", "langgraph", "fastapi", "uvicorn"):
        assert f"--exclude-module {dead}" in txt, f"脚本缺 --exclude-module {dead}"
