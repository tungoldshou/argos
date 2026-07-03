"""Internal documentation."""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
TAP_DIR = ROOT / "packaging" / "homebrew-tap"
LEGACY_CASK = ROOT / "packaging" / "homebrew" / "argos.rb"
FORMULA = TAP_DIR / "Formula" / "argos.rb"
CASK = TAP_DIR / "Casks" / "argos.rb"
BUMP_YML = ROOT / ".github" / "workflows" / "bump-homebrew-formula.yml"
BUMP_WINGET_YML = ROOT / ".github" / "workflows" / "bump-winget-manifest.yml"



def test_homebrew_tap_directory_exists():
    assert TAP_DIR.exists(), f"缺 {TAP_DIR}"
    assert (TAP_DIR / "README.md").exists(), "tap 缺 README.md"


def test_homebrew_tap_readme_marks_channel_unpublished():
    """Internal documentation."""
    txt = (TAP_DIR / "README.md").read_text()
    assert "not published yet" in txt.lower()
    assert "draft" in txt.lower()
    assert "published AppImage" not in txt


def test_homebrew_formula_argos_contains_required_fields():
    """Internal documentation."""
    assert FORMULA.exists(), f"缺 {FORMULA}"
    txt = FORMULA.read_text()
    for field in ("desc ", "homepage ", "url ", "sha256 ", 'license "MIT"',
                  "depends_on", '"fuse" => :linux', "def install", "bin.install"):
        assert field in txt, f"Formula 缺 {field!r};got:\n{txt}"


def test_homebrew_cask_argos_contains_app_directive():
    """Internal documentation."""
    assert CASK.exists(), f"缺 {CASK}"
    txt = CASK.read_text()
    assert 'app "Argos.app"' in txt, "Cask 缺 app \"Argos.app\""
    assert "zap trash:" in txt, "Cask 缺 zap trash:"


def test_legacy_homebrew_cask_is_marked_template_only():
    """Internal documentation."""
    txt = LEGACY_CASK.read_text()
    assert "template-only" in txt.lower()
    assert "not published" in txt.lower()


# --- T7 part 2:bump workflow ---

def test_bump_homebrew_workflow_triggers_on_release():
    """Internal documentation."""
    if not BUMP_YML.exists():
        pytest.skip(f"缺 {BUMP_YML} — plan T7 任务")
    txt = BUMP_YML.read_text()
    assert "release:" in txt
    assert "types: [published]" in txt or "types:\n          - published" in txt or\
           "types:\n    - published" in txt or "published" in txt,\
        f"bump workflow 缺 release.published 触发"


def test_bump_homebrew_workflow_uses_secrets_for_token():
    """Internal documentation."""
    txt = BUMP_YML.read_text()
    assert "HOMEBREW_TAP_TOKEN" in txt, "bump 缺 HOMEBREW_TAP_TOKEN 引用"


def test_bump_homebrew_workflow_sets_token_gate_env():
    """Internal documentation."""
    txt = BUMP_YML.read_text()
    assert "HAS_TOKEN:" in txt
    assert "secrets.HOMEBREW_TAP_TOKEN" in txt


def test_bump_homebrew_workflow_dispatch_requires_tag_input():
    """Internal documentation."""
    txt = BUMP_YML.read_text()
    assert "workflow_dispatch:" in txt
    assert "tag:" in txt
    assert "required: true" in txt
    assert "github.event.release.tag_name || inputs.tag" in txt


def test_bump_homebrew_workflow_fails_when_release_digests_missing():
    """Internal documentation."""
    txt = BUMP_YML.read_text()
    assert "[ -n \"${SHA256_APPIMAGE:-}\" ]" in txt
    assert "[ -n \"${SHA256_ARM64:-}\" ]" in txt
    assert "缺 AppImage digest" in txt
    assert "缺 macOS arm64 digest" in txt
    assert "exit 1" in txt


def test_bump_homebrew_workflow_replaces_existing_sha_values():
    """Internal documentation."""
    txt = BUMP_YML.read_text()
    assert 's/sha256 \\".*\\"/sha256' in txt
    assert 's/sha256 \\"PLACEHOLDER_FROM_BUMP\\"' not in txt


def test_bump_winget_manifest_workflow_exists():
    """Internal documentation."""
    if not BUMP_WINGET_YML.exists():
        pytest.skip(f"缺 {BUMP_WINGET_YML} — plan T7 任务")
    txt = BUMP_WINGET_YML.read_text()
    assert "release:" in txt
    assert "packaging/winget" in txt, "bump-winget 缺 packaging/winget 路径"
    assert "InstallerUrl" in txt or "PackageVersion" in txt,\
        "bump-winget 缺 version/URL 注入逻辑"
