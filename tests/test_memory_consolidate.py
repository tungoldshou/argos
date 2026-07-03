"""Internal documentation."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from argos.memory.consolidate import (
    ARCHIVE_NAME,
    ConsolidationReport,
    consolidate,
)


# ── helper ───────────────────────────────────────────────────────────────────
def _entry(
    key: str = "k",
    confidence: float = 0.9,
    ts: float | None = None,
    last_used_at: float | None = None,
    use_count: int = 1,
    value: str = "v",
    **kwargs,
) -> dict:
    now = time.time()
    return {
        "id": f"id-{key}",
        "type": "fact",
        "scope": "user",
        "key": key,
        "value": value,
        "confidence": confidence,
        "evidence": [],
        "ts": ts if ts is not None else now,
        "last_used_at": last_used_at if last_used_at is not None else now,
        "use_count": use_count,
        "skill_name": None,
        "project_id": None,
        "session_id": None,
        **kwargs,
    }


def _write_jsonl(path: Path, entries: list[dict | str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for e in entries:
        if isinstance(e, str):
            lines.append(e)
        else:
            lines.append(json.dumps(e, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict]:
    results = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            results.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return results


def test_merge_same_key_keeps_newest_sums_use_count(tmp_path):
    """Internal documentation."""
    now = time.time()
    old_entry = _entry(key="dup", value="old_value", confidence=0.9, ts=now - 100, use_count=2)
    new_entry = _entry(key="dup", value="new_value", confidence=0.85, ts=now, use_count=1)

    mem_dir = tmp_path / "memory"
    tier_file = mem_dir / "user.jsonl"
    _write_jsonl(tier_file, [old_entry, new_entry])

    rep: ConsolidationReport = consolidate(mem_dir, now=now)

    assert rep.merged == 1, f"expected merged=1, got {rep.merged}"
    assert rep.errors == 0

    remaining = _read_jsonl(tier_file)
    assert len(remaining) == 1, f"expected 1 entry, got {len(remaining)}: {remaining}"
    survivor = remaining[0]
    assert survivor["value"] == "new_value", f"expected new_value, got {survivor['value']}"
    assert survivor["use_count"] == 3, f"expected use_count=3, got {survivor['use_count']}"


def test_archive_decayed_entries_never_hard_delete(tmp_path):
    """Internal documentation."""
    now = time.time()
    ninety_days_ago = now - 86400 * 90
    stale = _entry(
        key="stale_key",
        confidence=0.7,
        ts=ninety_days_ago,
        last_used_at=ninety_days_ago,
        use_count=1,
    )
    fresh = _entry(
        key="fresh_key",
        confidence=0.9,
        ts=now,
        last_used_at=now,
        use_count=1,
    )

    mem_dir = tmp_path / "memory"
    tier_file = mem_dir / "user.jsonl"
    _write_jsonl(tier_file, [stale, fresh])

    rep: ConsolidationReport = consolidate(mem_dir, now=now)

    assert rep.archived == 1, f"expected archived=1, got {rep.archived}"
    assert rep.errors == 0

    remaining = _read_jsonl(tier_file)
    remaining_keys = [e["key"] for e in remaining]
    assert "fresh_key" in remaining_keys, f"fresh_key should remain: {remaining_keys}"
    assert "stale_key" not in remaining_keys, f"stale_key should be archived: {remaining_keys}"

    archive_path = mem_dir / ARCHIVE_NAME
    assert archive_path.exists(), "archive.jsonl should exist"
    archived_entries = _read_jsonl(archive_path)
    archived_keys = [e["key"] for e in archived_entries]
    assert "stale_key" in archived_keys, f"stale_key should be in archive: {archived_keys}"


def test_consolidate_skips_corrupt_lines_and_archive_file(tmp_path):
    """Internal documentation."""
    now = time.time()
    good = _entry(key="good_key", confidence=0.9, ts=now, last_used_at=now)
    corrupt_line = "NOT_VALID_JSON{{{broken"

    mem_dir = tmp_path / "memory"
    tier_file = mem_dir / "user.jsonl"
    _write_jsonl(tier_file, [corrupt_line, good])

    archive_path = mem_dir / ARCHIVE_NAME
    archive_content = '{"key":"archive_existing","value":"should_not_touch"}\n'
    archive_path.write_text(archive_content, encoding="utf-8")

    rep: ConsolidationReport = consolidate(mem_dir, now=now)

    assert rep.errors == 0, f"expected 0 errors, got {rep.errors}"

    raw_lines = [l for l in tier_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(raw_lines) == 2, f"expected 2 lines, got {len(raw_lines)}: {raw_lines}"
    assert any(corrupt_line in line for line in raw_lines), "corrupt line should be preserved"

    archive_after = archive_path.read_text(encoding="utf-8")
    assert "archive_existing" in archive_after, "archive.jsonl should not be rewritten by consolidate scan"


def test_merge_different_value_archives_older_never_hard_delete(tmp_path):
    """Internal documentation."""
    now = time.time()
    older = _entry(key="cmd", value="old_stderr", confidence=0.9, ts=now - 100, use_count=2)
    newer = _entry(key="cmd", value="new_stderr", confidence=0.85, ts=now, use_count=1)

    mem_dir = tmp_path / "memory"
    tier_file = mem_dir / "user.jsonl"
    _write_jsonl(tier_file, [older, newer])

    rep: ConsolidationReport = consolidate(mem_dir, now=now)

    assert rep.merged == 1, f"expected merged=1, got {rep.merged}"
    assert rep.errors == 0

    remaining = _read_jsonl(tier_file)
    assert len(remaining) == 1, f"expected 1 survivor, got {len(remaining)}: {remaining}"
    survivor = remaining[0]
    assert survivor["value"] == "new_stderr", f"expected new_stderr, got {survivor['value']}"
    assert survivor["use_count"] == 3, f"expected use_count=3, got {survivor['use_count']}"

    archive_path = mem_dir / ARCHIVE_NAME
    assert archive_path.exists(), "archive.jsonl 应存在(older 异 value 被归档)"
    archived_values = [e.get("value") for e in _read_jsonl(archive_path)]
    assert "old_stderr" in archived_values, (
        f"older.value 必须落进 archive(永不硬删),实得: {archived_values}"
    )


def test_merge_same_value_no_archive_but_sums_use_count(tmp_path):
    """Internal documentation."""
    now = time.time()
    older = _entry(key="dup", value="same", confidence=0.9, ts=now - 100, use_count=2)
    newer = _entry(key="dup", value="same", confidence=0.85, ts=now, use_count=1)

    mem_dir = tmp_path / "memory"
    tier_file = mem_dir / "user.jsonl"
    _write_jsonl(tier_file, [older, newer])

    rep: ConsolidationReport = consolidate(mem_dir, now=now)

    assert rep.merged == 1
    assert rep.errors == 0

    remaining = _read_jsonl(tier_file)
    assert len(remaining) == 1
    assert remaining[0]["use_count"] == 3, "纯重复也要累加 use_count"

    archive_path = mem_dir / ARCHIVE_NAME
    if archive_path.exists():
        assert _read_jsonl(archive_path) == [], "纯重复(同 value)不该产生归档"


def test_merge_uses_max_last_used_at(tmp_path):
    """Internal documentation."""
    now = time.time()
    ninety_days_ago = now - 86400 * 90
    older_ts_recent_use = _entry(
        key="cmd",
        value="old_stderr",
        confidence=0.9,
        ts=now - 100,
        last_used_at=now,
        use_count=2,
    )
    newer_ts_stale_use = _entry(
        key="cmd",
        value="new_stderr",
        confidence=0.5,
        ts=now,
        last_used_at=ninety_days_ago,
        use_count=1,
    )

    mem_dir = tmp_path / "memory"
    tier_file = mem_dir / "user.jsonl"
    _write_jsonl(tier_file, [older_ts_recent_use, newer_ts_stale_use])

    rep: ConsolidationReport = consolidate(mem_dir, now=now)

    assert rep.errors == 0
    assert rep.merged == 1

    remaining = _read_jsonl(tier_file)
    assert len(remaining) == 1, (
        f"survivor 不该因 last_used_at 退化被误归档,实得: {remaining}"
    )
    survivor = remaining[0]
    assert survivor["value"] == "new_stderr"
    assert survivor["last_used_at"] == now, (
        f"last_used_at 应 max 聚合为 {now},实得 {survivor['last_used_at']}"
    )
    assert survivor["confidence"] == 0.9, (
        f"confidence 应 max 聚合为 0.9,实得 {survivor['confidence']}"
    )


def test_archive_stale_entry_not_re_archived_or_deleted(tmp_path):
    """Internal documentation."""
    now = time.time()
    ninety_days_ago = now - 86400 * 90
    stale_archived = _entry(
        key="already_archived_key",
        confidence=0.7,
        ts=ninety_days_ago,
        last_used_at=ninety_days_ago,
        use_count=1,
    )

    mem_dir = tmp_path / "memory"
    archive_path = mem_dir / ARCHIVE_NAME
    _write_jsonl(archive_path, [stale_archived])

    fresh = _entry(key="fresh_key", confidence=0.9, ts=now, last_used_at=now)
    _write_jsonl(mem_dir / "user.jsonl", [fresh])

    rep: ConsolidationReport = consolidate(mem_dir, now=now)

    assert rep.errors == 0

    assert archive_path.exists(), "archive.jsonl 不该被删除"
    archived_entries = _read_jsonl(archive_path)
    assert len(archived_entries) == 1, f"archive 不该被二次归档/扩张: {archived_entries}"
    assert archived_entries[0]["key"] == "already_archived_key"
