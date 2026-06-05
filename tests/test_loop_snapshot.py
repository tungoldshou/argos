"""loop.run 入口应拍 RunSnapshot,失败时 _last_snapshot=None 不阻断 run。

铁证(Task 5,plan docs/superpowers/plans/2026-06-05-tui-ux-debt.md):
  · run 起点拍 workspace 快照 → loop._last_snapshot 落到 SNAPSHOT_ROOT,文件名含 session_id;
  · 拍快照 I/O 失败(精确 monkeypatch RunSnapshot.take 抛 OSError)→ _last_snapshot=None,
    run 仍能正常完成(此 run 走"/undo 不可用"诚实降级,不崩)。

夹具来源:tests/e2e/conftest.py (build_real_loop / drain)。本测试不在 e2e/ 目录下,
故显式 pytest_plugins 拉夹具(否则 pytest 不会自动发现 e2e/conftest.py 的 fixtures)。
"""
from __future__ import annotations

import pytest

from tests.e2e.conftest import drain

# 拉 tests/e2e/conftest.py 里的 build_real_loop / store / in_project fixtures(本文件在 tests/ 根,
# 默认只看 tests/conftest.py + tests/__init__.py 同级 conftest;e2e/conftest.py 不自动发现)。
pytest_plugins = ["tests.e2e.conftest"]


@pytest.mark.asyncio
async def test_run_records_snapshot(build_real_loop):
    """跑一个 noop 任务(脚本模型返回 '直接完成')→ 拍到的快照存在,workspace 文件可还原。"""
    from argos_agent.core.snapshot import SNAPSHOT_ROOT

    # 选个最便宜的任务:无 write_file,只读 + 落报告;脚本一次性宣告完成(无代码块)。
    scripts = ["完成。无事可做。"]
    loop = build_real_loop(scripts, verify_cmd=None)
    await drain(loop, "noop", session_id="sess-snap-1")
    # 不论任务干啥,_last_snapshot 都应在跑完后被设置(本任务= loop.run 起点拍)。
    assert loop._last_snapshot is not None
    assert loop._last_snapshot.tar_path.exists()
    # 确认 tar 在 SNAPSHOT_ROOT 下,且文件名含 session_id。
    assert str(loop._last_snapshot.tar_path).startswith(str(SNAPSHOT_ROOT))
    assert "sess-snap-1" in loop._last_snapshot.tar_path.name


@pytest.mark.asyncio
async def test_run_snapshot_failure_does_not_block_run(build_real_loop, monkeypatch):
    """拍快照 I/O 失败 → _last_snapshot=None,run 照常完成。

    精确 monkeypatch(方案 A):只让 RunSnapshot.take 抛 OSError(模拟磁盘故障/权限拒绝),
    其它路径(沙箱 spawn / verifier / store)不受影响 —— 严格隔离快照失败这一个变量。
    """
    from argos_agent.core import snapshot as snap_mod

    def _take_boom(cls, ws, tp):
        raise OSError("simulated snapshot I/O failure")

    monkeypatch.setattr(snap_mod.RunSnapshot, "take", classmethod(_take_boom))

    scripts = ["完成。"]
    loop = build_real_loop(scripts, verify_cmd=None)
    events = await drain(loop, "noop", session_id="sess-snap-fail")
    assert loop._last_snapshot is None
    # run 应正常完成(无未捕获异常透出 drain;events 至少有一个事件)。
    assert len(events) > 0
