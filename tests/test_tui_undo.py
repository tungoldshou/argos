"""Internal documentation."""
import pytest
from pathlib import Path
from argos.tui.app import ArgosApp
from argos.core.snapshot import RunSnapshot, SNAPSHOT_ROOT
from argos.tui.widgets.transcript import Transcript as TranscriptLog


@pytest.mark.asyncio
async def test_undo_restores_modified_files(tmp_path: Path):
    """Internal documentation."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.py").write_text("original")
    snap = RunSnapshot.take(ws, SNAPSHOT_ROOT / f"sessA-test1-{tmp_path.name}.tar")
    (ws / "a.py").write_text("modified")
    app = ArgosApp.__new__(ArgosApp)
    app._snapshot = snap
    app._workspace = ws
    log = TranscriptLog()
    await app._undo(log)  # type: ignore[attr-defined]
    assert (ws / "a.py").read_text() == "original"


@pytest.mark.asyncio
async def test_undo_does_not_delete_new_files(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.py").write_text("x")
    snap = RunSnapshot.take(ws, SNAPSHOT_ROOT / f"sessA-test2-{tmp_path.name}.tar")
    (ws / "a.py").write_text("mod")
    (ws / "new.py").write_text("created")
    app = ArgosApp.__new__(ArgosApp)
    app._snapshot = snap
    app._workspace = ws
    log = TranscriptLog()
    await app._undo(log)  # type: ignore[attr-defined]
    assert (ws / "new.py").exists(), "/undo 不应删 run 中新建的文件"


@pytest.mark.asyncio
async def test_undo_no_snapshot(tmp_path: Path):
    """Internal documentation."""
    app = ArgosApp.__new__(ArgosApp)
    app._snapshot = None
    app._workspace = tmp_path
    log = TranscriptLog()
    await app._undo(log)  # type: ignore[attr-defined]
    assert "无可撤销" in log.rendered_text  # type: ignore[attr-defined]
