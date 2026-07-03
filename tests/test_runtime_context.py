"""Internal documentation."""
import asyncio
from pathlib import Path

from argos import runtime
from argos.runtime import RunContext


def test_set_context_then_current_reads_it(tmp_path):
    ctx = RunContext(workspace=tmp_path / "a", verify_dir=tmp_path / "av")
    token = runtime.set_context(ctx)
    try:
        assert runtime.current().workspace == tmp_path / "a"
    finally:
        runtime.reset(token)


def test_use_project_returns_token_and_sets_project_mode(tmp_path):
    token = runtime.use_project(str(tmp_path))
    try:
        cur = runtime.current()
        assert cur.project_mode is True
        assert cur.workspace == tmp_path.resolve()
        assert cur.verify_dir == tmp_path.resolve()
    finally:
        runtime.reset(token)


def test_concurrent_tasks_isolated(tmp_path):
    """Internal documentation."""
    async def worker(tag: str) -> str:
        token = runtime.set_context(RunContext(workspace=tmp_path / tag, verify_dir=tmp_path / tag))
        await asyncio.sleep(0.01)
        seen = runtime.current().workspace.name
        runtime.reset(token)
        return seen

    async def main():
        return await asyncio.gather(worker("A"), worker("B"))

    assert asyncio.run(main()) == ["A", "B"]


def test_guard_and_detect_read_contextvar(tmp_path):
    """Internal documentation."""
    ws = tmp_path / "proj"
    ws.mkdir()
    t = ws / "test_x.py"
    t.write_text("orig", encoding="utf-8")
    token = runtime.set_context(RunContext(workspace=ws, verify_dir=ws, project_mode=True))
    try:
        runtime.guard_files(["test_x.py"])
        assert runtime.detect_tampering() == []
        t.write_text("tampered", encoding="utf-8")
        assert any("test_x.py" in c for c in runtime.detect_tampering())
    finally:
        runtime.reset(token)
