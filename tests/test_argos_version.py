import re
import subprocess

import argos


def test_argos_has_version():
    assert hasattr(argos, "__version__"), "缺少 __version__"
    assert re.match(r"^\d+\.\d+\.\d+", argos.__version__), (
        f"__version__ 格式错: {argos.__version__}"
    )


def test_argos_version_flag(tmp_path, monkeypatch):
    result = subprocess.run(
        ["python", "-m", "argos", "--version"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, f"--version 退出码 {result.returncode}: {result.stderr}"
    out = result.stdout + result.stderr
    assert re.search(r"\d+\.\d+\.\d+", out), f"报号缺版本号: {out!r}"
