"""RunSnapshot.restore_file — 文件粒度还原测试(A3)。

铁证:
  - 修改文件 → restore_file → 逐字节回原样
  - 其他文件不动
  - run 中新建的文件(快照中不存在)→ 还原 = 删除 + 文案断言
  - ../ 逃逸路径被拒(fail-closed)
  - 快照不存在 → errors
  - 快照中文件不存在(新建) + 目标文件不存在 → missing 不报错
"""
from __future__ import annotations

from pathlib import Path

import pytest

from argos.core.snapshot import RunSnapshot


class TestRestoreFileSingleFile:
    def test_modified_file_restored_byte_for_byte(self, tmp_path: Path):
        """铁证:修改文件 → restore_file → 内容逐字节回原样。"""
        ws = tmp_path / "ws"
        ws.mkdir()
        original = "original content\nline2\n"
        (ws / "report.md").write_text(original)

        snap_path = tmp_path / "snap.tar"
        snapshot = RunSnapshot.take(ws, snap_path)

        # agent 修改文件
        (ws / "report.md").write_text("modified by agent\n")

        result = snapshot.restore_file(ws, "report.md")
        assert not result.errors, f"不应有错误: {result.errors}"
        assert result.restored == ["report.md"]
        assert (ws / "report.md").read_text() == original

    def test_other_files_not_touched(self, tmp_path: Path):
        """还原单文件不影响其他文件。"""
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "target.py").write_text("v1")
        (ws / "untouched.py").write_text("keep_me")

        snap_path = tmp_path / "snap.tar"
        snapshot = RunSnapshot.take(ws, snap_path)

        (ws / "target.py").write_text("v2")
        (ws / "untouched.py").write_text("also_changed")  # 故意改但不 restore

        result = snapshot.restore_file(ws, "target.py")
        assert not result.errors
        assert (ws / "target.py").read_text() == "v1"
        # 未指定的文件保持修改后的状态
        assert (ws / "untouched.py").read_text() == "also_changed"

    def test_subdir_file_restored(self, tmp_path: Path):
        """子目录中的文件也能正确还原。"""
        ws = tmp_path / "ws"
        (ws / "src").mkdir(parents=True)
        original = "def foo(): pass\n"
        (ws / "src" / "main.py").write_text(original)

        snap_path = tmp_path / "snap.tar"
        snapshot = RunSnapshot.take(ws, snap_path)

        (ws / "src" / "main.py").write_text("def foo(): return 42\n")

        result = snapshot.restore_file(ws, "src/main.py")
        assert not result.errors
        assert (ws / "src" / "main.py").read_text() == original


class TestRestoreFileNewFileUndo:
    def test_new_file_undo_deletes_file(self, tmp_path: Path):
        """run 中新建的文件(快照中不存在)→ 还原 = 删除该文件。"""
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "existing.py").write_text("v1")

        snap_path = tmp_path / "snap.tar"
        snapshot = RunSnapshot.take(ws, snap_path)

        # agent 新建了一个文件
        (ws / "new_file.py").write_text("new content")
        assert (ws / "new_file.py").exists()

        result = snapshot.restore_file(ws, "new_file.py")
        assert not result.errors, f"不应有错误: {result.errors}"
        assert "new_file.py" in result.missing
        # 铁证:文件已被删除
        assert not (ws / "new_file.py").exists(), "新建文件 undo 后应被删除"

    def test_new_file_already_deleted_no_error(self, tmp_path: Path):
        """快照中不存在 + 目标文件也不存在 → missing 标记,无 errors。"""
        ws = tmp_path / "ws"
        ws.mkdir()

        snap_path = tmp_path / "snap.tar"
        snapshot = RunSnapshot.take(ws, snap_path)

        # 文件根本不存在(已被删除或从未创建)
        result = snapshot.restore_file(ws, "ghost.py")
        assert not result.errors
        assert "ghost.py" in result.missing


class TestRestoreFilePathJail:
    def test_dotdot_escape_rejected(self, tmp_path: Path):
        """../ 路径逃逸被 fail-closed 拒绝。"""
        ws = tmp_path / "ws"
        ws.mkdir()
        (tmp_path / "secret.txt").write_text("secret")

        snap_path = tmp_path / "snap.tar"
        snapshot = RunSnapshot.take(ws, snap_path)

        # 尝试逃逸到 workspace 外
        result = snapshot.restore_file(ws, "../secret.txt")
        assert result.errors, "../ 逃逸必须在 errors 列表中"
        assert not result.restored
        # 目标文件不应被修改
        assert (tmp_path / "secret.txt").read_text() == "secret"

    def test_absolute_path_outside_workspace_rejected(self, tmp_path: Path):
        """绝对路径指向 workspace 外 → fail-closed 拒绝。"""
        ws = tmp_path / "ws"
        ws.mkdir()

        snap_path = tmp_path / "snap.tar"
        snapshot = RunSnapshot.take(ws, snap_path)

        outside = str(tmp_path / "outside.txt")
        result = snapshot.restore_file(ws, outside)
        assert result.errors


class TestRestoreFileMissingSnapshot:
    def test_missing_snapshot_returns_error(self, tmp_path: Path):
        """快照文件不存在 → errors(fail-closed)。"""
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "f.py").write_text("v1")

        snap_path = tmp_path / "nonexistent.tar"
        snapshot = RunSnapshot(tar_path=snap_path)

        result = snapshot.restore_file(ws, "f.py")
        assert result.errors
        assert not result.restored
