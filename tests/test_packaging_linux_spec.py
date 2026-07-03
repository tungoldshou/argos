"""Internal documentation."""
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
    """Internal documentation."""
    txt = SCRIPT.read_text()
    assert "pyinstaller" in txt, "脚本缺 pyinstaller 调用"
    assert "--onefile" in txt, "脚本缺 --onefile"
    assert "--console" in txt, "脚本缺 --console (TUI 需 console)"
    assert "--name argos" in txt, "脚本缺 --name argos"


def test_build_linux_script_packs_appimage_deb_rpm():
    """Internal documentation."""
    txt = SCRIPT.read_text()
    assert "appimagetool" in txt, "脚本缺 appimagetool 调用"
    assert "dpkg-deb --build" in txt, "脚本缺 dpkg-deb --build"
    assert "rpmbuild" in txt and "-bb" in txt, "脚本缺 rpmbuild -bb"


def test_build_linux_script_fails_when_required_package_assets_are_missing():
    """Internal documentation."""
    txt = SCRIPT.read_text()
    assert "跳 .deb" not in txt
    assert "跳 .rpm" not in txt
    assert "WARN: rpmbuild 失败" not in txt
    assert "FATAL: dpkg-deb not found" in txt
    assert "FATAL: rpmbuild not found" in txt
    assert "FATAL: rpmbuild failed" in txt
    assert "FATAL: RPM missing" in txt
    assert "FATAL: RPM asset missing" in txt
    assert "mv dist/argos-agent-${ARGOS_VERSION}-1.*.\"${RPM_ARCH}\".rpm \\" in txt
    assert "mv dist/argos-agent-${ARGOS_VERSION}-1.*.\"${RPM_ARCH}\".rpm \\\n       \"dist/argos-${ARGOS_VERSION}-1.${RPM_ARCH}.rpm\" 2>/dev/null || true" not in txt


def test_build_linux_script_fails_when_appimage_is_missing():
    """Internal documentation."""
    txt = SCRIPT.read_text()
    assert "跳 AppImage" not in txt
    assert "FATAL: appimagetool" in txt
    assert "FATAL: AppImage missing" in txt


def test_build_linux_script_reads_argos_version():
    """Internal documentation."""
    txt = SCRIPT.read_text()
    assert "${ARGOS_VERSION:-}" in txt, "脚本缺 ARGOS_VERSION env fallback"
    assert "cat packaging/VERSION" in txt, "脚本缺 packaging/VERSION fallback"


def test_build_linux_script_strips_release_tag_v_prefix():
    """Internal documentation."""
    txt = SCRIPT.read_text()
    assert 'ARGOS_VERSION="${ARGOS_VERSION#v}"' in txt


def test_build_linux_script_excludes_dead_stacks():
    """Internal documentation."""
    txt = SCRIPT.read_text()
    for dead in ("langchain", "langgraph", "fastapi", "uvicorn"):
        assert f"--exclude-module {dead}" in txt, f"脚本缺 --exclude-module {dead}"


def test_build_linux_script_adds_data_files():
    """Internal documentation."""
    txt = SCRIPT.read_text()
    for data in ("schema.sql", "packaging/VERSION", "packaging/Info.plist"):
        assert data in txt, f"脚本缺 {data} add-data"
