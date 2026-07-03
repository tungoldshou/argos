import statistics
import time

import pytest

from argos.core.verify_gate import Verifier


@pytest.mark.slow
def test_verify_latency_baseline_p50_p99(in_project, capsys):
    (in_project / "test_fast.py").write_text("def test_fast():\n    assert True\n")
    v = Verifier(max_rounds=3)
    samples = []
    for _ in range(7):
        t0 = time.perf_counter()
        verdict = v.verify("pytest -q test_fast.py", attempts=1)
        samples.append(time.perf_counter() - t0)
        assert verdict.status == "passed"
    p50 = statistics.median(samples)
    p99 = max(samples)
    with capsys.disabled():
        print(f"\n[verify-latency] P50={p50:.3f}s P99={p99:.3f}s samples={[round(s, 3) for s in samples]}")
    assert p99 < 30.0, f"verify 单次不应超 30s(P99={p99:.3f}s)——超时说明降级失效或环境异常"


@pytest.mark.slow
def test_verify_timeout_degrades_not_hangs(in_project):
    (in_project / "test_slow.py").write_text("import time\ndef test_slow():\n    time.sleep(2)\n    assert True\n")
    v = Verifier(max_rounds=3, inline_timeout=0.3)
    t0 = time.perf_counter()
    verdict = v.verify("pytest -q test_slow.py", attempts=1)
    elapsed = time.perf_counter() - t0
    assert verdict.status in ("unverifiable", "failed"), "超时必须降级,不假装 passed"
    assert verdict.status != "passed"
    assert elapsed < 2.0, f"超时应在 inline_timeout 附近返回,不阻塞到测试跑完(elapsed={elapsed:.2f}s)"
