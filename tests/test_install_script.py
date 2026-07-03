"""Internal documentation."""
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT = Path(__file__).parent.parent / "packaging" / "install.sh"
ROOT_INSTALL = Path(__file__).parent.parent / "install.sh"
BUILD_ARM64 = Path(__file__).parent.parent / "packaging" / "build_arm64.sh"


def test_script_exists():
    assert SCRIPT.exists(), f"缺少 {SCRIPT}"


def test_syntax_check():
    """Internal documentation."""
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 0, f"bash -n 失败: {result.stderr}"


def test_install_script_mentions_current_packaging_stage():
    """Internal documentation."""
    text = SCRIPT.read_text()
    assert "#12" not in text
    assert "Deferred binary installer" in text
    assert "Public launch install uses root install.sh" in text


def test_install_script_requires_sha256sums():
    """Internal documentation."""
    text = SCRIPT.read_text()
    assert "skipping verification" not in text
    assert "Could not find SHA256SUMS" in text
    assert "Could not fetch SHA256SUMS" in text


def test_install_script_is_marked_as_deferred_binary_installer():
    """Internal documentation."""
    header = "\n".join(SCRIPT.read_text().splitlines()[:5]).lower()
    assert "deferred" in header
    assert "not the public launch installer" in header


def test_root_install_script_bootstraps_through_uv_tool_only():
    """Internal documentation."""
    assert ROOT_INSTALL.exists(), f"缺少 {ROOT_INSTALL}"
    result = subprocess.run(
        ["bash", "-n", str(ROOT_INSTALL)],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, f"bash -n 失败: {result.stderr}"

    text = ROOT_INSTALL.read_text()
    assert "uv tool install argos-agent" in text
    assert "uv tool upgrade argos-agent" in text
    assert "uv tool dir --bin" in text
    assert '"$TOOL_BIN/argos" --version' in text
    assert "uv tool update-shell" in text
    assert "argos setup" in text

    forbidden = (
        "sudo",
        "/usr/local/bin",
        "packaging/install.sh",
        "Homebrew",
        "WinGet",
        "AppImage",
        ".deb",
        ".rpm",
    )
    for term in forbidden:
        assert term not in text


def test_root_install_script_is_tracked_for_raw_github_install():
    """Internal documentation."""
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "install.sh"],
        capture_output=True,
        text=True,
        cwd=str(ROOT_INSTALL.parent),
        timeout=5,
    )
    assert result.returncode == 0, result.stderr


def test_root_install_script_verifies_installed_argos_without_path(tmp_path):
    """Internal documentation."""
    bin_dir = tmp_path / "bin"
    tool_bin = tmp_path / "uv-tools"
    bin_dir.mkdir()
    tool_bin.mkdir()
    log = tmp_path / "uv.log"

    uv = bin_dir / "uv"
    uv.write_text(
        "#!/usr/bin/env bash\n"
        "echo \"$*\" >> \"$UV_LOG\"\n"
        "case \"$*\" in\n"
        "  'tool list') exit 0 ;;\n"
        "  'tool install argos-agent') exit 0 ;;\n"
        "  'tool upgrade argos-agent') exit 0 ;;\n"
        "  'tool dir --bin') echo \"$UV_TOOL_BIN\"; exit 0 ;;\n"
        "esac\n"
        "exit 2\n",
        encoding="utf-8",
    )
    uv.chmod(0o755)

    argos = tool_bin / "argos"
    argos.write_text("#!/usr/bin/env bash\necho 'argos 0.1.0'\n", encoding="utf-8")
    argos.chmod(0o755)

    result = subprocess.run(
        ["/bin/bash", str(ROOT_INSTALL)],
        capture_output=True,
        text=True,
        timeout=10,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "UV_LOG": str(log),
            "UV_TOOL_BIN": str(tool_bin),
        },
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "argos 0.1.0" in result.stdout
    assert "tool install argos-agent" in log.read_text()
    assert "tool dir --bin" in log.read_text()


def test_root_install_script_bootstraps_uv_when_missing(tmp_path):
    """Internal documentation."""
    bin_dir = tmp_path / "bin"
    uv_bin = tmp_path / "home" / ".local" / "bin"
    tool_bin = tmp_path / "uv-tools"
    bin_dir.mkdir()
    uv_bin.mkdir(parents=True)
    tool_bin.mkdir()
    log = tmp_path / "install.log"

    curl = bin_dir / "curl"
    curl.write_text(
        "#!/usr/bin/env bash\n"
        "echo \"$*\" >> \"$INSTALL_LOG\"\n"
        "cat \"$UV_INSTALLER\"\n",
        encoding="utf-8",
    )
    curl.chmod(0o755)

    uv = uv_bin / "uv"
    uv.write_text(
        "#!/usr/bin/env bash\n"
        "echo \"uv $*\" >> \"$INSTALL_LOG\"\n"
        "case \"$*\" in\n"
        "  'tool list') exit 0 ;;\n"
        "  'tool install argos-agent') exit 0 ;;\n"
        "  'tool dir --bin') echo \"$UV_TOOL_BIN\"; exit 0 ;;\n"
        "esac\n"
        "exit 2\n",
        encoding="utf-8",
    )
    uv.chmod(0o755)

    uv_installer = tmp_path / "uv-install.sh"
    uv_installer.write_text(
        "#!/usr/bin/env bash\n"
        "echo install-uv >> \"$INSTALL_LOG\"\n",
        encoding="utf-8",
    )

    argos = tool_bin / "argos"
    argos.write_text("#!/usr/bin/env bash\necho 'argos 0.1.0'\n", encoding="utf-8")
    argos.chmod(0o755)

    result = subprocess.run(
        ["/bin/bash", str(ROOT_INSTALL)],
        capture_output=True,
        text=True,
        timeout=10,
        env={
            "HOME": str(tmp_path / "home"),
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "INSTALL_LOG": str(log),
            "UV_INSTALLER": str(uv_installer),
            "UV_TOOL_BIN": str(tool_bin),
        },
    )

    assert result.returncode == 0, result.stderr + result.stdout
    lines = log.read_text().splitlines()
    assert any("https://astral.sh/uv/install.sh" in line for line in lines)
    assert "install-uv" in lines
    assert "uv tool install argos-agent" in lines
    assert "argos 0.1.0" in result.stdout


def test_x86_64_exits_with_friendly_message(tmp_path):
    """Internal documentation."""
    src = SCRIPT.read_text()
    stubbed = (
        'uname() { echo "x86_64"; }\n'
        'export -f uname\n'
        + src
    )
    result = subprocess.run(
        ["bash", "-c", stubbed],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0, f"x86_64 应退出非 0,实际 {result.returncode}: {result.stdout}"
    out = (result.stdout + result.stderr).lower()
    assert "not yet supported" in out or "x86_64" in out, (
        f"未给友好提示: {out!r}"
    )


def test_non_darwin_exits_with_friendly_message(tmp_path):
    """Internal documentation."""
    src = SCRIPT.read_text()
    stubbed = (
        'uname() {\n'
        '  case "$1" in\n'
        '    -m) echo "arm64" ;;\n'
        '    -s) echo "Linux" ;;\n'
        '  esac\n'
        '}\n'
        'export -f uname\n'
        + src
    )
    result = subprocess.run(
        ["bash", "-c", stubbed],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0
    out = (result.stdout + result.stderr).lower()
    assert "darwin" in out or "macos" in out, f"未给 macOS 提示: {out!r}"


def test_homebrew_formula_syntax():
    """Internal documentation."""
    formula = Path(__file__).parent.parent / "packaging" / "homebrew" / "argos.rb"
    assert formula.exists(), f"缺少 {formula}"
    result = subprocess.run(
        ["ruby", "-c", str(formula)],
        capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 0, f"ruby -c 失败: {result.stderr}"


def test_build_arm64_uses_release_version_for_app_plist():
    """Internal documentation."""
    text = BUILD_ARM64.read_text()
    assert 'ARGOS_VERSION="${ARGOS_VERSION#v}"' in text
    assert 'VERSION="$ARGOS_VERSION"' in text
    assert "VERSION=$(cat packaging/VERSION)" not in text.splitlines()
    assert 'sed -i \'\' "s/<string>0\\.1\\.0<\\/string>/<string>$VERSION<\\/string>/g" "$APP_DIR/Contents/Info.plist"' in text
    assert 'sed -i \'\' "s/<string>0\\.1\\.0<\\/string>/<string>$VERSION<\\/string>/g" packaging/Info.plist' not in text


@pytest.mark.xdist_group(name="binary-dist")
def test_app_bundle_built():
    """Internal documentation."""
    import platform
    if platform.machine() != "arm64":
        pytest.skip("仅 arm64 macOS 需要 .app bundle")
    app_dir = Path(__file__).parent.parent / "dist" / "Argos.app"
    if not app_dir.exists():
        pytest.skip("dist/Argos.app 不存在;先跑 `bash packaging/build_arm64.sh`")
    assert app_dir.is_dir(), f"{app_dir} 不是目录"
    assert (app_dir / "Contents" / "MacOS" / "argos").exists(), "缺 MacOS/argos binary"
    assert (app_dir / "Contents" / "Info.plist").exists(), "缺 Info.plist"
    import plistlib
    with (app_dir / "Contents" / "Info.plist").open("rb") as f:
        plist = plistlib.load(f)
    assert plist.get("CFBundleExecutable") == "argos", "CFBundleExecutable 不是 argos"
    assert plist.get("CFBundleIdentifier", "").startswith("com.tungoldshou"), (
        f"CFBundleIdentifier 错: {plist.get('CFBundleIdentifier')}"
    )


@pytest.mark.slow
@pytest.mark.xdist_group(name="binary-dist")
def test_build_script_creates_bundle_when_run(tmp_path, monkeypatch):
    """Internal documentation."""
    import platform
    if platform.machine() != "arm64":
        pytest.skip("仅 arm64 macOS 能 build .app bundle")
    repo = Path(__file__).parent.parent
    monkeypatch.chdir(repo)
    result = subprocess.run(
        ["bash", "packaging/build_arm64.sh"],
        capture_output=True, text=True, timeout=300, cwd=str(repo),
    )
    assert result.returncode == 0, f"build 失败: {result.returncode}\n{result.stdout}\n{result.stderr}"
    assert (repo / "dist" / "Argos.app" / "Contents" / "MacOS" / "argos").exists(), (
        "build 后 dist/Argos.app 仍不存在"
    )
