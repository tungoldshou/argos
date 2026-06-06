"""打包 C 阶段 — install-deb.sh 结构测试(plan T5)。

沿用 B 阶段 packaging/install.sh 测试风格(契约 §5 锁):
  1. 脚本存在
  2. 走 dpkg -i (不是 tar / brew / pip)
  3. SHA256 校验(对齐 B 阶段)
"""
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
    """脚本走 dpkg -i 装 + apt-get install -f -y 修依赖(spec §7 锁)。"""
    txt = SCRIPT.read_text()
    assert "dpkg -i" in txt, "脚本缺 dpkg -i 装包"
    assert "apt-get install -f" in txt, "脚本缺 apt-get install -f 修依赖"


def test_install_deb_script_uses_sha256_verification():
    """脚本含 SHA256 校验(沿用 B 阶段 install.sh 模式)。"""
    txt = SCRIPT.read_text()
    assert "sha256sum" in txt, "脚本缺 sha256sum 校验"
    assert "SHA256SUMS" in txt or "SHA256" in txt, "脚本缺 SHA256SUMS 资产拉"
    assert "mismatch" in txt.lower() or "verified" in txt.lower(), "脚本缺 mismatch/verified 提示"
