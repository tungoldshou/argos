"""打包 C 阶段 — Homebrew tap + bump workflow 测试(plan T6+T7)。"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
TAP_DIR = ROOT / "packaging" / "homebrew-tap"
FORMULA = TAP_DIR / "Formula" / "argos.rb"
CASK = TAP_DIR / "Casks" / "argos.rb"
BUMP_YML = ROOT / ".github" / "workflows" / "bump-homebrew-formula.yml"
BUMP_WINGET_YML = ROOT / ".github" / "workflows" / "bump-winget-manifest.yml"


# --- T6 part 1:tap 骨架 ---

def test_homebrew_tap_directory_exists():
    assert TAP_DIR.exists(), f"缺 {TAP_DIR}"
    assert (TAP_DIR / "README.md").exists(), "tap 缺 README.md"


def test_homebrew_formula_argos_contains_required_fields():
    """Formula/argos.rb 必含 desc / homepage / url / sha256 / license / fuse 依赖。"""
    assert FORMULA.exists(), f"缺 {FORMULA}"
    txt = FORMULA.read_text()
    for field in ("desc ", "homepage ", "url ", "sha256 ", 'license "MIT"',
                  "depends_on", '"fuse" => :linux', "def install", "bin.install"):
        assert field in txt, f"Formula 缺 {field!r};got:\n{txt}"


def test_homebrew_cask_argos_contains_app_directive():
    """Casks/argos.rb 含 app 'Argos.app' + zap trash:。"""
    assert CASK.exists(), f"缺 {CASK}"
    txt = CASK.read_text()
    assert 'app "Argos.app"' in txt, "Cask 缺 app \"Argos.app\""
    assert "zap trash:" in txt, "Cask 缺 zap trash:"


# --- T7 part 2:bump workflow ---

def test_bump_homebrew_workflow_triggers_on_release():
    """bump-homebrew-formula.yml 必含 on: release: types: [published]。"""
    if not BUMP_YML.exists():
        pytest.skip(f"缺 {BUMP_YML} — plan T7 任务")
    txt = BUMP_YML.read_text()
    assert "release:" in txt
    assert "types: [published]" in txt or "types:\n          - published" in txt or \
           "types:\n    - published" in txt or "published" in txt, \
        f"bump workflow 缺 release.published 触发"


def test_bump_homebrew_workflow_uses_secrets_for_token():
    """bump-homebrew 必含 secrets.HOMEBREW_TAP_TOKEN(或注释占位)。"""
    txt = BUMP_YML.read_text()
    assert "HOMEBREW_TAP_TOKEN" in txt, "bump 缺 HOMEBREW_TAP_TOKEN 引用"


def test_bump_winget_manifest_workflow_exists():
    """bump-winget-manifest.yml 存在。"""
    if not BUMP_WINGET_YML.exists():
        pytest.skip(f"缺 {BUMP_WINGET_YML} — plan T7 任务")
    txt = BUMP_WINGET_YML.read_text()
    assert "release:" in txt
    assert "packaging/winget" in txt, "bump-winget 缺 packaging/winget 路径"
    assert "InstallerUrl" in txt or "PackageVersion" in txt, \
        "bump-winget 缺 version/URL 注入逻辑"
