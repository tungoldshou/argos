"""Internal documentation."""
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
    """Internal documentation."""
    txt = SCRIPT.read_text()
    assert "pyinstaller" in txt
    assert "--onefile" in txt
    assert "--name argos" in txt
    assert "--console" in txt
    assert "schema.sql;argos/memory" in txt, "Windows add-data 应 ; 分隔"


def test_build_windows_script_packs_zip_and_optional_msi():
    """Internal documentation."""
    txt = SCRIPT.read_text()
    assert "Compress-Archive" in txt
    assert not re.search(r'^\s*zip\s+"Argos-', txt, re.M)
    assert "-x86_64-windows.zip" in txt
    assert "candle" in txt, "脚本缺 candle(WiX 简化方案)"
    assert "light" in txt, "脚本缺 light(WiX 简化方案)"


def test_build_windows_script_strips_release_tag_v_prefix():
    """Internal documentation."""
    txt = SCRIPT.read_text()
    assert 'ARGOS_VERSION="${ARGOS_VERSION#v}"' in txt


def test_build_windows_script_excludes_dead_stacks():
    """Internal documentation."""
    txt = SCRIPT.read_text()
    for dead in ("langchain", "langgraph", "fastapi", "uvicorn"):
        assert f"--exclude-module {dead}" in txt, f"脚本缺 --exclude-module {dead}"
