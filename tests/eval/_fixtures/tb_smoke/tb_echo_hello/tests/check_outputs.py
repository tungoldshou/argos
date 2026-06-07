import subprocess
import pytest


def test_run_script_prints_hello():
    r = subprocess.run(["bash", "/app/run.sh"], capture_output=True, text=True, timeout=5)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "hello world"
