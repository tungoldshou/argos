"""/undo 命令端到端:test_app 走 Pilot,触发 undo 并断言 transcript 出现还原提示。

实现层:App 的 _snapshot 字段 + _dispatch_slash 走真逻辑(Task 10 改)。
"""
import pytest
from pathlib import Path
from argos.tui.app import ArgosApp
from argos.core.snapshot import RunSnapshot, SNAPSHOT_ROOT
from argos.tui.widgets.transcript import Transcript as TranscriptLog


@pytest.mark.asyncio
async def test_undo_restores_modified_files(tmp_path: Path):
    """改既有文件 → run 完成 → /undo → 文件回到起点。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.py").write_text("original")
    # 模拟"run 起点拍快照"
    snap = RunSnapshot.take(ws, SNAPSHOT_ROOT / f"sessA-test1-{tmp_path.name}.tar")
    # 模拟"agent 改文件"
    (ws / "a.py").write_text("modified")
    # 起 App、注入 _snapshot、调用 _undo(内部方法,被 _dispatch_slash 在 cmd.name=="undo" 时调用)
    app = ArgosApp.__new__(ArgosApp)  # 跳过 __init__ 的 Pilot 依赖
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
    """从未跑过 run → /undo → '无可撤销的运行'。"""
    app = ArgosApp.__new__(ArgosApp)
    app._snapshot = None
    app._workspace = tmp_path
    log = TranscriptLog()
    await app._undo(log)  # type: ignore[attr-defined]
    # 断言 transcript 含 "无可撤销"(用 widget 暴露的 rendered_text 而非私有 _lines)
    assert "无可撤销" in log.rendered_text  # type: ignore[attr-defined]
