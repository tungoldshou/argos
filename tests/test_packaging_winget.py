from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
WINGET_DIR = ROOT / "packaging" / "winget"
INSTALLER = WINGET_DIR / "tungoldshou.argos.installer.yaml"
LOCALE = WINGET_DIR / "tungoldshou.argos.locale.en-US.yaml"
DEFAULT = WINGET_DIR / "tungoldshou.argos.yaml"
BUMP_WINGET_YML = ROOT / ".github" / "workflows" / "bump-winget-manifest.yml"
VERSION = (ROOT / "packaging" / "VERSION").read_text().strip()


def test_winget_manifest_files_exist():
    assert WINGET_DIR.exists(), f"缺 {WINGET_DIR}"
    for p in (INSTALLER, LOCALE, DEFAULT):
        assert p.exists(), f"缺 {p.name}"


def test_winget_installer_yaml_has_required_fields():
    txt = INSTALLER.read_text()
    for f in ("PackageIdentifier: tungoldshou.argos",
              f"PackageVersion: {VERSION}",
              "ManifestType: installer",
              "ManifestVersion: 1.6.0",
              "Installers:",
              "Architecture: x64",
              "InstallerType: zip",
              "InstallerUrl:",
              "InstallerSha256:",
              "InstallBehavior:",
              "UpgradeBehavior: install"):
        assert f in txt, f"installer.yaml 缺 {f!r}"
    assert "UpgradeCommands:" not in txt


def test_winget_locale_yaml_has_description():
    txt = LOCALE.read_text()
    assert "PackageLocale: en-US" in txt
    assert "Description: |" in txt, "locale 缺 Description 长描述"
    m = txt.find("Description: |")
    chunk = txt[m:m+500]
    assert chunk.count("\n") >= 5, f"locale description 太短;got:\n{chunk[:200]}"


def test_winget_locale_does_not_claim_unpublished_channels_are_live():
    txt = LOCALE.read_text()
    assert "Homebrew Cask or the curl one-liner" not in txt
    assert "Linux via pip, AppImage, .deb, or .rpm" not in txt


def test_winget_version_yaml_points_to_default_locale():
    txt = DEFAULT.read_text()
    assert "ManifestType: version" in txt
    assert "DefaultLocale: en-US" in txt
    assert "PackageLocale:" not in txt


def test_winget_default_locale_yaml_declares_manifest_type():
    txt = LOCALE.read_text()
    assert "ManifestType: defaultLocale" in txt
    assert "ManifestVersion: 1.6.0" in txt


def test_winget_manifest_yaml_parseable():
    import yaml
    for p in (INSTALLER, LOCALE, DEFAULT):
        try:
            doc = yaml.safe_load(p.read_text())
        except yaml.YAMLError as e:
            pytest.fail(f"{p.name} YAML 解析失败:{e}")
        assert isinstance(doc, dict), f"{p.name} 解析后非 dict;got {type(doc)}"

    installer = yaml.safe_load(INSTALLER.read_text())
    assert installer["UpgradeBehavior"] in {"install", "uninstallPrevious", "deny"}


def test_bump_winget_workflow_fails_when_windows_digest_missing():
    txt = BUMP_WINGET_YML.read_text()
    assert "[ -n \"${SHA256_WIN:-}\" ]" in txt
    assert "exit 1" in txt


def test_bump_winget_workflow_dispatch_requires_tag_input():
    txt = BUMP_WINGET_YML.read_text()
    assert "workflow_dispatch:" in txt
    assert "tag:" in txt
    assert "required: true" in txt
    assert "github.event.release.tag_name || inputs.tag" in txt


def test_bump_winget_workflow_fails_when_manifest_file_missing():
    txt = BUMP_WINGET_YML.read_text()
    assert "|| continue" not in txt
    assert "missing winget manifest" in txt
