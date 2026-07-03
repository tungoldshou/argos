"""Internal documentation."""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
RELEASE_YML = ROOT / ".github" / "workflows" / "release.yml"


def test_release_workflow_pins_setup_python_v4():
    """Internal documentation."""
    txt = RELEASE_YML.read_text()
    assert "actions/setup-python@v5" not in txt, "release.yml 仍用 @v5(0 jobs bug 没修)"
    assert "actions/setup-python@v4" in txt, "release.yml 缺 actions/setup-python@v4 pin"


def test_release_workflow_has_three_os_jobs():
    """Internal documentation."""
    txt = RELEASE_YML.read_text()
    for job in ("build-macos:", "build-linux:", "build-windows:"):
        assert job in txt, f"release.yml 缺 {job}"


def test_release_workflow_uses_gh_release_create():
    """Internal documentation."""
    txt = RELEASE_YML.read_text()
    assert "gh release create" in txt, "release.yml 缺 gh release create(仍用 softprops?)"
    for line in txt.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("uses:") or stripped.startswith("- uses:"):
            assert "softprops" not in line,\
                f"release.yml 仍 uses: softprops(line: {line!r})"


def test_release_workflow_no_softprops_action_uses():
    """Internal documentation."""
    txt = RELEASE_YML.read_text()
    for line in txt.splitlines():
        s = line.lstrip()
        if s.startswith("uses:") or s.startswith("- uses:"):
            assert "softprops" not in line, f"uses: 仍引 softprops:{line!r}"


def test_release_workflow_uses_setup_uv_v4():
    """Internal documentation."""
    txt = RELEASE_YML.read_text()
    assert "astral-sh/setup-uv@v4" in txt


def test_release_workflow_is_manual_for_binary_assets():
    """Internal documentation."""
    txt = RELEASE_YML.read_text()
    assert "workflow_dispatch:" in txt
    assert "tags:" not in txt
    assert "'v*'" not in txt and '"v*"' not in txt


def test_release_workflow_hashes_downloaded_artifact_files_recursively():
    """Internal documentation."""
    txt = RELEASE_YML.read_text()
    assert "sha256sum -- * > SHA256SUMS" not in txt
    assert "while IFS= read -r asset" in txt
    assert "done < release-assets.txt > SHA256SUMS" in txt


def test_release_workflow_uses_exact_release_asset_manifest():
    """Internal documentation."""
    txt = RELEASE_YML.read_text()
    assert "release-assets.txt" in txt
    for expected in (
        "dist-macos/Argos-${VERSION}-arm64-mac.tar.gz",
        "dist-linux/Argos-${VERSION}-x86_64.AppImage",
        "dist-linux/argos_${VERSION}_amd64.deb",
        "dist-linux/argos-${VERSION}-1.x86_64.rpm",
        "dist-windows/Argos-${VERSION}-x86_64-windows.zip",
        "dist-windows/Argos-${VERSION}-x86_64.msi.zip",
    ):
        assert expected in txt
    for broad_glob in (
        '-name "*.tar.gz"',
        '-name "*.AppImage"',
        '-name "*.deb"',
        '-name "*.rpm"',
        '-name "*.zip"',
        '-name "*.msi.zip"',
    ):
        assert broad_glob not in txt


def test_release_workflow_fails_when_no_downloaded_artifacts_exist():
    """Internal documentation."""
    txt = RELEASE_YML.read_text()
    assert "ERROR: required release asset missing" in txt
    assert "[ \"$missing\" -eq 0 ] || exit 1" in txt


def test_release_workflow_fails_when_only_checksum_assets_are_releasable():
    """Internal documentation."""
    txt = RELEASE_YML.read_text()
    assert "ERROR: no releasable assets found" in txt
    assert "grep -Ev '(^|/)SHA256SUMS$'" in txt


def test_release_workflow_upload_artifacts_fail_when_dist_is_empty():
    """Internal documentation."""
    txt = RELEASE_YML.read_text()
    assert txt.count("actions/upload-artifact@v4") == 3
    assert txt.count("if-no-files-found: error") >= 3
