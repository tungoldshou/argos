"""Internal documentation."""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from argos import jsonl_log


def test_append_line_writes_dict_as_jsonl(tmp_path):
    """Internal documentation."""
    p = tmp_path / "log.jsonl"
    jsonl_log.append_line(p, {"a": 1, "b": "中文"})
    text = p.read_text(encoding="utf-8")
    assert text.endswith("\n")
    parsed = json.loads(text.strip())
    assert parsed == {"a": 1, "b": "中文"}


def test_append_line_writes_str_directly(tmp_path):
    """Internal documentation."""
    p = tmp_path / "log.jsonl"
    jsonl_log.append_line(p, '{"a": 1}')
    text = p.read_text(encoding="utf-8")
    assert text.endswith("\n")
    parsed = json.loads(text.strip())
    assert parsed == {"a": 1}


def test_append_line_creates_parent_dir(tmp_path):
    """Internal documentation."""
    p = tmp_path / "deep" / "nested" / "log.jsonl"
    jsonl_log.append_line(p, {"x": 1})
    assert p.exists()


def test_append_line_multiple_calls_sequential(tmp_path):
    """Internal documentation."""
    p = tmp_path / "log.jsonl"
    for i in range(5):
        jsonl_log.append_line(p, {"i": i})
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5
    assert [json.loads(l)["i"] for l in lines] == [0, 1, 2, 3, 4]


def test_append_line_io_error_swallows_with_warning(tmp_path, caplog):
    """Internal documentation."""
    p = tmp_path / "not_a_file"
    p.mkdir()
    target = p / "log.jsonl"
    bad = tmp_path / "is_a_file"
    bad.write_text("i am a file")
    target = bad / "log.jsonl"
    with caplog.at_level(logging.WARNING, logger="argos.jsonl_log"):
        jsonl_log.append_line(target, {"x": 1})
    assert any("jsonl_log" in rec.name for rec in caplog.records)


def test_append_line_appends_not_overwrites(tmp_path):
    """Internal documentation."""
    p = tmp_path / "log.jsonl"
    jsonl_log.append_line(p, {"first": 1})
    jsonl_log.append_line(p, {"second": 2})
    lines = p.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0]) == {"first": 1}
    assert json.loads(lines[1]) == {"second": 2}


def test_cleanup_files_by_name_date_removes_old_files(tmp_path):
    """Internal documentation."""
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
    """Internal documentation."""
    (tmp_path / "approvals-2025-01-10.jsonl").write_text("r")
    now = datetime(2025, 1, 15)
    removed = jsonl_log.cleanup_files_by_name_date(
        tmp_path, "approvals-*.jsonl", prefix="approvals-",
        days=30, now=now,
    )
    assert removed == 0
    assert (tmp_path / "approvals-2025-01-10.jsonl").exists()


def test_cleanup_files_by_name_date_swallows_parse_errors(tmp_path, caplog):
    """Internal documentation."""
    (tmp_path / "approvals-garbage.jsonl").write_text("x")
    (tmp_path / "approvals-2020-01-01.jsonl").write_text("old")
    now = datetime(2025, 1, 15)
    removed = jsonl_log.cleanup_files_by_name_date(
        tmp_path, "approvals-*.jsonl", prefix="approvals-",
        days=30, now=now,
    )
    assert removed == 1
    assert (tmp_path / "approvals-garbage.jsonl").exists()
    assert not (tmp_path / "approvals-2020-01-01.jsonl").exists()


def test_cleanup_files_by_name_date_missing_dir_is_noop():
    """Internal documentation."""
    removed = jsonl_log.cleanup_files_by_name_date(
        Path("/nonexistent_dir_xyz"), "x-*.jsonl", prefix="x-",
        days=30, now=datetime.now(),
    )
    assert removed == 0
