"""铁证⑤(spec §9 / §13 / §6):verify-loop 延迟基线 P50/P99 + 超时降级断言(可证伪)。

可证伪:超 inline_timeout 的 verify 被降级(不阻塞死);基线数字记录(量级合理,非硬卡)。
用 conftest 的 in_project fixture 提供 runtime 上下文(verify_dir=workspace=项目目录)。
"""
import statistics
import time

import pytest

from argos_agent.core.verify_gate import Verifier


@pytest.mark.slow  # 7 次 pytest 子进程采样 P50/P99 —— 真子进程,标 slow。
def test_verify_latency_baseline_p50_p99(in_project, capsys):
    """跑 N 次轻量 verify,测 P50/P99(记录到 stdout 供 beta 校准,不硬卡绝对值)。"""
    (in_project / "test_fast.py").write_text("def test_fast():\n    assert True\n")
    v = Verifier(max_rounds=3)
    samples = []
    for _ in range(7):
        t0 = time.perf_counter()
        verdict = v.verify("pytest -q test_fast.py", attempts=1)
        samples.append(time.perf_counter() - t0)
        assert verdict.status == "passed"
    p50 = statistics.median(samples)
    p99 = max(samples)  # 7 样本下 max ≈ P99 量级
    with capsys.disabled():
        print(f"\n[verify-latency] P50={p50:.3f}s P99={p99:.3f}s samples={[round(s, 3) for s in samples]}")
    # 量级断言(spec §13:pytest 启动 2-5s 已知;不硬卡绝对值,只断言"没失控到分钟级")。
    assert p99 < 30.0, f"verify 单次不应超 30s(P99={p99:.3f}s)——超时说明降级失效或环境异常"


@pytest.mark.slow  # 跑真 pytest 子进程验证降级 —— 真子进程,标 slow。
def test_verify_timeout_degrades_not_hangs(in_project):
    """超 inline_timeout 的 verify → 降级(unverifiable),不无限阻塞(契约 §6 分级延迟)。"""
    (in_project / "test_slow.py").write_text("import time\ndef test_slow():\n    time.sleep(2)\n    assert True\n")
    v = Verifier(max_rounds=3, inline_timeout=0.3)  # inline 阈值 0.3s,远小于 sleep(2)+pytest 启动
    t0 = time.perf_counter()
    verdict = v.verify("pytest -q test_slow.py", attempts=1)
    elapsed = time.perf_counter() - t0
    # 降级:不阻塞到测试真跑完(2s+);超时被识别 → unverifiable(三态 fail-closed,绝不当 passed)。
    assert verdict.status in ("unverifiable", "failed"), "超时必须降级,不假装 passed"
    assert verdict.status != "passed"
    assert elapsed < 2.0, f"超时应在 inline_timeout 附近返回,不阻塞到测试跑完(elapsed={elapsed:.2f}s)"
