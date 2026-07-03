"""Internal documentation."""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "packaging" / "install-deb.sh"


def test_install_deb_script_exists_and_executable():
    assert SCRIPT.exists(), f"缺 {SCRIPT}"
    import stat
    mode = SCRIPT.stat().st_mode
    assert mode & stat.S_IXUSR, f"{SCRIPT.name} 不可执行 (mode={oct(mode)})"


def test_install_deb_script_uses_dpkg_i_and_apt_f():
    """Internal documentation."""
    txt = SCRIPT.read_text()
    assert "dpkg -i" in txt, "脚本缺 dpkg -i 装包"
    assert "apt-get install -f" in txt, "脚本缺 apt-get install -f 修依赖"


def test_install_deb_script_uses_sha256_verification():
    """Internal documentation."""
    txt = SCRIPT.read_text()
    assert "sha256sum" in txt, "脚本缺 sha256sum 校验"
    assert "SHA256SUMS" in txt or "SHA256" in txt, "脚本缺 SHA256SUMS 资产拉"
    assert "mismatch" in txt.lower() or "verified" in txt.lower(), "脚本缺 mismatch/verified 提示"


def test_install_deb_script_requires_sha256sums():
    """Internal documentation."""
    txt = SCRIPT.read_text()
    assert "skipping verification" not in txt
    assert "Could not find SHA256SUMS" in txt
    assert "Could not fetch SHA256SUMS" in txt


def test_install_deb_script_is_marked_as_deferred_binary_installer():
    """Internal documentation."""
    header = "\n".join(SCRIPT.read_text().splitlines()[:5]).lower()
    assert "deferred" in header
    assert "not the public launch installer" in header


def test_install_deb_fallback_uses_current_source_install_path():
    """Internal documentation."""
    txt = SCRIPT.read_text()
    assert "brew install --cask argos" not in txt
    assert "brew install argos" not in txt
    assert "pip install argos-agent" not in txt
    assert "winget" not in txt
    assert ".exe zip" not in txt
    assert "git clone https://github.com/tungoldshou/argos" in txt
    assert "uv sync" in txt
