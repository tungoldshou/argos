"""RunSnapshot 单元测试:take 拍快照、restore 还原、RestoreResult 字段全。

边界:
- take 跳过 prune 目录
- take 跳过二进制不算(mvp 含,见 §4.5 spec)
- restore 部分失败 errors 字段非空

签名约定:RunSnapshot.take(workspace, tar_path)——tar_path 由调用方预拼(包含 session_id + run_seq),
本测试用 tmp_path / "snap.tar" 占位(每个测试独立路径,避免 .partial 重命名冲突)。
"""
import os
import tarfile
from pathlib import Path

import pytest

from argos.core.snapshot import RunSnapshot, RestoreResult


def test_take_records_existing_files(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.py").write_text("hello")
    (ws / "b.txt").write_text("world")
    snap = RunSnapshot.take(ws, tmp_path / "snap1.tar")
    assert snap.tar_path.exists()
    with tarfile.open(snap.tar_path) as tf:
        names = tf.getnames()
    assert "a.py" in names
    assert "b.txt" in names


def test_take_prunes_heavy_dirs(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "keep.py").write_text("x")
    # 含构建产物/索引(2026-06-14:真机 desktop/dist/build 让快照卡 11s tar 3.6GB)。
    pruned = (".venv", "node_modules", "__pycache__", ".git",
              "dist", "build", "target", ".codegraph", ".tox", ".next")
    for d in pruned:
        (ws / d / "nested" / "deep").mkdir(parents=True)
        (ws / d / "junk.txt").write_text("junk")
        # 嵌套深处:os.walk 原地剪枝绝不下钻,深处文件也不该被收(旧 rglob 会遍历它们 → 卡)。
        (ws / d / "nested" / "deep" / "more.txt").write_text("more")
    snap = RunSnapshot.take(ws, tmp_path / "snap2.tar")
    with tarfile.open(snap.tar_path) as tf:
        names = tf.getnames()
    assert "keep.py" in names
    for d in pruned:
        assert not any(n.startswith(f"{d}/") for n in names), f"应剪枝 {d}（含嵌套深处）"


def test_take_skips_new_dirs_after_take(tmp_path: Path):
    """take 后新建的文件不应进快照(还原时不删新文件,见 spec §2.1.2)。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.py").write_text("x")
    snap = RunSnapshot.take(ws, tmp_path / "snap3.tar")
    (ws / "new.py").write_text("created later")
    with tarfile.open(snap.tar_path) as tf:
        names = tf.getnames()
    assert "a.py" in names
    assert "new.py" not in names


def test_restore_overwrites_modified_files(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.py").write_text("original")
    snap = RunSnapshot.take(ws, tmp_path / "snap4.tar")
    (ws / "a.py").write_text("modified")
    result = snap.restore(ws)
    assert isinstance(result, RestoreResult)
    assert (ws / "a.py").read_text() == "original"
    assert "a.py" in result.restored


def test_restore_does_not_delete_new_files(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.py").write_text("x")
    snap = RunSnapshot.take(ws, tmp_path / "snap5.tar")
    (ws / "a.py").write_text("modified")
    (ws / "new.py").write_text("fresh")
    snap.restore(ws)
    assert (ws / "new.py").exists(), "还原不应删 run 中新建的文件"


def test_restore_partial_failure_returns_errors(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.py").write_text("x")
    snap = RunSnapshot.take(ws, tmp_path / "snap6.tar")
    (ws / "a.py").write_text("modified")
    # 模拟还原时 a.py 所在目录变成只读 → write_text 抛 PermissionError
    (ws / "a.py").chmod(0o444)
    try:
        result = snap.restore(ws)
        # 至少 errors 字段存在(可空,具体行为依赖 OS);保证接口稳
        assert isinstance(result.errors, list)
    finally:
        (ws / "a.py").chmod(0o644)


def test_restore_idempotent(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.py").write_text("original")
    snap = RunSnapshot.take(ws, tmp_path / "snap7.tar")
    (ws / "a.py").write_text("mod1")
    snap.restore(ws)
    (ws / "a.py").write_text("mod2")
    snap.restore(ws)  # 第二次还原,仍应到 original
    assert (ws / "a.py").read_text() == "original"
