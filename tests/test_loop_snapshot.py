from __future__ import annotations

import pytest

from tests.e2e.conftest import drain

pytest_plugins = ["tests.e2e.conftest"]


@pytest.mark.asyncio
async def test_run_records_snapshot(build_real_loop):
    from argos.core.snapshot import SNAPSHOT_ROOT

    scripts = ["完成。无事可做。"]
    loop = build_real_loop(scripts, verify_cmd=None)
    await drain(loop, "noop", session_id="sess-snap-1")
    assert loop._last_snapshot is not None
    assert loop._last_snapshot.tar_path.exists()
    assert str(loop._last_snapshot.tar_path).startswith(str(SNAPSHOT_ROOT))
    assert "sess-snap-1" in loop._last_snapshot.tar_path.name


@pytest.mark.asyncio
async def test_run_snapshot_failure_does_not_block_run(build_real_loop, monkeypatch):
    from argos.core import snapshot as snap_mod

    def _take_boom(cls, ws, tp):
        raise OSError("simulated snapshot I/O failure")

    monkeypatch.setattr(snap_mod.RunSnapshot, "take", classmethod(_take_boom))

    scripts = ["完成。"]
    loop = build_real_loop(scripts, verify_cmd=None)
    events = await drain(loop, "noop", session_id="sess-snap-fail")
    assert loop._last_snapshot is None
    assert len(events) > 0
