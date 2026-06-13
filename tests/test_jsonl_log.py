"""jsonl_log 助手验收(任务:audit / eval / memory 共享 best-effort JSONL append 样板)。

约束:
- 严格保留既有"IO 失败 continue"语义
- 不合并语义不同的持久化(daemon/store 那种"必须抛"+fsync+行守卫模式不动)
- 不强制 30 天(参数化)
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from argos import jsonl_log


# ── append_line 验收 ─────────────────────────────────
def test_append_line_writes_dict_as_jsonl(tmp_path):
    """传 dict → 写一行 JSON + 换行(ensure_ascii=False)。"""
    p = tmp_path / "log.jsonl"
    jsonl_log.append_line(p, {"a": 1, "b": "中文"})
    text = p.read_text(encoding="utf-8")
    assert text.endswith("\n")
    parsed = json.loads(text.strip())
    assert parsed == {"a": 1, "b": "中文"}


def test_append_line_writes_str_directly(tmp_path):
    """传 str → 直接 write + 换行(eval/results 传 to_json() str 的场景)。"""
    p = tmp_path / "log.jsonl"
    jsonl_log.append_line(p, '{"a": 1}')
    text = p.read_text(encoding="utf-8")
    # 助手会 ensure 有结尾 \n(无则补)
    assert text.endswith("\n")
    parsed = json.loads(text.strip())
    assert parsed == {"a": 1}


def test_append_line_creates_parent_dir(tmp_path):
    """目录不存在 → 自动建(mkdir parents exist_ok)。"""
    p = tmp_path / "deep" / "nested" / "log.jsonl"
    jsonl_log.append_line(p, {"x": 1})
    assert p.exists()


def test_append_line_multiple_calls_sequential(tmp_path):
    """多次 append → 多行(各行可独立解析)。"""
    p = tmp_path / "log.jsonl"
    for i in range(5):
        jsonl_log.append_line(p, {"i": i})
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5
    assert [json.loads(l)["i"] for l in lines] == [0, 1, 2, 3, 4]


def test_append_line_io_error_swallows_with_warning(tmp_path, caplog):
    """路径不可写 → log warning + 不抛(best-effort 语义;不阻塞主流程)。"""
    # 把路径设成目录(文件无法 open 写入)
    p = tmp_path / "not_a_file"
    p.mkdir()
    target = p / "log.jsonl"   # 在目录下,但 p 本身是目录 → open(p, "a") 会 OSError
    # 实际:p 是目录,target 是子路径 — open 子路径应该成功。改用更严的方式:把 parent 设成文件
    bad = tmp_path / "is_a_file"
    bad.write_text("i am a file")   # 写一个文件
    target = bad / "log.jsonl"      # target 的 parent 是文件(不是目录)→ OSError
    with caplog.at_level(logging.WARNING, logger="argos.jsonl_log"):
        # 不抛
        jsonl_log.append_line(target, {"x": 1})
    assert any("jsonl_log" in rec.name for rec in caplog.records)


def test_append_line_appends_not_overwrites(tmp_path):
    """append 模式("a")不覆盖已有内容。"""
    p = tmp_path / "log.jsonl"
    jsonl_log.append_line(p, {"first": 1})
    jsonl_log.append_line(p, {"second": 2})
    lines = p.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0]) == {"first": 1}
    assert json.loads(lines[1]) == {"second": 2}


# ── cleanup_files_by_name_date 验收 ─────────────────────
def test_cleanup_files_by_name_date_removes_old_files(tmp_path):
    """文件名 {prefix}YYYY-MM-DD.jsonl → 超过 days → 删除,返删除数。"""
    (tmp_path / "approvals-2020-01-01.jsonl").write_text("old")
    (tmp_path / "approvals-2024-12-30.jsonl").write_text("recent")
    now = datetime(2025, 1, 15)
    removed = jsonl_log.cleanup_files_by_name_date(
        tmp_path, "approvals-*.jsonl", prefix="approvals-",
        days=30, now=now,
    )
    assert removed == 1
    assert not (tmp_path / "approvals-2020-01-01.jsonl").exists()
    assert (tmp_path / "approvals-2024-12-30.jsonl").exists()


def test_cleanup_files_by_name_date_keeps_recent(tmp_path):
    """recent 文件不删。"""
    (tmp_path / "approvals-2025-01-10.jsonl").write_text("r")
    now = datetime(2025, 1, 15)
    removed = jsonl_log.cleanup_files_by_name_date(
        tmp_path, "approvals-*.jsonl", prefix="approvals-",
        days=30, now=now,
    )
    assert removed == 0
    assert (tmp_path / "approvals-2025-01-10.jsonl").exists()


def test_cleanup_files_by_name_date_swallows_parse_errors(tmp_path, caplog):
    """文件名不符合 prefix+日期 → 跳过(不删)+ log warning(不抛)。"""
    (tmp_path / "approvals-garbage.jsonl").write_text("x")
    (tmp_path / "approvals-2020-01-01.jsonl").write_text("old")
    now = datetime(2025, 1, 15)
    # 不抛
    removed = jsonl_log.cleanup_files_by_name_date(
        tmp_path, "approvals-*.jsonl", prefix="approvals-",
        days=30, now=now,
    )
    assert removed == 1
    assert (tmp_path / "approvals-garbage.jsonl").exists()  # 跳过
    assert not (tmp_path / "approvals-2020-01-01.jsonl").exists()


def test_cleanup_files_by_name_date_missing_dir_is_noop():
    """dir 不存在 → 返 0(无 IO)。"""
    removed = jsonl_log.cleanup_files_by_name_date(
        Path("/nonexistent_dir_xyz"), "x-*.jsonl", prefix="x-",
        days=30, now=datetime.now(),
    )
    assert removed == 0
