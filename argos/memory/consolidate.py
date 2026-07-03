from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

ARCHIVE_NAME = "archive.jsonl"
DEFAULT_ARCHIVE_THRESHOLD = 0.2


def _unique_tmp(target: Path) -> Path:
    return target.with_name(f"{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")


@dataclass(frozen=True, slots=True)
class ConsolidationReport:
    merged: int = 0
    archived: int = 0
    files_touched: int = 0
    errors: int = 0


def _score(e: dict, now: float) -> float:
    try:
        from argos.memory.auto import decayed_confidence
        conf = float(e.get("confidence", 0.5))
        last = float(e.get("last_used_at", e.get("ts", now)))
        days = max(0.0, (now - last) / 86400.0)
        return decayed_confidence(conf, days)
    except Exception as e:  # noqa: BLE001
        log.warning("consolidate: _score 失败,保守不归档: %s", e)
        return 1.0


def consolidate(
    memory_dir: Path, *, now: float | None = None,
    archive_threshold: float = DEFAULT_ARCHIVE_THRESHOLD,
) -> ConsolidationReport:
    now = time.time() if now is None else now
    merged = archived = touched = errors = 0
    archive_path = memory_dir / ARCHIVE_NAME
    if not memory_dir.exists():
        return ConsolidationReport()

    for f in sorted(memory_dir.rglob("*.jsonl")):
        if f.name == ARCHIVE_NAME:
            continue
        try:
            raw_lines = f.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as e:
            log.warning("consolidate: 读失败 %s: %s", f, e)
            errors += 1
            continue
        keep_raw: list[str] = []
        by_key: dict[str, dict] = {}
        to_archive: list[dict] = []
        merged_losers: list[dict] = []
        file_merged = 0
        for line in raw_lines:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                assert isinstance(e, dict) and "key" in e
            except Exception:  # noqa: BLE001
                keep_raw.append(line)
                continue
            k = str(e["key"])
            prev = by_key.get(k)
            if prev is None:
                by_key[k] = e
            else:
                newer, older = (
                    (e, prev)
                    if float(e.get("ts", 0)) >= float(prev.get("ts", 0))
                    else (prev, e)
                )
                newer = dict(newer)
                newer["use_count"] = int(newer.get("use_count", 0)) + int(older.get("use_count", 0))
                newer["last_used_at"] = max(
                    float(newer.get("last_used_at", newer.get("ts", 0))),
                    float(older.get("last_used_at", older.get("ts", 0))),
                )
                newer["confidence"] = max(
                    float(newer.get("confidence", 0.5)),
                    float(older.get("confidence", 0.5)),
                )
                by_key[k] = newer
                if older.get("value") != newer.get("value"):
                    merged_losers.append(older)
                file_merged += 1
        survivors: list[dict] = []
        for e in by_key.values():
            if _score(e, now) < archive_threshold:
                to_archive.append(e)
            else:
                survivors.append(e)
        if file_merged == 0 and not to_archive:
            continue
        archive_batch = to_archive + merged_losers
        try:
            if archive_batch:
                with archive_path.open("a", encoding="utf-8") as af:
                    for e in archive_batch:
                        af.write(json.dumps(e, ensure_ascii=False) + "\n")
            new_lines = keep_raw + [json.dumps(e, ensure_ascii=False) for e in survivors]
            tmp = _unique_tmp(f)
            tmp.write_text(
                "\n".join(new_lines) + ("\n" if new_lines else ""),
                encoding="utf-8",
            )
            tmp.replace(f)
            merged += file_merged
            archived += len(archive_batch)
            touched += 1
        except Exception as e:  # noqa: BLE001
            log.warning("consolidate: 重写失败 %s: %s", f, e)
            errors += 1
    return ConsolidationReport(merged=merged, archived=archived,
                               files_touched=touched, errors=errors)
