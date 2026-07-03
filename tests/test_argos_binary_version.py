from pathlib import Path

import pytest

pytestmark = pytest.mark.xdist_group(name="binary-dist")

BINARY = Path(__file__).parent.parent / "dist" / "argos"
VERSION = (Path(__file__).parent.parent / "packaging" / "VERSION").read_text().strip()


@pytest.mark.slow
@pytest.mark.skipif(
    not (Path(__file__).parent.parent / "dist" / "argos").exists(),
    reason="dist/argos 不存在(本地未 build);先跑 `bash packaging/build_arm64.sh`",
)
def test_binary_reports_correct_version():
    result = subprocess_run(BINARY, "--version")
    out = result.stdout + result.stderr
    assert VERSION in out, f"binary --version 报号错: {out!r}"
    assert "0.0.0" not in out, f"binary --version 走 fallback(应为 {VERSION}): {out!r}"


@pytest.mark.slow
@pytest.mark.skipif(
    not (Path(__file__).parent.parent / "dist" / "argos").exists(),
    reason="dist/argos 不存在",
)
def test_binary_self_update_uses_real_version():
    result = subprocess_run(BINARY, "self-update")
    out = (result.stdout + result.stderr).lower()
    assert "0.0.0" not in out, f"binary self-update 报 unknown: {out!r}"


def subprocess_run(binary: Path, *args: str):
    import subprocess
    return subprocess.run(
        [str(binary), *args],
        capture_output=True, text=True, timeout=15,
    )
