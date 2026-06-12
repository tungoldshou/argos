"""Task 7: consolidate — 记忆整理(合并 + 归档,永不硬删)TDD 套件。"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from argos_agent.memory.consolidate import (
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


# ── test 1: 同 key 合并,保留最新,累加 use_count ───────────────────────────
def test_merge_same_key_keeps_newest_sums_use_count(tmp_path):
    """同 key 两条(旧 use_count=2、新 use_count=1)→ merged==1,剩 1 条,value 是新的,use_count==3。"""
    now = time.time()
    old_entry = _entry(key="dup", value="old_value", confidence=0.9, ts=now - 100, use_count=2)
    new_entry = _entry(key="dup", value="new_value", confidence=0.85, ts=now, use_count=1)

    mem_dir = tmp_path / "memory"
    tier_file = mem_dir / "user.jsonl"
    _write_jsonl(tier_file, [old_entry, new_entry])

    # now 注入,确保新鲜条目不被归档
    rep: ConsolidationReport = consolidate(mem_dir, now=now)

    assert rep.merged == 1, f"expected merged=1, got {rep.merged}"
    assert rep.errors == 0

    remaining = _read_jsonl(tier_file)
    assert len(remaining) == 1, f"expected 1 entry, got {len(remaining)}: {remaining}"
    survivor = remaining[0]
    assert survivor["value"] == "new_value", f"expected new_value, got {survivor['value']}"
    assert survivor["use_count"] == 3, f"expected use_count=3, got {survivor['use_count']}"


# ── test 2: 衰减条目移入 archive,不硬删 ──────────────────────────────────
def test_archive_decayed_entries_never_hard_delete(tmp_path):
    """conf 0.7 但 90 天前的条目 + 新鲜条目 → archived==1,源文件只剩新鲜条,archive.jsonl 含旧条目 key。"""
    now = time.time()
    ninety_days_ago = now - 86400 * 90
    # 90 天前的条目: decayed_confidence(0.7, 90) = 0.7 - 0.9 = -0.2 → clamp 0.0 < 0.2 阈值
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

    # 源文件只剩新鲜条
    remaining = _read_jsonl(tier_file)
    remaining_keys = [e["key"] for e in remaining]
    assert "fresh_key" in remaining_keys, f"fresh_key should remain: {remaining_keys}"
    assert "stale_key" not in remaining_keys, f"stale_key should be archived: {remaining_keys}"

    # archive.jsonl 存在且含旧条目 key
    archive_path = mem_dir / ARCHIVE_NAME
    assert archive_path.exists(), "archive.jsonl should exist"
    archived_entries = _read_jsonl(archive_path)
    archived_keys = [e["key"] for e in archived_entries]
    assert "stale_key" in archived_keys, f"stale_key should be in archive: {archived_keys}"


# ── test 3: 坏行原样保留,archive.jsonl 不被扫描 ──────────────────────────
def test_consolidate_skips_corrupt_lines_and_archive_file(tmp_path):
    """文件含坏 JSON 行 + 一条好条目;目录里另有 archive.jsonl → errors==0,坏行原样保留(文件仍 2 行),archive.jsonl 不被扫描。"""
    now = time.time()
    good = _entry(key="good_key", confidence=0.9, ts=now, last_used_at=now)
    corrupt_line = "NOT_VALID_JSON{{{broken"

    mem_dir = tmp_path / "memory"
    tier_file = mem_dir / "user.jsonl"
    # 坏行 + 好条目(2 行)
    _write_jsonl(tier_file, [corrupt_line, good])

    # 预先写一个 archive.jsonl,里面有独立内容 — 不应被扫描/修改
    archive_path = mem_dir / ARCHIVE_NAME
    archive_content = '{"key":"archive_existing","value":"should_not_touch"}\n'
    archive_path.write_text(archive_content, encoding="utf-8")

    rep: ConsolidationReport = consolidate(mem_dir, now=now)

    assert rep.errors == 0, f"expected 0 errors, got {rep.errors}"

    # 文件仍然 2 行(坏行原样保留 + 好条目)
    raw_lines = [l for l in tier_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(raw_lines) == 2, f"expected 2 lines, got {len(raw_lines)}: {raw_lines}"
    # 坏行原样在里面
    assert any(corrupt_line in line for line in raw_lines), "corrupt line should be preserved"

    # archive.jsonl 内容未被改写(仍含原始内容)
    archive_after = archive_path.read_text(encoding="utf-8")
    assert "archive_existing" in archive_after, "archive.jsonl should not be rewritten by consolidate scan"


# ── test 4: archive.jsonl 里的陈旧条目不被二次归档/删除(rglob skip 真起作用) ──
def test_archive_stale_entry_not_re_archived_or_deleted(tmp_path):
    """archive.jsonl 预置一条 conf=0.7 但 90 天前的陈旧条目(若被扫描会再次触发归档)。

    整理后断言它仍原样在 archive.jsonl、未被二次归档(不会出现重复行)、未被删除 ——
    证明 consolidate 的 rglob skip(f.name == ARCHIVE_NAME → continue)真在起作用,
    归档区是只进不出的终态,绝不被反复搅动。
    """
    now = time.time()
    ninety_days_ago = now - 86400 * 90
    # 这条若被当作普通 tier 扫描,decayed_confidence(0.7, 90) → 0.0 < 0.2 阈值,会被归档
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

    # 另起一个普通 tier(给 consolidate 实际有事可做的对象,确保它真的跑了一轮)
    fresh = _entry(key="fresh_key", confidence=0.9, ts=now, last_used_at=now)
    _write_jsonl(mem_dir / "user.jsonl", [fresh])

    rep: ConsolidationReport = consolidate(mem_dir, now=now)

    assert rep.errors == 0

    # archive.jsonl 仍恰好 1 行,key 原样在,无重复(没被二次归档),文件未被删
    assert archive_path.exists(), "archive.jsonl 不该被删除"
    archived_entries = _read_jsonl(archive_path)
    assert len(archived_entries) == 1, f"archive 不该被二次归档/扩张: {archived_entries}"
    assert archived_entries[0]["key"] == "already_archived_key"
