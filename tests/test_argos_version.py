"""__version__ 字段 + --version flag 报号。"""
import re
import subprocess

import argos_agent


def test_argos_agent_has_version():
    """包级 __version__ 是 x.y.z。"""
    assert hasattr(argos_agent, "__version__"), "缺少 __version__"
    assert re.match(r"^\d+\.\d+\.\d+", argos_agent.__version__), (
        f"__version__ 格式错: {argos_agent.__version__}"
    )


def test_argos_version_flag(tmp_path, monkeypatch):
    """python -m argos_agent --version 报号。"""
    # --version 触发 SystemExit(0),用 subprocess 跑并捕获 stdout
    result = subprocess.run(
        ["python", "-m", "argos_agent", "--version"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, f"--version 退出码 {result.returncode}: {result.stderr}"
    out = result.stdout + result.stderr
    # argparse 默认报 "prog x.y.z",格式 "argos 0.1.0"
    assert re.search(r"\d+\.\d+\.\d+", out), f"报号缺版本号: {out!r}"
