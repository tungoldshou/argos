"""E2E:跑 dist/argos --version 断言报 0.1.0(不是 0.0.0+unknown)。

注意:依赖 dist/argos 已存在(由 packaging/build_arm64.sh 产出)。
本测试在 CI 上游先跑 `bash packaging/build_arm64.sh`,或在 skip 模式下 pytest skip。
"""
from pathlib import Path

import pytest

BINARY = Path(__file__).parent.parent / "dist" / "argos"


@pytest.mark.skipif(
    not (Path(__file__).parent.parent / "dist" / "argos").exists(),
    reason="dist/argos 不存在(本地未 build);先跑 `bash packaging/build_arm64.sh`",
)
def test_binary_reports_correct_version():
    """dist/argos --version 报 0.1.0(spec §2.4 报号正确)。"""
    result = subprocess_run(BINARY, "--version")
    out = result.stdout + result.stderr
    assert "0.1.0" in out, f"binary --version 报号错: {out!r}"
    assert "0.0.0" not in out, f"binary --version 走 fallback(应为 0.1.0): {out!r}"


@pytest.mark.skipif(
    not (Path(__file__).parent.parent / "dist" / "argos").exists(),
    reason="dist/argos 不存在",
)
def test_binary_self_update_uses_real_version():
    """dist/argos self-update 报号含 0.1.0(不报 unknown)。"""
    result = subprocess_run(BINARY, "self-update")
    out = (result.stdout + result.stderr).lower()
    # 自更新会查 GitHub latest + 报号。报号应不含 0.0.0(真实版本)
    assert "0.0.0" not in out, f"binary self-update 报 unknown: {out!r}"


def subprocess_run(binary: Path, *args: str):
    import subprocess
    return subprocess.run(
        [str(binary), *args],
        capture_output=True, text=True, timeout=15,
    )
