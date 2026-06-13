"""memory.py 测试:记忆持久化(append-only JSONL,诚实空态)。"""
import os

from argos import memory


def test_no_file_returns_empty(tmp_path, monkeypatch):
    # 文件不存在 → 空列表(诚实空态,不编造)
    monkeypatch.setenv("ARGOS_MEMORY_FILE", str(tmp_path / "mem.jsonl"))
    assert memory.load_memories() == []


def test_record_and_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_MEMORY_FILE", str(tmp_path / "mem.jsonl"))
    rec = memory.record_task(goal="写分页响应", verdict="passed", model="MiniMax-M3")
    assert rec["goal"] == "写分页响应"
    assert rec["verdict"] == "passed"
    assert rec["id"] and rec["ts"]

    loaded = memory.load_memories()
    assert len(loaded) == 1
    assert loaded[0]["goal"] == "写分页响应"


def test_newest_first(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_MEMORY_FILE", str(tmp_path / "mem.jsonl"))
    memory.record_task(goal="第一个")
    memory.record_task(goal="第二个")
    loaded = memory.load_memories()
    # 倒序:最新在前
    assert loaded[0]["goal"] == "第二个"
    assert loaded[1]["goal"] == "第一个"


def test_corrupt_line_skipped(tmp_path, monkeypatch):
    f = tmp_path / "mem.jsonl"
    monkeypatch.setenv("ARGOS_MEMORY_FILE", str(f))
    memory.record_task(goal="好记录")
    # 追加一行损坏数据
    with f.open("a", encoding="utf-8") as fh:
        fh.write("{ 这不是合法 json\n")
    loaded = memory.load_memories()
    # 损坏行被跳过,好记录仍在(一行坏数据不毁整个记忆)
    assert len(loaded) == 1
    assert loaded[0]["goal"] == "好记录"


def test_failed_verdict_recorded_honestly(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_MEMORY_FILE", str(tmp_path / "mem.jsonl"))
    memory.record_task(goal="难任务", verdict="failed", model="MiniMax-M3")
    loaded = memory.load_memories()
    # 失败也如实记录,不隐藏
    assert loaded[0]["verdict"] == "failed"
