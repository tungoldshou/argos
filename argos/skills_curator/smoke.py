"""#10 T5 smoke test runner.

两种路径:
1. skill 自带 tests/smoke.md -> 抽 python code block 跑
2. 通用探针:tmp python 跑 "ARGOS_SMOKE_PASS"

D12:smoke test 失败仅警告(spec §6.4)
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

SMOKE_TIMEOUT_S = 60

_PY_BLOCK = re.compile(r"```python\n(.*?)```", re.DOTALL)


def run_smoke_test(name: str, skill_dir: Path) -> str:
    """返 'pass: ...' / 'fail: ...'. 异常 -> 由 caller 包裹."""
    custom = skill_dir / "tests" / "smoke.md"
    if custom.exists():
        return _run_custom_smoke(name, custom)
    return _run_generic_probe(name)


def _extract_python_block(text: str) -> str:
    m = _PY_BLOCK.search(text)
    return m.group(1).strip() if m else ""


def _run_custom_smoke(name: str, smoke_md: Path) -> str:
    """本期 v1 简化:从 smoke.md 抽 python code block 跑;无 block -> fail."""
    text = smoke_md.read_text("utf-8")
    code = _extract_python_block(text)
    if not code:
        return f"fail: no python code block in {smoke_md}"
    with tempfile.TemporaryDirectory() as td:
        probe = Path(td) / f"{name}_smoke.py"
        probe.write_text(code, encoding="utf-8")
        try:
            r = subprocess.run(
                ["python3", str(probe)],
                cwd=td,
                capture_output=True,
                text=True,
                timeout=SMOKE_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            return f"fail: timeout after {SMOKE_TIMEOUT_S}s"
        if r.returncode == 0:
            return f"pass: exit=0 stdout={r.stdout.strip()[:80]}"
        return f"fail: exit={r.returncode} stderr={r.stderr.strip()[:80]}"


def _run_generic_probe(name: str) -> str:
    with tempfile.TemporaryDirectory() as td:
        probe = Path(td) / f"{name}_probe.py"
        probe.write_text("print('ARGOS_SMOKE_PASS')\n", encoding="utf-8")
        try:
            r = subprocess.run(
                ["python3", str(probe)],
                cwd=td,
                capture_output=True,
                text=True,
                timeout=SMOKE_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            return f"fail: timeout after {SMOKE_TIMEOUT_S}s"
        if r.returncode == 0 and "ARGOS_SMOKE_PASS" in r.stdout:
            return f"pass: probe exit=0"
        return f"fail: exit={r.returncode} stdout={r.stdout.strip()[:80]}"


__all__ = ["SMOKE_TIMEOUT_S", "run_smoke_test"]
