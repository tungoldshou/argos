"""打包 C 阶段 — WinGet manifest 测试(plan T8)。"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
WINGET_DIR = ROOT / "packaging" / "winget"
INSTALLER = WINGET_DIR / "tungoldshou.argos.installer.yaml"
LOCALE = WINGET_DIR / "tungoldshou.argos.locale.en-US.yaml"
DEFAULT = WINGET_DIR / "tungoldshou.argos.yaml"


def test_winget_manifest_files_exist():
    """3 件 manifest 必在(plan T8 锁)。"""
    assert WINGET_DIR.exists(), f"缺 {WINGET_DIR}"
    for p in (INSTALLER, LOCALE, DEFAULT):
        assert p.exists(), f"缺 {p.name}"


def test_winget_installer_yaml_has_required_fields():
    """tungoldshou.argos.installer.yaml 必含 PackageIdentifier / Version / ManifestType installer /
    ManifestVersion 1.6.0 / Installers list。"""
    txt = INSTALLER.read_text()
    for f in ("PackageIdentifier: tungoldshou.argos",
              "PackageVersion: 0.1.0",
              "ManifestType: installer",
              "ManifestVersion: 1.6.0",
              "Installers:",
              "Architecture: x64",
              "InstallerType: zip",
              "InstallerUrl:",
              "InstallerSha256:",
              "InstallBehavior:",
              "UpgradeBehavior:"):
        assert f in txt, f"installer.yaml 缺 {f!r}"


def test_winget_locale_yaml_has_description():
    """locale en-US 必含长 Description: | 段(winget schema 1.6 强制)。"""
    txt = LOCALE.read_text()
    assert "PackageLocale: en-US" in txt
    assert "Description: |" in txt, "locale 缺 Description 长描述"
    # 至少 100 字符(winget 拒绝过短)
    m = txt.find("Description: |")
    chunk = txt[m:m+500]
    assert chunk.count("\n") >= 5, f"locale description 太短;got:\n{chunk[:200]}"


def test_winget_default_locale_yaml_present():
    """tungoldshou.argos.yaml 必含 ManifestType: defaultLocale。"""
    txt = DEFAULT.read_text()
    assert "ManifestType: defaultLocale" in txt
    assert "PackageLocale: en-US" in txt


def test_winget_manifest_yaml_parseable():
    """3 件文件能被 yaml.safe_load 解析(spec §8 锁 schema 合法;不调 winget 工具)。"""
    import yaml
    for p in (INSTALLER, LOCALE, DEFAULT):
        try:
            doc = yaml.safe_load(p.read_text())
        except yaml.YAMLError as e:
            pytest.fail(f"{p.name} YAML 解析失败:{e}")
        assert isinstance(doc, dict), f"{p.name} 解析后非 dict;got {type(doc)}"
