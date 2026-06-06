"""打包 C 阶段 — Linux build script 结构测试(plan T3)。"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "packaging" / "build_linux.sh"


def test_build_linux_script_exists_and_executable():
    assert SCRIPT.exists(), f"缺 {SCRIPT}"
    import os
    import stat
    mode = SCRIPT.stat().st_mode
    assert mode & stat.S_IXUSR, f"{SCRIPT.name} 不可执行 (mode={oct(mode)})"


def test_build_linux_script_runs_pyinstaller_onefile():
    """脚本 grep 含 pyinstaller + --onefile + --console。"""
    txt = SCRIPT.read_text()
    assert "pyinstaller" in txt, "脚本缺 pyinstaller 调用"
    assert "--onefile" in txt, "脚本缺 --onefile"
    assert "--console" in txt, "脚本缺 --console (TUI 需 console)"
    assert "--name argos" in txt, "脚本缺 --name argos"


def test_build_linux_script_packs_appimage_deb_rpm():
    """脚本 grep 含 appimagetool + dpkg-deb --build + rpmbuild -bb。"""
    txt = SCRIPT.read_text()
    assert "appimagetool" in txt, "脚本缺 appimagetool 调用"
    assert "dpkg-deb --build" in txt, "脚本缺 dpkg-deb --build"
    assert "rpmbuild" in txt and "-bb" in txt, "脚本缺 rpmbuild -bb"


def test_build_linux_script_reads_argos_version():
    """脚本 grep 含 ARGOS_VERSION env 读取 + packaging/VERSION fallback。"""
    txt = SCRIPT.read_text()
    assert "${ARGOS_VERSION:-}" in txt, "脚本缺 ARGOS_VERSION env fallback"
    assert "cat packaging/VERSION" in txt, "脚本缺 packaging/VERSION fallback"


def test_build_linux_script_excludes_dead_stacks():
    """脚本排除 langchain/langgraph/fastapi/uvicorn(沿用 build_arm64.sh)。"""
    txt = SCRIPT.read_text()
    for dead in ("langchain", "langgraph", "fastapi", "uvicorn"):
        assert f"--exclude-module {dead}" in txt, f"脚本缺 --exclude-module {dead}"


def test_build_linux_script_adds_data_files():
    """脚本显式 add schema.sql / VERSION / Info.plist(沿用 arm64 spec)。"""
    txt = SCRIPT.read_text()
    for data in ("schema.sql", "packaging/VERSION", "packaging/Info.plist"):
        assert data in txt, f"脚本缺 {data} add-data"
